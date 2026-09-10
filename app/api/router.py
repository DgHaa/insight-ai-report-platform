"""API 路由汇总：注册全部模块路由。"""
from fastapi import APIRouter

from app.api import (
    admin,
    admin_departments,
    auth,
    credentials,
    dashboard,
    department,
    email,
    export,
    frameworks,
    generation,
    models_api,
    public,
    reports,
    styles,
    versions,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(reports.router)
api_router.include_router(generation.router)
api_router.include_router(frameworks.router)
api_router.include_router(versions.router)
api_router.include_router(export.router)
api_router.include_router(email.router)
api_router.include_router(models_api.router)
api_router.include_router(credentials.router)
api_router.include_router(department.router)
api_router.include_router(dashboard.router)
api_router.include_router(admin.router)
api_router.include_router(admin_departments.router)
api_router.include_router(styles.router)
api_router.include_router(public.router)
