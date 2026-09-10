"""ORM 对象 → 字典序列化。"""
import copy
import logging

from sqlalchemy import inspect as sa_inspect

from app.core.masking import mask_secret
from app.models import Report

logger = logging.getLogger(__name__)


def _relation_name(obj: object, rel_name: str) -> str | None:
    """安全读取关系的 name 字段。

    异步会话下未预加载的关系一旦访问会触发懒加载并抛 MissingGreenlet /
    DetachedInstanceError。这里先判断该属性是否已加载，避免序列化器因
    调用方忘记 selectinload 而整体报错。
    """
    try:
        state = sa_inspect(obj)
        if rel_name in state.unloaded:
            logger.debug("关系未预加载，序列化时返回 None: %s", rel_name)
            return None
        rel = getattr(obj, rel_name)
        return rel.name if rel else None
    except Exception:  # noqa: BLE001
        logger.debug("读取关系失败，序列化时返回 None: %s", rel_name, exc_info=True)
        return None


def mask_report_config(config: dict | None) -> dict | None:
    """对报告配置中的敏感字段进行脱敏（非所有者视角）。

    将每个模块 model_config.api_key 替换为脱敏字符串，
    前端在任何情况下都收不到明文密钥。
    """
    if not isinstance(config, dict):
        return config
    masked = copy.deepcopy(config)
    for module in masked.get("modules") or []:
        mc = module.get("model_config")
        if isinstance(mc, dict) and mc.get("api_key"):
            # 统一走 app.core.masking.mask_secret，避免多套掩码规则
            mc["api_key"] = mask_secret(mc["api_key"])
    return masked


def report_to_dict(
    report: Report,
    include_config: bool = False,
    mask_sensitive: bool = False,
) -> dict:
    """将报告对象序列化为接口响应字典。

    建议调用方预先加载 report.department / report.owner 关系（selectinload）；
    未预加载时不会抛错，对应字段返回 None（见 _relation_name）。

    - include_config=True 时附带 config 字段；
    - mask_sensitive=True 时对 config 中的 api_key 等敏感信息脱敏
      （用于非所有者查看详情）。
    """
    data: dict = {
        "id": str(report.id),
        "title": report.title,
        "description": report.description,
        "type": report.type,
        "department_id": str(report.department_id) if report.department_id else None,
        "department_name": _relation_name(report, "department"),
        "owner_id": str(report.owner_id) if report.owner_id else None,
        "owner_name": _relation_name(report, "owner"),
        "is_public": report.is_public,
        "status": report.status,
        "current_version": report.current_version,
        "generate_count": report.generate_count,
        "tags": report.tags,
        "style_id": str(report.style_id) if report.style_id else None,
        "last_generated_at": report.last_generated_at,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }
    if include_config:
        data["config"] = (
            mask_report_config(report.config) if mask_sensitive else report.config
        )
    return data
