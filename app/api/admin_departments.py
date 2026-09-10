"""超级管理员 - 全部门管理模块。

提供 /admin/departments 系列接口（仅超级管理员可用）：
- 部门列表（含成员数 / 报告数 / 管理员姓名）；
- 指定部门统计看板、用户管理；
- 指定部门公共模型配置 CRUD（api_key 一律脱敏返回，不返回明文）。
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_super_admin
from app.core.crypto import decrypt_value, encrypt_value
from app.core.exceptions import NotFoundError, ParamError, PermissionDeniedError
from app.core.masking import mask_secret
from app.core.response import ApiResponse, success
from app.db.operation_log import log_operation
from app.db.security import hash_password
from app.models import (
    Department,
    DepartmentModelConfig,
    GenerationTask,
    Report,
    User,
)
from app.schemas.admin import DepartmentModelConfigCreate, DepartmentModelConfigUpdate
from app.schemas.department import DepartmentUserCreate, DepartmentUserUpdate
from app.services.stats import build_dashboard_statistics

router = APIRouter(prefix="/admin/departments", tags=["超级管理员-部门管理"])

SUPER_ADMIN = Depends(require_super_admin)


def mask_api_key(key: str | None) -> str | None:
    """API Key 脱敏：仅显示前 2 位与后 4 位（如 sk-****abcd）。

    统一走 app.core.masking.mask_secret，避免全站多套掩码规则不一致。

    安全要求：公共模型配置的 api_key 在任何接口响应中均不允许明文出现，
    且不提供“显示明文 / 复制明文”的能力。
    """
    if not key:
        return None
    if len(key) <= 6:
        return "****"
    return mask_secret(key)


async def _load_department_or_404(
    db: AsyncSession, department_id: uuid.UUID
) -> Department:
    dept = await db.get(Department, department_id)
    if dept is None or not dept.is_active:
        raise NotFoundError("部门不存在")
    return dept


async def _load_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise NotFoundError("用户不存在")
    return user


# ==================== 部门列表 ====================


@router.get("", response_model=ApiResponse, summary="全部部门列表（含成员/报告数）")
async def list_departments(
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    depts = (
        await db.scalars(
            select(Department)
            .where(Department.is_active.is_(True))
            .order_by(Department.code)
        )
    ).all()
    if not depts:
        return success(data={"departments": []})

    dept_ids = [d.id for d in depts]

    # 一次性聚合成员数 / 报告数，避免“每个部门 3 次查询”的 N+1
    member_rows = await db.execute(
        select(User.department_id, func.count(User.id))
        .where(User.department_id.in_(dept_ids), User.is_active.is_(True))
        .group_by(User.department_id)
    )
    member_counts = {r[0]: r[1] for r in member_rows}

    report_rows = await db.execute(
        select(Report.department_id, func.count(Report.id))
        .where(Report.department_id.in_(dept_ids), Report.is_active.is_(True))
        .group_by(Report.department_id)
    )
    report_counts = {r[0]: r[1] for r in report_rows}

    # 一次性取回所有部门管理员姓名，避免逐个 db.get(User, ...)
    admin_names: dict = {}
    admin_ids = [d.admin_id for d in depts if d.admin_id]
    if admin_ids:
        admin_rows = await db.execute(
            select(User.id, User.username).where(User.id.in_(admin_ids))
        )
        admin_names = {r[0]: r[1] for r in admin_rows}

    result = [
        {
            "id": str(dept.id),
            "name": dept.name,
            "code": dept.code,
            "description": dept.description,
            "admin_id": str(dept.admin_id) if dept.admin_id else None,
            "admin_name": admin_names.get(dept.admin_id),
            "member_count": member_counts.get(dept.id, 0),
            "report_count": report_counts.get(dept.id, 0),
        }
        for dept in depts
    ]
    return success(data={"departments": result})


# ==================== 指定部门统计看板 ====================


@router.get("/{department_id}/statistics", response_model=ApiResponse, summary="指定部门统计看板")
async def get_department_statistics(
    department_id: uuid.UUID,
    time_range: str = Query("month", description="week / month / quarter"),
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await _load_department_or_404(db, department_id)
    data = await build_dashboard_statistics(db, department_id, time_range)
    return success(data=data)


# ==================== 指定部门用户管理 ====================


@router.get("/{department_id}/users", response_model=ApiResponse, summary="指定部门用户列表")
async def list_department_users(
    department_id: uuid.UUID,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await _load_department_or_404(db, department_id)
    users = (
        await db.scalars(
            select(User).where(
                User.department_id == department_id, User.is_active.is_(True)
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
            "id": str(u.id),
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


@router.post("/{department_id}/users", response_model=ApiResponse, summary="向指定部门添加用户")
async def create_department_user(
    department_id: uuid.UUID,
    body: DepartmentUserCreate,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await _load_department_or_404(db, department_id)

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
        department_id=department_id,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="admin.department.user.create",
        resource_type="user",
        resource_id=new_user.id,
        detail={"department_id": str(department_id), "username": new_user.username, "role": new_user.role},
    )
    await db.commit()
    return success(data={"id": new_user.id})


@router.put("/{department_id}/users/{target_user_id}", response_model=ApiResponse, summary="调整指定部门用户角色")
async def update_department_user(
    department_id: uuid.UUID,
    target_user_id: uuid.UUID,
    body: DepartmentUserUpdate,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    dept = await _load_department_or_404(db, department_id)
    target = await _load_user_or_404(db, target_user_id)
    if target.department_id != dept.id:
        raise ParamError("该用户不属于此部门")
    if target.role == "super_admin":
        raise PermissionDeniedError("不可操作超级管理员")

    target.role = body.role
    # 同步更新部门管理员字段：被设为部门管理员则成为该部门 admin；降级且原为 admin 则清空
    if body.role == "dept_admin":
        dept.admin_id = target.id
    elif dept.admin_id == target.id:
        dept.admin_id = None
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="admin.department.user.update",
        resource_type="user",
        resource_id=target.id,
        detail={"department_id": str(department_id), "role": body.role},
    )
    await db.commit()
    return success(message="success")


@router.delete("/{department_id}/users/{target_user_id}", response_model=ApiResponse, summary="移除指定部门用户")
async def delete_department_user(
    department_id: uuid.UUID,
    target_user_id: uuid.UUID,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    dept = await _load_department_or_404(db, department_id)
    target = await _load_user_or_404(db, target_user_id)
    if target.department_id != dept.id:
        raise ParamError("该用户不属于此部门")
    if target.role == "super_admin":
        raise PermissionDeniedError("不可操作超级管理员")
    if target.id == user.id:
        raise PermissionDeniedError("不能移除自己")

    target.is_active = False  # 软删除
    if dept.admin_id == target.id:
        dept.admin_id = None
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="admin.department.user.delete",
        resource_type="user",
        resource_id=target.id,
        detail={"department_id": str(department_id)},
    )
    await db.commit()
    return success(message="success")


# ==================== 指定部门公共模型配置 ====================


@router.get("/{department_id}/model-configs", response_model=ApiResponse, summary="指定部门公共模型配置列表（api_key 脱敏）")
async def list_model_configs(
    department_id: uuid.UUID,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await _load_department_or_404(db, department_id)
    rows = await db.scalars(
        select(DepartmentModelConfig)
        .where(
            DepartmentModelConfig.department_id == department_id,
            DepartmentModelConfig.is_active.is_(True),
        )
        .order_by(DepartmentModelConfig.created_at.desc())
    )
    items = [
        {
            "id": str(c.id),
            "name": c.name,
            "provider": c.provider,
            "endpoint": c.endpoint,
            # 落库为密文：先解密再脱敏，绝不返回明文
            "api_key": mask_api_key(decrypt_value(c.api_key)),
            "model_name": c.model_name,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in rows
    ]
    return success(data={"items": items})


@router.post("/{department_id}/model-configs", response_model=ApiResponse, summary="新增部门公共模型配置")
async def create_model_config(
    department_id: uuid.UUID,
    body: DepartmentModelConfigCreate,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await _load_department_or_404(db, department_id)
    cfg = DepartmentModelConfig(
        department_id=department_id,
        name=body.name,
        provider=body.provider,
        endpoint=body.endpoint,
        api_key=encrypt_value(body.api_key),  # 落库加密
        model_name=body.model_name,
        created_by=user.id,
    )
    db.add(cfg)
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="admin.department.model_config.create",
        resource_type="model_config",
        resource_id=cfg.id,
        detail={"department_id": str(department_id), "name": cfg.name},
    )
    await db.commit()
    return success(data={"id": cfg.id})


@router.put("/{department_id}/model-configs/{config_id}", response_model=ApiResponse, summary="更新部门公共模型配置（api_key 留空则不修改）")
async def update_model_config(
    department_id: uuid.UUID,
    config_id: uuid.UUID,
    body: DepartmentModelConfigUpdate,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await _load_department_or_404(db, department_id)
    cfg = await db.get(DepartmentModelConfig, config_id)
    if cfg is None or not cfg.is_active or cfg.department_id != department_id:
        raise NotFoundError("配置不存在")

    if body.name is not None:
        cfg.name = body.name
    if body.provider is not None:
        cfg.provider = body.provider
    if body.endpoint is not None:
        cfg.endpoint = body.endpoint
    if body.model_name is not None:
        cfg.model_name = body.model_name
    # api_key：仅在传入非空值时更新（不回显、不覆盖），落库加密
    if body.api_key:
        cfg.api_key = encrypt_value(body.api_key)

    await db.flush()
    await log_operation(
        db,
        user=user,
        action="admin.department.model_config.update",
        resource_type="model_config",
        resource_id=cfg.id,
        detail={"department_id": str(department_id), "name": cfg.name},
    )
    await db.commit()
    return success(message="success")


@router.delete("/{department_id}/model-configs/{config_id}", response_model=ApiResponse, summary="删除部门公共模型配置")
async def delete_model_config(
    department_id: uuid.UUID,
    config_id: uuid.UUID,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    await _load_department_or_404(db, department_id)
    cfg = await db.get(DepartmentModelConfig, config_id)
    if cfg is None or not cfg.is_active or cfg.department_id != department_id:
        raise NotFoundError("配置不存在")

    cfg.is_active = False  # 软删除
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="admin.department.model_config.delete",
        resource_type="model_config",
        resource_id=cfg.id,
        detail={"department_id": str(department_id), "name": cfg.name},
    )
    await db.commit()
    return success(message="success")

