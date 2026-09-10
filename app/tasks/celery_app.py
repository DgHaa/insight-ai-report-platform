"""Celery 应用配置（Redis broker/backend）。

启动方式：
    celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
    celery -A app.tasks.celery_app beat --loglevel=info
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "insight_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.generate_report",
        "app.tasks.email_tasks",
        "app.tasks.cleanup",
        "app.tasks.report_scheduler",
    ],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,          # 任务完成后才确认，避免执行中丢失
    worker_prefetch_multiplier=1, # 每个 Worker 同时只预取 1 个任务
    result_expires=3600,          # 结果保留 1 小时
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # 每小时清理临时导出文件
        "cleanup-temp-files-every-hour": {
            "task": "app.tasks.cleanup.cleanup_temp_files",
            "schedule": 3600.0,
        },
        # 每分钟扫描并派发到期的定时邮件任务
        "process-scheduled-emails-every-minute": {
            "task": "app.tasks.email_tasks.process_scheduled_emails_task",
            "schedule": 60.0,
        },
        # 每分钟扫描报告模块的 cron 调度并派发生成任务
        "scan-due-report-schedules-every-minute": {
            "task": "app.tasks.report_scheduler.scan_due_reports",
            "schedule": 60.0,
        },
    },
)
