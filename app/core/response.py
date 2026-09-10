"""统一 API 响应封装（code/message/data）。"""
from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一响应格式：{"code": 0, "message": "success", "data": ...}"""

    code: int = 0
    message: str = "success"
    data: Any = None


def success(data: Any = None, message: str = "success") -> ApiResponse:
    """构造成功响应。"""
    return ApiResponse(code=0, message=message, data=data)
