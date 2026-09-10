"""通用 ORM 混入类：创建时间戳 + 软删除标记。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, func, text
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """创建时间列（TIMESTAMP DEFAULT NOW()，与设计文档一致）。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )


class SoftDeleteMixin:
    """软删除标记列（is_active = False 表示逻辑删除）。"""

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        default=True,
        comment="软删除标记（true=有效，false=已逻辑删除）",
    )
