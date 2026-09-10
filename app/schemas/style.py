"""报告风格模块请求/响应模式。"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StyleCreate(BaseModel):
    """POST /styles 请求体。"""

    name: str = Field(min_length=1, max_length=100, description="风格名称")
    config: dict[str, Any] = Field(default_factory=dict, description="样式属性（CSS 变量键值对）")


class StyleUpdate(BaseModel):
    """PUT /styles/{id} 请求体（全字段可选，部分更新）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, Any] | None = None
    is_shared: bool | None = None  # true=设为部门共享；false=取消共享


class StyleData(BaseModel):
    """风格响应数据。"""

    id: Any
    name: str
    type: str  # builtin / custom
    config: dict[str, Any]
    owner_id: Any = None
    owner_name: str | None = None
    department_id: Any = None
    department_name: str | None = None
    is_shared: bool
    can_edit: bool = False
    can_delete: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
