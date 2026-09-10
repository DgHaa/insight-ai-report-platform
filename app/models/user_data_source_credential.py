"""用户数据源凭证表 ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserDataSourceCredential(SoftDeleteMixin, TimestampMixin, Base):
    """用户数据源凭证表（user_data_source_credentials）。"""

    __tablename__ = "user_data_source_credentials"
    __table_args__ = (
        Index("idx_credentials_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_credentials_user_id", ondelete="CASCADE"),
        nullable=True,
        comment="所属用户ID",
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="凭证名称")
    proxy: Mapped[str | None] = mapped_column(Text, nullable=True, comment="代理配置（加密存储）")
    cookies: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Cookie（加密存储）")
    custom_headers: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="自定义请求头（JSONB）"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # ---- 关系 ----
    user: Mapped[User | None] = relationship(back_populates="credentials")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserDataSourceCredential id={self.id} name={self.name!r}>"
