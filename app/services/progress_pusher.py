"""进度推送服务。

进度阶段与占比（对应设计文档 1.3.2 实时进度展示）：
- 初始化 init       5%
- 抓取外部数据 fetching  10%~40%
- 构建 Prompt building  45%
- 调用模型生成 generating 50%~90%
- 格式化存储 storing   95%
- 完成 complete    100%
"""
import json
import logging
from dataclasses import dataclass
from typing import Callable

from app.core.concurrency import REDIS_SOCKET_TIMEOUT

logger = logging.getLogger(__name__)

PHASE_INIT = "init"
PHASE_FETCHING = "fetching"
PHASE_BUILDING = "building"
PHASE_GENERATING = "generating"
PHASE_STORING = "storing"
PHASE_COMPLETE = "complete"
# 单个模块完成：携带该模块内容，供前端渐进渲染（非终态）
PHASE_MODULE_DONE = "module_done"
TERMINAL_PHASES = {"complete", "failed", "timeout", "terminated"}


@dataclass
class ProgressEvent:
    """一次进度事件。"""

    phase: str
    progress: int
    message: str
    version: int | None = None
    task_id: str | None = None
    # 模块级进度：当前第几个 / 共几个（用于前端显示「模块 2/5」）
    current: int | None = None
    total: int | None = None
    # 附加数据（如 PHASE_MODULE_DONE 携带 {index, module_title, content}）
    payload: dict | None = None

    def to_dict(self) -> dict:
        data = {"phase": self.phase, "progress": self.progress, "message": self.message}
        if self.version is not None:
            data["version"] = self.version
        if self.task_id is not None:
            data["task_id"] = self.task_id
        if self.current is not None:
            data["current"] = self.current
        if self.total is not None:
            data["total"] = self.total
        if self.payload is not None:
            data["payload"] = self.payload
        return data


class BasePusher:
    """进度推送基类。"""

    def push(self, event: ProgressEvent) -> None:
        raise NotImplementedError

    def complete(self, message: str = "生成成功！", version: int | None = None, task_id: str | None = None) -> None:
        self.push(ProgressEvent(PHASE_COMPLETE, 100, message, version, task_id))

    def failed(self, message: str, task_id: str | None = None) -> None:
        self.push(ProgressEvent("failed", 0, message, task_id=task_id))

    def timeout(self, message: str = "生成超时", task_id: str | None = None) -> None:
        self.push(ProgressEvent("timeout", 0, message, task_id=task_id))

    def module_done(
        self,
        *,
        index: int,
        total: int,
        module_title: str,
        content: str,
        progress: int,
        task_id: str | None = None,
        data_points: list[dict] | None = None,
        charts: list[dict] | None = None,
    ) -> None:
        """单个模块完成：携带内容（及结构化数据点/图表）供前端渐进渲染。"""
        payload: dict = {"index": index, "module_title": module_title, "content": content}
        if data_points is not None:
            payload["data_points"] = data_points
        if charts is not None:
            payload["charts"] = charts
        self.push(
            ProgressEvent(
                PHASE_MODULE_DONE,
                progress,
                f"模块完成：{module_title}",
                task_id=task_id,
                current=index,
                total=total,
                payload=payload,
            )
        )

    def terminated(self, message: str = "任务已终止", task_id: str | None = None) -> None:
        self.push(ProgressEvent("terminated", 0, message, task_id=task_id))


class CallbackPusher(BasePusher):
    """将进度事件转发给任意回调函数（如 GenerationManager 的事件发布）。"""

    def __init__(self, callback: Callable[[dict], None]) -> None:
        self._callback = callback

    def push(self, event: ProgressEvent) -> None:
        try:
            self._callback(event.to_dict())
        except Exception:  # noqa: BLE001
            logger.exception("progress callback push failed")


class QueueSetPusher(BasePusher):
    """向一组 asyncio.Queue（WebSocket 订阅者）广播进度事件。"""

    def __init__(self, queues: set) -> None:
        self._queues = queues

    def push(self, event: ProgressEvent) -> None:
        payload = event.to_dict()
        for q in list(self._queues):
            q.put_nowait(payload)


class RedisPusher(BasePusher):
    """将进度发布到 Redis：最新快照 key + 频道广播（Celery→WebSocket 桥接）。"""

    def __init__(self, task_id: str, ttl: int = 3600) -> None:
        from app.core.config import settings

        self._task_id = str(task_id)
        self._key = f"insight:gen:progress:{self._task_id}"
        self._channel = self._key
        self._ttl = ttl
        self._redis = None
        try:
            import redis as redis_sync

            self._redis = redis_sync.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Redis 不可用，进度快照与广播将失效")

    def push(self, event: ProgressEvent) -> None:
        if self._redis is None:
            return
        try:
            payload = json.dumps(event.to_dict(), ensure_ascii=False)
            self._redis.set(self._key, payload, ex=self._ttl)
            self._redis.publish(self._channel, payload)
        except Exception:  # noqa: BLE001
            logger.debug("redis progress push failed")


def make_pusher(
    *,
    task_id: str,
    callback: Callable[[dict], None] | None = None,
    queues: set | None = None,
    use_redis: bool = False,
) -> BasePusher:
    """按需组合进度推送实现（可多路同时推送）。"""
    if callback is None and not queues and not use_redis:
        return _NullPusher()
    if queues is not None and use_redis and callback is not None:
        return _MultiPusher(
            CallbackPusher(callback), QueueSetPusher(queues), RedisPusher(task_id)
        )
    if queues is not None and callback is not None:
        return _MultiPusher(CallbackPusher(callback), QueueSetPusher(queues))
    if callback is not None:
        return CallbackPusher(callback)
    if queues is not None:
        return QueueSetPusher(queues)
    return RedisPusher(task_id)


class _NullPusher(BasePusher):
    def push(self, event: ProgressEvent) -> None:  # pragma: no cover
        pass


class _MultiPusher(BasePusher):
    def __init__(self, *pushers: BasePusher) -> None:
        self._pushers = pushers

    def push(self, event: ProgressEvent) -> None:
        for p in self._pushers:
            p.push(event)
