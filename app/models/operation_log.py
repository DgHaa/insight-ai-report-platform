"""操作日志表 ORM 模型（关键操作审计）。"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class OperationLog(TimestampMixin, Base):
    """操作日志表（operation_logs）。"""

    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("idx_logs_user", "user_id"),
        Index("idx_logs_action", "action"),
        Index("idx_logs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_operation_logs_user_id"),
        nullable=True,
        comment="操作用户ID",
    )
    username: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="操作用户名（冗余）")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作动作")
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="资源类型")
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="资源ID")
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="操作详情（JSONB）")
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, comment="来源IP")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OperationLog action={self.action} user={self.username}>"
