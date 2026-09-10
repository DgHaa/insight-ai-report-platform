"""定时报告调度扫描（Celery Beat 每分钟触发）。

模块配置里的 schedule（每日/每周/每月 + cron）此前只落库、无人消费。
本任务扫描所有启用调度的报告，当「cron 最近一次触发时间晚于报告上次
生成时间」时派发 scheduled_generate_task（周期报告每次生成新版本）。

去重手段：
1) 跳过 status='generating' 的报告；
2) Redis SETNX 锁（10 分钟），避免扫描与派发之间的竞态重复；
   Redis 不可用时放行，仅靠状态检查兜底。

cron 按服务器本地时间解释（与 CronEditor 的用户视角一致）；
report.last_generated_at 为 naive UTC，比较前先转换为本地时间。
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Report
from app.models.report import ReportStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

LOCK_KEY = "insight:sched:lock:{report_id}"
LOCK_TTL = 600  # 派发锁（秒）：覆盖派发到状态置为 generating 的窗口


def _utc_to_local(dt: datetime | None) -> datetime | None:
    """naive UTC → naive 本地时间（用系统时区偏移换算）。"""
    if dt is None:
        return None
    offset = datetime.now() - datetime.utcnow()
    return dt + offset


def _first_schedule_cron(config: dict | None) -> str | None:
    """取报告中第一个非手动的调度 cron（多模块各有调度时，整报告一次生成）。"""
    for module in (config or {}).get("modules") or []:
        schedule = module.get("schedule") or {}
        cron = (schedule.get("cron") or "").strip()
        if schedule.get("type") not in (None, "", "manual") and cron:
            return cron
    return None


def _cron_due(cron: str, last_generated_utc: datetime | None) -> bool:
    """cron 最近一次触发时间是否晚于报告上次生成时间（即存在待执行的调度）。"""
    try:
        import croniter
    except ImportError:  # pragma: no cover
        logger.warning("croniter 未安装，定时报告调度不可用（pip install croniter）")
        return False
    now_local = datetime.now()
    try:
        prev_fire = croniter.croniter(cron, now_local).get_prev(datetime)
    except (ValueError, KeyError):
        logger.warning("无效的 cron 表达式，已跳过: %r", cron)
        return False
    last_local = _utc_to_local(last_generated_utc)
    if last_local is None:
        return True
    return prev_fire > last_local


def _acquire_dispatch_lock(report_id) -> bool:
    """派发锁：避免扫描周期内重复派发同一报告。"""
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        try:
            ok = r.set(LOCK_KEY.format(report_id=report_id), "1", nx=True, ex=LOCK_TTL)
        finally:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass
        return bool(ok)
    except Exception:  # noqa: BLE001
        # Redis 不可用时放行，由报告状态检查兜底防重
        return True


async def _scan_due_reports() -> dict:
    dispatched = 0
    skipped = 0
    async with SessionLocal() as db:
        reports = (
            await db.execute(
                select(Report).where(
                    Report.is_active.is_(True),
                )
            )
        ).scalars().all()
        for report in reports:
            if report.status == ReportStatus.GENERATING.value:
                continue
            cron = _first_schedule_cron(report.config)
            if not cron:
                continue
            try:
                if not _cron_due(cron, report.last_generated_at):
                    continue
            except Exception:  # noqa: BLE001
                logger.exception("评估报告调度失败: %s", report.id)
                continue
            if not _acquire_dispatch_lock(report.id):
                skipped += 1
                continue
            # 延迟导入避免循环依赖
            from app.tasks.generate_report import scheduled_generate_task

            scheduled_generate_task.delay(str(report.id))
            dispatched += 1
            logger.info("定时调度派发报告 %s (cron=%s)", report.id, cron)
    return {"total": len(reports), "dispatched": dispatched, "locked": skipped}


@celery_app.task(name="app.tasks.report_scheduler.scan_due_reports")
def scan_due_reports() -> dict:
    """每分钟扫描到期的报告调度并派发生成任务。"""
    if not settings.REPORT_SCHEDULER_ENABLED:
        return {"status": "disabled"}
    return asyncio.run(_scan_due_reports())
