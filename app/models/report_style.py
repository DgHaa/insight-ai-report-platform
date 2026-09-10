"""报告风格表 ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.department import Department
    from app.models.user import User


class ReportStyle(SoftDeleteMixin, TimestampMixin, Base):
    """报告风格表（report_styles）。

    - type='builtin'：系统内置风格（由迁移脚本预置，不可编辑/删除）；
    - type='custom'：用户自定义风格；
      - is_shared=false：仅创建者个人可见；
      - is_shared=true：对 department_id 指定部门共享（仅部门管理员可共享）。
    """

    __tablename__ = "report_styles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="风格名称")
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'custom'"),
        comment="风格类型：builtin / custom",
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, comment="样式属性（CSS 变量键值对，JSONB）"
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_report_styles_owner_id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者用户ID（内置风格为空）",
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "departments.id",
            name="fk_report_styles_department_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        comment="共享目标部门ID（is_shared=true 时生效）",
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
        comment="是否对部门共享",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # ---- 关系 ----
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    department: Mapped[Department | None] = relationship(foreign_keys=[department_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReportStyle id={self.id} name={self.name!r} type={self.type}>"
