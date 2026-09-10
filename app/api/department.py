"""部门管理模块（部门管理员）：GET/POST /department/users，PUT/DELETE /department/users/{id}。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role, get_db
from app.core.crypto import decrypt_value, encrypt_value
from app.core.exceptions import NotFoundError, ParamError, PermissionDeniedError
from app.core.masking import mask_secret
from app.core.response import ApiResponse, success
from app.db.operation_log import log_operation
from app.db.security import hash_password
from app.models import DepartmentModelConfig, GenerationTask, Report, User
from app.schemas.department import (
    DepartmentModelConfigSave,
    DepartmentUserCreate,
    DepartmentUserUpdate,
)

router = APIRouter(prefix="/department", tags=["部门管理"])

DEPARTMENT_ADMIN = Depends(require_role("dept_admin", "super_admin"))


async def _ensure_same_department(db: AsyncSession, user: User, target: User) -> None:
    """目标用户必须与操作者同部门，且不可操作超级管理员。"""
    if target.role == "super_admin":
        raise PermissionDeniedError("不可操作超级管理员")
    if user.role == "dept_admin":
        if not user.department_id or target.department_id != user.department_id:
            raise PermissionDeniedError("只能管理本部门用户")


@router.get("/users", response_model=ApiResponse, summary="本部门用户列表")
async def list_department_users(
    user: User = DEPARTMENT_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if not user.department_id:
        return success(data={"users": []})

    users = (
        await db.scalars(
            select(User).where(
                User.department_id == user.department_id, User.is_active.is_(True)
            )
        )
    ).all()
    if not users:
        return success(data={"users": []})

    owner_ids = [u.id for u in users]

    # 一次性聚合，避免“每位用户 2 次查询”的 N+1
    count_rows = await db.execute(
        select(Report.owner_id, func.count(Report.id))
        .where(Report.owner_id.in_(owner_ids))
        .group_by(Report.owner_id)
    )
    report_counts = {r[0]: r[1] for r in count_rows}

    last_rows = await db.execute(
        select(Report.owner_id, func.max(GenerationTask.created_at))
        .join(Report, Report.id == GenerationTask.report_id)
        .where(Report.owner_id.in_(owner_ids))
        .group_by(Report.owner_id)
    )
    last_active_map = {r[0]: r[1] for r in last_rows}

    result = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "report_count": report_counts.get(u.id, 0),
            "last_active": last_active_map.get(u.id),
        }
        for u in users
    ]
    return success(data={"users": result})


@router.post("/users", response_model=ApiResponse, summary="添加部门用户")
async def create_department_user(
    body: DepartmentUserCreate,
    user: User = DEPARTMENT_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if user.role == "dept_admin" and not user.department_id:
        raise ParamError("当前账号未绑定部门")
    if body.role == "dept_admin" and user.role == "dept_admin":
        raise PermissionDeniedError("部门管理员不可创建其他部门管理员")

    existing = await db.scalar(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if existing is not None:
        raise ParamError("用户名或邮箱已存在")

    new_user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password or "User@2026"),
        role=body.role,
        department_id=user.department_id,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="department.user.create",
        resource_type="user",
        resource_id=new_user.id,
        detail={"username": new_user.username, "role": new_user.role},
    )
    await db.commit()
    return success(data={"id": new_user.id})


@router.put("/users/{target_user_id}", response_model=ApiResponse, summary="更新部门用户角色")
async def update_department_user(
    target_user_id: uuid.UUID,
    body: DepartmentUserUpdate,
    user: User = DEPARTMENT_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    target = await db.get(User, target_user_id)
    if target is None or not target.is_active:
        raise NotFoundError("用户不存在")
    await _ensure_same_department(db, user, target)
    if target.id == user.id and body.role != "dept_admin":
        raise PermissionDeniedError("不能降级自己")

    target.role = body.role
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="department.user.update",
        resource_type="user",
        resource_id=target.id,
        detail={"role": body.role},
    )
    await db.commit()
    return success(message="success")


@router.delete("/users/{target_user_id}", response_model=ApiResponse, summary="移除部门用户")
async def delete_department_user(
    target_user_id: uuid.UUID,
    user: User = DEPARTMENT_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    target = await db.get(User, target_user_id)
    if target is None or not target.is_active:
        raise NotFoundError("用户不存在")
    await _ensure_same_department(db, user, target)
    if target.id == user.id:
        raise PermissionDeniedError("不能移除自己")

    target.is_active = False  # 软删除
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="department.user.delete",
        resource_type="user",
        resource_id=target.id,
    )
    await db.commit()
    return success(message="success")


# ==================== 本部门公共模型配置 ====================
# 替代此前前端把 api_key 明文暂存 localStorage 的半成品实现：
# 密钥落库加密、读取脱敏，仅本部门管理员可读写。


@router.get("/model-config", response_model=ApiResponse, summary="本部门公共模型配置（api_key 脱敏）")
async def get_department_model_config(
    user: User = DEPARTMENT_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if not user.department_id:
        return success(data=None)

    cfg = (
        await db.scalars(
            select(DepartmentModelConfig)
            .where(
                DepartmentModelConfig.department_id == user.department_id,
                DepartmentModelConfig.is_active.is_(True),
            )
            .order_by(DepartmentModelConfig.created_at.desc())
        )
    ).first()
    if cfg is None:
        return success(data=None)

    return success(
        data={
            "id": str(cfg.id),
            "name": cfg.name,
            "provider": cfg.provider,
            "endpoint": cfg.endpoint,
            "model_name": cfg.model_name,
            # 落库为密文，此处解密后脱敏，绝不返回明文
            "api_key": mask_secret(decrypt_value(cfg.api_key)),
            "has_api_key": bool(decrypt_value(cfg.api_key)),
        }
    )


@router.put("/model-config", response_model=ApiResponse, summary="保存本部门公共模型配置")
async def save_department_model_config(
    body: DepartmentModelConfigSave,
    user: User = DEPARTMENT_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if not user.department_id:
        raise ParamError("当前账号未绑定部门")

    cfg = (
        await db.scalars(
            select(DepartmentModelConfig)
            .where(
                DepartmentModelConfig.department_id == user.department_id,
                DepartmentModelConfig.is_active.is_(True),
            )
            .order_by(DepartmentModelConfig.created_at.desc())
        )
    ).first()

    if cfg is None:
        cfg = DepartmentModelConfig(
            department_id=user.department_id,
            name=body.name or "默认配置",
            provider=body.provider or "custom",
            endpoint=body.endpoint,
            api_key=encrypt_value(body.api_key),  # 落库加密
            model_name=body.model_name,
            created_by=user.id,
        )
        db.add(cfg)
    else:
        if body.name is not None:
            cfg.name = body.name
        if body.provider is not None:
            cfg.provider = body.provider
        if body.endpoint is not None:
            cfg.endpoint = body.endpoint
        if body.model_name is not None:
            cfg.model_name = body.model_name
        # api_key：仅当提交了新的真实密钥时才更新。
        # 前端回显的是脱敏值（含 ****），原样提交时不应覆盖真实密钥。
        if body.api_key and "****" not in body.api_key:
            cfg.api_key = encrypt_value(body.api_key)

    await db.flush()
    await log_operation(
        db,
        user=user,
        action="department.model_config.save",
        resource_type="model_config",
        resource_id=cfg.id,
        detail={"department_id": str(user.department_id)},
    )
    await db.commit()
    return success(message="success")
