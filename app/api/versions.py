"""历史版本模块：列表、详情、回滚。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.exceptions import NotFoundError
from app.core.response import ApiResponse, success
from app.db.operation_log import log_operation
from app.models import ReportVersion, User
from app.services.access import ensure_can_edit, ensure_can_view, load_report_or_404

router = APIRouter(tags=["历史版本"])


@router.get("/reports/{report_id}/versions", response_model=ApiResponse, summary="历史版本列表")
async def list_versions(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_view(report, user)

    rows = await db.scalars(
        select(ReportVersion)
        .where(
            ReportVersion.report_id == report.id,
            ReportVersion.is_active.is_(True),
        )
        .order_by(ReportVersion.version_number.desc())
    )
    versions = [
        {
            "version_number": v.version_number,
            "generated_at": v.generated_at,
            "model_used": v.model_used,
            "status": v.status,
            "style_id": str(v.style_id) if v.style_id else None,
            "is_current": v.version_number == report.current_version,
        }
        for v in rows
    ]
    return success(data={"versions": versions})


@router.get("/reports/{report_id}/versions/{version}", response_model=ApiResponse, summary="版本详情")
async def get_version(
    report_id: uuid.UUID,
    version: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_view(report, user)

    ver = await db.scalar(
        select(ReportVersion).where(
            ReportVersion.report_id == report.id,
            ReportVersion.version_number == version,
            ReportVersion.is_active.is_(True),
        )
    )
    if ver is None:
        raise NotFoundError(f"版本 {version} 不存在")
    return success(
        data={
            "version_number": ver.version_number,
            "content": ver.content,
            "config_snapshot": ver.config_snapshot,
            "model_used": ver.model_used,
            "status": ver.status,
            "style_id": str(ver.style_id) if ver.style_id else None,
            "content_hash": ver.content_hash,
            "generated_at": ver.generated_at,
        }
    )


@router.post("/reports/{report_id}/versions/{version}/rollback", response_model=ApiResponse, summary="回滚至指定版本")
async def rollback_version(
    report_id: uuid.UUID,
    version: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_edit(report, user)

    ver = await db.scalar(
        select(ReportVersion).where(
            ReportVersion.report_id == report.id,
            ReportVersion.version_number == version,
            ReportVersion.is_active.is_(True),
        )
    )
    if ver is None:
        raise NotFoundError(f"版本 {version} 不存在")

    report.current_version = ver.version_number
    report.status = "completed"
    await db.flush()

    await log_operation(
        db,
        user=user,
        action="report.rollback",
        resource_type="report",
        resource_id=report.id,
        detail={"version": version},
    )
    await db.commit()
    return success(data={"current_version": ver.version_number, "message": f"已回滚至版本 {version}"})
