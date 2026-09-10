"""报告管理模块请求/响应模式。"""
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ReportCreate(BaseModel):
    """POST /reports 请求体。"""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    type: Literal["department", "personal"] = "personal"
    is_public: bool = False
    tags: list[str] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    style_id: uuid.UUID | None = None  # 报告风格（为空则使用默认科技蓝）

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: dict) -> dict:
        """config 必须包含 modules 列表（详见设计文档报告模块配置）。"""
        if "modules" not in v:
            raise ValueError("config 必须包含 modules 列表")
        if not isinstance(v["modules"], list):
            raise ValueError("config.modules 必须是列表")
        return v


class ReportUpdate(BaseModel):
    """PUT /reports/{id} 请求体（全字段可选，部分更新）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_public: bool | None = None
    tags: list[str] | None = None
    config: dict[str, Any] | None = None
    style_id: uuid.UUID | None = None

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: dict | None) -> dict | None:
        if v is not None:
            if "modules" not in v or not isinstance(v["modules"], list):
                raise ValueError("config 必须包含 modules 列表")
        return v


class ReportCreateData(BaseModel):
    """创建报告响应数据。"""

    id: Any
    created_at: Any


class ReportUpdateData(BaseModel):
    """更新报告响应数据。"""

    id: Any
    updated_at: Any
