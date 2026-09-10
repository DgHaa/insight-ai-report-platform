"""操作日志写入服务。"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OperationLog, User


async def log_operation(
    db: AsyncSession,
    *,
    action: str,
    user: User | None = None,
    username: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> OperationLog:
    """写入一条操作日志（仅加入会话，由调用方统一 commit）。"""
    log = OperationLog(
        user_id=user.id if user is not None else None,
        username=username or (user.username if user is not None else None),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail=detail,
        ip_address=ip_address,
    )
    db.add(log)
    await db.flush()
    return log
