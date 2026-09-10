"""系统配置服务（system_configs 表，key = "system"）。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.models import SystemConfig

SYSTEM_CONFIG_KEY = "system"

DEFAULT_SYSTEM_CONFIG: dict = {
    "smtp": {
        "host": "",
        "port": 587,
        "username": "",
        "password": "",
        "tls": True,
        "sender": "",
    },
    "max_concurrent_tasks": 5,
    "task_timeout_seconds": 1800,
    # 模拟发送开关：True 时不真正调用 SMTP（开发环境默认开启，页面可关闭以真实发信）
    "email_simulate": True,
}


async def get_system_config(db: AsyncSession) -> dict:
    """读取系统配置；表中无记录时返回默认值。"""
    row = await db.scalar(
        select(SystemConfig).where(SystemConfig.key == SYSTEM_CONFIG_KEY)
    )
    if row is None:
        return dict(DEFAULT_SYSTEM_CONFIG)
    return row.value or {}


async def save_system_config(db: AsyncSession, data: dict, updated_by) -> dict:
    """合并并保存系统配置，返回合并后的完整配置。"""
    row = await db.scalar(
        select(SystemConfig).where(SystemConfig.key == SYSTEM_CONFIG_KEY)
    )
    current = row.value if row is not None else {}
    merged = {**DEFAULT_SYSTEM_CONFIG, **current, **data}
    if row is None:
        row = SystemConfig(key=SYSTEM_CONFIG_KEY, value=merged, updated_by=updated_by)
        db.add(row)
    else:
        row.value = merged
        row.updated_by = updated_by
        row.updated_at = utcnow()
    await db.commit()
    return merged
