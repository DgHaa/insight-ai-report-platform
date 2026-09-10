"""导出模块：GET /reports/{id}/export?format=pdf|docx|md。"""
import re
import urllib.parse
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.exceptions import NotFoundError
from app.db.operation_log import log_operation
from app.models import ReportStyle, ReportVersion, User
from app.services.access import ensure_can_view, load_report_or_404
from app.services.export import export_report

router = APIRouter(tags=["导出"])


@router.get("/reports/{report_id}/export", summary="导出报告（pdf/docx/md）")
async def export_version(
    report_id: uuid.UUID,
    format: Literal["pdf", "docx", "md"] = Query("md", alias="format"),
    version: int | None = Query(None, ge=1, description="默认导出最新版本"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    report = await load_report_or_404(db, report_id)
    ensure_can_view(report, user)

    target_version = version if version is not None else report.current_version
    ver = await db.scalar(
        select(ReportVersion).where(
            ReportVersion.report_id == report.id,
            ReportVersion.version_number == target_version,
            ReportVersion.is_active.is_(True),
        )
    )
    if ver is None:
        raise NotFoundError(f"版本 {target_version} 不存在")

    # 导出风格：优先版本生成时风格，其次报告当前风格；无则使用默认
    style_config: dict | None = None
    style_id = ver.style_id or report.style_id
    if style_id is not None:
        style = await db.get(ReportStyle, style_id)
        if style is not None and style.is_active:
            style_config = style.config

    payload, filename, media_type = await export_report(
        report.title, ver.content, target_version, format, style_config
    )

    await log_operation(
        db,
        user=user,
        action="report.export",
        resource_type="report",
        resource_id=report.id,
        detail={"format": format, "version": target_version},
    )
    await db.commit()

    # Content-Disposition：filename 提供 ASCII 兜底，filename*=UTF-8'' 提供原始中文名
    # （直接写中文到 header 会因 latin-1 编码失败而 500）
    safe_ascii = re.sub(r"[^\x20-\x7e]", "_", filename)
    disposition = (
        f"attachment; filename=\"{safe_ascii}\"; "
        f"filename*=UTF-8''{urllib.parse.quote(filename)}"
    )
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )
