"""报告风格模块：GET/POST /styles，PUT/DELETE /styles/{id}，POST /styles/{id}/share。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.core.exceptions import NotFoundError, ParamError, PermissionDeniedError
from app.core.response import ApiResponse, success
from app.core.utils import utcnow
from app.db.operation_log import log_operation
from app.models import ReportStyle, User
from app.schemas.style import StyleCreate, StyleData, StyleUpdate

router = APIRouter(prefix="/styles", tags=["报告风格"])


def is_style_usable(user: User, style: ReportStyle | None) -> bool:
    """当前用户是否可以使用该风格（内置 / 本人 / 本部门共享）。"""
    if style is None or not style.is_active:
        return False
    if style.type == "builtin":
        return True
    if style.owner_id == user.id:
        return True
    if style.is_shared and style.department_id == user.department_id:
        return True
    return False


def _check_manageable(style: ReportStyle, user: User) -> None:
    """校验当前用户能否编辑/删除该风格。"""
    if style.type == "builtin":
        raise PermissionDeniedError("内置风格不可修改")
    if style.owner_id == user.id:
        return
    if (
        style.is_shared
        and style.department_id is not None
        and style.department_id == user.department_id
        and user.role in ("dept_admin", "super_admin")
    ):
        return
    if user.role == "super_admin":
        return
    raise PermissionDeniedError("无权操作该风格")


def _style_dict(style: ReportStyle, user: User) -> dict:
    can_edit = can_delete = False
    try:
        _check_manageable(style, user)
        can_edit = can_delete = True
    except PermissionDeniedError:
        pass
    return {
        "id": str(style.id),
        "name": style.name,
        "type": style.type,
        "config": style.config,
        "owner_id": str(style.owner_id) if style.owner_id else None,
        "owner_name": style.owner.username if style.owner else None,
        "department_id": str(style.department_id) if style.department_id else None,
        "department_name": style.department.name if style.department else None,
        "is_shared": style.is_shared,
        "can_edit": can_edit,
        "can_delete": can_delete,
        "created_at": style.created_at,
        "updated_at": style.updated_at,
    }


async def _load_style(db: AsyncSession, style_id: uuid.UUID) -> ReportStyle:
    style = await db.scalar(
        select(ReportStyle)
        .where(ReportStyle.id == style_id, ReportStyle.is_active.is_(True))
        .options(selectinload(ReportStyle.owner), selectinload(ReportStyle.department))
    )
    if style is None:
        raise NotFoundError("风格不存在")
    return style


@router.get("", response_model=ApiResponse, summary="获取当前用户可用的全部风格")
async def list_styles(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    conditions = [
        ReportStyle.type == "builtin",
        ReportStyle.owner_id == user.id,
    ]
    if user.department_id is not None:
        conditions.append(
            ReportStyle.is_shared.is_(True) & (ReportStyle.department_id == user.department_id)
        )
    rows = await db.scalars(
        select(ReportStyle)
        .where(or_(*conditions), ReportStyle.is_active.is_(True))
        .options(selectinload(ReportStyle.owner), selectinload(ReportStyle.department))
        .order_by(ReportStyle.type.asc(), ReportStyle.created_at.desc())
    )
    return success(data=[_style_dict(s, user) for s in rows])


@router.post("", response_model=ApiResponse, summary="新建自定义风格")
async def create_style(
    body: StyleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if not body.config:
        raise ParamError("风格配置不能为空")
    style = ReportStyle(
        name=body.name,
        type="custom",
        config=body.config,
        owner_id=user.id,
        is_shared=False,
    )
    db.add(style)
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="style.create",
        resource_type="report_style",
        resource_id=style.id,
        detail={"name": style.name},
    )
    await db.commit()
    return success(data=_style_dict(style, user))


@router.put("/{style_id}", response_model=ApiResponse, summary="更新自定义风格")
async def update_style(
    style_id: uuid.UUID,
    body: StyleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    style = await _load_style(db, style_id)
    _check_manageable(style, user)

    if body.name is not None:
        style.name = body.name
    if body.config is not None:
        if not body.config:
            raise ParamError("风格配置不能为空")
        style.config = body.config
    if body.is_shared is not None:
        if body.is_shared and user.role not in ("dept_admin", "super_admin"):
            raise PermissionDeniedError("仅部门管理员可设置部门共享")
        if body.is_shared:
            if user.department_id is None:
                raise ParamError("您没有所属部门，无法设置部门共享")
            style.department_id = user.department_id
        style.is_shared = body.is_shared
    style.updated_at = utcnow()
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="style.update",
        resource_type="report_style",
        resource_id=style.id,
        detail={"name": style.name},
    )
    await db.commit()
    return success(data=_style_dict(style, user))


@router.delete("/{style_id}", response_model=ApiResponse, summary="删除自定义风格（软删除）")
async def delete_style(
    style_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    style = await _load_style(db, style_id)
    _check_manageable(style, user)
    style.is_active = False
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="style.delete",
        resource_type="report_style",
        resource_id=style.id,
        detail={"name": style.name},
    )
    await db.commit()
    return success(message="风格已删除")


@router.post("/{style_id}/share", response_model=ApiResponse, summary="将风格设为部门共享")
async def share_style(
    style_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    style = await _load_style(db, style_id)
    if style.type == "builtin":
        raise PermissionDeniedError("内置风格无需共享")
    if style.owner_id != user.id and user.role != "super_admin":
        raise PermissionDeniedError("只能共享自己创建的风格")
    if user.role not in ("dept_admin", "super_admin"):
        raise PermissionDeniedError("仅部门管理员可设置部门共享")
    if user.department_id is None:
        raise ParamError("您没有所属部门，无法设置部门共享")
    style.is_shared = True
    style.department_id = user.department_id
    style.updated_at = utcnow()
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="style.share",
        resource_type="report_style",
        resource_id=style.id,
        detail={"name": style.name, "department_id": str(user.department_id)},
    )
    await db.commit()
    return success(data=_style_dict(style, user))
