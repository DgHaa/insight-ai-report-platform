"""邮件服务：白名单校验、任务创建、真实/模拟发送、逐收件人状态、终止与定时调度。

设计要点：
- SMTP 参数读取顺序：系统配置页（数据库 system_configs）> .env 环境变量；
- 模拟发送开关（email_simulate）同样优先取系统配置，页面可一键切换；
- 附件（pdf/docx/md）复用导出服务生成，随邮件真实附带；
- 逐收件人发送：每个收件人独立记录状态（deliveries JSONB），每封之间检查终止标记；
- 终止：进程内 asyncio.Event + Redis 跨进程标记，幂等；
- 定时：scheduled_at 到期任务由进程内调度器或 Celery beat 原子抢占后派发；
- 进度：Redis 快照 + 频道广播（键 insight:email:progress:<task_id>），供 WebSocket 订阅。
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_value
from app.core.exceptions import ParamError
from app.core.utils import utcnow
from app.db.session import SessionLocal
from app.models import EmailTask, GlobalEmailWhitelist, Report, ReportVersion
from app.models.email_task import EmailTaskStatus, EmailTriggerType
from app.services.export import (
    export_docx,
    export_markdown,
    export_pdf,
    render_markdown,
)
from app.services.system_config import get_system_config

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_SEND_ATTEMPTS = 3        # 单次任务的 SMTP 连接尝试次数（含首次）
RETRY_BACKOFF = 5            # 连接失败重试基础等待（秒）
SMTP_CONNECT_TIMEOUT = 20    # SMTP 连接/登录超时（秒）

# ---- 终止标记（进程内 Event + Redis 跨进程） ----
EMAIL_CANCEL_PREFIX = "insight:email:cancel:"
EMAIL_PROGRESS_PREFIX = "insight:email:progress:"
_email_cancel_events: dict[uuid.UUID, asyncio.Event] = {}

# ---- 进程内定时调度器 ----
_scheduler_task: asyncio.Task | None = None
_scheduler_stop = asyncio.Event()



async def validate_recipients(db: AsyncSession, recipients: list[str]) -> None:
    """校验收件人：格式合法，且外部域名必须命中全局白名单。"""
    for recipient in recipients:
        if not _EMAIL_RE.match(recipient):
            raise ParamError(f"无效的邮箱地址: {recipient}")
        domain = recipient.rsplit("@", 1)[1].lower()
        if domain in [d.lower() for d in settings.INTERNAL_EMAIL_DOMAINS]:
            continue
        whitelisted = await db.scalar(
            select(GlobalEmailWhitelist).where(
                GlobalEmailWhitelist.is_active.is_(True),
                or_(
                    GlobalEmailWhitelist.domain == f"@{domain}",
                    GlobalEmailWhitelist.domain == domain,
                ),
            )
        )
        if whitelisted is None:
            from app.core.exceptions import EmailSendError

            raise EmailSendError(f"收件人 {recipient} 的域名不在外部邮箱白名单中，已拦截")


# ==================== SMTP 配置读取 ====================

async def read_email_config(db: AsyncSession) -> dict:
    """读取发送配置：系统配置页（DB）优先，缺失字段回退 .env。"""
    cfg = await get_system_config(db)
    smtp = cfg.get("smtp") or {}
    host = smtp.get("host") or settings.SMTP_HOST
    return {
        "host": host,
        "port": int(smtp.get("port") or settings.SMTP_PORT),
        "username": smtp.get("username") or settings.SMTP_USERNAME,
        # 库中口令为密文，发送前解密（无前缀的历史明文原样返回，兼容旧数据）
        "password": decrypt_value(smtp.get("password")) or settings.SMTP_PASSWORD,
        "tls": bool(smtp.get("tls", settings.SMTP_TLS)),
        "sender": smtp.get("sender") or settings.SMTP_SENDER or settings.SMTP_USERNAME,
        "simulate": bool(cfg.get("email_simulate", settings.EMAIL_SIMULATE)),
    }


# ==================== 任务创建与派发 ====================

async def create_email_task(
    db: AsyncSession,
    *,
    report: Report,
    recipients: list[str],
    formats: list[str],
    version: int | None,
    scheduled_at=None,
    trigger_type: str = EmailTriggerType.MANUAL.value,
) -> EmailTask:
    """创建邮件发送任务；立即发送或定时（scheduled_at 在未来时由调度器到点执行）。"""
    await validate_recipients(db, recipients)

    if version is not None:
        if version < 1 or version > report.current_version:
            raise ParamError(f"所选版本号 V{version} 不存在（当前最新 V{report.current_version}）")

    task = EmailTask(
        report_id=report.id,
        trigger_type=trigger_type,
        recipients=recipients,
        formats=formats,
        version=version,
        status=EmailTaskStatus.PENDING.value,
        scheduled_at=scheduled_at,
        deliveries=[
            {"recipient": r, "status": "pending", "error_msg": None, "sent_at": None}
            for r in recipients
        ],
    )
    db.add(task)
    await db.flush()
    await db.commit()

    if scheduled_at is not None and scheduled_at > datetime.now():
        return task  # 定时任务：由调度器到达时间后派发（按服务器本地时间解释，与前端展示一致）

    dispatch_email_task(task.id)
    return task


def dispatch_email_task(task_id) -> None:
    """进程内后台派发（FastAPI 路径）；Celery 场景由 tasks.email_tasks 承担。"""
    _email_cancel_events[task_id] = asyncio.Event()
    asyncio.create_task(_run_email_task(task_id))


async def _run_email_task(task_id) -> None:
    try:
        async with SessionLocal() as db:
            task = await db.get(EmailTask, task_id)
            if task is None:
                return
            await execute_email_send(db, task)
    except Exception:  # noqa: BLE001
        logger.exception("email task %s crashed", task_id)
    finally:
        _email_cancel_events.pop(task_id, None)


# ==================== 核心发送逻辑 ====================

async def execute_email_send(db: AsyncSession, task: EmailTask) -> None:
    """执行一次邮件任务（进程内 / Celery 复用，幂等抢占）。"""
    if task.status in (
        EmailTaskStatus.SENT.value,
        EmailTaskStatus.FAILED.value,
        EmailTaskStatus.CANCELLED.value,
    ):
        return
    if task.status == EmailTaskStatus.SENDING.value:
        pass  # 调度器/Celery 已抢占
    elif task.status == EmailTaskStatus.PENDING.value:
        task.status = EmailTaskStatus.SENDING.value
        task.attempts = (task.attempts or 0) + 1
        await db.commit()
    else:
        return

    cfg = await read_email_config(db)

    report = await db.get(Report, task.report_id) if task.report_id else None
    if report is None or not report.is_active:
        await _finalize(db, task, EmailTaskStatus.FAILED.value, "关联报告不存在")
        return

    version_number = task.version or report.current_version
    ver = await db.scalar(
        select(ReportVersion).where(
            ReportVersion.report_id == report.id,
            ReportVersion.version_number == version_number,
        )
    )
    if ver is None:
        await _finalize(
            db, task, EmailTaskStatus.FAILED.value, f"报告版本 V{version_number} 不存在"
        )
        return

    # 构建正文与附件
    try:
        body = render_markdown(report.title, ver.content)
        attachments = _build_attachments(report.title, ver.content, version_number, task.formats)
    except Exception as exc:  # noqa: BLE001
        logger.exception("email content build failed task=%s", task.id)
        await _finalize(db, task, EmailTaskStatus.FAILED.value, f"生成邮件附件失败: {exc}")
        return

    # 模拟模式：不真正调用 SMTP
    if cfg["simulate"]:
        now = utcnow().isoformat()
        task.deliveries = [
            {
                **d,
                "status": "sent",
                "sent_at": now,
                "error_msg": None,
            }
            for d in (task.deliveries or [])
        ]
        task.sent_at = utcnow()
        await _finalize(db, task, EmailTaskStatus.SENT.value, None)
        _push_progress(task, "complete", 100, "模拟发送完成（未真正调用 SMTP）")
        return

    sent, failed, cancelled, last_error = await _smtp_send_all(
        report.title, task, body, attachments, cfg, db
    )

    # 收尾：未处理的收件人按结果标记
    final_deliveries = []
    for d in task.deliveries or []:
        if d.get("status") == "pending":
            final_deliveries.append(
                {
                    **d,
                    "status": "cancelled" if cancelled else "failed",
                    "error_msg": "任务已终止" if cancelled else (last_error or "发送失败"),
                }
            )
        else:
            final_deliveries.append(d)
    task.deliveries = final_deliveries

    if cancelled:
        await _finalize(db, task, EmailTaskStatus.CANCELLED.value, "用户手动终止")
        _push_progress(task, "cancelled", 100, "任务已终止")
    elif failed and sent == 0:
        await _finalize(db, task, EmailTaskStatus.FAILED.value, last_error)
        _push_progress(task, "failed", 100, last_error or "发送失败")
    else:
        summary = f"部分收件人发送失败（成功 {sent}，失败 {failed}）" if failed else None
        await _finalize(db, task, EmailTaskStatus.SENT.value, summary)
        _push_progress(task, "complete", 100, summary or f"发送完成（{sent} 封）")


def _build_attachments(title: str, content: dict, version: int, formats: list[str]) -> list:
    """按所选格式生成附件。"""
    attachments = []
    for fmt in formats:
        if fmt == "md":
            data, fname = export_markdown(title, content, version)
            attachments.append((fname, data, "text/markdown; charset=utf-8"))
        elif fmt == "docx":
            data, fname = export_docx(title, content, version)
            attachments.append(
                (
                    fname,
                    data,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            )
        elif fmt == "pdf":
            data, fname = export_pdf(title, content, version)
            attachments.append((fname, data, "application/pdf"))
    return attachments


def build_smtp_client(*, host: str, port: int, tls: bool, timeout: int = SMTP_CONNECT_TIMEOUT):
    """构造 aiosmtplib 客户端。

    - tls 且端口 465：隐式 TLS（use_tls=True）；
    - tls 且端口非 465（如 587）：STARTTLS（start_tls=True，connect 时自动升级）；
    - tls 关闭：明文，显式 start_tls=False 防止 connect 自动升级。

    注意：不要手动再调 client.starttls()，否则会因已加密抛
    "Connection already using TLS"（aiosmtplib 5.x 行为）。
    """
    import aiosmtplib

    use_tls = bool(tls and port == 465)
    start_tls = None
    if not use_tls:
        start_tls = True if tls else False
    return aiosmtplib.SMTP(
        hostname=host,
        port=port,
        use_tls=use_tls,
        start_tls=start_tls,
        timeout=timeout,
    )


async def _smtp_send_all(
    title: str, task: EmailTask, body: str, attachments: list, cfg: dict, db: AsyncSession
) -> tuple[int, int, bool, str | None]:
    """连接 SMTP 并逐收件人发送；每封之间检查终止标记，返回 (成功, 失败, 是否终止, 最后错误)。"""
    client = build_smtp_client(host=cfg["host"], port=cfg["port"], tls=cfg["tls"])
    connected = False
    last_error: str | None = None

    for attempt in range(MAX_SEND_ATTEMPTS):
        try:
            await client.connect()
            if cfg["username"]:
                await client.login(cfg["username"], cfg["password"])
            connected = True
            break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:300]
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
            if attempt < MAX_SEND_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))

    if not connected:
        return 0, len(task.recipients or []), False, last_error

    sent = failed = 0
    cancelled = False
    total = len(task.recipients or [])
    try:
        for recipient in task.recipients or []:
            if await _is_cancelled(task.id):
                cancelled = True
                break
            try:
                msg = _build_message(title, body, attachments, cfg["sender"], recipient)
                await client.send_message(msg)
                sent += 1
                _update_delivery(task, recipient, "sent", None)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)[:300]
                failed += 1
                _update_delivery(task, recipient, "failed", last_error)
            if sent and task.sent_at is None:
                task.sent_at = utcnow()
            await db.commit()
            _push_progress(
                task,
                "sending",
                int((sent + failed) / max(total, 1) * 100),
                f"正在发送 {sent + failed}/{total}（成功 {sent}，失败 {failed}）",
            )
    finally:
        try:
            await client.quit()
        except Exception:  # noqa: BLE001
            pass
    return sent, failed, cancelled, last_error


def _build_message(title: str, body: str, attachments: list, sender: str, recipient: str):
    """构造 MIME 多部分邮件（纯文本正文 + 附件）。"""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = f"[AI洞察] {title}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    for filename, data, ctype in attachments:
        main, _, sub = ctype.partition("/")
        msg.add_attachment(
            data, maintype=main, subtype=sub or "octet-stream", filename=filename
        )
    return msg



# ==================== 逐收件人结果 / 收尾 ====================

def _update_delivery(task: EmailTask, recipient: str, status: str, error: str | None) -> None:
    """更新单个收件人的发送结果（整体重建列表，确保 JSONB 变更被 SQLAlchemy 追踪）。"""
    sent_at = utcnow().isoformat() if status == "sent" else None
    deliveries = list(task.deliveries or [])
    for i, d in enumerate(deliveries):
        if d.get("recipient") == recipient:
            deliveries[i] = {**d, "status": status, "sent_at": sent_at, "error_msg": error}
            task.deliveries = deliveries
            return
    deliveries.append(
        {"recipient": recipient, "status": status, "error_msg": error, "sent_at": sent_at}
    )
    task.deliveries = deliveries


async def _finalize(db: AsyncSession, task: EmailTask, status: str, error_msg: str | None) -> None:
    task.status = status
    task.error_msg = str(error_msg)[:500] if error_msg else None
    if status == EmailTaskStatus.SENT.value and task.sent_at is None:
        task.sent_at = utcnow()
    await db.commit()


# ==================== 终止 ====================

def request_email_cancel(task_id) -> None:
    """请求终止：进程内 Event + Redis 跨进程标记。"""
    ev = _email_cancel_events.get(task_id)
    if ev is not None:
        ev.set()
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=0.5
        )
        r.set(EMAIL_CANCEL_PREFIX + str(task_id), "1", ex=3600)
        r.close()
    except Exception:  # noqa: BLE001
        logger.debug("request_email_cancel redis failed")


async def _is_cancelled(task_id) -> bool:
    ev = _email_cancel_events.get(task_id)
    if ev is not None and ev.is_set():
        return True
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=0.5
        )
        exists = r.exists(EMAIL_CANCEL_PREFIX + str(task_id)) == 1
        r.close()
        return exists
    except Exception:  # noqa: BLE001
        return False


# ==================== 进度推送 ====================

def _push_progress(task: EmailTask, phase: str, progress: int, message: str) -> None:
    """推送进度到 Redis（快照 + 频道广播）。"""
    payload = {
        "task_id": str(task.id),
        "phase": phase,
        "progress": progress,
        "message": message,
        "sent": sum(1 for d in task.deliveries or [] if d.get("status") == "sent"),
        "failed": sum(1 for d in task.deliveries or [] if d.get("status") == "failed"),
        "total": len(task.recipients or []),
    }
    try:
        import redis as redis_sync

        data = json.dumps(payload, ensure_ascii=False)
        r = redis_sync.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=0.5
        )
        r.set(EMAIL_PROGRESS_PREFIX + str(task.id), data, ex=3600)
        r.publish(EMAIL_PROGRESS_PREFIX + str(task.id), data)
        r.close()
    except Exception:  # noqa: BLE001
        logger.debug("email progress push failed")


def get_email_progress_snapshot(task_id) -> dict | None:
    """读取最近一次进度快照（供 WebSocket 订阅者连入即得最新状态）。"""
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=0.5
        )
        raw = r.get(EMAIL_PROGRESS_PREFIX + str(task_id))
        r.close()
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.debug("email progress snapshot read failed")
    return None


def terminal_phase(status: str) -> str | None:
    """任务终态 → 进度阶段名。"""
    if status == EmailTaskStatus.SENT.value:
        return "complete"
    if status == EmailTaskStatus.CANCELLED.value:
        return "cancelled"
    if status == EmailTaskStatus.FAILED.value:
        return "failed"
    return None



# ==================== 定时调度 ====================

async def claim_due_email_tasks(db: AsyncSession) -> list:
    """原子抢占已到期的定时任务（pending → sending），返回抢占成功的任务 id 列表。

    并发安全：使用 UPDATE ... WHERE status='pending'，多进程（uvicorn 调度器 +
    Celery beat）同时执行时不会重复派发。
    """
    rows = await db.scalars(
        select(EmailTask).where(
            EmailTask.status == EmailTaskStatus.PENDING.value,
            EmailTask.scheduled_at.is_not(None),
            EmailTask.scheduled_at <= datetime.now(),  # 按服务器本地时间解释（与创建时一致）
        ).limit(50)
    )
    claimed = []
    for task in rows:
        result = await db.execute(
            update(EmailTask)
            .where(
                EmailTask.id == task.id,
                EmailTask.status == EmailTaskStatus.PENDING.value,
            )
            .values(
                status=EmailTaskStatus.SENDING.value,
                attempts=EmailTask.attempts + 1,
            )
        )
        if result.rowcount == 1:
            claimed.append(task.id)
    await db.commit()
    return claimed


def start_email_scheduler() -> None:
    """启动进程内定时发送调度器（uvicorn 环境；Celery beat 可同时运行，抢占互斥）。"""
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _scheduler_stop.clear()
    _scheduler_task = asyncio.create_task(_scheduled_email_loop())


async def reconcile_stuck_email_tasks() -> int:
    """启动对账：复位因进程重启/异常而卡在 sending 的邮件任务为失败。"""
    async with SessionLocal() as db:
        rows = await db.scalars(
            select(EmailTask).where(EmailTask.status == EmailTaskStatus.SENDING.value)
        )
        stuck = list(rows)
        for task in stuck:
            task.status = EmailTaskStatus.FAILED.value
            task.error_msg = "服务重启，发送中断，请重发"
            task.deliveries = [
                {**d, "status": "failed", "error_msg": "服务重启，发送中断"}
                if d.get("status") == "pending"
                else d
                for d in (task.deliveries or [])
            ]
        await db.commit()
        return len(stuck)


async def stop_email_scheduler() -> None:
    """停止进程内调度器（应用退出时调用）。"""
    _scheduler_stop.set()
    if _scheduler_task is not None:
        try:
            await asyncio.wait_for(_scheduler_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _scheduler_task.cancel()


async def _scheduled_email_loop() -> None:
    while not _scheduler_stop.is_set():
        try:
            async with SessionLocal() as db:
                claimed = await claim_due_email_tasks(db)
            for tid in claimed:
                dispatch_email_task(tid)
        except Exception:  # noqa: BLE001
            logger.exception("email scheduler tick failed")
        try:
            await asyncio.wait_for(_scheduler_stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            continue


# ==================== 兼容入口（Celery 复用） ====================

async def perform_email_send(db: AsyncSession, task: EmailTask) -> None:
    """保持旧入口，转发到统一执行逻辑（Celery 任务复用）。"""
    await execute_email_send(db, task)

