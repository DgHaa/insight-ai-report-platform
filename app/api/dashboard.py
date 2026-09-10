"""统计看板模块（部门管理员）：GET /dashboard/statistics。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role, get_db
from app.core.exceptions import ParamError
from app.core.response import ApiResponse, success
from app.models import User
from app.services.stats import build_dashboard_statistics

router = APIRouter(prefix="/dashboard", tags=["统计看板"])


@router.get("/statistics", response_model=ApiResponse, summary="部门统计看板")
async def get_statistics(
    time_range: str = Query("month", description="week / month / quarter"),
    user: User = Depends(require_role("dept_admin", "super_admin")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    if not user.department_id:
        raise ParamError("当前账号未绑定部门，无法查看统计看板")
    data = await build_dashboard_statistics(db, user.department_id, time_range)
    return success(data=data)
