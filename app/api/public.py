"""公开接口（无需登录）：注册页部门列表等。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.response import ApiResponse, success
from app.models import Department

router = APIRouter(tags=["公开"])


@router.get("/departments", response_model=ApiResponse, summary="公开部门列表（注册页下拉）")
async def list_public_departments(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = await db.scalars(
        select(Department)
        .where(Department.is_active.is_(True))
        .order_by(Department.code)
    )
    return success(
        data={
            "departments": [
                {"id": str(d.id), "name": d.name, "code": d.code}
                for d in rows
            ]
        }
    )
