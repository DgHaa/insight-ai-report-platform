"""报告生成模块：POST generate、WebSocket progress、POST terminate。

并发控制由 GenerationManager 的全局 asyncio.Semaphore(5) 实现，
超出上限的任务自动排队（FIFO）。
"""
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_ws, get_db
from app.api.styles import is_style_usable
from app.core.concurrency import request_remote_cancel
from app.core.exceptions import (
    TaskAlreadyExistsError,
    AuthError,
    ParamError,
    PermissionDeniedError,
)
from app.services.access import ensure_can_edit, ensure_can_view, load_report_or_404
from app.core.response import ApiResponse, success
from app.core.utils import utcnow
from app.db.operation_log import log_operation
from app.db.session import SessionLocal
from app.models import GenerationTask, Report, ReportStyle, User
from app.models.generation_task import GenerationTaskStatus
from app.models.report import ReportStatus
from app.schemas.generation import GenerateRequest, GenerateData
from app.services.access import ensure_can_edit, load_report_or_404
from app.services.generation import generation_manager

router = APIRouter(tags=["报告生成"])


@router.post("/reports/{report_id}/generate", response_model=ApiResponse, summary="触发报告生成")
async def trigger_generation(
    report_id: uuid.UUID,
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_edit(report, user)

    if generation_manager.is_running(report_id):
        raise TaskAlreadyExistsError("该报告已有生成任务在执行")

    # 本次生成可指定风格：写入报告当前风格（任务执行时快照到新版本）
    if body.style_id is not None:
        style = await db.get(ReportStyle, body.style_id)
        if style is None or not is_style_usable(user, style):
            raise ParamError("报告风格不可用或不存在")
        report.style_id = body.style_id
        await db.flush()

    # 清理孤儿任务：进程内已无存活任务，但 DB 仍残留 running/pending（如服务重启前排队未执行），
    # 避免旧任务残留状态与新生成叠加，导致“报告卡 generating、终止又提示无任务”的死状态。
    orphan_task = await db.scalar(
        select(GenerationTask)
        .where(
            GenerationTask.report_id == report.id,
            GenerationTask.status.in_(
                [
                    GenerationTaskStatus.RUNNING.value,
                    GenerationTaskStatus.PENDING.value,
                ]
            ),
        )
        .order_by(GenerationTask.created_at.desc())
    )
    if orphan_task is not None:
        orphan_task.status = GenerationTaskStatus.FAILED.value
        orphan_task.completed_at = utcnow()
        orphan_task.error_message = "进程重启，旧生成任务已作废，本次为重新生成"
        await db.flush()

    task = GenerationTask(
        report_id=report.id,
        trigger_type="manual",
        status=GenerationTaskStatus.PENDING.value,
    )
    db.add(task)
    await db.flush()

    report.status = "generating"
    await db.flush()

    await log_operation(
        db,
        user=user,
        action="report.generate",
        resource_type="report",
        resource_id=report.id,
        detail={"task_id": str(task.id), "force": body.force},
    )
    await db.commit()

    # 启动后台生成任务（超出并发上限自动排队）
    generation_manager.start(report.id, task.id, body.force)

    return success(data=GenerateData(task_id=task.id, status=task.status))


@router.post(
    "/reports/{report_id}/modules/{module_index}/regenerate",
    response_model=ApiResponse,
    summary="模块级重生成",
)
async def regenerate_module(
    report_id: uuid.UUID,
    module_index: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """重生成单个模块：补丁式更新当前版本该模块（不升版本号），支持 WebSocket 进度。"""
    report = await load_report_or_404(db, report_id)
    ensure_can_edit(report, user)

    if generation_manager.is_running(report_id):
        raise TaskAlreadyExistsError("该报告已有生成任务在执行")

    # 校验模块下标合法
    config = report.config or {}
    modules = list(config.get("modules") or [])
    if module_index < 0 or module_index >= len(modules):
        raise ParamError(f"模块下标越界：{module_index}（共 {len(modules)} 个模块）")

    # 清理孤儿任务（与 generate 一致，避免死状态叠加）
    orphan_task = await db.scalar(
        select(GenerationTask)
        .where(
            GenerationTask.report_id == report.id,
            GenerationTask.status.in_(
                [GenerationTaskStatus.RUNNING.value, GenerationTaskStatus.PENDING.value]
            ),
        )
        .order_by(GenerationTask.created_at.desc())
    )
    if orphan_task is not None:
        orphan_task.status = GenerationTaskStatus.FAILED.value
        orphan_task.completed_at = utcnow()
        orphan_task.error_message = "进程重启，旧生成任务已作废，本次为模块重生成"
        await db.flush()

    task = GenerationTask(
        report_id=report.id,
        trigger_type="module_regenerate",
        status=GenerationTaskStatus.PENDING.value,
    )
    db.add(task)
    await db.flush()

    report.status = "generating"
    await db.flush()

    await log_operation(
        db,
        user=user,
        action="report.module_regenerate",
        resource_type="report",
        resource_id=report.id,
        detail={"task_id": str(task.id), "module_index": module_index},
    )
    await db.commit()

    generation_manager.start_module_regenerate(report.id, module_index, task.id)

    return success(data=GenerateData(task_id=task.id, status=task.status))


@router.websocket("/reports/{report_id}/generate/progress")
async def generation_progress_ws(websocket: WebSocket, report_id: uuid.UUID) -> None:
    """WebSocket 实时推送生成进度。

    连接方式：ws://host/api/v1/reports/{id}/generate/progress?token=<JWT>
    """
    await websocket.accept()

    token = websocket.query_params.get("token", "")
    # 鉴权 + 报告校验：仅在此阶段使用 DB 连接，随后立即释放，
    # 避免订阅循环（queue.get 等待整个生成过程）长期占用连接导致连接池耗尽。
    async with SessionLocal() as db:
        try:
            user = await get_current_user_ws(token, db)
        except AuthError:
            await websocket.close(code=4401, reason="未认证")
            return

        report = await db.get(Report, report_id)
        if report is None or not report.is_active:
            await websocket.close(code=4404, reason="报告不存在")
            return

        # 对象级可见性校验：避免任意登录用户订阅他人报告的生成进度
        try:
            ensure_can_view(report, user)
        except PermissionDeniedError:
            await websocket.close(code=4403, reason="无权限查看该报告")
            return

    task_id = generation_manager.get_running_task_id(report_id)
    if task_id is None:
        # 无运行中任务时，回查数据库最近任务的终态再推送，避免误报“生成失败”。
        # 使用独立短会话，仅查询阶段占用连接。
        async with SessionLocal() as db:
            latest_task = await db.scalar(
                select(GenerationTask)
                .where(GenerationTask.report_id == report_id)
                .order_by(GenerationTask.created_at.desc())
            )
            phase_map = {
                GenerationTaskStatus.SUCCESS.value: "complete",
                GenerationTaskStatus.FAILED.value: "failed",
                GenerationTaskStatus.TIMEOUT.value: "timeout",
                GenerationTaskStatus.TERMINATED.value: "terminated",
            }
            if latest_task is not None and latest_task.status in phase_map:
                phase = phase_map[latest_task.status]
                message = {
                    "complete": "生成已完成",
                    "failed": latest_task.error_message or "生成失败",
                    "timeout": "生成超时",
                    "terminated": "生成已终止",
                }[phase]
                await websocket.send_json(
                    {
                        "phase": phase,
                        "progress": 100 if phase == "complete" else 0,
                        "message": message,
                        "task_id": str(latest_task.id),
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "phase": "failed",
                        "progress": 0,
                        "message": "该报告当前没有正在执行的生成任务（可能已结束或服务重启），可重新生成",
                    }
                )
        await websocket.close()
        return

    queue = await generation_manager.subscribe(task_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("phase") in ("complete", "failed", "timeout", "terminated"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        generation_manager.unsubscribe(task_id, queue)


@router.post("/reports/{report_id}/generate/terminate", response_model=ApiResponse, summary="终止生成任务")
async def terminate_generation(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    report = await load_report_or_404(db, report_id)
    ensure_can_edit(report, user)

    # 1) 进程内管理器中的任务（FastAPI 后台执行路径）
    task_id = generation_manager.get_running_task_id(report_id)
    # 2) Celery/遗留任务路径：从 DB 查找最近一次未结束（running/pending）任务。
    #    pending 场景覆盖“后台任务启动前进程退出/崩溃”导致的孤儿任务，
    #    避免报告卡在 generating、点终止却提示“该报告当前没有正在执行的生成任务”。
    if task_id is None:
        stale_task = await db.scalar(
            select(GenerationTask)
            .where(
                GenerationTask.report_id == report_id,
                GenerationTask.status.in_(
                    [
                        GenerationTaskStatus.RUNNING.value,
                        GenerationTaskStatus.PENDING.value,
                    ]
                ),
            )
            .order_by(GenerationTask.created_at.desc())
        )
        if stale_task is not None:
            task_id = stale_task.id
    if task_id is None:
        # 幂等处理：没有运行中的任务时不再报 404 卡住前端。
        if report.status == "generating":
            # 报告状态异常残留（无任务却显示生成中）：复位为 terminated，解除按钮置灰
            report.status = ReportStatus.TERMINATED.value
            report.error_message = "生成任务已不在执行，状态已由终止操作复位"
            await log_operation(
                db,
                user=user,
                action="report.terminate",
                resource_type="report",
                resource_id=report.id,
                detail={"note": "无运行任务，复位异常生成状态"},
            )
            await db.commit()
            return success(message="没有正在执行的生成任务，已复位异常生成状态")
        return success(message="当前没有正在执行的生成任务，无需终止")

    # 立即在数据库中标记终止（后台循环随后丢弃本次生成内容）
    task = await db.get(GenerationTask, task_id)
    if task is not None:
        task.status = GenerationTaskStatus.TERMINATED.value
        task.completed_at = utcnow()
        task.error_message = "用户手动终止"
    report.status = ReportStatus.TERMINATED.value
    await db.flush()

    await log_operation(
        db,
        user=user,
        action="report.terminate",
        resource_type="report",
        resource_id=report.id,
        detail={"task_id": str(task_id)},
    )
    await db.commit()

    # 跨进程取消标记（Celery worker 轮询 Redis 感知终止）
    request_remote_cancel(task_id)
    # 进程内取消：设置事件 + 取消后台任务（子调用抛 CancelledError）
    generation_manager.cancel(task_id)
    return success(message="任务已终止")
