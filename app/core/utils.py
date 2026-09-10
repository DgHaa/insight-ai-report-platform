"""通用工具函数。"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回不带时区的 UTC 当前时间（与数据库 TIMESTAMP 列一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
