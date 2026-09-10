"""数据源凭证模块请求/响应模式。"""
from typing import Any

from pydantic import BaseModel, Field


class CredentialCreate(BaseModel):
    """POST /credentials 请求体。"""

    name: str = Field(min_length=1, max_length=100)
    proxy: str | None = None
    cookies: str | None = None
    custom_headers: dict[str, Any] | None = None


class CredentialUpdate(BaseModel):
    """PUT /credentials/{id} 请求体（全字段可选）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    proxy: str | None = None
    cookies: str | None = None
    custom_headers: dict[str, Any] | None = None
