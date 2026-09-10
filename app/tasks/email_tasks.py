"""邮件发送 Celery 任务：单任务发送 + 定时任务到点扫描派发。"""
import asyncio
import uuid

from app.db.session import SessionLocal
from app.models import EmailTask
from app.services.email import claim_due_email_tasks, perform_email_send
from app.tasks.celery_app import celery_app


@celery_app.task(
    name="app.tasks.email_tasks.send_email_task",
    bind=True,
    max_retries=2,
)
def send_email_task(self, email_task_id: str) -> dict:
    """异步执行真实邮件发送（复用 services.email.execute_email_send）。"""
    asyncio.run(_send(email_task_id))
    return {"email_task_id": email_task_id}


@celery_app.task(
    name="app.tasks.email_tasks.process_scheduled_emails_task",
    bind=True,
    max_retries=1,
)
def process_scheduled_emails_task(self) -> dict:
    """定时扫描已到期（scheduled_at <= now）的 pending 邮件任务并派发（Celery Beat 调用）。

    与进程内调度器并发安全：claim_due_email_tasks 使用原子抢占。
    """
    return asyncio.run(_dispatch_due())


async def _dispatch_due() -> dict:
    async with SessionLocal() as db:
        claimed = await claim_due_email_tasks(db)
    for task_id in claimed:
        send_email_task.apply_async(args=[str(task_id)])
    return {"dispatched": len(claimed)}


async def _send(email_task_id: str) -> None:
    async with SessionLocal() as db:
        task = await db.get(EmailTask, uuid.UUID(email_task_id))
        if task is None:
            return
        await perform_email_send(db, task)
