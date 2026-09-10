"""邮件模块：发送、记录查询、单条详情、终止、重发、通讯录、WebSocket 进度。"""
import json
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_current_user_ws, get_db
from app.core.config import settings
from app.core.exceptions import AuthError, NotFoundError
from app.core.response import ApiResponse, success
from app.db.operation_log import log_operation
from app.db.session import SessionLocal
from app.models import EmailTask, Report, User
from app.schemas.email import EmailCreateRequest, EmailTaskData
from app.services.access import (
    can_view,
    ensure_can_view,
    load_report_or_404,
    ensure_can_manage,
)
from app.services.email import (
    EMAIL_PROGRESS_PREFIX,
    create_email_task,
    get_email_progress_snapshot,
    request_email_cancel,
    terminal_phase,
)
from app.models.email_task import EmailTaskStatus

router = APIRouter(tags=["邮件"])


def _serialize_task(t: EmailTask) -> dict:
    """邮件任务序列化（列表/详情共用）。"""
    return {
        "id": str(t.id),
        "report_id": str(t.report_id) if t.report_id else None,
        "report_title": t.report.title if t.report else None,
        "recipients": t.recipients,
        "formats": t.formats,
        "version": t.version,
        "status": t.status,
        "attempts": t.attempts,
        "deliveries": t.deliveries or [],
        "trigger_type": t.trigger_type,
        "cancel_requested_at": t.cancel_requested_at,
        "scheduled_at": t.scheduled_at,
        "sent_at": t.sent_at,
        "error_msg": t.error_msg,
        "created_at": t.created_at,
    }


@router.post("/reports/{report_id}/email", response_model=ApiResponse, summary="发送报告邮件")
async def send_report_email(
    report_id: uuid.UUID,
    body: EmailCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_view(report, user)

    task = await create_email_task(
        db,
        report=report,
        recipients=body.recipients,
        formats=body.formats,
        version=body.version,
        scheduled_at=body.scheduled_at,
    )

    await log_operation(
        db,
        user=user,
        action="email.send",
        resource_type="report",
        resource_id=report.id,
        detail={
            "task_id": str(task.id),
            "recipients": body.recipients,
            "formats": body.formats,
            "version": body.version,
            "scheduled_at": str(body.scheduled_at) if body.scheduled_at else None,
        },
    )
    await db.commit()
    return success(data=EmailTaskData(task_id=task.id, status=task.status))


@router.get("/email/tasks", response_model=ApiResponse, summary="邮件发送记录")
async def list_email_tasks(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    report_id: uuid.UUID | None = None,
    keyword: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    # 权限范围：我的报告 / 本部门报告 / 全部（超级管理员）
    if user.role == "super_admin":
        report_sub = select(Report.id)
    elif user.role == "dept_admin" and user.department_id:
        report_sub = select(Report.id).where(Report.department_id == user.department_id)
    elif user.department_id:
        report_sub = select(Report.id).where(Report.owner_id == user.id)
    else:
        report_sub = select(Report.id).where(Report.owner_id == user.id)

    base = select(EmailTask).options(selectinload(EmailTask.report)).where(
        EmailTask.report_id.in_(report_sub)
    )
    if status:
        base = base.where(EmailTask.status == status)
    if report_id is not None:
        base = base.where(EmailTask.report_id == report_id)
    if keyword:
        # 按报告标题模糊搜索
        title_sub = select(Report.id).where(Report.title.ilike(f"%{keyword}%"))
        base = base.where(EmailTask.report_id.in_(title_sub))

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.order_by(EmailTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize_task(t) for t in rows]
    return success(data={"list": items, "total": total or 0, "page": page, "page_size": page_size})


async def _load_task_for_user(
    db: AsyncSession, task_id: uuid.UUID, user: User
) -> EmailTask:
    """按权限加载邮件任务（可查看其关联报告的用户可见）。"""
    task = await db.scalar(
        select(EmailTask)
        .options(selectinload(EmailTask.report))
        .where(EmailTask.id == task_id)
    )
    if task is None:
        raise NotFoundError("邮件任务不存在")
    report = await db.get(Report, task.report_id) if task.report_id else None
    if report is None or not can_view(report, user):
        raise NotFoundError("邮件任务不存在")
    return task


@router.get("/email/tasks/{task_id}", response_model=ApiResponse, summary="邮件任务详情")
async def get_email_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    task = await _load_task_for_user(db, task_id, user)
    return success(data=_serialize_task(task))


@router.post("/email/tasks/{task_id}/cancel", response_model=ApiResponse, summary="终止邮件任务")
async def cancel_email_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """终止邮件任务：排队/定时的直接置为 cancelled；正在发送的通过标记中断。"""
    from app.core.utils import utcnow
    from app.services.email import _push_progress

    task = await db.get(EmailTask, task_id)
    if task is None:
        raise NotFoundError("邮件任务不存在")
    report = await db.get(Report, task.report_id) if task.report_id else None
    if report is None:
        raise NotFoundError("邮件任务不存在")
    ensure_can_manage(report, user)

    if task.status in (EmailTaskStatus.SENT.value, EmailTaskStatus.CANCELLED.value):
        return success(message="任务已结束，无需终止")
    if task.status == EmailTaskStatus.FAILED.value:
        return success(message="任务已失败，无需终止")

    task.cancel_requested_at = utcnow()
    request_email_cancel(task.id)
    # 设置终止标记后立即在 DB 标记终止（发送循环在每封之间感知标记并中断）
    task.status = EmailTaskStatus.CANCELLED.value
    task.error_msg = "用户手动终止"
    task.deliveries = [
        {**d, "status": "cancelled", "error_msg": "任务已终止"}
        if d.get("status") == "pending"
        else d
        for d in (task.deliveries or [])
    ]
    _push_progress(task, "cancelled", 100, "任务已终止")

    await log_operation(
        db,
        user=user,
        action="email.cancel",
        resource_type="report",
        resource_id=report.id,
        detail={"task_id": str(task.id)},
    )
    await db.commit()
    return success(message="任务已终止")



@router.post("/email/tasks/{task_id}/resend", response_model=ApiResponse, summary="重发邮件任务")
async def resend_email_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """按原收件人/格式/版本新建一条发送任务并立即发送。"""
    old = await _load_task_for_user(db, task_id, user)
    report = await db.get(Report, old.report_id) if old.report_id else None
    if report is None:
        raise NotFoundError("关联报告不存在")
    ensure_can_manage(report, user)

    task = await create_email_task(
        db,
        report=report,
        recipients=old.recipients,
        formats=old.formats,
        version=old.version,
        trigger_type="manual",
    )
    await log_operation(
        db,
        user=user,
        action="email.resend",
        resource_type="report",
        resource_id=report.id,
        detail={"old_task_id": str(old.id), "new_task_id": str(task.id)},
    )
    await db.commit()
    return success(data=EmailTaskData(task_id=task.id, status=task.status))


@router.get("/email/contacts", response_model=ApiResponse, summary="可选择的收件人通讯录")
async def email_contacts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """当前用户可选收件人：超管=全部活跃用户；部门管理员/普通用户=本部门活跃用户。"""
    if user.role == "super_admin":
        rows = await db.scalars(select(User).where(User.is_active.is_(True)))
    elif user.department_id:
        rows = await db.scalars(
            select(User).where(
                User.department_id == user.department_id, User.is_active.is_(True)
            )
        )
    else:
        rows = await db.scalars(select(User).where(User.id == user.id))

    contacts = [{"id": str(u.id), "username": u.username, "email": u.email} for u in rows]
    return success(data={"contacts": contacts})


@router.websocket("/email/tasks/{task_id}/progress")
async def email_progress_ws(websocket: WebSocket, task_id: uuid.UUID) -> None:
    """WebSocket 实时推送邮件发送进度（复用 Redis 快照 + 频道）。"""
    await websocket.accept()
    token = websocket.query_params.get("token", "")
    try:
        async with SessionLocal() as db:
            user = await get_current_user_ws(token, db)
            task = await db.get(EmailTask, task_id)
            if task is None:
                await websocket.send_json(
                    {"phase": "failed", "progress": 0, "message": "邮件任务不存在"}
                )
                await websocket.close()
                return
            report = await db.get(Report, task.report_id) if task.report_id else None
            if report is None or not can_view(report, user):
                await websocket.close(code=4403, reason="无权限")
                return
            terminal = terminal_phase(task.status)
            last = get_email_progress_snapshot(task.id)
            if last:
                await websocket.send_json(last)
            if terminal:
                if not last:
                    await websocket.send_json(
                        {
                            "phase": terminal,
                            "progress": 100 if terminal == "complete" else 0,
                            "message": "邮件任务已结束",
                            "task_id": str(task.id),
                        }
                    )
                await websocket.close()
                return

        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        channel = EMAIL_PROGRESS_PREFIX + str(task_id)
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    await websocket.send_text(message["data"])
                    data = json.loads(message["data"])
                    if data.get("phase") in ("complete", "failed", "cancelled"):
                        break
        except WebSocketDisconnect:
            pass
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                await r.aclose()
            except Exception:  # noqa: BLE001
                pass
    except AuthError:
        await websocket.close(code=4401, reason="未认证")
    except Exception:  # noqa: BLE001
        await websocket.close()

