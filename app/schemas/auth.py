"""认证模块请求/响应模式。"""
import uuid

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """POST /auth/login 请求体（用户名 + 部门，无需密码）。"""

    username: str = Field(min_length=1, max_length=50)
    department_id: uuid.UUID | None = Field(
        default=None,
        description="所属部门ID；超级管理员等无部门账号可不传",
    )


class RegisterRequest(BaseModel):
    """POST /auth/register 请求体（仅用户名 + 部门）。"""

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[\u4e00-\u9fa5a-zA-Z0-9_]+$",
        description="用户名：3-50位中英文、数字或下划线",
    )
    department_id: uuid.UUID


class LoginUserInfo(BaseModel):
    """登录响应用户信息。"""

    id: uuid.UUID
    username: str
    email: str
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    role: str


class LoginData(BaseModel):
    """登录响应数据。"""

    token: str
    user: LoginUserInfo


class UpdateMeRequest(BaseModel):
    """PUT /auth/me 请求体（个人中心修改资料）。"""

    email: EmailStr
