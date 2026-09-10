"""报告生成编排服务（GenerationManager）。

负责：
- 全局 asyncio.Semaphore(settings.MAX_CONCURRENT_TASKS=5) 并发控制，
  超出并发的任务自动进入等待队列（FIFO）；
- WebSocket 进度订阅与广播：通过 CallbackPusher 接入 GenerationEngine；
- 版本规则（设计文档 1.3.3）：
  配置发生变更（与最近成功版本 config_snapshot 不同）才累加版本号 V+1；
  配置未变时重新生成覆盖当前最新版本；
  force=true 时强制生成新版本（忽略覆盖规则）；
- 超时：task_timeout_seconds（默认 1800s）硬止损；
- 终止：用户手动终止后完全丢弃本次生成内容，历史版本不变。
"""
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.concurrency import (
    TaskCancelledError,
    TaskControl,
    TaskTimeoutError,
    get_async_limiter,
    get_worker_id,
)
from app.core.utils import utcnow
from app.db.session import SessionLocal
from app.models import GenerationTask, Report, ReportVersion
from app.models.generation_task import GenerationTaskStatus
from app.models.report import ReportStatus
from app.services.generation_engine import (
    GenerationEngine,
    ModuleConfig,
    ModuleResult,
    _module_config_hash,
)
from app.services.progress_pusher import CallbackPusher
from app.services.system_config import get_system_config

logger = logging.getLogger(__name__)


async def save_report_version(
    db: AsyncSession,
    report: Report,
    config: dict,
    module_results: list[ModuleResult],
    force: bool,
    summary: str,
    model_used: str,
    all_failed: bool = False,
) -> int:
    """保存历史版本（含版本升版/覆盖规则），返回版本号。

    供异步管理（GenerationManager）与 Celery worker（tasks.generate_report）
    复用，保证两条执行路径的版本规则一致。

    - 失败模块明细写入版本内容（content.errors），供前端展示警告；
    - all_failed=True 时报告状态置为 failed（而非 completed）。
    """
    raw_modules = list(config.get("modules") or [])
    content = {
        "summary": summary,
        "modules": [
            {
                "module_title": r.module_title,
                "content": r.content,
                # 记录生成该模块时的配置签名，供增量生成判断是否需要重跑
                "config_hash": _module_config_hash(raw_modules[i]) if i < len(raw_modules) else "",
                **({"data_points": r.data_points} if getattr(r, "data_points", None) else {}),
                **({"charts": r.charts} if getattr(r, "charts", None) else {}),
            }
            for i, r in enumerate(module_results)
        ],
    }
    failed_modules = [
        {"module_title": r.module_title, "error": r.error}
        for r in module_results
        if r.error
    ]
    if failed_modules:
        content["errors"] = failed_modules
    content_hash = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    latest = await db.scalar(
        select(ReportVersion).where(
            ReportVersion.report_id == report.id,
            ReportVersion.version_number == report.current_version,
        )
    )
    config_json = json.dumps(config, ensure_ascii=False, sort_keys=True)
    same_config = latest is not None and config_json == json.dumps(
        latest.config_snapshot, ensure_ascii=False, sort_keys=True
    )

    if not force and same_config and latest is not None:
        # 配置未变更 → 覆盖当前最新版本，不累加版本号
        latest.content = content
        latest.config_snapshot = config
        latest.model_used = model_used
        latest.style_id = report.style_id
        latest.content_hash = content_hash
        latest.status = GenerationTaskStatus.SUCCESS.value
        latest.generated_at = utcnow()
        version_number = latest.version_number
    else:
        # 配置变更 或 强制生成 → 版本号 V+1
        # 取当前版本号与表内最大版本号较大者 +1，避免历史残留的孤儿版本
        # （version_number 已存在但 current_version 未同步）触发唯一约束冲突。
        max_version = await db.scalar(
            select(func.max(ReportVersion.version_number)).where(
                ReportVersion.report_id == report.id
            )
        )
        version_number = max(report.current_version, max_version or 0) + 1
        db.add(
            ReportVersion(
                report_id=report.id,
                version_number=version_number,
                content=content,
                config_snapshot=config,
                model_used=model_used,
                style_id=report.style_id,
                status=GenerationTaskStatus.SUCCESS.value,
                content_hash=content_hash,
                generated_at=utcnow(),
            )
        )
        report.current_version = version_number

    report.generate_count += 1
    # 全部模块失败时报告标记为 failed，不再伪装成 completed
    report.status = (
        ReportStatus.FAILED.value if all_failed else ReportStatus.COMPLETED.value
    )
    report.last_generated_at = utcnow()
    await db.flush()
    return version_number


class GenerationManager:
    """全局报告生成管理器（单例）。"""

    def __init__(self) -> None:
        self._running: dict[uuid.UUID, asyncio.Task] = {}  # report_id -> 后台任务
        self._report_of_task: dict[uuid.UUID, uuid.UUID] = {}  # task_id -> report_id
        self._cancel_events: dict[uuid.UUID, asyncio.Event] = {}  # task_id -> 取消标记
        self._queues: dict[uuid.UUID, set[asyncio.Queue]] = {}  # task_id -> 订阅队列
        self._last_progress: dict[uuid.UUID, dict] = {}  # task_id -> 最近进度快照
        self._worker_id = get_worker_id()  # Worker 标识（任务归属与状态追踪）

    # ---------------- 对外查询 ----------------

    def get_running_task_id(self, report_id: uuid.UUID) -> uuid.UUID | None:
        """返回指定报告当前正在执行的任务ID；无则 None。"""
        task = self._running.get(report_id)
        if task is None or task.done():
            return None
        for task_id, rid in self._report_of_task.items():
            if rid == report_id and task_id in self._cancel_events:
                return task_id
        return None

    def is_running(self, report_id: uuid.UUID) -> bool:
        task = self._running.get(report_id)
        return task is not None and not task.done()

    # ---------------- 订阅 / 发布 ----------------

    async def subscribe(self, task_id: uuid.UUID) -> asyncio.Queue:
        """注册一个进度订阅者（WebSocket），返回事件队列。"""
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(task_id, set()).add(q)
        last = self._last_progress.get(task_id)
        if last:
            q.put_nowait(last)
        return q

    def unsubscribe(self, task_id: uuid.UUID, q: asyncio.Queue) -> None:
        queues = self._queues.get(task_id)
        if queues:
            queues.discard(q)
            if not queues:
                self._queues.pop(task_id, None)

    def _publish(self, task_id: uuid.UUID, event: dict) -> None:
        for q in list(self._queues.get(task_id, ())):
            q.put_nowait(event)
        self._last_progress[task_id] = event

    # ---------------- 启停 ----------------

    def start(
        self, report_id: uuid.UUID, task_id: uuid.UUID, force: bool
    ) -> None:
        """启动后台生成任务；超出并发上限自动排队（asyncio.Semaphore FIFO）。"""
        self._cancel_events[task_id] = asyncio.Event()
        self._report_of_task[task_id] = report_id
        background = asyncio.create_task(
            self._run(report_id, task_id, force, self._cancel_events[task_id])
        )
        self._running[report_id] = background
        background.add_done_callback(lambda _t: self._cleanup(report_id, task_id))

    def cancel(self, task_id: uuid.UUID) -> None:
        """请求终止任务。

        同时设置取消标记并取消后台任务本身，使正在等待的子调用
        （模型调用/数据抓取）抛出 asyncio.CancelledError。
        """
        ev = self._cancel_events.get(task_id)
        if ev is not None:
            ev.set()
        report_id = self._report_of_task.get(task_id)
        if report_id is not None:
            bg = self._running.get(report_id)
            if bg is not None and not bg.done():
                bg.cancel()

    def _cleanup(self, report_id: uuid.UUID, task_id: uuid.UUID) -> None:
        self._running.pop(report_id, None)
        self._report_of_task.pop(task_id, None)
        self._cancel_events.pop(task_id, None)
        self._queues.pop(task_id, None)
        self._last_progress.pop(task_id, None)

    # ---------------- 执行 ----------------

    async def _run(
        self,
        report_id: uuid.UUID,
        task_id: uuid.UUID,
        force: bool,
        cancel_event: asyncio.Event,
    ) -> None:
        """在全局并发限制器保护下执行（Semaphore(5) + Redis FIFO 排队）。"""
        limiter = get_async_limiter()
        await limiter.acquire(f"report:{report_id}")
        try:
            await self._execute(report_id, task_id, force, cancel_event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # _execute 内部 try 之外的异常（如 SessionLocal 打开/DB 读取失败等），
            # 不能让任务静默消失，否则 DB 任务永远 PENDING、报告永远 generating，
            # 表现为“生成按钮置灰但终止提示没有正在执行的生成任务”。
            logger.exception("generation task %s crashed before completion", task_id)
            try:
                async with SessionLocal() as db:
                    task = await db.get(GenerationTask, task_id)
                    report = await db.get(Report, report_id)
                    if task is not None:
                        task.status = GenerationTaskStatus.FAILED.value
                        task.completed_at = utcnow()
                        task.error_message = f"生成任务异常退出: {str(exc)[:200]}"
                    if report is not None:
                        report.status = ReportStatus.FAILED.value
                    await db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist task failure for %s", task_id)
        finally:
            await limiter.release()

    async def _execute(
        self,
        report_id: uuid.UUID,
        task_id: uuid.UUID,
        force: bool,
        cancel_event: asyncio.Event,
    ) -> None:
        async with SessionLocal() as db:
            task = await db.get(GenerationTask, task_id)
            report = await db.get(Report, report_id)
            if task is None or report is None:
                return

            # 读取超时配置（默认 1800s）
            timeout = settings.GENERATION_TIMEOUT_SECONDS
            sys_cfg = await get_system_config(db)
            if sys_cfg:
                timeout = int(sys_cfg.get("task_timeout_seconds", timeout))

            # 进度推送（转发到 WebSocket 订阅队列）与任务控制（取消/超时）
            pusher = CallbackPusher(lambda ev: self._publish(task_id, ev))
            control = TaskControl(
                cancel_event=cancel_event,
                deadline=utcnow() + timedelta(seconds=timeout),
            )

            task.status = GenerationTaskStatus.RUNNING.value
            task.started_at = utcnow()
            await db.commit()

            try:
                config = report.config or {}
                # 串行模块执行引擎（抓取→构建Prompt→调模型→解析→存储）
                engine = GenerationEngine()
                result = await engine.execute(
                    report=report,
                    task_id=task_id,
                    config=config,
                    pusher=pusher,
                    control=control,
                    db=db,
                    worker_id=self._worker_id,
                    force=force,
                )
                # 全部模块失败时任务与报告标记为 failed（版本仍保存，便于排查）
                all_failed = bool(result.module_results) and result.ok_count == 0
                version_number = await save_report_version(
                    db,
                    report,
                    config,
                    result.module_results,
                    force,
                    result.summary,
                    result.model_used,
                    all_failed=all_failed,
                )
                task.completed_at = utcnow()
                if all_failed:
                    task.status = GenerationTaskStatus.FAILED.value
                    task.error_message = (
                        f"全部 {len(result.module_results)} 个模块生成失败: "
                        + "; ".join(e["error"] for e in result.errors[:3])
                    )
                else:
                    task.status = GenerationTaskStatus.SUCCESS.value
                    if result.errors:
                        task.error_message = "部分模块失败: " + "; ".join(
                            e["error"] for e in result.errors[:3]
                        )
                await db.commit()
                # 先提交事务再推送完成事件：避免前端收到 complete 时版本尚未提交
                if all_failed:
                    pusher.failed(
                        message=f"生成失败：全部 {len(result.module_results)} 个模块失败，请查看任务详情",
                        task_id=str(task_id),
                    )
                else:
                    pusher.complete(
                        message="生成成功！", version=version_number, task_id=str(task_id)
                    )

            except asyncio.CancelledError:
                # 后台任务被取消（用户手动终止），丢弃本次生成内容
                await self._mark_terminated(task_id, report_id)
                pusher.terminated(message="任务已终止", task_id=str(task_id))
                raise

            except TaskCancelledError:
                await self._mark_terminated(task_id, report_id)
                pusher.terminated(message="任务已终止", task_id=str(task_id))

            except TaskTimeoutError:
                task.status = GenerationTaskStatus.TIMEOUT.value
                task.completed_at = utcnow()
                task.error_message = f"生成超时（超过 {timeout} 秒硬止损）"
                report.status = ReportStatus.TIMEOUT.value
                await db.commit()
                pusher.timeout(message="生成超时", task_id=str(task_id))

            except Exception as exc:  # noqa: BLE001
                logger.exception("generation task %s failed", task_id)
                # 若异常源自数据库，会话已处于 pending-rollback 状态，必须先 rollback
                # 才能继续写终态，否则失败状态写不进去，报告会永久卡在 generating。
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    logger.debug("rollback 失败（会话可能已失效）", exc_info=True)
                try:
                    task.status = GenerationTaskStatus.FAILED.value
                    task.completed_at = utcnow()
                    task.error_message = str(exc)[:500]
                    report.status = ReportStatus.FAILED.value
                    await db.commit()
                except Exception:  # noqa: BLE001
                    logger.exception("原会话写入失败终态失败，改用独立会话重试")
                    await self._mark_failed(task_id, report_id, str(exc)[:500])
                pusher.failed(message=str(exc)[:200], task_id=str(task_id))

    @staticmethod
    async def _mark_terminated(task_id, report_id) -> None:
        """标记任务与报告为已终止（完全丢弃本次生成内容，历史版本不变）。

        使用独立会话：任务被取消时原会话事务可能已回滚（PendingRollbackError），
        若继续用原会话提交会导致终止标记写库失败，前端进度条将一直挂起。
        """
        async with SessionLocal() as db:
            task = await db.get(GenerationTask, task_id)
            report = await db.get(Report, report_id)
            if task is None or report is None:
                return
            task.status = GenerationTaskStatus.TERMINATED.value
            task.completed_at = utcnow()
            task.error_message = "用户手动终止"
            report.status = ReportStatus.TERMINATED.value
            await db.commit()

    @staticmethod
    async def _mark_failed(task_id, report_id, error_message: str) -> None:
        """标记任务与报告为失败（原会话不可用时的兜底，使用独立会话）。"""
        async with SessionLocal() as db:
            task = await db.get(GenerationTask, task_id)
            report = await db.get(Report, report_id)
            if task is None or report is None:
                return
            task.status = GenerationTaskStatus.FAILED.value
            task.completed_at = utcnow()
            task.error_message = (error_message or "生成失败")[:500]
            report.status = ReportStatus.FAILED.value
            await db.commit()

    # ---------------- 模块级重生成 ----------------

    def start_module_regenerate(
        self, report_id: uuid.UUID, module_index: int, task_id: uuid.UUID
    ) -> None:
        """启动单个模块的后台重生成任务（补丁式更新当前版本，不升版本号）。"""
        self._cancel_events[task_id] = asyncio.Event()
        self._report_of_task[task_id] = report_id
        background = asyncio.create_task(
            self._run_module_regenerate(
                report_id, module_index, task_id, self._cancel_events[task_id]
            )
        )
        self._running[report_id] = background
        background.add_done_callback(lambda _t: self._cleanup(report_id, task_id))

    async def _run_module_regenerate(
        self,
        report_id: uuid.UUID,
        module_index: int,
        task_id: uuid.UUID,
        cancel_event: asyncio.Event,
    ) -> None:
        """单模块重生成：在全局并发限制器保护下执行，进度发布到 WS 订阅队列。"""
        limiter = get_async_limiter()
        await limiter.acquire(f"report:{report_id}")
        try:
            await self._execute_module_regenerate(
                report_id, module_index, task_id, cancel_event
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("module regenerate task %s crashed", task_id)
            try:
                async with SessionLocal() as db:
                    task = await db.get(GenerationTask, task_id)
                    report = await db.get(Report, report_id)
                    if task is not None:
                        task.status = GenerationTaskStatus.FAILED.value
                        task.completed_at = utcnow()
                        task.error_message = f"模块重生成异常退出: {str(exc)[:200]}"
                    if report is not None:
                        report.status = ReportStatus.FAILED.value
                    await db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist module regen failure for %s", task_id)
        finally:
            await limiter.release()

    async def _execute_module_regenerate(
        self,
        report_id: uuid.UUID,
        module_index: int,
        task_id: uuid.UUID,
        cancel_event: asyncio.Event,
    ) -> None:
        async with SessionLocal() as db:
            task = await db.get(GenerationTask, task_id)
            report = await db.get(Report, report_id)
            if task is None or report is None:
                return

            config = report.config or {}
            modules = list(config.get("modules") or [])
            if module_index < 0 or module_index >= len(modules):
                task.status = GenerationTaskStatus.FAILED.value
                task.completed_at = utcnow()
                task.error_message = f"模块下标越界：{module_index}（共 {len(modules)} 个模块）"
                await db.commit()
                return

            timeout = settings.GENERATION_TIMEOUT_SECONDS
            pusher = CallbackPusher(lambda ev: self._publish(task_id, ev))
            control = TaskControl(
                cancel_event=cancel_event,
                deadline=utcnow() + timedelta(seconds=timeout),
            )
            task.status = GenerationTaskStatus.RUNNING.value
            task.started_at = utcnow()
            report.status = ReportStatus.GENERATING.value
            await db.commit()

            engine = GenerationEngine()
            try:
                module = ModuleConfig.from_dict(modules[module_index])
                mresult = await engine._execute_module(
                    module,
                    module_index,
                    len(modules),
                    str(task_id),
                    pusher,
                    control,
                    task_id,
                    report_department_id=getattr(report, "department_id", None),
                )
                version_number = await self._patch_module_in_version(
                    db, report, module_index, mresult
                )
                task.completed_at = utcnow()
                if mresult.error:
                    task.status = GenerationTaskStatus.FAILED.value
                    task.error_message = f"模块「{mresult.module_title}」重生成失败: {mresult.error[:200]}"
                    await db.commit()
                    pusher.failed(
                        message=f"模块「{mresult.module_title}」重生成失败",
                        task_id=str(task_id),
                    )
                else:
                    task.status = GenerationTaskStatus.SUCCESS.value
                    await db.commit()
                    pusher.complete(
                        message="模块已重新生成", version=version_number, task_id=str(task_id)
                    )
            except asyncio.CancelledError:
                await self._mark_terminated(task_id, report_id)
                pusher.terminated(message="任务已终止", task_id=str(task_id))
                raise
            except TaskCancelledError:
                await self._mark_terminated(task_id, report_id)
                pusher.terminated(message="任务已终止", task_id=str(task_id))
            except TaskTimeoutError:
                task.status = GenerationTaskStatus.TIMEOUT.value
                task.completed_at = utcnow()
                task.error_message = "模块重生成超时"
                report.status = ReportStatus.TIMEOUT.value
                await db.commit()
                pusher.timeout(message="模块重生成超时", task_id=str(task_id))
            except Exception as exc:  # noqa: BLE001
                logger.exception("module regenerate %s failed", task_id)
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    logger.debug("rollback failed in module regen", exc_info=True)
                try:
                    task.status = GenerationTaskStatus.FAILED.value
                    task.completed_at = utcnow()
                    task.error_message = str(exc)[:500]
                    report.status = ReportStatus.FAILED.value
                    await db.commit()
                except Exception:  # noqa: BLE001
                    logger.exception("module regen write failure, retry with new session")
                    await self._mark_failed(task_id, report_id, str(exc)[:500])
                pusher.failed(message=str(exc)[:200], task_id=str(task_id))

    @staticmethod
    async def _patch_module_in_version(
        db: AsyncSession,
        report: Report,
        module_index: int,
        mresult: "ModuleResult",
    ) -> int:
        """把单个模块的产出补丁式写回「当前版本」（不升版本号，属于对当前版本的精修）。

        - 当前版本存在：就地替换 content.modules[module_index]（下标不一致时按标题兜底匹配，
          仍找不到则追加）；
        - 报告从未生成过版本（current_version=0）：以该模块创建首个版本（其余模块留空占位）。
        """
        payload: dict = {
            "module_title": mresult.module_title,
            "content": mresult.content,
        }
        # 记录配置签名，保证下次增量生成能正确识别该模块「已成功且未改动」而复用
        try:
            raw_modules = list((report.config or {}).get("modules") or [])
            if module_index < len(raw_modules):
                payload["config_hash"] = _module_config_hash(raw_modules[module_index])
        except Exception:  # noqa: BLE001
            logger.debug("模块重生成配置签名计算失败", exc_info=True)
        if getattr(mresult, "data_points", None):
            payload["data_points"] = mresult.data_points
        if getattr(mresult, "charts", None):
            payload["charts"] = mresult.charts

        latest = await db.scalar(
            select(ReportVersion).where(
                ReportVersion.report_id == report.id,
                ReportVersion.version_number == report.current_version,
                ReportVersion.is_active.is_(True),
            )
        )

        if latest is None:
            # 从未生成过版本：以该模块为首版（其余模块空占位）
            config = report.config or {}
            raw_modules = list(config.get("modules") or [])
            content_modules = []
            for i, m in enumerate(raw_modules):
                if i == module_index:
                    content_modules.append(payload)
                else:
                    mt = m.get("module_title", "") if isinstance(m, dict) else ""
                    content_modules.append({"module_title": mt, "content": ""})
            content = {"modules": content_modules}
            content_hash = hashlib.sha256(
                json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            db.add(
                ReportVersion(
                    report_id=report.id,
                    version_number=1,
                    content=content,
                    config_snapshot=config,
                    model_used=mresult.engine_used or "",
                    style_id=report.style_id,
                    status=GenerationTaskStatus.SUCCESS.value,
                    content_hash=content_hash,
                    generated_at=utcnow(),
                )
            )
            report.current_version = 1
            version_number = 1
        else:
            content = dict(latest.content or {})
            modules = list(content.get("modules") or [])
            if 0 <= module_index < len(modules):
                modules[module_index] = payload
            else:
                matched = next(
                    (
                        i
                        for i, m in enumerate(modules)
                        if isinstance(m, dict)
                        and m.get("module_title") == mresult.module_title
                    ),
                    None,
                )
                if matched is not None:
                    modules[matched] = payload
                else:
                    modules.append(payload)
            content["modules"] = modules
            content_hash = hashlib.sha256(
                json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            latest.content = content
            latest.content_hash = content_hash
            latest.generated_at = utcnow()
            version_number = latest.version_number

        report.generate_count += 1
        # 模块级重生成是「对当前版本的精修」，无论该模块是否失败，报告整体置为 completed
        report.status = ReportStatus.COMPLETED.value
        await db.flush()
        return version_number


    @staticmethod
    async def reconcile_orphans() -> int:
        """服务启动对账：复位因重启/异常而卡在 generating 的孤儿报告。

        进程内管理器（GenerationManager）启动时为空，因此任何 status='generating'
        的报告都必然没有存活任务；将其残留的 running/pending 任务标记为 failed，
        并把报告复位为终态，避免“生成按钮置灰、终止又提示无任务”的死状态长期存在。
        """
        fixed = 0
        async with SessionLocal() as db:
            reports = (
                await db.execute(select(Report).where(Report.status == "generating"))
            ).scalars().all()
            for report in reports:
                tasks = (
                    await db.execute(
                        select(GenerationTask).where(
                            GenerationTask.report_id == report.id
                        )
                    )
                ).scalars().all()
                active = [
                    t
                    for t in tasks
                    if t.status
                    in (
                        GenerationTaskStatus.RUNNING.value,
                        GenerationTaskStatus.PENDING.value,
                    )
                ]
                msg = "服务启动对账：生成任务已中断，可重新生成"
                for t in active:
                    t.status = GenerationTaskStatus.FAILED.value
                    t.completed_at = utcnow()
                    t.error_message = msg
                terminal_map = {
                    GenerationTaskStatus.SUCCESS.value: ReportStatus.COMPLETED.value,
                    GenerationTaskStatus.TERMINATED.value: ReportStatus.TERMINATED.value,
                    GenerationTaskStatus.TIMEOUT.value: ReportStatus.TIMEOUT.value,
                    GenerationTaskStatus.FAILED.value: ReportStatus.FAILED.value,
                }
                latest = tasks[0] if tasks else None
                if active:
                    report.status = ReportStatus.FAILED.value
                elif latest is not None:
                    report.status = terminal_map.get(
                        latest.status, ReportStatus.FAILED.value
                    )
                else:
                    report.status = ReportStatus.FAILED.value
                report.error_message = msg
                fixed += 1
            await db.commit()
        return fixed


# 全局单例
generation_manager = GenerationManager()

