"""部门公共模型配置表 ORM 模型。

用于存储各部门可复用的默认模型配置（provider / endpoint / api_key / model_name）。
安全要求：api_key 在接口返回时必须脱敏（仅显示前 2 位 + 后 4 位），
任何情况下不返回明文。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class DepartmentModelConfig(SoftDeleteMixin, TimestampMixin, Base):
    """部门公共模型配置表（department_model_configs）。"""

    __tablename__ = "department_model_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", name="fk_dmc_department_id"),
        nullable=False,
        index=True,
        comment="所属部门ID",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="配置名称")
    provider: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="模型提供商"
    )
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True, comment="API 地址")
    api_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="API Key（接口返回时脱敏，不返回明文）"
    )
    model_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="模型名称"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_dmc_created_by"),
        nullable=True,
        comment="创建人用户ID",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
