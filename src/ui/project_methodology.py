from __future__ import annotations

import streamlit as st

from src.metrics import SCORE_DIMENSIONS
from src.model_boundary import BOUNDARY_AWARENESS_LABEL
from src.ui.components import (
    render_context_grid,
    render_cta_group,
    render_feature_card,
    render_flow_strip,
    render_hero,
    render_info_panel,
    render_section_block,
)


def _distinct_count(df, column: str) -> int:
    if column in getattr(df, "columns", []):
        return int(df[column].dropna().nunique())
    return 0


def build_dataset_summary_items(data) -> list[tuple[str, str]]:
    """数据集的关键规模，全部从当前 tasks / gold / 评分维度动态计算，不写死数量。"""
    task_count = len(data.tasks)
    domain_count = _distinct_count(data.tasks, "domain")
    task_type_count = _distinct_count(data.tasks, "task_type")
    gold_count = len(data.gold_answer_map)
    dimension_count = len(SCORE_DIMENSIONS)

    return [
        ("任务样本", f"{task_count} 道脱敏尽调任务"),
        ("覆盖领域", f"{domain_count} 个专业领域"),
        ("任务类型", f"{task_type_count} 类专业任务"),
        ("Gold Answer", f"{gold_count}/{task_count} 道已配参考答案"),
        ("评价维度", f"{dimension_count} 个 Rubric 维度 + {BOUNDARY_AWARENESS_LABEL}"),
    ]


def build_hero_stats(data) -> list[tuple[str, str]]:
    """首屏 Hero 右侧的动态数字：题量、领域数、评分维度数，全部按当前数据 / Rubric 计算，
    不写死任何数量；空数据时各项自然回退为 0，Hero 仍可渲染。"""
    task_count = len(tasks) if (tasks := getattr(data, "tasks", None)) is not None else 0
    domain_count = _distinct_count(tasks, "domain")
    dimension_count = len(SCORE_DIMENSIONS)
    return [
        (str(task_count), "尽调任务样本"),
        (str(domain_count), "专业领域"),
        (str(dimension_count), "Rubric 评分维度"),
    ]


def scored_case_count(scores_df) -> int:
    """当前样本中已产出评分的条数（运行真实评测后才大于 0），从 scores 动态计算。"""
    if scores_df is None or getattr(scores_df, "empty", True):
        return 0
    if "total_score" not in getattr(scores_df, "columns", []):
        return 0
    return int(scores_df["total_score"].notna().sum())


# 样本结构字段说明：与题库 / Gold Answer 的字段一一对应，描述结构而非数量。
def get_sample_structure_items() -> list[tuple[str, str]]:
    return [
        ("任务题与背景", "每道题给出业务场景、问题与必要背景，对应真实尽调中的一个判断节点。"),
        ("考察能力", "标注这道题主要考察的专业能力，便于按能力维度归类分析。"),
        ("风险等级", "标注任务的风险等级，风险越高的任务，红线判定越严格。"),
        ("Gold Answer", "人工撰写的参考答案，包含核心结论、关键依据与边界条件。"),
        ("必须覆盖点", "这道题必须命中的要点，遗漏即扣风险覆盖分。"),
        ("不可接受错误", "触碰即触发红线的错误，例如重大风险遗漏或无依据定性。"),
    ]


# 评价框架：五个 Rubric 维度的标签直接取自 metrics.SCORE_DIMENSIONS，避免与评分口径漂移；
# 边界意识作为一条横切维度，由红线与错误标注频率反映。
_RUBRIC_DIM_NOTES = {
    "accuracy_score": "结论与事实、法规、财务口径是否准确，有没有“写得像对”的硬伤。",
    "reasoning_score": "推理是否完整、贴合具体业务场景，而不是套用通用模板。",
    "coverage_score": "该提示的关键风险是否覆盖到位，有没有漏掉致命风险。",
    "evidence_score": "结论是否给出可核查的依据，有没有无依据的定性。",
    "expression_score": "表达是否专业克制、结构清楚，能否直接进入尽调底稿。",
}


def get_rubric_framework_items() -> list[tuple[str, str]]:
    items = [(label, _RUBRIC_DIM_NOTES.get(key, "")) for key, label in SCORE_DIMENSIONS]
    items.append(
        (
            BOUNDARY_AWARENESS_LABEL,
            "不确定的地方是否明确标注核查边界，而不是给出虚假的确定性。",
        )
    )
    return items


def get_redline_triggers() -> list[str]:
    return [
        "重大风险遗漏：该提示的致命风险没有被提示出来。",
        "无依据定性：给出确定性结论，却拿不出可核查的依据。",
        "错误适用规则：套错法规、准则或财务口径，出现方向性错误。",
    ]


def get_usage_flow_steps() -> list[str]:
    return [
        "先看离线评测结论",
        "选模型与典型样本",
        "现场复现实验",
        "对照 Gold 与红线",
        "判断可用边界",
    ]


def render_project_methodology_page(data_bundle: dict) -> None:
    data = data_bundle["data"]

    render_hero(
        eyebrow="项目作品集 · 尽调模型评测",
        title="FinDueEval",
        subtitle="基于投行 / 财务 / 法律尽调经验沉淀的模型评测样本库",
        value_line=(
            "不是模型排行榜，而是专业尽调场景下的可用边界评测：判断模型的回答"
            "哪些能直接用、哪些必须人工复核、哪些不能用。"
        ),
        stats=build_hero_stats(data),
    )
    render_cta_group(
        [
            ("查看评测结论 →", "evaluation_conclusions"),
            ("进入红线评测台 →", "overview"),
            ("发起可复现实验 →", "eval_run"),
        ],
        note="建议先看评测结论里的样本内可用边界，再到红线评测台与可复现实验自行验证。",
        key_prefix="methodology_hero",
    )

    render_section_block(
        "01",
        "项目背景",
        "尽调回答常“写得像对，却漏掉关键风险”，这类问题最难发现、也最危险。",
    )
    st.markdown(
        "在投行、财务和法律尽调里，模型的回答经常“写得像对，但漏掉关键风险”——"
        "结论读起来通顺、专业，却没有提示真正致命的问题，或者给出无依据的确定性判断。"
        "在这种高风险、强合规的工作中，这类问题比明显的事实错误更难发现，也更危险。"
        "FinDueEval 想回答的就是一个具体问题：在尽调任务上，模型的回答到底能不能放心用、"
        "在哪些地方必须人工兜底。"
    )

    render_section_block(
        "02",
        "样本来源",
        "来自真实尽调经验，脱敏抽象后重写，不含任何真实公司与敏感数据。",
    )
    st.markdown(
        "样本来自我过往在投行、财务尽调、法律核查与并购项目中的经验，经过脱敏与抽象后"
        "重新编写。题目保留了真实尽调中的判断结构与风险点，但**不包含任何真实公司、"
        "真实交易或敏感数据**，只作为评测用途。"
    )

    render_section_block(
        "03",
        "样本体系",
        "每道题按统一结构组织，便于按能力与风险归类分析。",
    )
    render_feature_card(get_sample_structure_items())

    render_section_block(
        "04",
        "评价框架",
        "把“一份好的尽调回答”拆成可评分的维度。",
    )
    st.markdown(
        "我先用历史尽调资料人工梳理了“优秀回答应该长什么样”，把它落成下面这套评分维度，"
        "由裁判模型对照 Gold Answer 给出建议分，再人工复核。"
    )
    render_feature_card(get_rubric_framework_items())

    render_section_block(
        "05",
        "红线机制",
        "触碰红线的回答，再高分也不能直接使用。",
    )
    st.markdown(
        "评分之外还有一层红线判定。当回答触发下列任一红线时，这道题不计入“可直接使用”，"
        "必须人工复核或判为不可用："
    )
    for trigger in get_redline_triggers():
        st.markdown(f"- {trigger}")

    render_section_block(
        "06",
        "评测结论与使用方式",
        "先看离线得出的结论，再上手现场验证。",
    )
    render_flow_strip(get_usage_flow_steps())
    st.markdown(
        "建议先在「模型边界报告」「模型能力指纹」「评测结论」等页看离线评测得出的结论——"
        "各模型在当前样本下的强弱项、高频风险与可用边界；再到「可复现实验」用项目样本"
        "现场测试感兴趣的模型，对照 Gold Answer 与红线看它在专业题上的真实表现。"
    )

    render_section_block(
        "07",
        "数据集规模",
        "下列数字均由当前题库与评分维度动态计算。",
    )
    render_context_grid(build_dataset_summary_items(data))
    scored = scored_case_count(getattr(data, "scores", None))
    if scored > 0:
        st.caption(f"当前样本内已产出 {scored} 条裁判评分，可在各分析页查看样本内观察结论。")
    else:
        st.caption("当前尚无评测评分；运行一次真实评测后，各分析页会基于真实结果生成样本内观察。")

    render_info_panel(
        "口径与边界",
        "题库与 Gold 为 MVP 脱敏样本；裁判给出的是建议分，需人工复核确认后归档；"
        "所有结论均为当前样本内观察，不构成模型采购或业务决策建议。",
    )
    render_cta_group(
        [
            ("进入红线评测台 →", "overview"),
            ("浏览样本库 →", "tasks"),
            ("发起可复现实验 →", "eval_run"),
        ],
        key_prefix="methodology_foot",
    )
