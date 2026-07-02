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


def get_project_brief_items() -> list[tuple[str, str]]:
    """Project Brief 的四个叙事卡片：背景、问题、方法、输出。"""
    return [
        (
            "背景",
            "在投行、财务和法律尽调中，模型的回答经常‘写得像对，但漏掉关键风险’——"
            "结论通顺专业，却可能隐藏致命遗漏或无依据的确定性判断。",
        ),
        (
            "问题",
            "尽调是高风险、强合规工作。相比明显的事实错误，‘看起来对’的错误更难发现，也更危险。"
            "我想回答：在尽调任务上，模型回答到底能不能放心用？",
        ),
        (
            "我的方法",
            "把过往尽调经验脱敏抽象成标准化任务，人工撰写 Gold Answer，"
            "再用 Rubric 多维评分 + 红线错误 + 人工复核，量化模型的可用边界。",
        ),
        (
            "项目输出",
            "一套可复用的评测样本库、离线评测结论、典型样本拆解与可复现实验入口，"
            "让‘能不能用’从主观判断变成可验证的样本内观察。",
        ),
    ]


def get_methodology_items() -> list[tuple[str, str]]:
    """Methodology 的五个核心方法卡片。"""
    return [
        (
            "样本脱敏抽象",
            "从真实投行、财务、法律尽调经验中抽取判断结构与风险点，"
            "去除真实公司、交易与敏感数据，保留可评测的专业任务。",
        ),
        (
            "Gold Answer",
            "每道题人工撰写参考答案：核心结论、关键依据、边界条件与必须覆盖点，"
            "作为评分和错误归因的锚点。",
        ),
        (
            "Rubric 多维评分",
            "把‘好的尽调回答’拆成准确性、推理完整性、风险覆盖、证据充分、专业表达五个维度，"
            "由裁判模型对照 Gold 给出建议分。",
        ),
        (
            "红线错误",
            "重大风险遗漏、无依据定性、错误适用规则等触碰红线的回答，"
            "再高分也不能直接使用，必须人工复核或判为不可用。",
        ),
        (
            "人工复核归档",
            "裁判分数为建议分；现场评测结果默认进入草稿（pending），"
            "经人工复核确认后才计入正式评测结论。",
        ),
    ]


def get_dataset_snapshot_items(data) -> list[tuple[str, str]]:
    """Dataset Snapshot 的关键数字，全部从当前数据动态计算。"""
    task_count = len(getattr(data, "tasks", []))
    domain_count = _distinct_count(getattr(data, "tasks", None), "domain")
    gold_count = len(getattr(data, "gold_answer_map", {}))
    output_count = len(getattr(data, "model_outputs", []))
    scored = scored_case_count(getattr(data, "scores", None))
    return [
        ("任务样本", f"{task_count} 道"),
        ("覆盖领域", f"{domain_count} 个"),
        ("Gold 覆盖", f"{gold_count}/{task_count}"),
        ("评分记录", f"{scored} 条"),
        ("模型回答", f"{output_count} 条"),
    ]


def get_how_to_read_steps() -> list[str]:
    return [
        "先看已有评测结论",
        "再看典型样本拆解",
        "最后可现场发起可复现实验",
    ]
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


def get_how_to_read_steps() -> list[str]:
    return [
        "先看已有评测结论",
        "再看典型样本拆解",
        "最后可现场发起可复现实验",
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
        "Project Brief",
        "为什么做这个项目、解决什么问题、用什么方法、输出什么。",
    )
    render_feature_card(get_project_brief_items())

    render_section_block(
        "02",
        "Methodology",
        "从真实经验到可复现评测：脱敏抽象、Gold Answer、Rubric、红线、复核归档。",
    )
    render_feature_card(get_methodology_items())

    render_section_block(
        "03",
        "Dataset Snapshot",
        "当前数据规模与覆盖情况，全部从加载的数据动态计算。",
    )
    render_context_grid(get_dataset_snapshot_items(data))
    scored = scored_case_count(getattr(data, "scores", None))
    if scored > 0:
        st.caption(f"当前样本内已产出 {scored} 条裁判评分，可在各分析页查看样本内观察结论。")
    else:
        st.caption("当前尚无评测评分；运行一次真实评测后，Dataset Snapshot 会更新评分记录。")

    render_section_block(
        "04",
        "How to Read",
        "推荐阅读顺序：先看结论，再拆样本，最后现场复现。",
    )
    render_flow_strip(get_how_to_read_steps())
    st.markdown(
        "建议先在「评测结论」「模型边界报告」「模型能力指纹」等页看离线得出的结论；"
        "再到「典型样本拆解」看单题为什么能测出模型能力；"
        "最后到「可复现实验」用项目样本现场测试模型，对照 Gold Answer 与红线验证可用边界。"
    )

    render_info_panel(
        "口径与边界",
        "题库与 Gold 为 MVP 脱敏样本；裁判给出的是建议分，需人工复核确认后归档；"
        "所有结论均为当前样本内观察，不构成模型采购或业务决策建议。",
    )
    render_cta_group(
        [
            ("查看评测结论 →", "evaluation_conclusions"),
            ("典型样本拆解 →", "case_detail"),
            ("发起可复现实验 →", "eval_run"),
        ],
        key_prefix="methodology_foot",
    )
