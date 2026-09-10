"""认证模块：POST /auth/login、POST /auth/logout。"""
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import bearer_scheme, get_current_user, get_db
from app.core.exceptions import AuthError, ParamError, RateLimitError
from app.core.ratelimit import RateLimited, check_rate_limit, client_ip
from app.core.response import ApiResponse, success
from app.core.security import create_access_token, revoke_token
from app.db.operation_log import log_operation
from app.db.security import hash_password
from app.models import Department, User
from app.schemas.auth import (
    LoginRequest,
    LoginData,
    LoginUserInfo,
    RegisterRequest,
    UpdateMeRequest,
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=ApiResponse, summary="登录")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    # 速率限制：登录为无密码校验入口，必须抑制用户名/部门枚举爆破
    ip = client_ip(request)
    try:
        check_rate_limit(f"login:{ip}:{body.username}", limit=10, window=60)
        check_rate_limit(f"login-ip:{ip}", limit=60, window=60)
    except RateLimited as exc:
        raise RateLimitError(str(exc)) from exc

    user = await db.scalar(select(User).where(User.username == body.username))
    if user is None:
        raise AuthError("用户名与部门不匹配")
    # 部门匹配校验：无部门账号（如超级管理员）不可选择部门；有部门账号必须选择对应部门
    if user.department_id is None:
        if body.department_id is not None:
            raise AuthError("用户名与部门不匹配")
    elif body.department_id != user.department_id:
        raise AuthError("用户名与部门不匹配")
    if not user.is_active:
        raise AuthError("账号已被禁用")

    token, _jti, _expires = create_access_token(user.id, user.username, user.role)
    department_name = None
    if user.department_id:
        dept = await db.get(Department, user.department_id)
        department_name = dept.name if dept else None

    await log_operation(
        db,
        user=user,
        action="auth.login",
        detail={"ip": request.client.host if request.client else None},
    )
    await db.commit()

    user_info = LoginUserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        department_id=user.department_id,
        department_name=department_name,
        role=user.role,
    )
    return success(data=LoginData(token=token, user=user_info))


@router.put("/me", response_model=ApiResponse, summary="更新个人资料")
async def update_me(
    body: UpdateMeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """修改个人邮箱（唯一性校验）。"""
    if body.email and body.email != user.email:
        existing = await db.scalar(select(User).where(User.email == body.email))
        if existing is not None and existing.id != user.id:
            raise ParamError("该邮箱已被其他账号使用")
        user.email = body.email
        await log_operation(
            db, user=user, action="user.update", detail={"changed": ["email"]}
        )
        await db.commit()
    return success(message="success")


@router.post("/logout", response_model=ApiResponse, summary="登出")
async def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if credentials is not None:
        revoke_token(credentials.credentials)
    await log_operation(db, user=user, action="auth.logout")
    await db.commit()
    return success(message="success")


@router.post("/register", response_model=ApiResponse, summary="用户注册")
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """新用户自助注册：仅需用户名与所属部门。

    登录已改为“用户名 + 部门”，密码不再参与校验；此处自动生成邮箱与随机密码
    哈希仅用于满足 users 表 email / password_hash 非空约束，不影响任何现有用户。
    """
    # 速率限制：避免匿名批量注册 / 资源耗尽
    try:
        check_rate_limit(f"register:{client_ip(request)}", limit=10, window=3600)
    except RateLimited as exc:
        raise RateLimitError(str(exc)) from exc

    dept = await db.get(Department, body.department_id)
    if dept is None or not dept.is_active:
        raise ParamError("所选部门不存在")

    email = f"{body.username}@company.com"
    existing = await db.scalar(
        select(User).where((User.username == body.username) | (User.email == email))
    )
    if existing is not None:
        raise ParamError("用户名已存在")

    new_user = User(
        username=body.username,
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(16)),
        role="user",
        department_id=body.department_id,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    await log_operation(
        db,
        user=new_user,
        action="auth.register",
        resource_type="user",
        resource_id=new_user.id,
        detail={"ip": request.client.host if request.client else None},
    )
    await db.commit()
    return success(data={"id": new_user.id}, message="注册成功")
