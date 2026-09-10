"""数据源凭证模块：GET/POST /credentials，PUT/DELETE /credentials/{id}。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.crypto import decrypt_value, encrypt_value
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.masking import mask_custom_headers, mask_secret
from app.core.response import ApiResponse, success
from app.db.operation_log import log_operation
from app.models import User, UserDataSourceCredential
from app.schemas.credential import CredentialCreate, CredentialUpdate

router = APIRouter(prefix="/credentials", tags=["数据源凭证"])


@router.get("", response_model=ApiResponse, summary="我的数据源凭证列表")
async def list_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = await db.scalars(
        select(UserDataSourceCredential)
        .where(
            UserDataSourceCredential.user_id == user.id,
            UserDataSourceCredential.is_active.is_(True),
        )
        .order_by(UserDataSourceCredential.created_at.desc())
    )
    items = [
        {
            "id": str(c.id),
            "name": c.name,
            # 落库为密文，读取时先解密再脱敏展示
            "proxy": mask_secret(decrypt_value(c.proxy)),
            "cookies": mask_secret(decrypt_value(c.cookies)),
            # 自定义请求头不回显敏感头的值（Authorization/Cookie 等）
            "custom_headers": mask_custom_headers(c.custom_headers),
            "created_at": c.created_at,
        }
        for c in rows
    ]
    return success(data=items)


@router.post("", response_model=ApiResponse, summary="创建数据源凭证")
async def create_credential(
    body: CredentialCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    credential = UserDataSourceCredential(
        user_id=user.id,
        name=body.name,
        # 敏感字段落库加密（兼容迁移前明文：无前缀原样存储）
        proxy=encrypt_value(body.proxy),
        cookies=encrypt_value(body.cookies),
        custom_headers=body.custom_headers,
    )
    db.add(credential)
    await db.flush()
    await log_operation(
        db, user=user, action="credential.create", resource_type="credential", resource_id=credential.id
    )
    await db.commit()
    return success(data={"id": credential.id})


@router.put("/{credential_id}", response_model=ApiResponse, summary="更新数据源凭证")
async def update_credential(
    credential_id: uuid.UUID,
    body: CredentialUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    credential = await db.get(UserDataSourceCredential, credential_id)
    if credential is None or not credential.is_active or credential.user_id != user.id:
        raise NotFoundError("凭证不存在")

    if body.name is not None:
        credential.name = body.name
    if body.proxy is not None:
        credential.proxy = encrypt_value(body.proxy)
    if body.cookies is not None:
        credential.cookies = encrypt_value(body.cookies)
    if body.custom_headers is not None:
        credential.custom_headers = body.custom_headers
    await db.flush()
    await log_operation(
        db, user=user, action="credential.update", resource_type="credential", resource_id=credential.id
    )
    await db.commit()
    return success(message="success")


@router.delete("/{credential_id}", response_model=ApiResponse, summary="删除数据源凭证")
async def delete_credential(
    credential_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    credential = await db.get(UserDataSourceCredential, credential_id)
    if credential is None or not credential.is_active or credential.user_id != user.id:
        raise NotFoundError("凭证不存在")

    credential.is_active = False  # 软删除
    await db.flush()
    await log_operation(
        db, user=user, action="credential.delete", resource_type="credential", resource_id=credential.id
    )
    await db.commit()
    return success(message="success")
