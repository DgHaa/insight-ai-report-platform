"""系统管理模块（超级管理员）：白名单、系统配置、全部报告。"""
import time
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_super_admin, get_db
from app.core.config import settings
from app.core.crypto import decrypt_value, encrypt_value
from app.core.exceptions import ParamError
from app.core.response import ApiResponse, success
from app.db.operation_log import log_operation
from app.models import GlobalEmailWhitelist, Report, User
from app.schemas.admin import (
    SmtpTestRequest,
    WhitelistCreate,
    SystemConfigUpdate,
    SystemConfigData,
    SmtpConfig,
)
from app.services.serializers import report_to_dict
from app.services.system_config import get_system_config, save_system_config

router = APIRouter(prefix="/admin", tags=["系统管理"])

SUPER_ADMIN = Depends(require_super_admin)


# ==================== 全局外部邮箱白名单 ====================

@router.get("/email-whitelist", response_model=ApiResponse, summary="外部邮箱白名单列表")
async def list_whitelist(
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = await db.scalars(
        select(GlobalEmailWhitelist)
        .where(GlobalEmailWhitelist.is_active.is_(True))
        .order_by(GlobalEmailWhitelist.created_at.desc())
    )
    domains = [
        {
            "id": str(w.id),
            "domain": w.domain,
            "description": w.description,
            "created_at": w.created_at,
        }
        for w in rows
    ]
    return success(data={"domains": domains})


@router.post("/email-whitelist", response_model=ApiResponse, summary="添加白名单域名")
async def add_whitelist(
    body: WhitelistCreate,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    domain = WhitelistCreate.normalize_domain(body.domain)
    existing = await db.scalar(
        select(GlobalEmailWhitelist).where(GlobalEmailWhitelist.domain == domain)
    )
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            existing.description = body.description
            whitelist = existing
        else:
            raise ParamError("该域名已在白名单中")
    else:
        whitelist = GlobalEmailWhitelist(
            domain=domain, description=body.description, created_by=user.id
        )
        db.add(whitelist)

    await db.flush()
    await log_operation(
        db,
        user=user,
        action="whitelist.create",
        resource_type="whitelist",
        resource_id=whitelist.id,
        detail={"domain": domain},
    )
    await db.commit()
    return success(data={"id": whitelist.id})


@router.delete("/email-whitelist/{whitelist_id}", response_model=ApiResponse, summary="删除白名单域名")
async def delete_whitelist(
    whitelist_id: uuid.UUID,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    whitelist = await db.get(GlobalEmailWhitelist, whitelist_id)
    if whitelist is None or not whitelist.is_active:
        raise ParamError("白名单记录不存在")
    whitelist.is_active = False  # 软删除
    await db.flush()
    await log_operation(
        db,
        user=user,
        action="whitelist.delete",
        resource_type="whitelist",
        resource_id=whitelist.id,
    )
    await db.commit()
    return success(message="success")


# ==================== 全部报告 ====================

@router.get("/all-reports", response_model=ApiResponse, summary="查看所有报告")
async def list_all_reports(
    department_id: uuid.UUID | None = Query(None),
    tag: str | None = Query(None),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    query = (
        select(Report)
        .options(selectinload(Report.department), selectinload(Report.owner))
        .where(Report.is_active.is_(True))
    )
    if department_id is not None:
        query = query.where(Report.department_id == department_id)
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


# ==================== 系统配置 ====================

@router.get("/system/config", response_model=ApiResponse, summary="获取系统配置")
async def get_system_config_api(
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    cfg = await get_system_config(db)
    smtp = cfg.get("smtp", {})
    # 落库为密文，此处仅判断“是否已配置”，不回显明文
    stored_password = decrypt_value(smtp.get("password"))
    return success(
        data=SystemConfigData(
            smtp=SmtpConfig(
                host=smtp.get("host", ""),
                port=smtp.get("port", 587),
                username=smtp.get("username", ""),
                password="******" if stored_password else None,  # 不回显明文
                tls=smtp.get("tls", True),
                sender=smtp.get("sender", ""),
            ),
            max_concurrent_tasks=cfg.get("max_concurrent_tasks", 5),
            task_timeout_seconds=cfg.get("task_timeout_seconds", 1800),
            email_simulate=bool(cfg.get("email_simulate", settings.EMAIL_SIMULATE)),
        )
    )


@router.put("/system/config", response_model=ApiResponse, summary="更新系统配置")
async def update_system_config_api(
    body: SystemConfigUpdate,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    data: dict = {}
    if body.smtp is not None:
        # 保留旧密码：未提交新密码时沿用库中已加密的旧值（避免重复加密）
        current = await get_system_config(db)
        old_password = (current.get("smtp") or {}).get("password", "")
        new_password = body.smtp.password
        if new_password is None or new_password == "******":
            new_password = old_password
        else:
            new_password = encrypt_value(new_password)
        data["smtp"] = {
            "host": body.smtp.host,
            "port": body.smtp.port,
            "username": body.smtp.username,
            "password": new_password,
            "tls": body.smtp.tls,
            "sender": body.smtp.sender,
        }
    # 注意：并发/超时仅持久化到 system_configs，不再运行时改写全局 settings。
    # 原因：get_async_limiter() 为懒加载单例，构造时已读走旧值，运行时赋值实际无效，
    #      且多请求并发写入存在竞态、无取值范围校验。
    if body.max_concurrent_tasks is not None:
        if body.max_concurrent_tasks < 1:
            raise ParamError("max_concurrent_tasks 不能小于 1")
        data["max_concurrent_tasks"] = body.max_concurrent_tasks
    if body.task_timeout_seconds is not None:
        if body.task_timeout_seconds < 1:
            raise ParamError("task_timeout_seconds 不能小于 1")
        data["task_timeout_seconds"] = body.task_timeout_seconds
    if body.email_simulate is not None:
        data["email_simulate"] = body.email_simulate

    await save_system_config(db, data, updated_by=user.id)
    await log_operation(
        db, user=user, action="system.config.update", detail={"changed_keys": list(data.keys())}
    )
    await db.commit()
    return success(message="success")


@router.post("/system/config/test-smtp", response_model=ApiResponse, summary="测试 SMTP 连接")
async def test_smtp_api(
    body: SmtpTestRequest,
    user: User = SUPER_ADMIN,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """用当前表单填写的 SMTP 参数测试连通性（不保存）。"""
    start = time.monotonic()
    try:
        from app.services.email import build_smtp_client

        client = build_smtp_client(
            host=body.host, port=body.port, tls=body.tls, timeout=15
        )
        try:
            await client.connect()
            if body.username:
                await client.login(body.username, body.password or "")
        finally:
            try:
                await client.quit()
            except Exception:  # noqa: BLE001
                pass
        return success(
            data={
                "success": True,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "message": "SMTP 连接成功",
            }
        )
    except Exception as exc:  # noqa: BLE001
        return success(
            data={
                "success": False,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "message": str(exc)[:300],
            }
        )

