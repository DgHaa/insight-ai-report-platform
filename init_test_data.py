#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_test_data.py — 服务部AI洞察平台 测试数据初始化脚本
================================================================================
功能：
    向 PostgreSQL 数据库插入丰富的模拟业务数据（部门 / 用户 / 凭证 / 报告 /
    历史版本 / 生成任务 / 邮件任务 / 模型成本日志 / 外部邮箱白名单），
    使平台所有功能页面（报告列表、报告详情、部门统计看板、系统管理、个人中心
    等）均有数据展示，便于视觉与功能验收。

使用说明：
    1. 安装依赖（asyncpg + bcrypt）：
           pip install asyncpg bcrypt

    2. 设置数据库连接串环境变量（默认为本地 insight_ai 库）：
           # Windows PowerShell
           $env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/insight_ai"
           # Linux / macOS
           export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/insight_ai"

    3. 运行脚本：
           python init_test_data.py

    ⚠️ 注意：脚本会先清空以下业务表（按外键依赖顺序）：
       model_cost_logs → email_tasks → generation_tasks → report_versions
       → reports → operation_logs → user_data_source_credentials → users
       → departments → global_email_whitelist
       （departments 与 users 存在循环外键，清空前会将 departments.admin_id 置空）

    所有用户的统一登录密码为：Test@123（超级管理员 admin 亦同）。
================================================================================
"""

import asyncio
import hashlib
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
import bcrypt

# ==================== 基础配置 ====================

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/insight_ai"

# 数据规模可调参数
USERS_PER_DEPT = (3, 5)          # 每个部门普通用户数范围
REPORTS_PER_USER = (2, 4)        # 每个用户个人报告数范围
REPORTS_PER_DEPT_ADMIN = (2, 3)  # 每个部门管理员部门报告数范围
VERSIONS_PER_COMPLETED = (2, 3)  # 已完成报告的版本数范围
PAST_DAYS = 30                   # 时间回溯天数（过去 30 天内）

# 统一登录密码（bcrypt 哈希仅生成一次，所有用户共用）
TEST_PASSWORD = "Test@123"

# ==================== 静态数据池 ====================

# 11 个部门（与设计文档/种子脚本一致）
DEFAULT_DEPARTMENTS = [
    {"code": "care", "name": "Care业务部[终端BG]", "description": "终端BG Care业务部"},
    {"code": "service_quality", "name": "服务质量与运营官[终端BG]", "description": "终端BG服务质量与运营管理"},
    {"code": "iot_service", "name": "IoT产品服务部[终端BG]", "description": "IoT产品服务与支持"},
    {"code": "tablet_pc_service", "name": "平板与PC产品服务部[终端BG]", "description": "平板与PC产品服务与支持"},
    {"code": "global_hrd", "name": "全球服务部HRD[终端BG]", "description": "全球服务人力资源开发"},
    {"code": "mobile_service", "name": "手机产品服务部[终端BG]", "description": "手机产品服务与支持"},
    {"code": "bg_spare_parts", "name": "终端BG备件管理部", "description": "终端BG备件计划与管理"},
    {"code": "bg_mkt_solution", "name": "终端BG服务MKT与解决方案销售部", "description": "服务营销与解决方案销售"},
    {"code": "bg_finance", "name": "终端BG服务财经管理部", "description": "服务财经管理与核算"},
    {"code": "bg_online_service", "name": "终端BG线上服务部", "description": "线上服务渠道运营"},
    {"code": "reserved", "name": "（预留扩展）", "description": "预留部门，用于未来组织扩展"},
]

# 各部门业务主题（用于报告标题/描述/关键词）
DEPT_TOPIC = {
    "care": ("客户关怀", ["客户关怀", "满意度", "用户体验", "投诉处理"]),
    "service_quality": ("服务质量", ["服务质量", "运营", "质检", "工单"]),
    "iot_service": ("IoT产品", ["IoT", "智能家居", "连接质量", "设备"]),
    "tablet_pc_service": ("平板PC", ["平板", "PC", "硬件质量", "系统体验"]),
    "global_hrd": ("人力资源", ["招聘", "培训", "绩效", "员工满意度"]),
    "mobile_service": ("手机服务", ["手机", "售后", "维修", "续航"]),
    "bg_spare_parts": ("备件管理", ["备件", "库存", "供应链", "物料"]),
    "bg_mkt_solution": ("服务营销", ["营销", "方案", "商机", "竞品"]),
    "bg_finance": ("服务财经", ["成本", "预算", "核算", "费用"]),
    "bg_online_service": ("线上服务", ["线上", "App", "客服", "工单"]),
    "reserved": ("综合服务", ["服务", "数据", "趋势", "分析"]),
}

# 用户名英文名池
NAME_POOL = [
    "zhang", "li", "wang", "liu", "chen", "yang", "huang", "zhao", "wu",
    "zhou", "xu", "sun", "ma", "zhu", "hu", "guo", "he", "gao", "lin",
    "luo", "tang", "han", "deng", "cao", "peng", "xiao", "tian", "dong",
]

# 报告标题模板（围绕部门业务）
REPORT_TITLES = [
    "{topic}舆情日报", "{topic}竞品动向周报", "{topic}服务数据分析", "{topic}用户反馈监测",
    "{topic}投诉热点跟踪", "{topic}趋势研判月报", "{topic}质量复盘报告", "{topic}风险预警专报",
    "{topic}满意度调研分析", "{topic}渠道表现对比", "{topic}运营周报", "{topic}专项分析",
]

# 标签池
TAG_POOL = ["质量", "舆情", "竞品", "售后", "用户反馈", "满意度", "成本", "供应链", "营销", "风险", "趋势", "专项"]

# 数据源 URL 池
SOURCE_URLS = [
    "https://news.example.com/consumer-electronics",
    "https://bbs.example.com/forum/service",
    "https://weibo.example.com/topic/service",
    "https://zhihu.example.com/topic/service-quality",
    "https://www.example.com/industry/report",
    "https://forum.example.com/repair",
    "https://jd.example.com/review/mobile",
    "https://media.example.com/analysis",
]

# 凭证名称池
CREDENTIAL_NAMES = ["爬取微博专用", "爬取知乎专用", "行业论坛爬取", "新闻站点采集", "电商评论抓取"]

# 模型提供商（provider / endpoint / model_name）
MODEL_PROVIDERS = [
    ("ascend", "https://maas.example.com/v1/chat/completions", "Qwen3.8-27B"),
    ("openai", "https://api.openai.example.com/v1/chat/completions", "gpt-4o"),
    ("anthropic", "https://api.anthropic.example.com/v1/messages", "claude-3-5-sonnet"),
]

# 模块标题池
MODULE_TITLES = [
    "舆情监控", "竞品动态分析", "质量投诉分析", "售后评价挖掘",
    "服务数据统计", "用户心声聚类", "风险预警", "渠道对比分析",
]

# Prompt 模板（中文，约 50~200 字）
PROMPT_TEMPLATES = [
    "你是一名行业分析专家，请围绕关键词「{keywords}」分析近期热点、风险与趋势。"
    "要求：1) 梳理事件时间线与传播路径；2) 识别负面风险点并评估影响等级；"
    "3) 提炼核心结论，输出 500 字以内的结构化分析。数据来源：{urls}。",
    "你是服务质量分析专家，请基于「{keywords}」从以下数据源提取用户诉求与不满点，"
    "按问题分类、根因、改进建议三个维度输出分析报告。要求结论可落地，"
    "每条建议注明优先级。数据来源：{urls}。",
    "你是竞品分析专家，请分析数据源中与「{keywords}」相关的竞品动态，"
    "输出对比表格：产品特性、定价策略、渠道策略、近期动作。"
    "最后给出本部门的应对建议。数据来源：{urls}。",
]

# 外部邮箱白名单域名
WHITELIST_DOMAINS = [
    ("partner.com", "合作方邮箱"),
    ("supplier.com", "供应商邮箱"),
    ("vendor.com", "外协厂商邮箱"),
    ("consultant.com", "咨询顾问邮箱"),
    ("collaborator.com", "联合项目邮箱"),
]

# ==================== 工具函数 ====================


def utcnow() -> datetime:
    """返回 naive UTC 时间（与业务代码 utcnow() 一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def rand_time(max_days_ago: int = PAST_DAYS) -> datetime:
    """返回过去 max_days_ago 天内的随机时间。"""
    return utcnow() - timedelta(
        days=random.uniform(0, max_days_ago),
        hours=random.uniform(0, 24),
        minutes=random.uniform(0, 60),
    )


def rand_choice_weighted(pairs) -> object:
    """按权重随机选择。pairs: [(值, 权重), ...]"""
    values = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]
    return random.choices(values, weights=weights, k=1)[0]


def random_keywords(topic_keywords: list) -> list:
    """从主题关键词池中随机抽取 2~5 个。"""
    n = random.randint(2, 5)
    n = min(n, len(topic_keywords))
    return random.sample(topic_keywords, n)


def random_tags() -> list:
    n = random.randint(1, 3)
    return random.sample(TAG_POOL, n)


def hash_password(password: str) -> str:
    """生成 bcrypt 哈希（$2b$12$ 前缀）。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def sha256_hex(content: dict) -> str:
    """对内容计算 SHA-256（与业务 save_report_version 一致）。"""
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_cron(schedule_type: str) -> str:
    """按调度类型生成 cron 表达式。"""
    if schedule_type == "daily":
        return f"{random.randint(0, 59)} {random.randint(0, 23)} * * *"
    if schedule_type == "weekly":
        return f"{random.randint(0, 59)} {random.randint(0, 23)} * * {random.randint(0, 6)}"
    if schedule_type == "monthly":
        return f"{random.randint(0, 59)} {random.randint(0, 23)} {random.randint(1, 28)} * *"
    return ""


def random_model_config() -> dict:
    """随机生成一个模型配置。"""
    provider, endpoint, model_name = random.choice(MODEL_PROVIDERS)
    return {
        "provider": provider,
        "endpoint": endpoint,
        "api_key": "sk-test",
        "model_name": model_name,
        "parameters": {"temperature": 0.7, "max_tokens": 4096},
    }


def make_module(credential_ids: list, topic_keywords: list) -> dict:
    """生成单个模块配置（model_config / keywords / prompt / data_sources / schedule）。"""
    module_title = random.choice(MODULE_TITLES)
    keywords = random_keywords(topic_keywords)
    template = random.choice(PROMPT_TEMPLATES)
    has_urls = random.random() < 0.6  # 60% 模块带外部数据源

    urls = []
    if has_urls:
        n = random.randint(1, 2)
        urls = random.sample(SOURCE_URLS, min(n, len(SOURCE_URLS)))

    data_sources = {
        "urls": urls,
        "grab_config": {
            "timeout": random.choice([10, 15, 20]),
            "retries": random.choice([1, 2, 3]),
            "max_length": random.choice([2000, 5000, 10000]),
        },
    }
    if urls and credential_ids and random.random() < 0.5:
        data_sources["credential_id"] = str(random.choice(credential_ids))

    schedule_type = rand_choice_weighted(
        [("manual", 4), ("daily", 2), ("weekly", 2), ("monthly", 2)]
    )
    schedule = {"type": schedule_type}
    if schedule_type != "manual":
        schedule["cron"] = make_cron(schedule_type)

    prompt = template.format(
        keywords="、".join(keywords),
        urls="、".join(urls) if urls else "内置知识库",
    )

    return {
        "module_title": module_title,
        "model_config": random_model_config(),
        "keywords": keywords,
        "prompt": prompt,
        "data_sources": data_sources,
        "schedule": schedule,
        "output_format": "text",
    }


def make_report_config(credential_ids: list, topic_keywords: list) -> dict:
    """生成报告 config（1~3 个模块）。"""
    n_modules = random.randint(1, 3)
    modules = [make_module(credential_ids, topic_keywords) for _ in range(n_modules)]
    return {"modules": modules}


def make_version_content(config: dict, topic: str) -> dict:
    """根据报告配置生成历史版本内容（summary + modules，Markdown 文本）。"""
    modules = config.get("modules", [])
    kw_text = ""
    if modules:
        kw_text = "、".join((modules[0].get("keywords") or [])[:3])
    summary = (
        f"## 摘要\n\n"
        f"本期「{topic}」报告围绕「{kw_text}」等主题展开分析。"
        f"共监测到相关数据 **{random.randint(80, 600)}** 条，"
        f"识别高风险信号 {random.randint(0, 15)} 条、中风险信号 {random.randint(5, 40)} 条。\n\n"
        f"主要结论：{random.choice(['整体态势平稳，局部风险可控', '负面舆情略有上升，需重点关注', '服务质量显著改善，用户满意度提升', '竞品动作频繁，建议加快应对'])}。\n\n"
        f"建议：{random.choice(['加强重点渠道监测频次', '对高风险事件启动专项跟进', '组织专题复盘并输出改进方案', '优化话术与处理流程'])}。"
    )
    module_blocks = []
    for m in modules:
        title = m.get("module_title", "分析模块")
        keywords = "、".join(m.get("keywords") or [])
        model_name = (m.get("model_config") or {}).get("model_name", "AI")
        ups = random.choice(["上升", "平稳", "下降"])
        risk = random.choice(["低", "中", "高"])
        module_blocks.append(
            {
                "module_title": title,
                "content": (
                    f"## {title}\n\n"
                    f"### 分析概览\n\n"
                    f"围绕关键词「{keywords}」共采集到相关样本 **{random.randint(50, 500)}** 条，"
                    f"环比{ups}，整体风险等级：**{risk}**。\n\n"
                    f"### 关键发现\n\n"
                    f"- 讨论热度集中在 {random.choice(['社交媒体', '行业论坛', '电商评论区', '新闻媒体'])}，"
                    f"高峰出现在{random.randint(1, 28)}日前后。\n"
                    f"- 高频问题包括：{random.choice(['响应时效', '产品故障', '价格敏感', '服务流程', '售后体验'])}、"
                    f"{random.choice(['功能缺陷', '信息不一致', '排队时间', '维修周期'])}。\n"
                    f"- 正面评价占比 {random.randint(55, 90)}%，负面评价集中在"
                    f"{random.choice(['物流配送', '客服响应', '硬件质量', '系统稳定性'])}。\n\n"
                    f"### 建议\n\n"
                    f"- 对高频问题建立专项监测看板，按周跟踪变化趋势。\n"
                    f"- 建议渠道团队针对负面集中点输出 SOP 优化方案（模型：{model_name}）。\n"
                    f"- 风险信号达到阈值时自动升级到部门管理员跟进。\n"
                ),
            }
        )
    return {"summary": summary, "modules": module_blocks}


def make_error_message() -> str:
    """生成失败/超时任务错误信息（含 stats 分类关键词）。"""
    return random.choice(
        [
            "数据抓取超时: 访问来源站点超时（fetch timeout）",
            "模型调用失败: 上游模型接口返回 502",
            "内容为空: 抓取到的页面内容为空，无法生成模块",
            "网络连接超时: 部分数据源无法访问",
        ]
    )


# ==================== 主流程 ====================


def build_report(
    dept_code: str,
    dept_id: uuid.UUID,
    owner_id: uuid.UUID,
    report_type: str,
    is_public: bool,
    credential_ids: list,
) -> dict:
    """构建单份报告记录（含状态 / config / 版本号 / 生成次数）。"""
    topic, topic_kws = DEPT_TOPIC[dept_code]
    status = rand_choice_weighted(
        [
            ("draft", 10),
            ("generating", 5),
            ("completed", 70),
            ("failed", 10),
            ("timeout", 5),
        ]
    )
    config = make_report_config(credential_ids, topic_kws)
    created_at = rand_time()
    updated_at = created_at + timedelta(days=random.uniform(0, 2), hours=random.uniform(0, 8))

    if status == "completed":
        n_versions = random.randint(*VERSIONS_PER_COMPLETED)
        current_version = n_versions
        generate_count = n_versions
        last_generated_at = updated_at
    elif status == "generating":
        current_version = 0
        generate_count = 1
        last_generated_at = updated_at
    elif status in ("failed", "timeout"):
        current_version = 0
        generate_count = random.randint(1, 2)
        last_generated_at = updated_at
    else:  # draft
        current_version = 0
        generate_count = 0
        last_generated_at = None

    return {
        "id": uuid.uuid4(),
        "title": random.choice(REPORT_TITLES).format(topic=topic),
        "description": f"{topic}相关的{'部门级' if report_type == 'department' else '个人'}分析报告，"
                       f"聚焦{random.choice(['近期热点', '风险趋势', '用户反馈', '竞品动态'])}，"
                       f"为业务决策提供数据支撑。",
        "type": report_type,
        "department_id": dept_id,
        "owner_id": owner_id,
        "is_public": is_public,
        "status": status,
        "config": config,
        "tags": random_tags(),
        "current_version": current_version,
        "generate_count": generate_count,
        "last_generated_at": last_generated_at,
        "created_at": created_at,
        "updated_at": updated_at,
        "topic": topic,
        "dept_code": dept_code,
    }


async def main() -> None:
    """主流程：连接数据库 → 清空旧数据 → 生成并插入全部模拟数据。"""
    dsn = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # 兼容 SQLAlchemy 风格的 postgresql+asyncpg:// 前缀
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    print(f"[连接] DATABASE_URL = {dsn}")

    conn = await asyncpg.connect(dsn=dsn)
    try:
        async with conn.transaction():
            # ---------------- 清空旧数据（按外键依赖顺序） ----------------
            print("[清空] 开始清理旧数据...")
            await conn.execute("UPDATE departments SET admin_id = NULL")
            for table in [
                "model_cost_logs",
                "email_tasks",
                "generation_tasks",
                "report_versions",
                "reports",
                "operation_logs",
                "user_data_source_credentials",
                "users",
                "departments",
                "global_email_whitelist",
            ]:
                await conn.execute(f"DELETE FROM {table}")
            print("[清空] 旧数据已清空 ✅")

            # ---------------- 1. 部门 ----------------
            dept_rows = []
            dept_ids: dict[str, uuid.UUID] = {}
            for item in DEFAULT_DEPARTMENTS:
                did = uuid.uuid4()
                dept_ids[item["code"]] = did
                dept_rows.append(
                    (
                        did,
                        item["name"],
                        item["code"],
                        item["description"],
                        rand_time(),
                    )
                )
            await conn.executemany(
                "INSERT INTO departments (id, name, code, description, admin_id, created_at, is_active) "
                "VALUES ($1, $2, $3, $4, NULL, $5, true)",
                dept_rows,
            )

            # ---------------- 2. 用户 ----------------
            pwd_hash = hash_password(TEST_PASSWORD)

            # 超级管理员
            admin_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO users (id, username, email, password_hash, department_id, role, created_at, is_active) "
                "VALUES ($1, $2, $3, $4, NULL, 'super_admin', $5, true)",
                admin_id,
                "admin",
                "admin@company.com",
                pwd_hash,
                rand_time(),
            )

            # 各部门：1 名部门管理员 + 3~5 名普通用户
            user_rows = []
            users_by_dept: dict[str, dict] = {}
            user_names: set[str] = set()  # 全局唯一 username
            for item in DEFAULT_DEPARTMENTS:
                code = item["code"]
                dept_id = dept_ids[code]
                n_users = random.randint(*USERS_PER_DEPT)
                pick_names = random.sample(
                    NAME_POOL, min(n_users + 1, len(NAME_POOL))
                )

                # 部门管理员
                admin_name = pick_names[0]
                admin_username = f"{admin_name}_{code}"
                while admin_username in user_names:
                    admin_name = random.choice(NAME_POOL)
                    admin_username = f"{admin_name}_{code}"
                user_names.add(admin_username)
                dept_admin_id = uuid.uuid4()
                user_rows.append(
                    (
                        dept_admin_id,
                        admin_username,
                        f"{admin_username}@company.com",
                        pwd_hash,
                        dept_id,
                        "dept_admin",
                        rand_time(),
                    )
                )

                # 普通用户
                member_ids = []
                for name in pick_names[1 : n_users + 1]:
                    username = f"{name}_{code}"
                    if username in user_names:
                        continue
                    user_names.add(username)
                    uid = uuid.uuid4()
                    member_ids.append(uid)
                    user_rows.append(
                        (
                            uid,
                            username,
                            f"{username}@company.com",
                            pwd_hash,
                            dept_id,
                            "user",
                            rand_time(),
                        )
                    )

                users_by_dept[code] = {
                    "dept_id": dept_id,
                    "admin_id": dept_admin_id,
                    "member_ids": member_ids,
                }

            await conn.executemany(
                "INSERT INTO users (id, username, email, password_hash, department_id, role, created_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, true)",
                user_rows,
            )

            # 回填 departments.admin_id（循环外键）
            for code, info in users_by_dept.items():
                await conn.execute(
                    "UPDATE departments SET admin_id = $1 WHERE id = $2",
                    info["admin_id"],
                    info["dept_id"],
                )

            # ---------------- 3. 外部邮箱白名单 ----------------
            whitelist_rows = []
            for domain, desc in WHITELIST_DOMAINS:
                whitelist_rows.append(
                    (uuid.uuid4(), domain, desc, admin_id, rand_time())
                )
            await conn.executemany(
                "INSERT INTO global_email_whitelist (id, domain, description, created_by, created_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, true)",
                whitelist_rows,
            )

            # ---------------- 4. 用户数据源凭证 ----------------
            credential_rows = []
            credential_ids: list = []
            cred_users: list = []
            # 每个部门管理员 + 每部门 2~3 名普通用户
            for code, info in users_by_dept.items():
                cred_users.append(info["admin_id"])
                n_active = random.randint(2, 3)
                if len(info["member_ids"]) >= n_active:
                    cred_users.extend(random.sample(info["member_ids"], n_active))
                else:
                    cred_users.extend(info["member_ids"])

            for uid in cred_users:
                n_cred = random.randint(1, 2)
                cred_names = random.sample(
                    CREDENTIAL_NAMES, min(n_cred, len(CREDENTIAL_NAMES))
                )
                for name in cred_names:
                    cid = uuid.uuid4()
                    credential_ids.append(cid)
                    t = rand_time()
                    credential_rows.append(
                        (
                            cid,
                            uid,
                            name,
                            "http://proxy.example.com:8080",
                            "sessionid=abc123; uid=test_user; token=testtoken",
                            json.dumps(
                                {
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                    "Referer": "https://example.com",
                                    "Accept-Language": "zh-CN,zh;q=0.9",
                                },
                                ensure_ascii=False,
                            ),
                            t,
                            t,
                        )
                    )
            await conn.executemany(
                "INSERT INTO user_data_source_credentials "
                "(id, user_id, name, proxy, cookies, custom_headers, created_at, updated_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, true)",
                credential_rows,
            )

            print(
                f"[数据] 部门={len(dept_rows)}，用户={len(user_rows) + 1}，"
                f"白名单={len(whitelist_rows)}，凭证={len(credential_rows)}"
            )

            # ---------------- 5. 报告 ----------------
            report_rows = []
            report_meta: dict = {}  # report_id -> {config, status, topic, owner_id}
            for code, info in users_by_dept.items():
                dept_id = info["dept_id"]
                admin_id_dept = info["admin_id"]
                # 部门报告（部门管理员创建）
                for _ in range(random.randint(*REPORTS_PER_DEPT_ADMIN)):
                    r = build_report(
                        code, dept_id, admin_id_dept, "department", False, credential_ids
                    )
                    report_rows.append(
                        (
                            r["id"], r["title"], r["description"], r["type"],
                            r["department_id"], r["owner_id"], r["is_public"],
                            r["status"], json.dumps(r["config"], ensure_ascii=False), r["tags"],
                            r["current_version"], r["generate_count"],
                            r["last_generated_at"], r["created_at"], r["updated_at"],
                        )
                    )
                    report_meta[str(r["id"])] = {
                        "config": r["config"],
                        "status": r["status"],
                        "topic": r["topic"],
                        "owner_id": r["owner_id"],
                        "current_version": r["current_version"],
                    }
                # 个人报告（每位普通用户）
                for uid in info["member_ids"]:
                    for _ in range(random.randint(*REPORTS_PER_USER)):
                        is_public = random.random() < 0.3  # 约 30% 公开
                        r = build_report(
                            code, dept_id, uid, "personal", is_public, credential_ids
                        )
                        report_rows.append(
                            (
                                r["id"], r["title"], r["description"], r["type"],
                                r["department_id"], r["owner_id"], r["is_public"],
                                r["status"], json.dumps(r["config"], ensure_ascii=False), r["tags"],
                                r["current_version"], r["generate_count"],
                                r["last_generated_at"], r["created_at"], r["updated_at"],
                            )
                        )
                        report_meta[str(r["id"])] = {
                            "config": r["config"],
                            "status": r["status"],
                            "topic": r["topic"],
                            "owner_id": r["owner_id"],
                            "current_version": r["current_version"],
                        }

            await conn.executemany(
                "INSERT INTO reports "
                "(id, title, description, type, department_id, owner_id, is_public, status, config, "
                "tags, current_version, generate_count, last_generated_at, created_at, updated_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, true)",
                report_rows,
            )
            print(f"[数据] 报告={len(report_rows)}")

            # ---------------- 6. 报告历史版本 ----------------
            version_rows = []
            for rid_str, meta in report_meta.items():
                n_versions = meta["current_version"]
                if n_versions <= 0:
                    continue
                config = meta["config"]
                topic = meta["topic"]
                report_id = uuid.UUID(rid_str)
                modules = config.get("modules", [])
                model_used = (
                    (modules[0].get("model_config") or {}).get("model_name", "AI")
                    if modules else "AI"
                )
                # 版本 1 最旧，版本 n 最新；generated_at 依次向当前靠近
                latest_t = rand_time()
                for v in range(1, n_versions + 1):
                    content = make_version_content(config, topic)
                    gen_time = latest_t - timedelta(
                        days=(n_versions - v) * random.uniform(1, 5)
                    )
                    version_rows.append(
                        (
                            uuid.uuid4(), report_id, v,
                            json.dumps(content, ensure_ascii=False),
                            json.dumps(config, ensure_ascii=False),
                            model_used, "success", sha256_hex(content), gen_time,
                        )
                    )
            await conn.executemany(
                "INSERT INTO report_versions "
                "(id, report_id, version_number, content, config_snapshot, model_used, "
                "status, content_hash, generated_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true)",
                version_rows,
            )
            print(f"[数据] 历史版本={len(version_rows)}")

            # ---------------- 7. 生成任务 ----------------
            task_rows = []
            task_meta: dict = {}  # task_id -> {report_id, config, status}
            for rid_str, meta in report_meta.items():
                status = meta["status"]
                report_id = uuid.UUID(rid_str)
                config = meta["config"]

                if status == "completed":
                    n_tasks, task_status, err = random.randint(1, 3), "success", None
                elif status == "failed":
                    n_tasks, task_status, err = random.randint(1, 2), "failed", make_error_message()
                elif status == "timeout":
                    n_tasks, task_status, err = random.randint(1, 2), "timeout", make_error_message()
                elif status == "generating":
                    n_tasks, task_status, err = 1, "running", None
                else:  # draft 不创建任务
                    continue

                for _ in range(n_tasks):
                    tid = uuid.uuid4()
                    trigger = random.choice(["manual", "scheduled"])
                    started = rand_time()
                    completed = None
                    if task_status in ("success", "failed", "timeout"):
                        completed = started + timedelta(minutes=random.uniform(1, 40))
                    task_rows.append(
                        (
                            tid, report_id, trigger, task_status, started, completed,
                            err,
                            f"worker-{random.randint(1, 9)}:{os.getpid()}:{uuid.uuid4().hex[:6]}",
                            started,
                        )
                    )
                    task_meta[str(tid)] = {
                        "report_id": report_id,
                        "config": config,
                        "status": task_status,
                    }
            await conn.executemany(
                "INSERT INTO generation_tasks "
                "(id, report_id, trigger_type, status, started_at, completed_at, "
                "error_message, worker_id, created_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true)",
                task_rows,
            )
            print(f"[数据] 生成任务={len(task_rows)}")

            # ---------------- 8. 邮件任务 ----------------
            email_rows = []
            completed_items = [
                (rid, m) for rid, m in report_meta.items() if m["status"] == "completed"
            ]
            # 约 30% 的 completed 报告创建邮件发送记录
            email_targets = [x for x in completed_items if random.random() < 0.3]

            internal_emails = [f"{u}@company.com" for u in user_names] + ["admin@company.com"]
            for rid_str, meta in email_targets:
                report_id = uuid.UUID(rid_str)
                n_recv = random.randint(2, 3)
                recipients = random.sample(
                    internal_emails, min(n_recv, len(internal_emails))
                )
                if random.random() < 0.3:
                    domain = random.choice([d for d, _ in WHITELIST_DOMAINS])
                    recipients.append(f"external.{random.randint(100, 999)}@{domain}")

                formats = random.choice(
                    [["pdf", "docx"], ["pdf"], ["docx", "md"], ["pdf", "docx", "md"]]
                )
                trigger = random.choice(["auto", "manual", "scheduled"])
                status = "sent" if random.random() < 0.8 else "failed"
                scheduled_at = rand_time() if trigger == "scheduled" else None
                sent_at = rand_time() if status == "sent" else None
                error_msg = None if status == "sent" else "SMTP 连接超时，邮件发送失败"
                t = rand_time()
                email_rows.append(
                    (
                        uuid.uuid4(), report_id, trigger, recipients, formats, status,
                        scheduled_at, sent_at, error_msg, t,
                    )
                )
            await conn.executemany(
                "INSERT INTO email_tasks "
                "(id, report_id, trigger_type, recipients, formats, status, "
                "scheduled_at, sent_at, error_msg, created_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true)",
                email_rows,
            )
            print(f"[数据] 邮件任务={len(email_rows)}")

            # ---------------- 9. 模型成本日志 ----------------
            cost_rows = []
            for tid_str, tmeta in task_meta.items():
                config = tmeta["config"]
                modules = config.get("modules", [])
                if not modules:
                    continue
                # success 任务：每个模块一条成本日志；失败/超时任务：记录 1~模块数 条
                if tmeta["status"] == "success":
                    n_logs = len(modules)
                else:
                    n_logs = random.randint(1, len(modules))

                for m in modules[:n_logs]:
                    mc = m.get("model_config") or {}
                    prompt_tokens = random.randint(100, 3000)
                    completion_tokens = random.randint(100, 2000)
                    total_tokens = prompt_tokens + completion_tokens
                    unit_price = Decimal(str(random.uniform(0.001, 0.02))).quantize(
                        Decimal("0.000001")
                    )
                    estimated_cost = (
                        Decimal(total_tokens) / Decimal(1000) * unit_price
                    ).quantize(Decimal("0.0001"))
                    cost_rows.append(
                        (
                            uuid.uuid4(), uuid.UUID(tid_str),
                            mc.get("provider", "unknown"), mc.get("model_name", "unknown"),
                            prompt_tokens, completion_tokens, total_tokens,
                            unit_price, estimated_cost, rand_time(),
                        )
                    )
            await conn.executemany(
                "INSERT INTO model_cost_logs "
                "(id, task_id, model_provider, model_name, prompt_tokens, completion_tokens, "
                "total_tokens, unit_price_per_1k_tokens, estimated_cost, created_at, is_active) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true)",
                cost_rows,
            )
            print(f"[数据] 模型成本日志={len(cost_rows)}")

            # ---------------- 统计汇总 ----------------
            status_count: dict = {}
            for r in report_rows:
                key = r[7]  # reports.status
                status_count[key] = status_count.get(key, 0) + 1

            print("\n==================== 插入完成 ✅ ====================")
            print(f"部门: {len(dept_rows)} 个")
            print(f"用户: {len(user_rows) + 1} 名（含超级管理员 admin）")
            print(f"数据源凭证: {len(credential_rows)} 套")
            print(f"外部邮箱白名单: {len(whitelist_rows)} 条")
            print(f"报告: {len(report_rows)} 份")
            for s in ["draft", "generating", "completed", "failed", "timeout"]:
                print(f"  - {s}: {status_count.get(s, 0)}")
            print(f"历史版本: {len(version_rows)} 个")
            print(f"生成任务: {len(task_rows)} 条")
            print(f"邮件任务: {len(email_rows)} 条")
            print(f"模型成本日志: {len(cost_rows)} 条")
            print("=======================================================")
            print(f"统一登录密码: {TEST_PASSWORD}")
            print(f"超级管理员账号: admin / admin@company.com")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())








