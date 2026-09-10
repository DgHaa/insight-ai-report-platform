"""全局外部邮箱白名单表 ORM 模型。"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class GlobalEmailWhitelist(SoftDeleteMixin, TimestampMixin, Base):
    """全局外部邮箱白名单表（global_email_whitelist）。

    仅超级管理员可维护；所有外发邮件目标地址必须命中白名单域名。
    """

    __tablename__ = "global_email_whitelist"
    __table_args__ = (
        Index("idx_whitelist_domain", "domain", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    domain: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="白名单域名（唯一）"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_whitelist_created_by"),
        nullable=True,
        comment="创建人用户ID",
    )

    # ---- 关系 ----
    creator: Mapped[User | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GlobalEmailWhitelist domain={self.domain}>"
