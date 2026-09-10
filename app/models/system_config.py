"""系统配置表 ORM 模型（key-value JSONB）。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemConfig(Base):
    """系统配置表（system_configs）。

    以 key-value 形式存储系统级配置（如 SMTP、并发上限、任务超时等），
    值使用 JSONB。当前使用固定 key = "system" 存放全部系统配置。
    """

    __tablename__ = "system_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    key: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True, comment="配置键（唯一）"
    )
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="配置值（JSONB）")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_system_configs_updated_by"),
        nullable=True,
        comment="最后更新人",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SystemConfig key={self.key}>"
