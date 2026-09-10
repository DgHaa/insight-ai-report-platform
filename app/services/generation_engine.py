"""报告生成引擎：模块执行器。

每个模块执行流程（设计文档 1.3.2《生成流程》）：
    抓取外部数据 → 构建 Prompt → 调用模型 API → 解析结果 → 存储

关键特性：
- 模块之间无数据依赖，默认「有界并发」执行（GENERATION_MODULE_CONCURRENCY，
  设为 1 可恢复严格串行）；结果仍按 config.modules 原顺序汇总；
- 模块级错误隔离：某模块失败时记录错误并继续执行其余模块（不中断整个报告）；
- 超时（硬止损）与手动终止通过 TaskControl 统一控制；
- 支持从 user_data_source_credentials 表引用数据源凭证（密文自动解密）；
- 支持引用「部门公共模型配置」作为模块模型默认值（避免逐模块重复填密钥）；
- Prompt 支持 {keywords} / {urls} / {date} 占位符替换；
- 参考资料按 PROMPT_MAX_CHARS 做总预算裁剪，避免超出模型上下文；
- 模型调用失败按指数退避重试；
- 全部模块完成后可再生成一次跨模块「执行摘要」。
"""
import asyncio
import contextlib
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.concurrency import TaskCancelledError, TaskTimeoutError
from app.core.crypto import decrypt_value
from app.models import ReportVersion
from app.services.cost_logger import record_model_call
from app.services.fetcher import FetchConfig, FetchResult, Fetcher, load_credential_config
from app.services.frameworks import get_framework_prompt
from app.services.model_client import (
    ModelCallResult,
    ModelClient,
    ModelCallError,
    ModelOutputTruncatedError,
    _is_reasoning_model,
)
from app.services.progress_pusher import (
    PHASE_BUILDING,
    PHASE_FETCHING,
    PHASE_GENERATING,
    PHASE_INIT,
    PHASE_STORING,
    BasePusher,
    ProgressEvent,
)

logger = logging.getLogger(__name__)

# 每个模块单独使用会话：模块可并发执行，共享 AsyncSession 并非并发安全
from app.db.session import SessionLocal  # noqa: E402


def _module_config_hash(raw: dict) -> str:
    """模块「生成相关配置」签名：用于增量生成时判断历史模块是否需要重跑。

    仅纳入会影响产出的字段（prompt/框架/输出格式/关键词/数据源/模型），
    排除调度等无关字段，避免无关改动触发整模块重算。
    """
    sig = {
        "prompt": raw.get("prompt"),
        "framework": raw.get("framework"),
        "output_format": raw.get("output_format"),
        "keywords": raw.get("keywords"),
        "urls": (raw.get("data_sources") or {}).get("urls"),
        "model_name": (raw.get("model_config") or {}).get("model_name"),
    }
    return hashlib.sha256(
        json.dumps(sig, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass
class ModuleConfig:
    """解析后的单个模块配置。"""

    raw: dict
    module_title: str
    keywords: list[str]
    prompt: str
    model_config: dict
    data_sources: dict
    schedule: dict | None

    @classmethod
    def from_dict(cls, raw: dict) -> "ModuleConfig":
        return cls(
            raw=raw,
            module_title=(raw.get("module_title") or "").strip(),
            keywords=list(raw.get("keywords") or []),
            prompt=raw.get("prompt") or "",
            model_config=raw.get("model_config") or {},
            data_sources=raw.get("data_sources") or {},
            schedule=raw.get("schedule"),
        )

    @property
    def provider(self) -> str:
        return (self.model_config.get("provider") or "custom").lower()

    @property
    def model_name(self) -> str:
        return self.model_config.get("model_name") or "模拟模型"

    @property
    def output_format(self) -> str:
        return (self.raw.get("output_format") or "text").lower()

    @property
    def structured(self) -> bool:
        """是否为「结构化输出」：除叙述外还需产出数据点 + 图表规格。"""
        return self.output_format == "structured"

    @property
    def parameters(self) -> dict:
        return self.model_config.get("parameters") or {}

    @property
    def unit_price_per_1k(self):
        """用户自填单价（平台不做保障）。"""
        return self.model_config.get("unit_price_per_1k_tokens") or self.model_config.get(
            "unit_price"
        )


@dataclass
class ModuleResult:
    """单个模块的执行结果。"""

    module_title: str
    content: str
    error: str | None = None
    fetched: list[FetchResult] = field(default_factory=list)
    model_result: ModelCallResult | None = None
    engine_used: str | None = None
    prompt_chars: int = 0
    truncated_refs: bool = False
    # 结构化输出（output_format=structured）解析出的辅助洞察组件
    data_points: list[dict] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)


@dataclass
class GenerationResult:
    """整份报告的生成结果。"""

    report_id: str
    task_id: str
    module_results: list[ModuleResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    summary: str = ""
    version_number: int | None = None
    worker_id: str | None = None

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.module_results if not r.error)

    @property
    def model_used(self) -> str:
        """汇总使用过的模型标识（去重）。"""
        models = list(
            dict.fromkeys(
                r.engine_used for r in self.module_results if r.engine_used
            )
        )
        return ", ".join(models) or "模拟模型"


def _simulate_content(module: ModuleConfig, fetched: list[FetchResult]) -> str:
    """模拟模式下的模块内容生成（不调用真实模型/抓取）。"""
    lines = [
        f"## {module.module_title or '未命名模块'}",
        "",
        "### 概述",
        f"关键词：{'、'.join(module.keywords) if module.keywords else '无'}",
        "",
        "### 分析",
        "（模拟生成内容：请在真实环境中配置模型 API 以获取实际分析结果。）",
    ]
    if fetched:
        lines += ["", "### 数据来源"]
        lines += [f"- {f.url}" for f in fetched]
    return "\n".join(lines)


# 结构化输出（output_format=structured）的 JSON 信封 schema 指令。
# 模型除叙述(content)外，还需产出 data_points（关键量化结论）与 charts（图表规格），
# 供前端渲染数据点卡片与图表，实现「洞察可视化」的质变。
_STRUCTURED_SCHEMA_PROMPT = (
    "输出格式要求：请仅输出一个合法的 JSON 对象（不要用代码块包裹、不要输出任何解释性文字），"
    "结构严格如下：\n"
    "{\n"
    '  "content": "（必填）基于分析的中文叙述，使用 Markdown，可在句末用 [编号] 标注资料依据",\n'
    '  "data_points": [{"label": "指标名", "value": "数值", "unit": "单位(可选)", '
    '"trend": "up|down|flat(可选)", "note": "一句话说明(可选)", '
    '"source": "支撑该结论的参考资料编号，须为提供的 [编号]（如 [1]），无对应资料可留空"}],\n'
    '  "charts": [{"type": "bar|line|pie", "title": "图表标题", "caption": "一句话解读(可选)", '
    '"x": ["类目1","类目2"], "series": [{"name": "系列名", "data": [数值, 数值]}]}]\n'
    "}\n"
    "要求：\n"
    "1) data_points 提取 3~6 个最关键、可量化的结论，value 尽量为数字字符串；\n"
        "2) charts 至多 2 个，类型仅限 bar / line / pie；series.data 必须为数值数组；"
        "x 为类目数组（pie 图可省略 x，改用 series[0].name 作为各扇区类目）；\n"
        "3) 务必保证 JSON 可被直接解析（不要有尾随逗号、不要有注释）；\n"
        "4) data_points 的 source 必须来自上方提供的参考资料 [编号]，不得编造未提供的来源。"
    )


def _simulate_structured(
    module: ModuleConfig, fetched: list[FetchResult]
) -> tuple[str, list[dict], list[dict]]:
    """模拟模式下的结构化模块产出（叙述 + 数据点 + 图表）。"""
    content = _simulate_content(module, fetched)
    data_points = [
        {"label": "关键指标 A", "value": "87.5", "unit": "%", "trend": "up", "note": "较上周期提升"},
        {"label": "关键指标 B", "value": "12", "unit": "件", "trend": "down", "note": "风险事件下降"},
        {"label": "关键指标 C", "value": "3.2", "unit": "天", "trend": "flat", "note": "基本持平"},
    ]
    charts = [
        {
            "type": "bar",
            "title": "各维度评分",
            "caption": "模拟数据：用于演示结构化图表渲染",
            "x": ["维度一", "维度二", "维度三", "维度四"],
            "series": [{"name": "得分", "data": [82, 76, 91, 68]}],
        }
    ]
    return content, data_points, charts


_CONTROL_RE = re.compile(r'"(\\.|[^"\\])*"')


def _repair_json_strings(s: str) -> str:
    """转义 JSON 字符串字面量内的非法控制字符（未转义的换行/回车/制表符）。

    模型偶发会在 JSON 字符串值里直接写裸换行（而非 \\n），导致严格 json.loads 失败。
    此处仅对双引号包裹的字符串内部做转义，不影响结构空白，使“裸换行 JSON”也能解析。
    """

    def _esc(m: "re.Match") -> str:
        body = m.group(0)[1:-1]
        body = (
            body.replace("\\", "\x00")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
            .replace("\x00", "\\")
        )
        return '"' + body + '"'

    return _CONTROL_RE.sub(_esc, s)


def _parse_structured(text: str) -> tuple[str, list[dict], list[dict]]:
    """解析结构化 JSON 信封，返回 (content, data_points, charts)。

    容错：JSON 解析失败或字段缺失时，返回 (原文, [], [])，由上层按普通文本兜底，
    绝不静默丢内容。
    """
    raw = (text or "").strip()
    if not raw:
        return "", [], []
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    raw = _repair_json_strings(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                data = json.loads(_repair_json_strings(match.group(0)))
            except json.JSONDecodeError:
                return (text or "（模型返回空内容）"), [], []
        else:
            return (text or "（模型返回空内容）"), [], []
    if not isinstance(data, dict):
        return (text or "（模型返回空内容）"), [], []

    content = data.get("content")
    if not isinstance(content, str):
        content = text or "（模型返回空内容）"

    data_points: list[dict] = []
    for dp in data.get("data_points") or []:
        if isinstance(dp, dict) and dp.get("label"):
            data_points.append(
                {
                    "label": str(dp.get("label", "")),
                    "value": str(dp.get("value", "")) if dp.get("value") is not None else "",
                    "unit": str(dp.get("unit", "")) if dp.get("unit") else "",
                    "trend": str(dp.get("trend", "")) if dp.get("trend") else "",
                    "note": str(dp.get("note", "")) if dp.get("note") else "",
                    "source": str(dp.get("source", "")) if dp.get("source") else "",
                }
            )

    charts: list[dict] = []
    for ch in data.get("charts") or []:
        if not isinstance(ch, dict) or ch.get("type") not in ("bar", "line", "pie"):
            continue
        series = ch.get("series") or []
        if not isinstance(series, list) or not series:
            continue
        clean_series = []
        for s in series:
            if not isinstance(s, dict):
                continue
            sd = s.get("data") or []
            clean_series.append(
                {
                    "name": str(s.get("name", "系列")),
                    "data": [float(x) for x in sd if _is_number(x)],
                }
            )
        if not clean_series:
            continue
        charts.append(
            {
                "type": ch.get("type"),
                "title": str(ch.get("title", "图表")),
                "caption": str(ch.get("caption", "")) if ch.get("caption") else "",
                "x": [str(x) for x in (ch.get("x") or [])],
                "series": clean_series,
            }
        )
    return content, data_points, charts


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) or (isinstance(v, str) and v.strip() != "" and v.strip().lstrip("-").replace(".", "", 1).isdigit())


def _merge_fetch_config(base: FetchConfig, overlay: FetchConfig) -> FetchConfig:
    """合并抓取配置：凭证引用（overlay）覆盖模块默认（base）。"""
    return FetchConfig(
        proxy=overlay.proxy or base.proxy,
        cookies=overlay.cookies or base.cookies,
        headers={**(base.headers or {}), **(overlay.headers or {})},
        timeout=overlay.timeout or base.timeout,
        retries=overlay.retries or base.retries,
        max_length=overlay.max_length or base.max_length,
        use_playwright=overlay.use_playwright
        if overlay.use_playwright is not None
        else base.use_playwright,
    )


def _render_placeholders(text: str, module: ModuleConfig, fetched: list[FetchResult]) -> str:
    """替换 Prompt 中的占位符：{keywords} / {urls} / {date}。

    前端模块表单与内置模板均使用这些占位符，若不替换模型会收到字面量。
    """
    if not text:
        return text
    mapping = {
        "{keywords}": "、".join(module.keywords) if module.keywords else "（未指定关键词）",
        "{urls}": "、".join(f.url for f in fetched) if fetched else "（未配置外部数据源）",
        "{date}": datetime.now().strftime("%Y-%m-%d"),
    }
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def _budget_refs(refs: list[str], max_chars: int) -> tuple[list[str], bool]:
    """按总字符预算等比裁剪参考资料，返回 (裁剪后的 refs, 是否发生裁剪)。"""
    total = sum(len(r) for r in refs)
    if max_chars <= 0 or total <= max_chars:
        return refs, False
    scale = max_chars / total
    trimmed = []
    for r in refs:
        keep = max(200, int(len(r) * scale))
        if len(r) > keep:
            trimmed.append(r[:keep] + "…（按预算裁剪）")
        else:
            trimmed.append(r)
    # 二次收敛：保证总量不超预算
    while sum(len(r) for r in trimmed) > max_chars and len(trimmed) > 1:
        trimmed = trimmed[:-1]
    return trimmed, True


def _select_refs(fetched: list[FetchResult], module: ModuleConfig) -> tuple[list[str], bool]:
    """按模块关键词做相关性筛选：仅保留含关键词的段落，显著降低喂给模型的 token（①）。

    关闭相关性筛选（settings.GENERATION_REF_RELEVANCE_FILTER=False）或模块无关键词时，
    退化为返回完整抓取文本，再由 _budget_refs 做总预算裁剪。
    """
    enable = bool(getattr(settings, "GENERATION_REF_RELEVANCE_FILTER", True))
    keywords = [k.strip().lower() for k in (module.keywords or []) if k.strip()]
    refs: list[str] = []
    truncated = False
    for i, f in enumerate(fetched, start=1):
        text = f.text or ""
        if enable and keywords:
            paras = [p.strip() for p in re.split(r"\n{1,}", text) if len(p.strip()) > 20]
            matched = [p for p in paras if any(kw in p.lower() for kw in keywords)]
            if matched:
                body = "\n".join(matched)
            else:
                # 关键词在本文中无命中：保留开头，避免完全丢失上下文
                body = text[:2000]
                truncated = True
        else:
            body = text
        refs.append(f"[{i}] 来源：{f.url}\n{body}")
    return refs, truncated


def _build_system_extra(module: ModuleConfig) -> str | None:
    """构建追加到共享 system 的模块级引导语（分析框架 + 结构化 schema）（⑤）。

    与基础角色设定一同被厂商 prompt caching 命中，从而缩短每次 user prompt。
    """
    parts: list[str] = []
    fw = get_framework_prompt(module.raw.get("framework"))
    if fw:
        parts.append(fw)
    if module.structured:
        parts.append(_STRUCTURED_SCHEMA_PROMPT)
    elif module.output_format == "json":
        parts.append(
            "输出格式要求：只输出一个合法的 JSON 对象，不要输出任何解释性文字、"
            "不要用代码块包裹。确保 JSON 可被直接解析。"
        )
    return "\n\n".join(parts) or None


class GenerationEngine:
    """模块执行引擎（默认有界并发）。"""

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        model_client: ModelClient | None = None,
    ) -> None:
        self.fetcher = fetcher or Fetcher()
        self.model_client = model_client or ModelClient()

    async def execute(
        self,
        *,
        report,
        task_id,
        config: dict,
        pusher: BasePusher,
        control,
        db: AsyncSession,
        worker_id: str | None = None,
        force: bool = False,
    ) -> GenerationResult:
        """执行 config.modules 中的全部模块。

        force=False（增量生成，默认）：若当前版本中已有「配置未变且内容非空」的模块，
        直接复用其历史产出（内容/数据点/图表），不再调用模型，避免对已成功模块空耗 token。
        force=True：忽略历史版本，逐模块重新生成。
        """
        task_id_str = str(task_id)
        result = GenerationResult(
            report_id=str(report.id), task_id=task_id_str, worker_id=worker_id
        )
        modules = list(config.get("modules") or [])
        total = max(len(modules), 1)

        pusher.push(
            ProgressEvent(PHASE_INIT, 5, "正在解析报告配置...", task_id=task_id_str, total=len(modules))
        )
        control.check()
        # 成功模块及其配置（供生成跨模块执行摘要时复用模型配置）
        ok_pairs: list[tuple[ModuleConfig, ModuleResult]] = []
        # 按模块下标收集，保证结果与 config.modules 原顺序一致（并行完成顺序不定）
        results_by_index: dict[int, tuple[ModuleConfig, ModuleResult]] = {}
        # ① 报告级共享抓取池：同一 (url, 凭证) 只抓取一次，跨模块复用，避免重复网络与重复喂入。
        shared_fetched: dict = {}
        shared_lock = asyncio.Lock()
        # 按 (url, 凭证id) 的细粒度锁，消除并发下「检查缓存→抓取→写回」的 TOCTOU 竞态
        shared_key_locks: dict = {}

        # 增量生成：读取当前版本中已成功且配置未变的模块，后续直接复用（不调模型）
        existing_by_index: list[dict | None] = [None] * len(modules)
        if not force and getattr(report, "current_version", 0):
            try:
                latest = await db.scalar(
                    select(ReportVersion).where(
                        ReportVersion.report_id == report.id,
                        ReportVersion.version_number == report.current_version,
                    )
                )
                if latest and latest.content:
                    emods = latest.content.get("modules") or []
                    for i, em in enumerate(emods):
                        if isinstance(em, dict) and em.get("content"):
                            existing_by_index[i] = em
            except Exception:  # noqa: BLE001
                logger.debug("读取历史版本失败，按全量生成处理", exc_info=True)

        def _reuse_or_run(self, idx: int, module_raw: dict) -> "ModuleResult":
            """增量逻辑：命中历史成功模块则复用，否则真正执行。"""
            cached = existing_by_index[idx] if not force else None
            if cached is not None and cached.get("config_hash") == _module_config_hash(module_raw):
                mresult = ModuleResult(
                    module_title=module_raw.get("module_title", ""),
                    content=cached.get("content", ""),
                )
                mresult.data_points = cached.get("data_points") or []
                mresult.charts = cached.get("charts") or []
                mresult.cached = True
                return mresult
            return None  # 需真正执行

        # 大纲先行（⑥）：在真正生成模块前，用一次轻量调用规划各模块角度，避免重复与遗漏。
        outline: dict = {}
        will_run = [
            i for i, m in enumerate(modules)
            if not (existing_by_index[i] is not None
                    and existing_by_index[i].get("config_hash") == _module_config_hash(m))
        ]
        if settings.GENERATION_ENABLE_OUTLINE and len(modules) > 1 and len(will_run) >= 2:
            try:
                outline = await self._build_outline(modules, control, task_id, pusher, report)
            except (asyncio.CancelledError, TaskCancelledError, TaskTimeoutError):
                raise
            except Exception:  # noqa: BLE001
                logger.exception("报告大纲生成失败，按无大纲模式继续")
                outline = {}

        try:
            concurrency = max(1, int(settings.GENERATION_MODULE_CONCURRENCY or 1))
            if concurrency == 1 or len(modules) <= 1:
                for idx, module_raw in enumerate(modules):
                    control.check()
                    module = ModuleConfig.from_dict(module_raw)
                    reused = _reuse_or_run(self, idx, module_raw)
                    if reused is not None:
                        mresult = reused
                    else:
                        mresult = await self._execute_module(
                            module, idx, len(modules), task_id_str, pusher, control, task_id,
                            report_department_id=getattr(report, "department_id", None),
                            shared_fetched=shared_fetched, shared_lock=shared_lock,
                            shared_key_locks=shared_key_locks,
                            outline_brief=outline.get(idx),
                        )
                    results_by_index[idx] = (module, mresult)
            else:
                sem = asyncio.Semaphore(concurrency)

                async def runner(index: int, raw: dict) -> None:
                    async with sem:
                        control.check()
                        module = ModuleConfig.from_dict(raw)
                        reused = _reuse_or_run(self, index, raw)
                        if reused is not None:
                            mresult = reused
                        else:
                            mresult = await self._execute_module(
                                module, index, len(modules), task_id_str, pusher, control, task_id,
                                report_department_id=getattr(report, "department_id", None),
                                shared_fetched=shared_fetched, shared_lock=shared_lock,
                                shared_key_locks=shared_key_locks,
                                outline_brief=outline.get(index),
                            )
                        results_by_index[index] = (module, mresult)

                await asyncio.gather(*(runner(i, raw) for i, raw in enumerate(modules)))

            # 按配置原顺序汇总（含进度推送，保持与报告结构一致）
            for idx in sorted(results_by_index):
                module, mresult = results_by_index[idx]
                self._collect(
                    result, module, mresult, idx, len(modules), pusher, task_id_str,
                    done_count=idx + 1, ok_pairs=ok_pairs,
                )

            control.check()
            pusher.push(
                ProgressEvent(PHASE_STORING, 95, "正在生成历史版本并保存...", task_id=task_id_str)
            )
            if settings.GENERATION_ENABLE_SUMMARY and len(modules) > 1 and ok_pairs:
                result.summary = await self._build_executive_summary(
                    ok_pairs, result.errors, control, task_id, pusher,
                    report_department_id=getattr(report, "department_id", None),
                )
            else:
                result.summary = self._build_summary(result.module_results, result.errors)
        except asyncio.CancelledError:
            self._emit_terminated(pusher, task_id_str)
            raise
        except (TaskCancelledError, TaskTimeoutError):
            self._emit_terminated(pusher, task_id_str)
            raise
        return result

    def _collect(
        self,
        result: GenerationResult,
        module: ModuleConfig,
        mresult: ModuleResult,
        idx: int,
        total: int,
        pusher: BasePusher,
        task_id_str: str,
        done_count: int | None = None,
        ok_pairs: list | None = None,
    ) -> None:
        """汇总单个模块结果并推送进度/内容。"""
        result.module_results.append(mresult)
        if mresult.error:
            result.errors.append(
                {"module_title": module.module_title, "error": mresult.error}
            )
            logger.warning(
                "模块[%s]执行失败（继续执行其余模块）: %s",
                module.module_title,
                mresult.error,
            )
        else:
            if ok_pairs is not None:
                ok_pairs.append((module, mresult))
            done = done_count if done_count is not None else idx + 1
            progress = 10 + int(80 * done / max(total, 1))
            # 渐进渲染：模块完成即推送内容，前端可边生成边看
            pusher.module_done(
                index=idx + 1,
                total=total,
                module_title=module.module_title,
                content=mresult.content,
                progress=min(progress, 92),
                task_id=task_id_str,
                data_points=mresult.data_points,
                charts=mresult.charts,
            )

    # ---------------- 单模块执行 ----------------

    async def _execute_module(
        self,
        module: ModuleConfig,
        idx: int,
        total: int,
        task_id_str: str,
        pusher: BasePusher,
        control,
        task_id,
        report_department_id=None,
        shared_fetched: dict | None = None,
        shared_lock=None,
        shared_key_locks: dict | None = None,
        outline_brief: str | None = None,
    ) -> ModuleResult:
        mresult = ModuleResult(module_title=module.module_title, content="")
        try:
            # ---- 1. 抓取外部数据（进度 10%~40%） ----
            urls = list(module.data_sources.get("urls") or [])
            fetch_cfg = FetchConfig.from_module(module.raw)
            credential_id = module.data_sources.get("credential_id")

            # 需要读库的操作（凭证/部门默认模型）使用模块独立会话
            async with SessionLocal() as db:
                if credential_id:
                    cred_cfg = await load_credential_config(db, credential_id)
                    if cred_cfg:
                        fetch_cfg = _merge_fetch_config(fetch_cfg, cred_cfg)
                dept_model = await self._load_department_model(db, report_department_id, module)

            for i, url in enumerate(urls, start=1):
                control.check()
                # ① 共享池：同一 (url, 凭证) 只抓取一次，跨模块复用，避免重复网络与重复喂入。
                # 用「按 key 的锁」包裹「检查+抓取」，消除并发下的 TOCTOU 竞态——
                # 否则在 GENERATION_MODULE_CONCURRENCY>1 时，两个并发模块可能在彼此写入缓存前
                # 都判定为未命中，导致同一 URL 被抓取多次、去重失效。
                key = (url, credential_id)
                key_lock = contextlib.nullcontext()
                if shared_key_locks is not None:
                    async with shared_lock:
                        key_lock = shared_key_locks.setdefault(key, asyncio.Lock())
                async with key_lock:
                    cached_fr = shared_fetched.get(key) if shared_fetched is not None else None
                    if cached_fr is not None:
                        logger.info("① 共享资料池命中，跳过重复抓取：%s", url)
                        mresult.fetched.append(cached_fr)
                        continue
                    progress = 10 + int(30 * (i - 1) / max(len(urls), 1))
                    pusher.push(
                        ProgressEvent(
                            PHASE_FETCHING,
                            progress,
                            f"正在抓取 {url} ({i}/{len(urls)})...",
                            task_id=task_id_str,
                            current=idx + 1,
                            total=total,
                        )
                    )
                    if settings.GENERATION_SIMULATE:
                        await asyncio.sleep(settings.GENERATION_STEP_DELAY)
                        fr = FetchResult(
                            url=url,
                            text=f"（模拟抓取内容：{url}）",
                            final_url=url,
                            status_code=200,
                            engine="simulate",
                        )
                    else:
                        logger.info("① 抓取资料：%s", url)
                        fr = await self.fetcher.fetch_url(url, fetch_cfg, control)
                    if shared_fetched is not None:
                        shared_fetched[key] = fr
                    mresult.fetched.append(fr)

            # ---- 2. 构建 Prompt（进度 45%） ----
            control.check()
            pusher.push(
                ProgressEvent(
                    PHASE_BUILDING, 45, "正在整合上下文信息...",
                    task_id=task_id_str, current=idx + 1, total=total,
                )
            )
            prompt = self._build_prompt(module, mresult.fetched, mresult, outline_brief)
            mresult.prompt_chars = len(prompt)

            # ---- 3. 调用模型 API（进度 50%~90%） ----
            control.check()
            progress = 50 + int(40 * idx / max(total, 1))
            pusher.push(
                ProgressEvent(
                    PHASE_GENERATING,
                    progress,
                    f"正在调用 {module.model_name} 生成...",
                    task_id=task_id_str,
                    current=idx + 1,
                    total=total,
                )
            )
            if settings.GENERATION_SIMULATE:
                await asyncio.sleep(settings.GENERATION_STEP_DELAY)
                if module.structured:
                    content, dps, charts = _simulate_structured(module, mresult.fetched)
                    mresult.content = content
                    mresult.data_points = dps
                    mresult.charts = charts
                else:
                    mresult.content = _simulate_content(module, mresult.fetched)
                mresult.engine_used = "simulate"
            else:
                system_extra = _build_system_extra(module)
                model_result = await self._call_model(
                    module, prompt, control, dept_model, system_extra=system_extra
                )
                mresult.model_result = model_result
                mresult.engine_used = f"{module.provider}:{module.model_name}"
                # ---- 4. 解析结果 ----
                if module.structured:
                    content, dps, charts = _parse_structured(model_result.text)
                    mresult.content = content
                    mresult.data_points = dps
                    mresult.charts = charts
                else:
                    mresult.content = self._parse_output(model_result.text, module)
                # ---- 模型成本日志 ----
                try:
                    async with SessionLocal() as db:
                        await record_model_call(
                            db,
                            task_id=task_id,
                            provider=module.provider,
                            model_name=module.model_name,
                            prompt_tokens=model_result.prompt_tokens,
                            completion_tokens=model_result.completion_tokens,
                            total_tokens=model_result.total_tokens,
                            unit_price_per_1k_tokens=module.unit_price_per_1k,
                        )
                except Exception:  # noqa: BLE001
                    logger.exception("模型成本日志写入失败")
        except asyncio.CancelledError:
            raise
        except (TaskCancelledError, TaskTimeoutError):
            raise
        except Exception as exc:  # noqa: BLE001
            mresult.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            mresult.content = f"（模块执行失败：{mresult.error}）"
            logger.exception("模块[%s]执行异常", module.module_title)
        return mresult

    # ---------------- 子流程 ----------------

    async def _load_department_model(self, db, department_id, module: ModuleConfig) -> dict | None:
        """若模块勾选了「使用部门公共模型配置」，读取该部门默认配置（密钥已解密）。"""
        if not module.model_config.get("use_department_default") or not department_id:
            return None
        from app.models import DepartmentModelConfig

        cfg = (
            await db.scalars(
                select(DepartmentModelConfig)
                .where(
                    DepartmentModelConfig.department_id == department_id,
                    DepartmentModelConfig.is_active.is_(True),
                )
                .order_by(DepartmentModelConfig.created_at.desc())
            )
        ).first()
        if cfg is None:
            return None
        return {
            "provider": cfg.provider,
            "endpoint": cfg.endpoint,
            "api_key": decrypt_value(cfg.api_key),
            "model_name": cfg.model_name,
        }

    async def _call_model(
        self,
        module: ModuleConfig,
        prompt: str,
        control,
        dept_model: dict | None = None,
        system_extra: str | None = None,
    ) -> ModelCallResult:
        """调用模型 API（带单次超时保护 + 失败指数退避重试）。

        注意：输出被 max_tokens 截断（ModelOutputTruncatedError）属于「不可重试错误」，
        相同 prompt + 相同过小预算必然再次失败，因此直接上抛、不进入重试循环（③）。
        """
        params = module.parameters
        endpoint = module.model_config.get("endpoint", "")
        api_key = module.model_config.get("api_key")
        model_name = module.model_name
        provider = module.provider

        # 部门公共配置作为底座，模块内显式配置优先
        if dept_model:
            endpoint = module.model_config.get("endpoint") or dept_model.get("endpoint") or ""
            api_key = module.model_config.get("api_key") or dept_model.get("api_key")
            model_name = module.model_config.get("model_name") or dept_model.get("model_name") or model_name
            if not module.model_config.get("provider"):
                provider = dept_model.get("provider") or provider

        attempts = max(0, int(settings.MODEL_CALL_RETRIES or 0)) + 1
        last_exc: Exception | None = None
        retries_done = 0
        for attempt in range(1, attempts + 1):
            control.check()
            try:
                return await asyncio.wait_for(
                    self.model_client.call(
                        provider=provider,
                        endpoint=endpoint,
                        api_key=api_key,
                        model_name=model_name,
                        prompt=prompt,
                        temperature=params.get("temperature"),
                        max_tokens=params.get("max_tokens"),
                        system=system_extra,
                    ),
                    timeout=settings.MODEL_CALL_TIMEOUT,
                )
            except (asyncio.CancelledError, TaskCancelledError, TaskTimeoutError):
                raise
            except ModelOutputTruncatedError as exc:
                # 截断错误：重试无意义，直接上抛（不计入重试次数）
                last_exc = exc
                break
            except (ModelCallError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                retries_done += 1
                delay = min(8.0, 1.5 * (2 ** (attempt - 1)))
                logger.warning(
                    "模型调用失败（%d/%d），%.1fs 后重试: %s", attempt, attempts, delay, exc
                )
                await asyncio.sleep(delay)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                break
        raise ModelCallError(f"模型调用失败（已重试 {retries_done} 次）: {last_exc}")

    def _build_prompt(
        self,
        module: ModuleConfig,
        fetched: list[FetchResult],
        mresult: ModuleResult | None = None,
        outline_brief: str | None = None,
    ) -> str:
        """构建 Prompt：占位符替换 + 提示词 + 关键词 + 抓取资料（相关性筛选）+ 输出要求。

        注：分析框架引导语与结构化 JSON schema 已移至共享 system（见 _build_system_extra），
        不再重复写入 user prompt，以便厂商 prompt caching 命中、并缩短单次输入。
        """
        sections: list[str] = []

        prompt_text = _render_placeholders(module.prompt, module, fetched)
        if prompt_text:
            sections.append(prompt_text)
        if module.keywords:
            sections.append(f"关键词：{'、'.join(module.keywords)}")

        if fetched:
            refs, rel_truncated = _select_refs(fetched, module)
            if mresult is not None:
                mresult.truncated_refs = rel_truncated
            refs, budget_truncated = _budget_refs(refs, int(settings.PROMPT_MAX_CHARS or 0))
            if budget_truncated:
                if mresult is not None:
                    mresult.truncated_refs = True
                logger.info(
                    "模块[%s] 参考资料超出预算，已按比例裁剪", module.module_title
                )
            sections.append("参考资料：\n" + "\n\n".join(refs))
            sections.append(
                "输出要求：分析结论请在句末用 [编号] 标注所依据的资料（如 [1]）；"
                "文末列出「参考来源」清单，格式为 [编号] URL。不要引用未提供的资料。"
            )

        if outline_brief:
            sections.append(
                f"撰写要点（来自报告大纲，请紧扣此角度、勿与其它模块重复）：{outline_brief}"
            )

        return "\n\n".join(sections) or "请基于给定主题生成分析内容。"

    def _parse_output(self, text: str, module: ModuleConfig) -> str:
        """解析模型输出：支持 json / structured 结构化输出。"""
        if module.structured:
            content, _dps, _charts = _parse_structured(text)
            return content
        if module.output_format == "json":
            cleaned = text.strip()
            fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
            if fence:
                cleaned = fence.group(1).strip()
            try:
                data = json.loads(cleaned)
                return json.dumps(data, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", cleaned, re.S)
                if match:
                    try:
                        return json.dumps(
                            json.loads(match.group(0)), ensure_ascii=False, indent=2
                        )
                    except json.JSONDecodeError:
                        pass
                return f"（JSON 解析失败，返回原文）\n{text}"
        return text or "（模型返回空内容）"

    async def _build_outline(
        self, modules: list[dict], control, task_id, pusher: BasePusher, report
    ) -> dict:
        """大纲先行（⑥）：用一次轻量调用规划各模块撰写角度，避免内容重复与遗漏。

        仅在非模拟模式发起真实调用；模拟模式返回空（不消耗模型）。返回的 dict
        以「0 基模块下标」为键，值为该模块的撰写要点，注入对应模块的 prompt。
        """
        if settings.GENERATION_SIMULATE:
            return {}
        metas = []
        for i, m in enumerate(modules, start=1):
            mc = ModuleConfig.from_dict(m)
            metas.append(f"{i}. {mc.module_title}（关键词：{('、'.join(mc.keywords) or '无')}）")
        title = getattr(report, "title", "") or ""
        plan_prompt = (
            "你正在为一份企业洞察报告规划撰写大纲，目标是让各模块角度互补、避免内容重复。\n"
            + (f"报告主题：{title}\n" if title else "")
            + "报告包含以下模块：\n" + "\n".join(metas) + "\n\n"
            "请输出一个 JSON 对象：键为模块序号（从 1 开始，字符串），值为该模块的「撰写要点」"
            "（1~2 句，说明它应聚焦的独特角度，避免与其它模块重复）；"
            "并额外给出一个键 \"_common\"，值为各模块应共同强调的 1~3 条核心结论。"
            "只输出 JSON，不要任何解释性文字，不要代码块包裹。"
        )
        first = ModuleConfig.from_dict(modules[0])
        task_id_str = str(task_id)
        try:
            control.check()
            pusher.push(
                ProgressEvent(PHASE_BUILDING, 8, "正在规划报告大纲...", task_id=task_id_str)
            )
            model_result = await self._call_model(first, plan_prompt, control, None)
        except (asyncio.CancelledError, TaskCancelledError, TaskTimeoutError):
            raise
        except Exception:  # noqa: BLE001
            logger.exception("大纲规划调用失败")
            return {}
        # 成本日志（②）：大纲调用也应计入审计
        try:
            async with SessionLocal() as db:
                await record_model_call(
                    db,
                    task_id=task_id,
                    provider=first.provider,
                    model_name=first.model_name,
                    prompt_tokens=model_result.prompt_tokens,
                    completion_tokens=model_result.completion_tokens,
                    total_tokens=model_result.total_tokens,
                    unit_price_per_1k_tokens=first.unit_price_per_1k,
                )
        except Exception:  # noqa: BLE001
            logger.exception("大纲成本日志写入失败")
        # 解析大纲 JSON
        text = (model_result.text or "").strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(_repair_json_strings(text))
        except Exception:  # noqa: BLE001
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    data = json.loads(_repair_json_strings(m.group(0)))
                except Exception:
                    return {}
            else:
                return {}
        outline: dict = {}
        for k, v in data.items():
            if k == "_common":
                continue
            try:
                idx = int(k) - 1
            except (TypeError, ValueError):
                continue
            if isinstance(v, str):
                outline[idx] = v
            elif isinstance(v, dict) and v.get("brief"):
                outline[idx] = str(v.get("brief"))
        return outline

    async def _build_executive_summary(
        self,
        ok_pairs: list,
        errors: list[dict],
        control,
        task_id,
        pusher: BasePusher,
        report_department_id=None,
    ) -> str:
        """基于各模块产出，再调用一次模型生成跨模块「执行摘要」。

        模型配置复用首个成功模块（含「部门公共模型配置」引用）。
        """
        if len(ok_pairs) < 2:
            return self._build_summary(
                [r for _, r in ok_pairs] + [], errors
            ) or self._build_summary(
                [ModuleResult(module_title="m", content="")], errors
            )

        # 模拟模式不再真实调用模型（此前会以空 endpoint 发起请求）
        if settings.GENERATION_SIMULATE:
            return self._build_summary([r for _, r in ok_pairs], errors)

        first_module, _ = ok_pairs[0]
        digest = []
        for module_cfg, r in ok_pairs:
            snippet = r.content.strip()
            if len(snippet) > 1200:
                snippet = snippet[:1200] + "…"
            digest.append(f"### {module_cfg.module_title}\n{snippet}")
        prompt = (
            "以下是同一份洞察报告各模块的产出内容。请生成一份面向管理层的「执行摘要」，"
            "要求：\n1) 用中文，控制在 300 字以内；\n2) 提炼跨模块的 3~5 条关键结论，"
            "突出共性趋势与最值得关注的风险；\n3) 不要逐模块复述，要做综合提炼；\n"
            "4) 如需引用具体数据，保留原文中的 [编号] 标注；\n"
            "5) 引用核验：检查各模块结论是否都有 [编号] 来源支撑；若发现明显缺乏来源支撑的结论，"
            "在摘要末尾以「⚠️ 引用核验：」开头列出（⑦）。\n\n"
            "各模块产出：\n\n" + "\n\n".join(digest)
        )

        try:
            control.check()
            pusher.push(
                ProgressEvent(PHASE_STORING, 96, "正在生成执行摘要...", task_id=str(task_id))
            )
            # 复用首个成功模块的模型配置（仅覆盖 prompt 与输出格式）
            summary_module = ModuleConfig(
                raw={**first_module.raw, "output_format": "text"},
                module_title="执行摘要",
                keywords=[],
                prompt=prompt,
                model_config=dict(first_module.model_config),
                data_sources={},
                schedule=None,
            )
            # 执行摘要 prompt 比单模块更长（含各模块摘要），推理模型若沿用模块的较小
            # max_tokens，思考过程会耗尽预算、最终答案为空。按模型类别给一个安全下限。
            sum_params = dict(summary_module.model_config.get("parameters") or {})
            if _is_reasoning_model(summary_module.model_name):
                floor = int(settings.MODEL_REASONING_MAX_TOKENS_CAP) // 4
            else:
                floor = int(settings.EXEC_SUMMARY_MAX_TOKENS)
            sum_params["max_tokens"] = max(int(sum_params.get("max_tokens") or 0), floor)
            summary_module.model_config["parameters"] = sum_params
            dept_model = None
            if summary_module.model_config.get("use_department_default"):
                async with SessionLocal() as db:
                    dept_model = await self._load_department_model(
                        db, report_department_id, summary_module
                    )
            model_result = await self._call_model(
                summary_module, prompt, control, dept_model,
                system_extra=_build_system_extra(summary_module),
            )
            # ② 成本日志：执行摘要这次调用此前被漏记，现补上审计
            try:
                async with SessionLocal() as db:
                    await record_model_call(
                        db,
                        task_id=task_id,
                        provider=summary_module.provider,
                        model_name=summary_module.model_name,
                        prompt_tokens=model_result.prompt_tokens,
                        completion_tokens=model_result.completion_tokens,
                        total_tokens=model_result.total_tokens,
                        unit_price_per_1k_tokens=summary_module.unit_price_per_1k,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("执行摘要成本日志写入失败")
            text = (model_result.text or "").strip()
            if not text:
                return self._build_summary([r for _, r in ok_pairs], errors)
            failed_note = ""
            if errors:
                failed_note = f"\n\n> 注：{len(errors)} 个模块生成失败，摘要仅覆盖成功模块。"
            return text + failed_note
        except (asyncio.CancelledError, TaskCancelledError, TaskTimeoutError):
            raise
        except Exception:  # noqa: BLE001
            logger.exception("执行摘要生成失败，回退为统计摘要")
            return self._build_summary([r for _, r in ok_pairs], errors)

    @staticmethod
    def _build_summary(results: list[ModuleResult], errors: list[dict]) -> str:
        total = len(results)
        ok = sum(1 for r in results if not r.error)
        failed = total - ok
        summary = f"本报告共 {total} 个模块，成功 {ok} 个，失败 {failed} 个。"
        if failed:
            names = "、".join(e.get("module_title") or "未知" for e in errors)
            summary += f" 失败模块：{names}。"
        return summary

    @staticmethod
    def _emit_terminated(pusher: BasePusher, task_id_str: str) -> None:
        try:
            pusher.terminated(task_id=task_id_str)
        except Exception:  # noqa: BLE001
            pass
