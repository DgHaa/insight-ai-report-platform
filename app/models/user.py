"""用户表 ORM 模型。"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.department import Department
    from app.models.report import Report
    from app.models.user_data_source_credential import UserDataSourceCredential


class UserRole(str, Enum):
    """用户角色（与设计文档一致）。"""

    SUPER_ADMIN = "super_admin"  # 超级管理员
    DEPT_ADMIN = "dept_admin"  # 部门管理员
    USER = "user"  # 普通用户


class User(SoftDeleteMixin, TimestampMixin, Base):
    """用户表（users）。"""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True, comment="用户名"
    )
    email: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True, comment="邮箱"
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", name="fk_users_department_id"),
        nullable=True,
        index=True,
        comment="所属部门ID",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'user'"),
        default=UserRole.USER.value,
        comment="角色：super_admin / dept_admin / user",
    )

    # ---- 关系 ----
    department: Mapped[Department | None] = relationship(
        back_populates="users",
        foreign_keys=[department_id],
    )
    admin_department: Mapped[Department | None] = relationship(
        back_populates="admin",
        foreign_keys="Department.admin_id",
        post_update=True,
    )
    reports: Mapped[list[Report]] = relationship(back_populates="owner")
    credentials: Mapped[list[UserDataSourceCredential]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User username={self.username} role={self.role}>"
