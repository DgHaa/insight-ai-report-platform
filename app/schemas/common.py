"""通用响应模式。"""
from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一响应格式：{"code": 0, "message": "success", "data": ...}"""

    code: int = 0
    message: str = "success"
    data: Any = None


class PageInfo(BaseModel):
    """分页信息。"""

    list: list[Any]
    total: int
    page: int
    page_size: int
