#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验收 Insight 报告生成链路「优化①：报告级共享资料池 + 相关性筛选」的抓取路径。

三部分（无需 pytest，直接 `python tests/test_fetch_path.py` 运行）：
  Part 1  _select_refs 相关性筛选  —— 纯函数级，确定性，零网络
  Part 2  共享资料池去重          —— 进程内 mock fetcher，确定性，零网络 / 零 token
  Part 3  真实端到端（API）       —— 两模块共享同一真实 URL，验收生产环境抓取去重 + 内容引用

运行前请确保后端已在 8080 端口运行（本脚本 Part 3 会真实调用模型，消耗少量 token）。
"""
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------- 配置 ----------------
BASE = "http://localhost:8080/api/v1"
DEPT = "0657408b-5193-4a67-b473-98069166bd2e"
USER = "dong_bg_finance"
# 真实模型密钥：仅从环境变量读取（切勿硬编码入库，GitHub 密钥扫描会拦截）。
# 运行 Part 3 / Part 4 前请先设置：  set DEEPSEEK_API_KEY=sk-xxx
# 未设置时 Part 3 / Part 4 会自动跳过（不影响 Part 1 / Part 2 / Part 2b 的确定性验收）。
API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BACKEND_LOG = os.environ.get(
    "INSIGHT_BACKEND_LOG",
    r"C:/Users/Dong/WorkBuddy/2026-08-31-20-07-29/insight_backend.log",
)
DB_DSN = "postgresql://postgres:postgres@localhost:5432/insight_ai"

# 用于验收去重的三个 URL：SHARED 被两个模块共享，URL_A / URL_B 各自独有
SHARED_URL = "https://example.com/"
URL_A = "https://example.com/?t=a"
URL_B = "https://example.com/?t=b"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")


# ---------------- Part 1：_select_refs 相关性筛选 ----------------
def part1() -> None:
    print("\n=== Part 1: _select_refs 相关性筛选 ===")
    from app.core.config import settings
    from app.services.fetcher import FetchResult
    from app.services.generation_engine import ModuleConfig, _select_refs

    text = (
        "量子计算是一种基于量子力学原理的全新计算范式，具备强大的并行处理能力。\n"
        "今天天气晴朗，适合去公园散步和户外运动，心情显得十分愉悦。\n"
        "量子比特是量子计算的基本信息单元，可处于叠加态从而表达更多信息。\n"
        "公司食堂今日供应红烧肉和清炒时蔬，广受同事们的一致好评。\n"
        "超导量子处理器在多家顶尖实验室已实现稳定运算，推动算力持续突破。\n"
    )
    fr = FetchResult(
        url="https://example.com/q",
        text=text,
        final_url="https://example.com/q",
        status_code=200,
        engine="requests",
    )
    mod_kw = ModuleConfig.from_dict(
        {"module_title": "M", "keywords": ["量子"], "prompt": "", "model_config": {}, "data_sources": {}}
    )
    mod_miss = ModuleConfig.from_dict(
        {"module_title": "M", "keywords": ["区块链"], "prompt": "", "model_config": {}, "data_sources": {}}
    )
    mod_none = ModuleConfig.from_dict(
        {"module_title": "M", "keywords": [], "prompt": "", "model_config": {}, "data_sources": {}}
    )

    # 1) 相关性开启 + 关键词命中 -> 仅保留含关键词段落
    settings.GENERATION_REF_RELEVANCE_FILTER = True
    refs, truncated = _select_refs([fr], mod_kw)
    joined = "\n".join(refs)
    ok = (
        "量子计算" in joined and "量子比特" in joined and "超导量子" in joined
    ) and ("户外运动" not in joined)
    check("相关性开启-仅保留含关键词段落", ok, f"truncated={truncated}")

    # 2) 关键词完全无命中 -> 回退 text[:2000] 且 truncated=True
    refs2, truncated2 = _select_refs([fr], mod_miss)
    check(
        "关键词无命中-回退text[:2000]且标记truncated",
        truncated2 is True and "量子计算" in "\n".join(refs2),
    )

    # 3) 关闭相关性筛选 -> 返回完整文本
    settings.GENERATION_REF_RELEVANCE_FILTER = False
    refs3, truncated3 = _select_refs([fr], mod_kw)
    check(
        "关闭筛选-返回完整文本",
        truncated3 is False and "户外运动" in "\n".join(refs3) and "量子计算" in "\n".join(refs3),
    )

    # 4) 无关键词 -> 返回完整文本
    settings.GENERATION_REF_RELEVANCE_FILTER = True
    refs4, truncated4 = _select_refs([fr], mod_none)
    check("无关键词-返回完整文本", truncated4 is False and "户外运动" in "\n".join(refs4))


# ---------------- Part 2：共享资料池去重（mock fetcher） ----------------
async def part2() -> None:
    print("\n=== Part 2: 共享资料池去重（mock fetcher） ===")
    from unittest.mock import AsyncMock

    from app.services.fetcher import FetchResult
    from app.services.generation_engine import GenerationEngine, ModuleConfig
    from app.services.model_client import ModelCallResult

    fetches: list[str] = []

    async def fake_fetch(url, cfg, control):
        fetches.append(url)
        return FetchResult(
            url=url, text=f"公开资料：{url}", final_url=url, status_code=200, engine="requests"
        )

    engine = GenerationEngine(fetcher=object(), model_client=object())
    # 进程内测试不写库：把成本日志落库调用打桩为 no-op（task_id 非真实 UUID，避免噪音）
    import app.services.generation_engine as _ge_mod

    _ge_mod.record_model_call = AsyncMock()
    engine.fetcher = type("F", (), {"fetch_url": staticmethod(fake_fetch)})()
    engine.model_client = AsyncMock()
    engine.model_client.call = AsyncMock(
        return_value=ModelCallResult(
            text="生成的模块内容。",
            provider="openai",
            model_name="deepseek-v4-flash",
            prompt_tokens=5,
            completion_tokens=5,
            total_tokens=10,
            latency_ms=100.0,
            usage={"total_tokens": 10},
        )
    )
    engine._load_department_model = AsyncMock(return_value=None)

    class Ctl:
        def check(self):
            pass

    class Push:
        def push(self, e):
            pass

    base_cfg = {
        "module_title": "M",
        "keywords": ["AI"],
        "prompt": "分析",
        "output_format": "text",
        "model_config": {
            "provider": "openai",
            "endpoint": "https://api.deepseek.com/v1/chat/completions",
            "api_key": "x",
            "model_name": "deepseek-v4-flash",
            "parameters": {"max_tokens": 2000},
        },
    }
    m1 = ModuleConfig.from_dict(
        {**base_cfg, "module_title": "模块A", "data_sources": {"urls": [SHARED_URL, URL_A]}}
    )
    m2 = ModuleConfig.from_dict(
        {**base_cfg, "module_title": "模块B", "data_sources": {"urls": [SHARED_URL, URL_B]}}
    )

    shared: dict = {}
    lock = asyncio.Lock()
    r1 = await engine._execute_module(
        m1, 0, 2, "task-p2", Push(), Ctl(), "task-p2", shared_fetched=shared, shared_lock=lock
    )
    r2 = await engine._execute_module(
        m2, 1, 2, "task-p2", Push(), Ctl(), "task-p2", shared_fetched=shared, shared_lock=lock
    )

    check("去重-抓取次数=唯一URL数(3)", len(fetches) == 3, f"fetches={fetches}")
    check("共享URL仅真实抓取1次", fetches.count(SHARED_URL) == 1)
    check("模块A引用数=其URL数(2)", len(r1.fetched) == 2)
    check(
        "模块B复用同一FetchResult对象(真共享而非重复抓取)",
        r2.fetched[0] is r1.fetched[0] and r2.fetched[1] is not r1.fetched[1],
    )
    check("两模块内容均非空(走完生成链路)", bool(r1.content) and bool(r2.content))


# ---------------- Part 2b：并发去重（证伪 TOCTOU 竞态） ----------------
async def part2b() -> None:
    print("\n=== Part 2b: 并发去重（gather 两模块共享 SHARED_URL，证伪 TOCTOU） ===")
    from unittest.mock import AsyncMock

    from app.services.fetcher import FetchResult
    from app.services.generation_engine import GenerationEngine, ModuleConfig
    from app.services.model_client import ModelCallResult

    fetches: list[str] = []

    async def fake_fetch(url, cfg, control):
        # 制造让出点：让并发的另一协程有机会在「检查缓存」后、「写回缓存」前插入，
        # 从而在 TOCTOU 未修复时重复抓取同一 URL。
        await asyncio.sleep(0.01)
        fetches.append(url)
        return FetchResult(
            url=url, text=f"公开资料：{url}", final_url=url, status_code=200, engine="requests"
        )

    engine = GenerationEngine(fetcher=object(), model_client=object())
    import app.services.generation_engine as _ge_mod

    _ge_mod.record_model_call = AsyncMock()
    engine.fetcher = type("F", (), {"fetch_url": staticmethod(fake_fetch)})()
    engine.model_client = AsyncMock()
    engine.model_client.call = AsyncMock(
        return_value=ModelCallResult(
            text="生成的模块内容。",
            provider="openai",
            model_name="deepseek-v4-flash",
            prompt_tokens=5,
            completion_tokens=5,
            total_tokens=10,
            latency_ms=100.0,
            usage={"total_tokens": 10},
        )
    )
    engine._load_department_model = AsyncMock(return_value=None)

    class Ctl:
        def check(self):
            pass

    class Push:
        def push(self, e):
            pass

    base_cfg = {
        "module_title": "M",
        "keywords": ["AI"],
        "prompt": "分析",
        "output_format": "text",
        "model_config": {
            "provider": "openai",
            "endpoint": "https://api.deepseek.com/v1/chat/completions",
            "api_key": "x",
            "model_name": "deepseek-v4-flash",
            "parameters": {"max_tokens": 2000},
        },
    }
    m1 = ModuleConfig.from_dict(
        {**base_cfg, "module_title": "模块A", "data_sources": {"urls": [SHARED_URL, URL_A]}}
    )
    m2 = ModuleConfig.from_dict(
        {**base_cfg, "module_title": "模块B", "data_sources": {"urls": [SHARED_URL, URL_B]}}
    )

    shared: dict = {}
    lock = asyncio.Lock()
    key_locks: dict = {}
    # 并发执行两个共享 SHARED_URL 的模块；若 TOCTOU 未修复，二者都会判定未命中并各自抓取一次。
    r1, r2 = await asyncio.gather(
        engine._execute_module(
            m1, 0, 2, "task-p2b", Push(), Ctl(), "task-p2b",
            shared_fetched=shared, shared_lock=lock, shared_key_locks=key_locks,
        ),
        engine._execute_module(
            m2, 1, 2, "task-p2b", Push(), Ctl(), "task-p2b",
            shared_fetched=shared, shared_lock=lock, shared_key_locks=key_locks,
        ),
    )

    check("并发-共享URL仅真实抓取1次(证伪TOCTOU)", fetches.count(SHARED_URL) == 1, f"fetches={fetches}")
    check("并发-抓取总数=唯一URL数(3)", len(fetches) == 3, f"fetches={fetches}")
    check(
        "并发-两模块均复用同一SHARED FetchResult(真共享)",
        r1.fetched[0] is r2.fetched[0],
    )
    check("并发-两模块内容均非空(走完生成链路)", bool(r1.content) and bool(r2.content))


# ---------------- Part 3：真实端到端（API） ----------------
def api(method: str, path: str, token=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def _module(prompt: str, urls: list[str]) -> dict:
    return {
        "module_title": "模块",
        "keywords": ["AI"],
        "prompt": prompt,
        "output_format": "text",
        "model_config": {
            "provider": "openai",
            "endpoint": "https://api.deepseek.com/v1/chat/completions",
            "api_key": API_KEY,
            "model_name": "deepseek-v4-flash",
            "parameters": {"max_tokens": 2000},
        },
        "data_sources": {"urls": urls},
    }


def part3() -> None:
    print("\n=== Part 3: 真实端到端（两模块共享同一 URL） ===")
    if not API_KEY:
        print("  [SKIP] 未设置环境变量 DEEPSEEK_API_KEY，跳过真实 E2E（Part 1/2/2b 仍有效验收）")
        return
    st, login = api("POST", "/auth/login", body={"username": USER, "department_id": DEPT})
    assert st == 200, f"login failed {st} {login}"
    token = login["data"]["token"]

    # 记录日志基线，仅统计本轮运行新增的抓取/命中行（日志是追加的，避免历史运行干扰）
    try:
        with open(BACKEND_LOG, "r", encoding="utf-8", errors="ignore") as f:
            log_before = f.read()
    except FileNotFoundError:
        log_before = ""

    modules = [
        _module("基于资料写一段关于 AI 的简短分析（不超过100字）。", [SHARED_URL, URL_A]),
        _module("基于资料写一段关于 AI 的简短分析（不超过100字）。", [SHARED_URL, URL_B]),
    ]
    st, created = api(
        "POST", "/reports", token=token, body={"title": "验收①-共享抓取池", "config": {"modules": modules}}
    )
    assert st == 200, f"create failed {st} {created}"
    rid = created["data"]["id"]
    print("  created report", rid)

    st, gen = api("POST", f"/reports/{rid}/generate", token=token, body={"force": True})
    assert st == 200, f"generate failed {st} {gen}"

    status = None
    for _ in range(80):
        st, det = api("GET", f"/reports/{rid}", token=token)
        d = det.get("data", {}) if isinstance(det, dict) else {}
        status = d.get("status") or (d.get("report") or {}).get("status")
        if status in ("completed", "failed"):
            break
        time.sleep(3)
    print("  final status:", status)
    check("生成任务完成", status == "completed", f"status={status}")

    # 从 DB 读取版本内容，确认抓取资料确实喂入并生成
    import asyncpg

    async def q():
        c = await asyncpg.connect(DB_DSN, timeout=5)
        content = await c.fetchval(
            "select content from report_versions where report_id=$1 order by version_number desc limit 1",
            rid,
        )
        await c.close()
        return content

    content = asyncio.run(q())
    full = json.dumps(json.loads(content), ensure_ascii=False) if content else ""
    check("生成内容引用了抓取URL(example.com)", "example.com" in full)

    # 通过新增的抓取日志，验收生产环境去重
    try:
        with open(BACKEND_LOG, "r", encoding="utf-8", errors="ignore") as f:
            log = f.read()
    except FileNotFoundError:
        log = ""
    new_log = log[len(log_before):]  # 仅本轮新增内容
    # 按行精确匹配 URL（避免 SHARED_URL 是其它 URL 的前缀导致子串误计数）
    import re

    fetch_urls = re.findall(r"① 抓取资料：(.+)$", new_log, re.M)
    hit_urls = re.findall(r"① 共享资料池命中，跳过重复抓取：(.+)$", new_log, re.M)
    shared_fetch = fetch_urls.count(SHARED_URL)
    shared_hit = hit_urls.count(SHARED_URL)
    check("生产环境-共享URL确有真实抓取(>=1)", shared_fetch >= 1, f"fetch日志数={shared_fetch}")
    # 关键不变量：每个被真实抓取的共享URL，被其它模块从缓存复用恰好一次（1:1，无冗余抓取）。
    # 该断言对日志跨运行累积免疫（N 次运行累加后仍满足 fetch==hit）。
    check(
        "生产环境-共享URL命中缓存数==真实抓取数(1:1 无冗余)",
        shared_hit == shared_fetch and shared_fetch >= 1,
        f"fetch={shared_fetch}, hit={shared_hit}",
    )

    # 清理：删除测试报告
    st, _ = api("DELETE", f"/reports/{rid}", token=token)
    print("  deleted report", rid, "status", st)


# ---------------- Part 4：真实并发路径（GENERATION_MODULE_CONCURRENCY>1）验证 ----------------
def part4() -> None:
    print("\n=== Part 4: 真实并发路径去重（3 模块共享 SHARED_URL，concurrency>1） ===")
    if not API_KEY:
        print("  [SKIP] 未设置环境变量 DEEPSEEK_API_KEY，跳过真实并发路径验证")
        return
    st, login = api("POST", "/auth/login", body={"username": USER, "department_id": DEPT})
    assert st == 200, f"login failed {st} {login}"
    token = login["data"]["token"]

    try:
        with open(BACKEND_LOG, "r", encoding="utf-8", errors="ignore") as f:
            log_before = f.read()
    except FileNotFoundError:
        log_before = ""

    # 三个模块均共享 SHARED_URL，并各带一个独有 URL；后端需以 concurrency>1 运行才会走 runner 并发分支。
    modules = [
        _module("基于资料写一段关于 AI 的简短分析（不超过100字）。", [SHARED_URL, "https://example.com/?c=a"]),
        _module("基于资料写一段关于 AI 的简短分析（不超过100字）。", [SHARED_URL, "https://example.com/?c=b"]),
        _module("基于资料写一段关于 AI 的简短分析（不超过100字）。", [SHARED_URL, "https://example.com/?c=c"]),
    ]
    st, created = api(
        "POST", "/reports", token=token, body={"title": "验收①-并发共享抓取池", "config": {"modules": modules}}
    )
    assert st == 200, f"create failed {st} {created}"
    rid = created["data"]["id"]
    print("  created report", rid)

    st, gen = api("POST", f"/reports/{rid}/generate", token=token, body={"force": True})
    assert st == 200, f"generate failed {st} {gen}"

    status = None
    for _ in range(80):
        st, det = api("GET", f"/reports/{rid}", token=token)
        d = det.get("data", {}) if isinstance(det, dict) else {}
        status = d.get("status") or (d.get("report") or {}).get("status")
        if status in ("completed", "failed"):
            break
        time.sleep(3)
    print("  final status:", status)
    check("并发路径-生成任务完成", status == "completed", f"status={status}")

    # 仅统计本轮新增日志
    try:
        with open(BACKEND_LOG, "r", encoding="utf-8", errors="ignore") as f:
            log = f.read()
    except FileNotFoundError:
        log = ""
    new_log = log[len(log_before):]
    import re
    fetch_urls = re.findall(r"① 抓取资料：(.+)$", new_log, re.M)
    hit_urls = re.findall(r"① 共享资料池命中，跳过重复抓取：(.+)$", new_log, re.M)
    shared_fetch = fetch_urls.count(SHARED_URL)
    shared_hit = hit_urls.count(SHARED_URL)
    # 关键不变量：3 个并发模块共享同一 URL，在并发路径（runner + Semaphore + 按 key 锁）下仍只真实抓取 1 次，
    # 其余 2 个从缓存复用。若 TOCTOU 未修复，3 个会各自抓取（fetch=2~3）。
    check("并发路径-共享URL仅真实抓取1次(证伪TOCTOU)", shared_fetch == 1, f"fetch={shared_fetch}")
    check("并发路径-其余模块命中缓存复用(2次)", shared_hit == 2, f"hit={shared_hit}")

    import asyncpg
    async def q():
        c = await asyncpg.connect(DB_DSN, timeout=5)
        content = await c.fetchval(
            "select content from report_versions where report_id=$1 order by version_number desc limit 1", rid
        )
        await c.close()
        return content
    content = asyncio.run(q())
    full = json.dumps(json.loads(content), ensure_ascii=False) if content else ""
    check("并发路径-生成内容引用了抓取URL(example.com)", "example.com" in full)

    st, _ = api("DELETE", f"/reports/{rid}", token=token)
    print("  deleted report", rid, "status", st)


# ---------------- 入口 ----------------
def main() -> int:
    part1()
    asyncio.run(part2())
    asyncio.run(part2b())
    try:
        part3()
    except AssertionError as e:
        print("  [ABORT] Part 3 前置调用失败:", e)
        FAIL.append("Part3-precondition")

    try:
        part4()
    except AssertionError as e:
        print("  [ABORT] Part 4 前置调用失败:", e)
        FAIL.append("Part4-precondition")

    print("\n================ 验收汇总 ================")
    print(f"PASS({len(PASS)}):")
    for n in PASS:
        print("  ✓", n)
    if FAIL:
        print(f"FAIL({len(FAIL)}):")
        for n in FAIL:
            print("  ✗", n)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
