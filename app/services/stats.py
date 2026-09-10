"""统计看板服务：按部门聚合生成趋势、热词、活跃用户、模型用量与成功率。"""
from collections import Counter
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ParamError
from app.core.utils import utcnow
from app.models import GenerationTask, ModelCostLog, Report, User

TIME_RANGE_DAYS = {"week": 7, "month": 30, "quarter": 90}


async def _get_department_report_ids(db: AsyncSession, department_id) -> list:
    rows = await db.scalars(
        select(Report.id).where(Report.department_id == department_id, Report.is_active.is_(True))
    )
    return list(rows)


async def _generate_trend(db: AsyncSession, report_ids: list, start) -> dict:
    """生成次数按日趋势。"""
    days = (utcnow().date() - start.date()).days + 1
    labels = [(start.date() + timedelta(days=i)).strftime("%m/%d") for i in range(days)]
    daily = [0] * days

    if report_ids:
        rows = await db.execute(
            select(
                func.date(GenerationTask.created_at).label("d"),
                func.count().label("c"),
            )
            .where(
                GenerationTask.report_id.in_(report_ids),
                GenerationTask.created_at >= start,
            )
            .group_by("d")
        )
        for row in rows:
            d = row.d
            if d is not None:
                delta = (d - start.date()).days
                if 0 <= delta < days:
                    daily[delta] = row.c
    return {"daily": daily, "labels": labels}


async def _hot_keywords(db: AsyncSession, report_ids: list, start) -> list[dict]:
    """热门关键词排行（统计时间段内有生成活动的报告 config.modules[].keywords）。"""
    counter: Counter = Counter()
    if report_ids:
        # 仅统计在时间范围内发起过生成任务的报告
        active_report_ids = await db.scalars(
            select(GenerationTask.report_id)
            .where(
                GenerationTask.report_id.in_(report_ids),
                GenerationTask.created_at >= start,
            )
            .distinct()
        )
        active_ids = list(active_report_ids)
        if active_ids:
            reports = await db.scalars(
                select(Report).where(Report.id.in_(active_ids), Report.is_active.is_(True))
            )
            for report in reports:
                config = report.config or {}
                for module in config.get("modules", []):
                    for kw in module.get("keywords") or []:
                        kw = str(kw).strip()
                        if kw:
                            counter[kw] += 1
    return [
        {"keyword": kw, "count": cnt}
        for kw, cnt in counter.most_common(10)
    ]


async def _active_users(db: AsyncSession, report_ids: list, start) -> list[dict]:
    """活跃用户排行（统计时间段内发起生成任务次数，前10）。"""
    if not report_ids:
        return []
    rows = (
        await db.execute(
            select(
                Report.owner_id.label("owner_id"),
                func.count(GenerationTask.id).label("cnt"),
            )
            .join(GenerationTask, GenerationTask.report_id == Report.id)
            .where(Report.id.in_(report_ids), GenerationTask.created_at >= start)
            .group_by(Report.owner_id)
            .order_by(func.count(GenerationTask.id).desc())
            .limit(10)
        )
    ).all()
    if not rows:
        return []

    # 一次性取回用户名，避免“每行一次 db.get(User, ...)”的 N+1
    owner_ids = [r.owner_id for r in rows if r.owner_id]
    usernames: dict = {}
    if owner_ids:
        user_rows = await db.execute(
            select(User.id, User.username).where(User.id.in_(owner_ids))
        )
        usernames = {r[0]: r[1] for r in user_rows}

    return [
        {
            "username": usernames.get(r.owner_id) or "未知用户",
            "generate_count": r.cnt,
        }
        for r in rows
    ]


async def _model_usage(db: AsyncSession, report_ids: list, start) -> list[dict]:
    """模型调用与用量（统计时间段内，优先 cost_logs，缺失时从报告配置推导）。"""
    if report_ids:
        rows = await db.execute(
            select(
                ModelCostLog.model_provider.label("provider"),
                ModelCostLog.model_name.label("model"),
                func.count().label("calls"),
            )
            .join(GenerationTask, GenerationTask.id == ModelCostLog.task_id)
            .where(
                GenerationTask.report_id.in_(report_ids),
                GenerationTask.created_at >= start,
            )
            .group_by(ModelCostLog.model_provider, ModelCostLog.model_name)
        )
        usage = [
            {"provider": r.provider or "unknown", "model": r.model or "unknown", "calls": r.calls}
            for r in rows
        ]
        if usage:
            return usage
    # 兜底：从报告配置推导已配置的模型
    counter: Counter = Counter()
    if report_ids:
        reports = await db.scalars(
            select(Report).where(Report.id.in_(report_ids), Report.is_active.is_(True))
        )
        for report in reports:
            config = report.config or {}
            for module in config.get("modules", []):
                mc = module.get("model_config") or {}
                if mc.get("provider") and mc.get("model_name"):
                    counter[(mc["provider"], mc["model_name"])] += 1
    return [
        {"provider": p, "model": m, "calls": c}
        for (p, m), c in counter.most_common()
    ]


async def _module_success_rate(db: AsyncSession, report_ids: list, start) -> dict:
    """模块生成成功率（统计时间段内生成任务状态与错误信息）。"""
    if not report_ids:
        return {"total_attempts": 0, "success": 0, "failed": 0, "failure_reasons": {}}

    rows = await db.execute(
        select(GenerationTask.status.label("status"), GenerationTask.error_message.label("err"))
        .where(
            GenerationTask.report_id.in_(report_ids),
            GenerationTask.created_at >= start,
        )
    )
    success = 0
    failed = 0
    reasons: Counter = Counter()
    for row in rows:
        if row.status == "success":
            success += 1
        else:
            failed += 1
            err = (row.err or "").lower()
            if "timeout" in err or "超时" in err:
                reasons["fetch_timeout"] += 1
            elif "model" in err or "模型" in err:
                reasons["model_error"] += 1
            elif "empty" in err or "内容为空" in err:
                reasons["content_empty"] += 1
            else:
                reasons["other"] += 1
    total = success + failed
    return {
        "total_attempts": total,
        "success": success,
        "failed": failed,
        "failure_reasons": dict(reasons),
    }


async def build_dashboard_statistics(
    db: AsyncSession, department_id, time_range: str = "month"
) -> dict:
    """构建部门统计看板数据。"""
    if time_range not in TIME_RANGE_DAYS:
        raise ParamError("time_range 仅支持 week / month / quarter")
    start = utcnow() - timedelta(days=TIME_RANGE_DAYS[time_range])
    report_ids = await _get_department_report_ids(db, department_id)

    return {
        "generate_trend": await _generate_trend(db, report_ids, start),
        "hot_keywords": await _hot_keywords(db, report_ids, start),
        "active_users": await _active_users(db, report_ids, start),
        "model_usage": await _model_usage(db, report_ids, start),
        "module_success_rate": await _module_success_rate(db, report_ids, start),
    }

