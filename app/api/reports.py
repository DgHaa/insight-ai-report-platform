"""报告管理模块：GET/POST /reports，GET/PUT/DELETE /reports/{id}。"""
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.core.exceptions import NotFoundError, ParamError, PermissionDeniedError
from app.core.response import ApiResponse, success
from app.core.utils import utcnow
from app.db.operation_log import log_operation
from app.models import Report, ReportStyle, User
from app.schemas.report import ReportCreate, ReportUpdate, ReportCreateData, ReportUpdateData
from app.services.access import (
    ensure_can_edit,
    ensure_can_view,
    load_report_or_404,
)
from app.services.serializers import report_to_dict
from app.api.styles import is_style_usable

router = APIRouter(tags=["报告管理"])

VALID_VIEWS = {"my", "department", "public", "all"}


async def _resolve_style_id(
    db: AsyncSession, user: User, style_id: uuid.UUID | None
) -> uuid.UUID | None:
    """校验并返回可用的风格ID（None 表示使用默认科技蓝风格）。"""
    if style_id is None:
        return None
    style = await db.get(ReportStyle, style_id)
    if style is None or not is_style_usable(user, style):
        raise ParamError("报告风格不可用或不存在")
    return style.id


def _report_query():
    return select(Report).options(
        selectinload(Report.department), selectinload(Report.owner)
    ).where(Report.is_active.is_(True))


@router.get("/reports", response_model=ApiResponse, summary="报告列表（多视图）")
async def list_reports(
    view: str = Query("my", description="my/department/public/all"),
    department_id: uuid.UUID | None = Query(None, description="部门筛选（仅超级管理员可跨部门）"),
    tag: str | None = Query(None, description="标签筛选"),
    keyword: str | None = Query(None, description="标题搜索"),
    status: str | None = Query(None, description="draft/completed/generating/..."),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if view not in VALID_VIEWS:
        raise ParamError(f"view 仅支持 {'/'.join(sorted(VALID_VIEWS))}")

    query = _report_query()

    # ---- 视图过滤 ----
    if view == "all":
        if user.role != "super_admin":
            raise PermissionDeniedError("view=all 仅超级管理员可用")
    elif view == "department":
        if not user.department_id:
            return success(data={"list": [], "total": 0, "page": page, "page_size": page_size})
        query = query.where(Report.department_id == user.department_id)
    elif view == "public":
        query = query.where(Report.is_public.is_(True))
    else:  # my
        query = query.where(Report.owner_id == user.id)

    # ---- 其他筛选 ----
    if department_id is not None:
        if user.role == "super_admin" or view == "public":
            # 公开报告允许任意登录用户按部门筛选；其他视图仅超管可跨部门
            query = query.where(Report.department_id == department_id)
        else:
            raise PermissionDeniedError("仅超级管理员可按部门筛选（公开报告除外）")
    if tag:
        query = query.where(Report.tags.any(tag))
    if keyword:
        query = query.where(Report.title.ilike(f"%{keyword}%"))
    if status:
        query = query.where(Report.status == status)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.scalars(
        query.order_by(Report.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [report_to_dict(r, include_config=False) for r in rows]
    return success(
        data={"list": items, "total": total or 0, "page": page, "page_size": page_size}
    )


@router.post("/reports", response_model=ApiResponse, summary="创建报告")
async def create_report(
    body: ReportCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    department_id = user.department_id
    if body.type == "department":
        # 部门报告：仅部门管理员/超级管理员可创建，且强制对内公开
        if user.role not in ("dept_admin", "super_admin"):
            raise PermissionDeniedError("仅部门管理员可创建部门报告")
        if user.role == "dept_admin" and not department_id:
            raise ParamError("当前账号未绑定部门，无法创建部门报告")
        is_public = False
    else:
        is_public = body.is_public

    report = Report(
        title=body.title,
        description=body.description,
        type=body.type,
        department_id=department_id,
        owner_id=user.id,
        is_public=is_public,
        tags=body.tags,
        config=body.config,
        style_id=await _resolve_style_id(db, user, body.style_id),
        status="draft",
    )
    db.add(report)
    await db.flush()

    await log_operation(
        db,
        user=user,
        action="report.create",
        resource_type="report",
        resource_id=report.id,
        detail={
            "title": report.title,
            "type": report.type,
            "ip": request.client.host if request.client else None,
        },
    )
    await db.commit()
    return success(data=ReportCreateData(id=report.id, created_at=report.created_at))


@router.get("/reports/{report_id}", response_model=ApiResponse, summary="报告详情")
async def get_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await db.scalar(_report_query().where(Report.id == report_id))
    if report is None or not report.is_active:
        raise NotFoundError("报告不存在")
    ensure_can_view(report, user)
    # 非所有者查看详情时对配置中的 api_key 等敏感信息脱敏
    return success(
        data=report_to_dict(
            report,
            include_config=True,
            mask_sensitive=(report.owner_id != user.id),
        )
    )


@router.put("/reports/{report_id}", response_model=ApiResponse, summary="更新报告")
async def update_report(
    report_id: uuid.UUID,
    body: ReportUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_edit(report, user)
    if report.status == "generating":
        raise ParamError("报告生成中，不可修改")

    if body.title is not None:
        report.title = body.title
    if body.description is not None:
        report.description = body.description
    if body.is_public is not None:
        if report.type == "department":
            raise ParamError("部门报告强制对内公开，不可设置公开状态")
        report.is_public = body.is_public
    if body.tags is not None:
        report.tags = body.tags
    if body.config is not None:
        report.config = body.config
    if body.style_id is not None:
        report.style_id = await _resolve_style_id(db, user, body.style_id)
    report.updated_at = utcnow()
    await db.flush()

    await log_operation(
        db,
        user=user,
        action="report.update",
        resource_type="report",
        resource_id=report.id,
    )
    await db.commit()
    return success(data=ReportUpdateData(id=report.id, updated_at=report.updated_at))


@router.delete("/reports/{report_id}", response_model=ApiResponse, summary="删除报告（生成中除外）")
async def delete_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_edit(report, user)
    if report.status == "generating":
        raise ParamError("报告生成中，不可删除，请先终止或等待完成")

    report.is_active = False  # 软删除
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="report.delete",
        resource_type="report",
        resource_id=report.id,
    )
    await db.commit()
    return success(message="success")

