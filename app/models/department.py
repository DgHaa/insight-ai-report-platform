"""部门表 ORM 模型。"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.report import Report
    from app.models.user import User


class Department(SoftDeleteMixin, TimestampMixin, Base):
    """部门表（departments）。"""

    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门名称")
    code: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True, comment="部门编码（唯一）"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="部门描述")
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # 循环外键（departments.admin_id -> users.id），
        # use_alter=True：建表后通过 ALTER 追加外键约束，解决环状依赖。
        ForeignKey("users.id", use_alter=True, name="fk_departments_admin_id"),
        nullable=True,
        index=True,
        comment="部门管理员用户ID",
    )

    # ---- 关系 ----
    users: Mapped[list[User]] = relationship(
        back_populates="department",
        foreign_keys="User.department_id",
    )
    admin: Mapped[User | None] = relationship(
        back_populates="admin_department",
        foreign_keys=[admin_id],
        post_update=True,
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="department",
        foreign_keys="Report.department_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Department code={self.code} name={self.name}>"
