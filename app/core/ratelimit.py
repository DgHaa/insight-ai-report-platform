"""轻量速率限制（Redis 优先，进程内存兜底）。

用于抑制登录/注册爆破、模型连通性测试（SSRF 放大器）等高频或敏感接口。
采用与 app/core/concurrency.py 一致的熔断策略：Redis 不可用时降级为进程内计数。
"""
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---- Redis 熔断 ----
_redis_down_until: float = 0.0
_REDIS_DOWN_BACKOFF = 30.0
_REDIS_SOCKET_TIMEOUT = 0.5

_client = None
_lock = threading.Lock()

# ---- 进程内存兜底：key -> 请求时间戳队列 ----
_mem_hits: dict[str, deque[float]] = defaultdict(deque)


def _redis_down() -> bool:
    return time.monotonic() < _redis_down_until


def _mark_redis_down() -> None:
    global _redis_down_until
    _redis_down_until = time.monotonic() + _REDIS_DOWN_BACKOFF


def _get_redis():
    global _client
    with _lock:
        if _redis_down():
            return None
        if _client is None:
            try:
                import redis as redis_sync

                _client = redis_sync.Redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
                    socket_timeout=_REDIS_SOCKET_TIMEOUT,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Redis 客户端初始化失败，速率限制降级为进程内存")
                _mark_redis_down()
                return None
        return _client


class RateLimited(Exception):
    """请求超出速率限制。"""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"请求过于频繁，请 {retry_after} 秒后再试")


def _check_memory(key: str, limit: int, window: int) -> tuple[bool, int]:
    """进程内滑动窗口计数，返回 (是否允许, 需等待秒数)。"""
    now = time.monotonic()
    with _lock:
        hits = _mem_hits[key]
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= limit:
            return False, max(1, int(window - (now - hits[0])))
        hits.append(now)
        # 防止长期累积字典膨胀：仅保留近期有记录的 key
        if len(_mem_hits) > 10000:
            for k in [k for k, v in _mem_hits.items() if not v]:
                _mem_hits.pop(k, None)
        return True, 0


def check_rate_limit(key: str, limit: int, window: int) -> None:
    """检查并登记一次访问；超限抛出 RateLimited。

    key 由调用方按业务维度构造（如 "login:<ip>:<username>"）。
    """
    # 先尝试 Redis（跨进程生效）
    client = _get_redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            redis_key = f"insight:ratelimit:{key}:{int(time.time()) // window}"
            pipe.incr(redis_key)
            pipe.expire(redis_key, window)
            count = pipe.execute()[0]
            if int(count) > limit:
                raise RateLimited(window)
            return
        except RateLimited:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("Redis 速率限制失败，降级为进程内存计数")
            _mark_redis_down()

    allowed, wait = _check_memory(key, limit, window)
    if not allowed:
        raise RateLimited(wait)


def client_ip(request) -> str:
    """提取客户端 IP（兼容反向代理 X-Forwarded-For）。"""
    forwarded = request.headers.get("x-forwarded-for") if request else None
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request and request.client else "unknown"


def request_id() -> str:
    return uuid.uuid4().hex
