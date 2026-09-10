"""报告表 ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.department import Department
    from app.models.email_task import EmailTask
    from app.models.generation_task import GenerationTask
    from app.models.report_style import ReportStyle
    from app.models.report_version import ReportVersion
    from app.models.user import User


class ReportType(str, Enum):
    """报告类型。"""

    DEPARTMENT = "department"  # 部门报告
    PERSONAL = "personal"  # 个人报告


class ReportStatus(str, Enum):
    """报告状态。"""

    DRAFT = "draft"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    TERMINATED = "terminated"


class Report(SoftDeleteMixin, TimestampMixin, Base):
    """报告表（reports）。"""

    __tablename__ = "reports"
    __table_args__ = (
        Index("idx_reports_department", "department_id"),
        Index("idx_reports_owner", "owner_id"),
        Index("idx_reports_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="报告标题")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="报告描述")
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="报告类型：department / personal"
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", name="fk_reports_department_id"),
        nullable=True,
        comment="所属部门ID",
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_reports_owner_id"),
        nullable=True,
        comment="创建者用户ID",
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False, comment="是否公开"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'draft'"),
        default=ReportStatus.DRAFT.value,
        comment="报告状态：draft/generating/completed/failed/timeout/terminated",
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, comment="报告模块配置（JSONB）"
    )
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0, comment="当前版本号"
    )
    generate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0, comment="生成次数"
    )
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True, comment="标签（TEXT[]）"
    )
    style_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_styles.id", name="fk_reports_style_id", ondelete="SET NULL"),
        nullable=True,
        comment="当前使用的报告风格ID（为空则使用默认科技蓝风格）",
    )
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, comment="最近生成时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # ---- 关系 ----
    owner: Mapped[User | None] = relationship(back_populates="reports", foreign_keys=[owner_id])
    department: Mapped[Department | None] = relationship(
        back_populates="reports", foreign_keys=[department_id]
    )
    style: Mapped[ReportStyle | None] = relationship(foreign_keys=[style_id])
    versions: Mapped[list[ReportVersion]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ReportVersion.version_number",
    )
    generation_tasks: Mapped[list[GenerationTask]] = relationship(back_populates="report")
    email_tasks: Mapped[list[EmailTask]] = relationship(back_populates="report")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Report id={self.id} title={self.title!r}>"
