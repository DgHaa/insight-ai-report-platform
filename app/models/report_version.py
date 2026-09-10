"""报告历史版本表 ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin

if TYPE_CHECKING:
    from app.models.report import Report
    from app.models.report_style import ReportStyle


class ReportVersion(SoftDeleteMixin, Base):
    """报告历史版本表（report_versions）。

    注意：设计文档中本表无 created_at，只有 generated_at（生成时间）。
    """

    __tablename__ = "report_versions"
    __table_args__ = (
        Index("idx_versions_report", "report_id"),
        # 同一报告下版本号唯一（对应迁移中的唯一索引 idx_versions_report_number）
        Index("idx_versions_report_number", "report_id", "version_number", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", name="fk_report_versions_report_id", ondelete="CASCADE"),
        nullable=True,
        comment="所属报告ID",
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    content: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, comment="报告内容（JSONB）"
    )
    config_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, comment="生成时的配置快照（JSONB）"
    )
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="使用的模型")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="生成状态")
    style_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "report_styles.id", name="fk_report_versions_style_id", ondelete="SET NULL"
        ),
        nullable=True,
        comment="生成时使用的报告风格ID（历史版本保留当时风格）",
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="内容哈希")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), comment="生成时间"
    )

    # ---- 关系 ----
    report: Mapped[Report | None] = relationship(back_populates="versions")
    style: Mapped[ReportStyle | None] = relationship(foreign_keys=[style_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReportVersion report_id={self.report_id} v{self.version_number}>"
