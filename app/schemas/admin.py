"""系统管理模块请求/响应模式。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WhitelistCreate(BaseModel):
    """POST /admin/email-whitelist 请求体。"""

    domain: str = Field(min_length=1, max_length=255)
    description: str | None = None

    @classmethod
    def normalize_domain(cls, domain: str) -> str:
        """规范化域名：统一小写，自动补 @ 前缀（如 partner.com -> @partner.com）。"""
        domain = domain.strip().lower().lstrip("@")
        return f"@{domain}"


class WhitelistItem(BaseModel):
    """白名单列表项。"""

    id: uuid.UUID
    domain: str
    description: str | None = None
    created_at: datetime


class SmtpConfig(BaseModel):
    """SMTP 配置。"""

    host: str = ""
    port: int = 587
    username: str = ""
    password: str | None = None  # GET 时不回显完整密码
    tls: bool = True
    sender: str = ""


class SystemConfigUpdate(BaseModel):
    """PUT /admin/system/config 请求体（全字段可选）。"""

    smtp: SmtpConfig | None = None
    max_concurrent_tasks: int | None = Field(default=None, ge=1, le=50)
    task_timeout_seconds: int | None = Field(default=None, ge=60, le=7200)
    # 邮件模拟发送开关（True 时不真正调用 SMTP）
    email_simulate: bool | None = None


class SmtpTestRequest(BaseModel):
    """POST /admin/system/config/test-smtp 请求体。"""

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = ""
    password: str = ""
    tls: bool = True


class SystemConfigData(BaseModel):
    """系统配置响应数据。"""

    smtp: SmtpConfig
    max_concurrent_tasks: int
    task_timeout_seconds: int
    email_simulate: bool


class DepartmentModelConfigCreate(BaseModel):
    """POST /admin/departments/{id}/model-configs 请求体。"""

    name: str = Field(min_length=1, max_length=100)
    provider: str | None = Field(default=None, max_length=50)
    endpoint: str | None = None
    api_key: str | None = Field(default=None, max_length=512)
    model_name: str | None = Field(default=None, max_length=100)


class DepartmentModelConfigUpdate(BaseModel):
    """PUT /admin/departments/{id}/model-configs/{cid} 请求体（全字段可选）。

    api_key 传 None 或空字符串表示不修改（不覆盖已保存的密钥）。
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = Field(default=None, max_length=50)
    endpoint: str | None = None
    api_key: str | None = Field(default=None, max_length=512)
    model_name: str | None = Field(default=None, max_length=100)
