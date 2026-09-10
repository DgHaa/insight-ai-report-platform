"""报告生成 Celery 任务。

- generate_report_task：异步生成报告（内部通过 asyncio.run 调用异步引擎）；
- scheduled_generate_task：定时调度入口（Celery Beat 调用）。
"""
import asyncio
import uuid

from app.core.concurrency import (
    TaskCancelledError,
    TaskTimeoutError,
    get_sync_limiter,
    get_worker_id,
)
from app.core.utils import utcnow
from app.db.session import SessionLocal
from app.models import GenerationTask, Report
from app.models.generation_task import GenerationTaskStatus
from app.models.report import ReportStatus
from app.services.generation import save_report_version
from app.services.generation_engine import GenerationEngine
from app.services.progress_pusher import RedisPusher
from app.services.system_config import get_system_config
from app.tasks.celery_app import celery_app


@celery_app.task(
    name="app.tasks.generate_report.generate_report_task",
    bind=True,
    max_retries=1,
)
def generate_report_task(self, report_id: str, force: bool = False) -> dict:
    """异步生成报告（Celery worker 执行）。"""
    worker_id = get_worker_id()
    task_key = f"report:{report_id}"
    limiter = get_sync_limiter()
    limiter.acquire(task_key)
    try:
        return asyncio.run(
            _run_generation(report_id, force, worker_id, trigger_type="manual")
        )
    finally:
        limiter.release()


@celery_app.task(
    name="app.tasks.generate_report.scheduled_generate_task",
    bind=True,
    max_retries=1,
)
def scheduled_generate_task(self, report_id: str) -> dict:
    """定时调度生成：按报告的 schedule 配置触发（Beat 调度器派发）。

    force=True：周期报告每次生成各自成版，保留历史以支持期次对比。
    """
    worker_id = get_worker_id()
    task_key = f"report:{report_id}"
    limiter = get_sync_limiter()
    limiter.acquire(task_key)
    try:
        return asyncio.run(
            _run_generation(report_id, force=True, worker_id=worker_id, trigger_type="scheduled")
        )
    finally:
        limiter.release()


async def _run_generation(
    report_id: str, force: bool, worker_id: str, trigger_type: str
) -> dict:
    """在 asyncio 事件循环中执行报告生成（引擎 + 版本保存 + 状态更新）。"""
    async with SessionLocal() as db:
        report = await db.get(Report, uuid.UUID(report_id))
        if report is None or not report.is_active:
            return {"status": "not_found"}

        # 创建生成任务记录
        task = GenerationTask(
            report_id=report.id,
            trigger_type=trigger_type,
            status=GenerationTaskStatus.PENDING.value,
            worker_id=worker_id,
        )
        db.add(task)
        await db.flush()
        task_id = task.id
        report.status = ReportStatus.GENERATING.value
        await db.commit()

        # 进度推送（Redis：快照 + 频道，供 WebSocket 桥接）
        pusher = RedisPusher(str(task_id))

        # 任务控制：超时硬止损 + Redis 跨进程取消标记
        timeout = int((await get_system_config(db)).get("task_timeout_seconds", 1800))
        control = _build_task_control(task_id, timeout)

        task.status = GenerationTaskStatus.RUNNING.value
        task.started_at = utcnow()
        await db.commit()

        try:
            config = report.config or {}
            engine = GenerationEngine()
            result = await engine.execute(
                report=report,
                task_id=task_id,
                config=config,
                pusher=pusher,
                control=control,
                db=db,
                worker_id=worker_id,
            )
            # 全部模块失败时任务标记为 failed（版本仍保存，便于排查）
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
                pusher.failed(
                    f"生成失败：全部 {len(result.module_results)} 个模块失败",
                    task_id=str(task_id),
                )
            else:
                task.status = GenerationTaskStatus.SUCCESS.value
                if result.errors:
                    task.error_message = "部分模块失败: " + "; ".join(
                        e["error"] for e in result.errors[:3]
                    )
                pusher.complete(
                    message="生成成功！", version=version_number, task_id=str(task_id)
                )
            await db.commit()
            return {
                "task_id": str(task_id),
                "report_id": report_id,
                "status": "failed" if all_failed else "success",
                "version": version_number,
                "worker_id": worker_id,
            }

        except TaskCancelledError:
            await _mark_terminated(db, task, report)
            return {"task_id": str(task_id), "status": "terminated", "worker_id": worker_id}

        except TaskTimeoutError:
            task.status = GenerationTaskStatus.TIMEOUT.value
            task.completed_at = utcnow()
            task.error_message = f"生成超时（超过 {timeout} 秒硬止损）"
            report.status = ReportStatus.TIMEOUT.value
            await db.commit()
            pusher.failed("生成超时，任务已终止", task_id=str(task_id))
            return {"task_id": str(task_id), "status": "timeout", "worker_id": worker_id}

        except Exception as exc:  # noqa: BLE001
            task.status = GenerationTaskStatus.FAILED.value
            task.completed_at = utcnow()
            task.error_message = str(exc)[:500]
            report.status = ReportStatus.FAILED.value
            await db.commit()
            pusher.failed(f"生成失败: {exc}", task_id=str(task_id))
            return {"task_id": str(task_id), "status": "failed", "error": str(exc)[:200], "worker_id": worker_id}


def _build_task_control(task_id, timeout_seconds):
    """构造带 Redis 跨进程取消探测的任务控制（Celery 无法用进程内 Event）。"""
    from datetime import timedelta

    from app.core.concurrency import TaskControl, is_remote_cancelled

    return TaskControl(
        deadline=utcnow() + timedelta(seconds=timeout_seconds),
        cancel_check=lambda: is_remote_cancelled(task_id),
    )


async def _mark_terminated(db, task: GenerationTask, report: Report) -> None:
    task.status = GenerationTaskStatus.TERMINATED.value
    task.completed_at = utcnow()
    task.error_message = "用户手动终止"
    report.status = ReportStatus.TERMINATED.value
    await db.commit()
