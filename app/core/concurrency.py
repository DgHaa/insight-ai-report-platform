"""并发控制与任务控制。

- GlobalConcurrencyLimiter      异步：全局 asyncio.Semaphore(5) + Redis FIFO 等待队列；
- GlobalConcurrencyLimiterSync  Celery 场景同步版：Redis FIFO + 运行计数（跨进程）；
- TaskControl                   任务控制：30 分钟硬止损 + 手动终止（进程内 Event / 跨进程 Redis 标记）；
- get_worker_id                 Worker 标识（hostname:pid:随机串），用于任务归属与状态追踪。
"""
import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import timedelta
from typing import Callable

from app.core.config import settings
from app.core.utils import utcnow

logger = logging.getLogger(__name__)

WAIT_QUEUE_KEY = "insight:concurrency:waiting"
RUNNING_COUNT_KEY = "insight:concurrency:running"
CANCEL_FLAG_PREFIX = "insight:gen:cancel:"
POLL_INTERVAL = 0.2

# ---- Redis 熔断：本地开发/Redis 未启动时快速失败，避免每次操作等待 2~4s 超时 ----
_redis_down_until: float = 0.0
REDIS_DOWN_BACKOFF = 30.0   # 检测到 Redis 不可用后的冷却期（秒）
REDIS_SOCKET_TIMEOUT = 0.5  # Redis 连接超时（秒）


def redis_circuit_open() -> bool:
    """Redis 处于冷却期时返回 True（调用方直接跳过，不再尝试连接）。"""
    return time.monotonic() < _redis_down_until


def mark_redis_down() -> None:
    """标记 Redis 不可用，进入冷却期。"""
    global _redis_down_until
    _redis_down_until = time.monotonic() + REDIS_DOWN_BACKOFF


class TaskCancelledError(Exception):
    """任务被用户手动终止。"""


class TaskTimeoutError(Exception):
    """任务执行超时（硬止损）。"""


def get_worker_id() -> str:
    """生成 Worker 标识：hostname:pid:随机后缀。"""
    host = (socket.gethostname() or "host").split(".")[0]
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


# ==================== Redis 跨进程取消标记 ====================

def request_remote_cancel(task_id) -> None:
    """写入 Redis 取消标记（供 Celery worker 轮询），进程内路径不受影响。"""
    if redis_circuit_open():
        return
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
        )
        r.set(CANCEL_FLAG_PREFIX + str(task_id), "1", ex=3600)
        r.close()
    except Exception:  # noqa: BLE001
        mark_redis_down()
        logger.debug("request_remote_cancel failed (redis unavailable)")


def is_remote_cancelled(task_id) -> bool:
    """检查 Redis 取消标记。"""
    if redis_circuit_open():
        return False
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
        )
        exists = r.exists(CANCEL_FLAG_PREFIX + str(task_id)) == 1
        r.close()
        return exists
    except Exception:  # noqa: BLE001
        mark_redis_down()
        return False


# ==================== 任务控制 ====================

class TaskControl:
    """统一的任务取消与超时控制。

    - cancel_event：进程内取消（asyncio.Event）；
    - cancel_check：跨进程取消探测回调（如轮询 Redis 标记）；
    - deadline：硬止损时间点。
    """

    def __init__(
        self,
        *,
        cancel_event: asyncio.Event | None = None,
        deadline=None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self._cancel_event = cancel_event
        self._deadline = deadline
        self._cancel_check = cancel_check or (lambda: False)

    @classmethod
    def with_deadline(
        cls,
        seconds: float,
        *,
        cancel_event: asyncio.Event | None = None,
        task_id=None,
    ) -> "TaskControl":
        """构造带硬止损与（可选）Redis 取消探测的任务控制。"""
        deadline = utcnow() + timedelta(seconds=seconds)
        cancel_check = None
        if task_id is not None:
            cancel_check = lambda: is_remote_cancelled(task_id)  # noqa: E731
        return cls(cancel_event=cancel_event, deadline=deadline, cancel_check=cancel_check)

    def request_cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        if self._cancel_event is not None and self._cancel_event.is_set():
            return True
        try:
            return bool(self._cancel_check())
        except Exception:  # noqa: BLE001
            return False

    def check(self) -> None:
        """检查取消与超时；触发时抛出对应异常。"""
        if self.cancelled:
            raise TaskCancelledError()
        if self._deadline is not None and utcnow() > self._deadline:
            raise TaskTimeoutError()


# ==================== 异步并发限制器 ====================

class GlobalConcurrencyLimiter:
    """全局并发控制器（FastAPI 异步路径）。

    - 本地 asyncio.Semaphore 限制最大并发数（默认 5）；
    - 超出并发的任务进入 Redis FIFO 队列排队（FIFO 顺序执行）；
    - Redis 不可用时降级为纯信号量（进程内生效，记录告警）。
    """

    def __init__(
        self, max_concurrent: int | None = None, redis_url: str | None = None
    ) -> None:
        self.max_concurrent = max_concurrent or settings.MAX_CONCURRENT_TASKS
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._queue_key = WAIT_QUEUE_KEY
        self._redis = None
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                redis_url or settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
            )
        except Exception:  # noqa: BLE001
            self._redis = None
            mark_redis_down()
        self._mem_queue: list[str] = []
        if self._redis is None:
            logger.warning("Redis 不可用，并发控制降级为进程内信号量（跨进程 FIFO 排队失效）")
        self.worker_id = get_worker_id()

    async def acquire(self, task_key: str) -> str:
        """进入 FIFO 等待队列，获得执行权后返回 worker_id。"""
        await self._enqueue(task_key)
        try:
            while True:
                if await self._is_front(task_key):
                    await self._semaphore.acquire()
                    # 二次确认：获取信号量期间队首可能已被其它任务移除
                    if await self._is_front(task_key):
                        await self._dequeue(task_key)
                        return self.worker_id
                    self._semaphore.release()
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            await self._dequeue(task_key)
            raise

    async def release(self) -> None:
        """释放执行权。"""
        self._semaphore.release()

    async def _enqueue(self, task_key: str) -> None:
        if self._redis is not None:
            try:
                await self._redis.rpush(self._queue_key, task_key)
                return
            except Exception:  # noqa: BLE001
                logger.warning("Redis 写入失败，降级为内存队列")
                self._redis = None
                mark_redis_down()
        self._mem_queue.append(task_key)

    async def _is_front(self, task_key: str) -> bool:
        if self._redis is not None:
            try:
                front = await self._redis.lindex(self._queue_key, 0)
                return front == task_key
            except Exception:  # noqa: BLE001
                logger.warning("Redis 读取失败，并发控制降级为纯信号量")
                self._redis = None
                mark_redis_down()
        if self._mem_queue:
            return self._mem_queue[0] == task_key
        # 降级模式：内存队列为空时由信号量直接限流（FIFO 排序失效，并发仍受 5 限制）
        return True

    async def _dequeue(self, task_key: str) -> None:
        if self._redis is not None:
            try:
                await self._redis.lrem(self._queue_key, 1, task_key)
                return
            except Exception:  # noqa: BLE001
                self._redis = None
                mark_redis_down()
        if self._mem_queue and self._mem_queue[0] == task_key:
            self._mem_queue.pop(0)


# ==================== 同步并发限制器（Celery） ====================

class GlobalConcurrencyLimiterSync:
    """Celery worker 场景的跨进程并发控制。

    通过 Redis FIFO 队列 + 运行计数实现进程间最大并发（默认 5）；
    Redis 不可用时退化为直接放行（仅记录告警）。
    """

    def __init__(
        self, max_concurrent: int | None = None, redis_url: str | None = None
    ) -> None:
        self.max_concurrent = max_concurrent or settings.MAX_CONCURRENT_TASKS
        self._redis = None
        try:
            import redis as redis_sync

            self._redis = redis_sync.Redis.from_url(
                redis_url or settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
            )
        except Exception:  # noqa: BLE001
            self._redis = None
        if self._redis is None:
            logger.warning("Redis 不可用，Celery 并发控制退化为无排队执行")
        self.worker_id = get_worker_id()

    def acquire(self, task_key: str) -> str:
        """进入 FIFO 队列并等待执行权，返回 worker_id。"""
        if self._redis is None:
            return self.worker_id
        self._redis.rpush(WAIT_QUEUE_KEY, task_key)
        while True:
            front = self._redis.lindex(WAIT_QUEUE_KEY, 0)
            running = int(self._redis.get(RUNNING_COUNT_KEY) or 0)
            if front == task_key and running < self.max_concurrent:
                self._redis.incr(RUNNING_COUNT_KEY)
                self._redis.lrem(WAIT_QUEUE_KEY, 1, task_key)
                return self.worker_id
            time.sleep(POLL_INTERVAL)

    def release(self) -> None:
        """释放执行权（递减运行计数）。"""
        if self._redis is not None:
            try:
                self._redis.decr(RUNNING_COUNT_KEY)
            except Exception:  # noqa: BLE001
                logger.debug("concurrency release failed")


# 全局单例（应用内共享）
_async_limiter: GlobalConcurrencyLimiter | None = None
_sync_limiter: GlobalConcurrencyLimiterSync | None = None


def get_async_limiter() -> GlobalConcurrencyLimiter:
    """获取全局异步并发限制器单例。"""
    global _async_limiter
    if _async_limiter is None:
        _async_limiter = GlobalConcurrencyLimiter()
    return _async_limiter


def get_sync_limiter() -> GlobalConcurrencyLimiterSync:
    """获取全局同步（Celery）并发限制器单例。"""
    global _sync_limiter
    if _sync_limiter is None:
        _sync_limiter = GlobalConcurrencyLimiterSync()
    return _sync_limiter

