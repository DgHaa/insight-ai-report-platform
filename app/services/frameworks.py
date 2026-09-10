"""分析框架模板库（纯 Prompt 工程，无架构改动）。

每个框架是一段「分析视角引导语」，由生成引擎在构建 Prompt 时追加到模块提示词之后，
约束模型「从哪个角度、按什么结构」产出洞察。

- 前端在模块表单以「下拉框」呈现，用户选择即生效，零开发成本、杠杆最大；
- 后端仅做「命中即追加」，不引入新表、不改报告配置结构（framework 仅作为模块
  raw 配置里的一个普通字符串字段存储）。

框架按 category 分组，前端下拉可据此分组展示。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisFramework:
    id: str
    name: str
    category: str
    description: str
    # 追加到模块 Prompt 后的「分析视角引导语」
    prompt: str


# ==================== 框架目录 ====================
FRAMEWORKS: list[AnalysisFramework] = [
    AnalysisFramework(
        id="general",
        name="通用自由分析",
        category="通用",
        description="不限定结构，由模型自由发挥（默认）",
        prompt=(
            "请围绕主题做自由、客观的洞察分析，结论须有依据。"
        ),
    ),
    AnalysisFramework(
        id="swot",
        name="SWOT 分析",
        category="战略",
        description="优势 / 劣势 / 机会 / 威胁 四象限拆解",
        prompt=(
            "请使用 SWOT 框架分析，将内容严格拆为四个维度："
            "**优势(Strengths)**、**劣势(Weaknesses)**、**机会(Opportunities)**、**威胁(Threats)**。"
            "每个维度下列出 2~4 条要点，并指出其中最值得关注的一条。"
        ),
    ),
    AnalysisFramework(
        id="pest",
        name="PEST 分析",
        category="战略",
        description="政治 / 经济 / 社会 / 技术 宏观环境扫描",
        prompt=(
            "请使用 PEST 框架，从四个宏观维度展开：**政治(Political)**、**经济(Economic)**、"
            "**社会(Social)**、**技术(Technological)**，分析其对主题的影响方向与程度。"
        ),
    ),
    AnalysisFramework(
        id="five_w_one_h",
        name="5W1H 拆解",
        category="问题诊断",
        description="何人/何事/何时/何地/为何/如何 全面拆解",
        prompt=(
            "请使用 5W1H 框架系统拆解主题：**何人(Who)**、**何事(What)**、**何时(When)**、"
            "**何地(Where)**、**为何(Why)**、**如何(How)**。逐项给出事实与判断，"
            "并在最后指出最关键、最需优先处理的一项。"
        ),
    ),
    AnalysisFramework(
        id="mece",
        name="MECE 结构化拆解",
        category="问题诊断",
        description="相互独立、完全穷尽地分层拆解问题",
        prompt=(
            "请使用 MECE（相互独立、完全穷尽）原则对主题做结构化拆解："
            "先给出 3~5 个互不重叠的一级维度，再在每个维度下展开要点，"
            "确保覆盖完整且无重复。"
        ),
    ),
    AnalysisFramework(
        id="pyramid",
        name="金字塔原理",
        category="表达",
        description="结论先行，再以上下层级论据支撑",
        prompt=(
            "请使用金字塔原理组织内容：**先给出核心结论（一句话）**，"
            "再分 3~5 个支撑论点，每个论点配以关键事实或数据。自上而下、结论先行。"
        ),
    ),
    AnalysisFramework(
        id="first_principles",
        name="第一性原理",
        category="思维模型",
        description="回归本质假设，层层下探再重构",
        prompt=(
            "请使用第一性原理思考：先剥离行业惯例与类比，回到最基本的要素与假设，"
            "再自下而上推导出对主题的判断，并指出哪些「常识」其实站不住脚。"
        ),
    ),
    AnalysisFramework(
        id="cause_chain",
        name="因果链 / 5 Why",
        category="问题诊断",
        description="逐层追问根因，定位真正的驱动因素",
        prompt=(
            "请使用因果链（5 Why）分析：从表象问题出发，连续追问「为什么」至少 3 层，"
            "定位根本原因，并给出切断因果链的可行干预点。"
        ),
    ),
    AnalysisFramework(
        id="compare",
        name="对比分析",
        category="分析维度",
        description="按统一维度横向对比（如竞品/方案/时段）",
        prompt=(
            "请使用对比分析框架：先明确 3~5 个**统一对比维度**（如规模、成本、风险、体验），"
            "再在各维度上横向比较对象差异，最后给出综合优劣判断。建议用对比表格呈现。"
        ),
    ),
    AnalysisFramework(
        id="trend",
        name="趋势外推与拐点",
        category="分析维度",
        description="识别趋势、拐点与异常波动",
        prompt=(
            "请使用趋势分析框架：识别关键指标的变化方向、速率与拐点，"
            "区分「长期趋势」与「短期波动」，并指出最值得警惕的异常信号。"
        ),
    ),
    AnalysisFramework(
        id="funnel",
        name="漏斗 / 转化分析",
        category="分析维度",
        description="分阶段拆解转化与流失",
        prompt=(
            "请使用漏斗/转化分析框架：将过程拆为若干阶段，分析各阶段转化率与流失点，"
            "定位最大瓶颈，并给出提升该环节的优先动作。"
        ),
    ),
    AnalysisFramework(
        id="scenario",
        name="情景分析",
        category="战略",
        description="乐观 / 中性 / 悲观 多情景推演",
        prompt=(
            "请使用情景分析框架：分别推演**乐观 / 中性 / 悲观**三种情景下的可能走向，"
            "说明各自的触发条件与概率判断，并指出应提前布局的共性动作。"
        ),
    ),
    AnalysisFramework(
        id="risk_matrix",
        name="风险矩阵",
        category="战略",
        description="按「可能性 × 影响」对风险分级",
        prompt=(
            "请使用风险矩阵框架：列出主要风险，按**发生可能性（高/中/低）**与"
            "**影响程度（高/中/低）**两个维度分级，优先处置「高可能×高影响」项，"
            "并给出对应缓释措施。"
        ),
    ),
    AnalysisFramework(
        id="okr",
        name="OKR 目标拆解",
        category="表达",
        description="目标(O)+可衡量关键结果(KR)拆解",
        prompt=(
            "请使用 OKR 框架：给出 1 个核心目标(Objective)，并拆解为 3~5 个"
            "可衡量的关键结果(Key Results)，每个 KR 需包含「当前值 → 目标值」的量化表达。"
        ),
    ),
    AnalysisFramework(
        id="star",
        name="STAR 复盘",
        category="问题诊断",
        description="情境/任务/行动/结果 结构化复盘",
        prompt=(
            "请使用 STAR 框架复盘：按 **情境(Situation)**、**任务(Task)**、**行动(Action)**、"
            "**结果(Result)** 四段叙述，并在结果中量化成效、提炼可复用经验。"
        ),
    ),
]

FRAMEWORK_MAP: dict[str, AnalysisFramework] = {f.id: f for f in FRAMEWORKS}


def get_framework(framework_id: str | None) -> AnalysisFramework | None:
    """按 id 取框架；空或未知返回 None。"""
    if not framework_id:
        return None
    return FRAMEWORK_MAP.get(framework_id)


def get_framework_prompt(framework_id: str | None) -> str:
    """返回框架引导语（命中时），未命中返回空串。"""
    fw = get_framework(framework_id)
    if fw is None or fw.id == "general":
        return ""
    return f"\n\n【分析框架：{fw.name}】\n{fw.prompt}"


def list_frameworks() -> list[dict]:
    """对外暴露的框架目录（前端下拉用）。"""
    return [
        {
            "id": f.id,
            "name": f.name,
            "category": f.category,
            "description": f.description,
        }
        for f in FRAMEWORKS
    ]
