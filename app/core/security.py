"""JWT 令牌工具：生成、解析、注销（Redis 黑名单 + 内存兜底）。

注销黑名单默认存 Redis（跨 uvicorn worker / 重启后依然有效），
并在 Redis 不可用时回退到进程内存集合，保证登出功能不中断。

采用与 app/core/concurrency.py 一致的熔断策略：Redis 连接失败后进入
冷却期，冷却期内不再尝试连接，避免每个请求都等待连接超时。
"""
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.core.exceptions import AuthError

logger = logging.getLogger(__name__)

# Redis 中已注销令牌的键前缀：insight:auth:revoked:<jti>
_REVOKED_KEY_PREFIX = "insight:auth:revoked:"

# ---- 熔断：Redis 不可用时的冷却机制 ----
_redis_down_until: float = 0.0
_REDIS_DOWN_BACKOFF = 30.0     # 冷却期（秒）
_REDIS_SOCKET_TIMEOUT = 0.5    # Redis 连接/读写超时（秒）

# ---- 兜底：Redis 不可用时的进程内黑名单 ----
_revoked_jti_fallback: set[str] = set()

_client = None


def _redis_down() -> bool:
    return time.monotonic() < _redis_down_until


def _mark_redis_down() -> None:
    global _redis_down_until
    _redis_down_until = time.monotonic() + _REDIS_DOWN_BACKOFF


def _get_redis():
    """获取复用的同步 Redis 客户端；不可用时返回 None。"""
    global _client
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
            logger.warning("Redis 客户端初始化失败，JWT 注销黑名单降级为进程内存")
            _mark_redis_down()
            return None
    return _client


def _is_revoked_in_redis(jti: str) -> bool:
    client = _get_redis()
    if client is None:
        return False
    try:
        return bool(client.exists(_REVOKED_KEY_PREFIX + jti))
    except Exception:  # noqa: BLE001
        logger.warning("查询 JWT 黑名单失败，降级为进程内存查询")
        _mark_redis_down()
        return False


def create_access_token(user_id, username: str, role: str) -> tuple[str, str, datetime]:
    """生成 JWT 访问令牌，返回 (token, jti, 过期时间)。"""
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "jti": jti,
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti, expire


def decode_token(token: str) -> dict:
    """解析并校验 JWT 令牌，返回载荷；无效或已注销时抛出 AuthError。"""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        raise AuthError("无效或已过期的认证令牌")
    jti = payload.get("jti")
    if jti and _is_revoked_in_redis(jti):
        raise AuthError("认证令牌已失效")
    # Redis 不可用时回退到进程内黑名单
    if jti and _redis_down() and jti in _revoked_jti_fallback:
        raise AuthError("认证令牌已失效")
    return payload


def revoke_token(token: str) -> None:
    """注销令牌（写入 Redis 黑名单），用于登出。

    TTL 与令牌剩余有效期一致，过期后由 Redis 自动清理，无需手动维护。
    """
    try:
        # verify_exp=False：允许注销“刚刚过期但仍在窗口内”的令牌
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.PyJWTError:
        return

    jti = payload.get("jti")
    if not jti:
        return

    now = datetime.now(timezone.utc).timestamp()
    exp = payload.get("exp") or (
        now + settings.JWT_EXPIRE_MINUTES * 60
    )
    ttl = max(1, int(exp - now))

    client = _get_redis()
    if client is None:
        _revoked_jti_fallback.add(jti)
        return
    try:
        client.setex(_REVOKED_KEY_PREFIX + jti, ttl, "1")
    except Exception:  # noqa: BLE001
        logger.warning("写入 JWT 黑名单失败，降级为进程内存黑名单")
        _mark_redis_down()
        _revoked_jti_fallback.add(jti)
