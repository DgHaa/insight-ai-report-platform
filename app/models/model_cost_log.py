"""模型成本日志表 ORM 模型。"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.generation_task import GenerationTask


class ModelCostLog(SoftDeleteMixin, TimestampMixin, Base):
    """模型成本日志表（model_cost_logs）。"""

    __tablename__ = "model_cost_logs"
    __table_args__ = (
        Index("idx_cost_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generation_tasks.id", name="fk_model_cost_logs_task_id"),
        nullable=True,
        comment="所属生成任务ID",
    )
    model_provider: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="模型提供商"
    )
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="模型名称")
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输入 token 数")
    completion_tokens: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="输出 token 数"
    )
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="总 token 数")
    unit_price_per_1k_tokens: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True, comment="每千 token 单价"
    )
    estimated_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, comment="估算成本"
    )

    # ---- 关系 ----
    task: Mapped[GenerationTask | None] = relationship(back_populates="cost_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ModelCostLog id={self.id} model={self.model_name}>"
