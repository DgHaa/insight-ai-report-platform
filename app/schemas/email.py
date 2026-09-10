"""邮件模块请求/响应模式。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class EmailCreateRequest(BaseModel):
    """POST /reports/{id}/email 请求体。"""

    recipients: list[str] = Field(min_length=1, max_length=50)
    formats: list[str] = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)
    scheduled_at: datetime | None = None

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, v: list[str]) -> list[str]:
        allowed = {"pdf", "docx", "md"}
        for fmt in v:
            if fmt not in allowed:
                raise ValueError(f"不支持的附件格式: {fmt}（仅支持 pdf/docx/md）")
        return list(dict.fromkeys(v))


class EmailTaskData(BaseModel):
    """发送邮件响应数据。"""

    task_id: uuid.UUID
    status: str
