"""模型成本日志服务。

注意：unit_price 由用户在模块配置中自行填写，平台不做任何确认和保障
（设计文档 1.3.7《模型调用与成本》：成本由用户自行评估，平台不做任何确认和保障）。
"""
import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelCostLog

logger = logging.getLogger(__name__)


def compute_estimated_cost(
    total_tokens: int, unit_price_per_1k: Decimal | float | int | None
) -> Decimal | None:
    """估算成本 = total_tokens / 1000 * unit_price_per_1k（保留 4 位小数）。"""
    if unit_price_per_1k is None or total_tokens <= 0:
        return None
    try:
        price = Decimal(str(unit_price_per_1k))
        return (Decimal(total_tokens) / Decimal(1000) * price).quantize(
            Decimal("0.0001")
        )
    except Exception:  # noqa: BLE001
        logger.warning("成本计算失败: total=%s unit=%s", total_tokens, unit_price_per_1k)
        return None


async def record_model_call(
    db: AsyncSession,
    *,
    task_id,
    provider: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    unit_price_per_1k_tokens=None,
) -> ModelCostLog:
    """记录一次成功的模型调用成本日志（写入 model_cost_logs 表）。"""
    estimated_cost = compute_estimated_cost(total_tokens, unit_price_per_1k_tokens)
    log = ModelCostLog(
        task_id=task_id,
        model_provider=provider,
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        unit_price_per_1k_tokens=unit_price_per_1k_tokens,
        estimated_cost=estimated_cost,
    )
    db.add(log)
    await db.flush()
    #  caller 使用独立会话（async with SessionLocal()）仅用于写这条日志，
    #  若只 flush 不 commit，会话退出即回滚，导致 model_cost_logs 永远为空。
    await db.commit()
    return log
