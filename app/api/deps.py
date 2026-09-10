"""API 通用依赖：数据库会话、当前用户、角色权限校验。"""
import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError, PermissionDeniedError
from app.core.security import decode_token
from app.db.session import get_db_session
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncSession:
    """FastAPI 数据库会话依赖。"""
    async for session in get_db_session():
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Bearer Token 并加载当前用户（未认证抛出 1001）。"""
    if credentials is None or not credentials.credentials:
        raise AuthError("未提供认证令牌")
    return await _load_user_from_token(credentials.credentials, db)


async def _load_user_from_token(token: str, db: AsyncSession) -> User:
    payload = decode_token(token)
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise AuthError("无效的认证令牌")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("用户不存在或已被禁用")
    return user


async def get_current_user_ws(token: str, db: AsyncSession) -> User:
    """WebSocket 场景的当前用户解析（token 通过 query 参数传递）。"""
    if not token:
        raise AuthError("未提供认证令牌")
    return await _load_user_from_token(token, db)


def require_role(*roles: str):
    """角色权限校验依赖工厂：用户角色不在允许列表时抛出 1002。"""

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise PermissionDeniedError()
        return user

    return _dependency


# 常用角色组合
require_dept_admin = require_role("dept_admin", "super_admin")
require_super_admin = require_role("super_admin")
