"""部门管理模块请求/响应模式。"""
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class DepartmentUserCreate(BaseModel):
    """POST /department/users 请求体。"""

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[\u4e00-\u9fa5a-zA-Z0-9_]+$",
        description="用户名：3-50位中英文、数字或下划线",
    )
    email: EmailStr
    role: Literal["user", "dept_admin"] = "user"
    password: str | None = Field(
        default=None, min_length=8, max_length=128,
        description="默认密码（可选），缺省使用占位密码 User@2026",
    )


class DepartmentUserUpdate(BaseModel):
    """PUT /department/users/{id} 请求体。"""

    role: Literal["user", "dept_admin"]


class DepartmentUserItem(BaseModel):
    """部门用户列表项。"""

    id: uuid.UUID
    username: str
    email: str
    role: str
    is_active: bool
    report_count: int = 0
    last_active: str | None = None


class DepartmentModelConfigSave(BaseModel):
    """PUT /department/model-config 请求体（本部门公共模型配置，全字段可选）。"""

    name: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    api_key: str | None = Field(
        default=None,
        description="API 密钥；留空或提交脱敏值（含 ****）表示不修改",
    )
    model_name: str | None = None
