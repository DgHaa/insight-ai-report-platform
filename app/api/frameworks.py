"""分析框架模板接口：GET /api/frameworks（下拉选项，无需鉴权也可命中缓存）。"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.response import ApiResponse, success
from app.models import User
from app.services.frameworks import list_frameworks

router = APIRouter(tags=["分析框架"])


@router.get("/frameworks", response_model=ApiResponse, summary="分析框架模板列表")
async def get_frameworks(_user: User = Depends(get_current_user)) -> ApiResponse:
    """返回内置分析框架目录，供模块表单「分析框架」下拉使用。"""
    return success(data={"frameworks": list_frameworks()})
