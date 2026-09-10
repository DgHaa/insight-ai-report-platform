"""生成任务表 ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.model_cost_log import ModelCostLog
    from app.models.report import Report


class GenerationTriggerType(str, Enum):
    """生成任务触发方式。"""

    MANUAL = "manual"
    SCHEDULED = "scheduled"


class GenerationTaskStatus(str, Enum):
    """生成任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    TERMINATED = "terminated"


class GenerationTask(SoftDeleteMixin, TimestampMixin, Base):
    """生成任务表（generation_tasks）。"""

    __tablename__ = "generation_tasks"
    __table_args__ = (
        Index("idx_tasks_report", "report_id"),
        Index("idx_tasks_status", "status"),
        # 看板趋势/成功率按时间聚合、详情按时间倒序，补充时间索引
        Index("idx_tasks_created_at", "created_at"),
        Index("idx_tasks_report_created", "report_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", name="fk_generation_tasks_report_id"),
        nullable=True,
        comment="所属报告ID",
    )
    trigger_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="触发方式：manual / scheduled"
    )
    status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="状态：pending/running/success/failed/timeout/terminated",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, comment="开始时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, comment="完成时间"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    worker_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="执行 Worker ID")

    # ---- 关系 ----
    report: Mapped[Report | None] = relationship(back_populates="generation_tasks")
    cost_logs: Mapped[list[ModelCostLog]] = relationship(back_populates="task")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GenerationTask id={self.id} status={self.status}>"
