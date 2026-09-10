"""邮件任务表 ORM 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.report import Report


class EmailTriggerType(str, Enum):
    """邮件触发方式。"""

    AUTO = "auto"  # 生成后自动发送
    MANUAL = "manual"  # 手动发送
    SCHEDULED = "scheduled"  # 定时发送


class EmailTaskStatus(str, Enum):
    """邮件任务状态。"""

    PENDING = "pending"    # 排队中 / 定时未到
    SENDING = "sending"    # 正在发送
    SENT = "sent"          # 已发送（可能部分收件人失败，见 deliveries）
    FAILED = "failed"      # 发送失败
    CANCELLED = "cancelled"  # 用户终止


class EmailTask(SoftDeleteMixin, TimestampMixin, Base):
    """邮件任务表（email_tasks）。"""

    __tablename__ = "email_tasks"
    __table_args__ = (
        Index("idx_email_report", "report_id"),
        Index("idx_email_status", "status"),
        # 定时派发抢占：WHERE status='pending' AND scheduled_at <= now()
        Index("idx_email_status_scheduled", "status", "scheduled_at"),
        # 列表按创建时间倒序
        Index("idx_email_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", name="fk_email_tasks_report_id"),
        nullable=True,
        comment="所属报告ID",
    )
    trigger_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="触发方式：auto / manual / scheduled"
    )
    recipients: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, comment="收件人列表（TEXT[]）"
    )
    formats: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, comment="附件格式（TEXT[]）：['pdf', 'docx', 'md']"
    )
    version: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="发送的报告版本号（为空表示发送当前版本）"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
        default=EmailTaskStatus.PENDING.value,
        comment="状态：pending / sending / sent / failed / cancelled",
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0, comment="发送尝试次数"
    )
    deliveries: Mapped[list] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        comment="逐收件人发送结果（JSONB）：[{recipient, status, error_msg, sent_at}]",
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, comment="终止请求时间"
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, comment="计划发送时间"
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, comment="实际发送时间"
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")

    # ---- 关系 ----
    report: Mapped[Report | None] = relationship(back_populates="email_tasks")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EmailTask id={self.id} status={self.status}>"
