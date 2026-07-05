from __future__ import annotations

import streamlit as st

from src.metrics import SCORE_DIMENSIONS
from src.model_boundary import BOUNDARY_AWARENESS_LABEL
from src.ui.components import (
    render_checklist,
    render_cta_group,
    render_mockup_stack,
    render_portfolio_landing_hero,
    render_project_meta_line,
    render_story_section,
    render_process_line,
    render_tag_cloud,
    render_pull_quote,
    render_conclusion_list,
    render_evidence_block,
)


def _distinct_count(df, column: str) -> int:
    if column in getattr(df, "columns", []):
        return int(df[column].dropna().nunique())
    return 0


def scored_case_count(scores_df) -> int:
    """当前样本中已产出评分的条数（运行真实评测后才大于 0），从 scores 动态计算。"""
    if scores_df is None or getattr(scores_df, "empty", True):
        return 0
    if "total_score" not in getattr(scores_df, "columns", []):
        return 0
    return int(scores_df["total_score"].notna().sum())


def _build_meta_line(data) -> str:
    """Build the one-line meta text from live data."""
    tasks = getattr(data, "tasks", None)
    task_count = len(tasks) if tasks is not None else 0
    domain_count = _distinct_count(tasks, "domain")
    scored = scored_case_count(getattr(data, "scores", None))
    dimension_count = len(SCORE_DIMENSIONS)
    return f"{task_count} 任务 · {domain_count} 领域 · {scored} 已评分 · {dimension_count} 维度"


def _get_domain_tags(data) -> list[str]:
    """Extract domain tags from tasks, with Chinese labels."""
    from src.ui.tasks import DOMAIN_LABELS, display_label
    tasks = getattr(data, "tasks", None)
    if tasks is None or tasks.empty or "domain" not in tasks.columns:
        return ["资本市场", "财务尽调", "法律核查", "并购交易"]
    domains = tasks["domain"].dropna().astype(str).unique()
    return [display_label(d, DOMAIN_LABELS) for d in domains]


def _get_formal_conclusions(data) -> list[tuple[str, str]]:
    """Build up to 3 formal conclusion summaries from data."""
    from app.services import conclusions as cc
    seed_scores = getattr(data, "scores", None)
    conclusions = cc.build_formal_conclusions(seed_scores, [])
    items = []
    for item in conclusions[:3]:
        text = f"{item['display_name']} 在当前样本中平均总分 {item['avg_total']:.1f}"
        notes = item.get("review_notes", []) or []
        meta = " · ".join(notes[:2]) if notes else "暂无人工点评"
        items.append((text, meta))
    if not items:
        items.append((
            "当前暂无正式评测结论。运行一次真实评测并经人工复核归档后，结论会在此汇总。",
            ""
        ))
    return items


def render_project_methodology_page(data_bundle: dict) -> None:
    data = data_bundle["data"]

    # --- Hero: two-column with huge title, checklist, mockups ---
    # Portfolio case-study structure uses render_hero + render_section_block + render_feature_card
    render_portfolio_landing_hero(
        title="FinDueEval",
        subtitle="专业尽调场景下的大模型可用边界评测",
        description=(
            "基于投资投行、财务与法律尽调经验，不是模型排行榜；"
            "判断模型的回答哪些能参考、哪些需人工复核、哪些触发红线。"
        ),
        checklist_items=[
            "经验样本脱敏沉淀",
            "Gold Answer + Rubric 多维评价",
            "草稿评测经人工复核后归档",
        ],
        meta_line=_build_meta_line(data),
    )
    # Render mockups on the right side
    render_mockup_stack()

    # --- Section 01: Why this project (Project Brief) ---
    render_story_section(
        title="Why this project",
        paragraphs=[
            "在投行、财务和法律尽调中，模型的回答经常‘写得像对，但漏掉关键风险’——结论通顺专业，却可能隐藏致命遗漏或无依据的确定性判断。",
            "尽调是高风险、强合规工作。相比明显的事实错误，‘看起来对’的错误更难发现，也更危险。我想回答：在尽调任务上，模型回答到底能不能放心用？",
            "把过往尽调经验脱敏抽象成标准化任务，人工撰写 Gold Answer，再用 Rubric 多维评分 + 红线错误 + 人工复核，量化模型的可用边界。",
        ],
        index="01",
    )

    # --- Section 02: Method (Methodology) ---
    render_story_section(
        title="Method",
        paragraphs=[
            "从真实经验到可复现评测，整个流程分为六个环节：",
        ],
        index="02",
    )
    render_process_line([
        "经验样本", "Gold Answer", "Rubric", "模型回答", "人工复核", "结论归档"
    ])

    # --- Section 03: Dataset (Dataset Snapshot) ---
    render_story_section(
        title="Dataset",
        paragraphs=[
            "所有样本均从真实尽调经验中脱敏抽象，去除真实公司、交易与敏感数据，保留可评测的专业任务结构。每道题包含业务场景、考察能力、风险等级与 Gold Answer。",
        ],
        index="03",
    )
    render_tag_cloud(_get_domain_tags(data))
    st.caption("样本脱敏原则：去除真实公司名、交易金额、敏感数据，保留判断结构与风险点。")

    # --- Section 04: Evaluation ---
    render_story_section(
        title="Evaluation",
        paragraphs=[
            "把‘好的尽调回答’拆成五个维度，由裁判模型对照 Gold 给出建议分：",
        ],
        index="04",
    )
    eval_items = []
    for key, label in SCORE_DIMENSIONS:
        note = {
            "accuracy_score": "结论与事实、法规、财务口径是否准确",
            "reasoning_score": "推理是否完整、贴合具体业务场景",
            "coverage_score": "关键风险是否覆盖到位",
            "evidence_score": "结论是否给出可核查的依据",
            "expression_score": "表达是否专业克制、结构清楚",
        }.get(key, "")
        eval_items.append(f"{label}：{note}")
    render_checklist(eval_items)
    render_pull_quote("高分只能作为初稿参考，红线错误一票否决。")

    # --- Section 05: Conclusions ---
    render_story_section(
        title="Conclusions",
        paragraphs=[
            "正式结论只纳入已人工沉淀的基准结论与已复核归档的现场结论。草稿评测未进入正式结论。",
        ],
        index="05",
    )
    render_conclusion_list(_get_formal_conclusions(data))

    # --- Section 06: Try it (How to Read) ---
    render_story_section(
        title="Try it",
        paragraphs=[
            "从样本库浏览到可复现实验，三个入口按需进入：",
        ],
        index="06",
    )
    render_cta_group(
        [
            ("浏览样本库 →", "tasks"),
            ("查看评测结论 →", "evaluation_conclusions"),
            ("发起可复现实验 →", "eval_run"),
        ],
        key_prefix="methodology_try",
    )


# --------------------------------------------------------------------------- #
# Backward-compatible aliases for tests that import removed functions.
# --------------------------------------------------------------------------- #

def build_hero_stats(data) -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility with PR-A tests."""
    task_count = len(tasks) if (tasks := getattr(data, "tasks", None)) is not None else 0
    domain_count = _distinct_count(tasks, "domain")
    dimension_count = len(SCORE_DIMENSIONS)
    return [
        (str(task_count), "尽调任务样本"),
        (str(domain_count), "专业领域"),
        (str(dimension_count), "Rubric 评分维度"),
    ]


def build_dataset_summary_items(data) -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility with PR-A tests."""
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


def get_sample_structure_items() -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility."""
    return [
        ("任务题与背景", "每道题给出业务场景、问题与必要背景，对应真实尽调中的一个判断节点。"),
        ("考察能力", "标注这道题主要考察的专业能力，便于按能力维度归类分析。"),
        ("风险等级", "标注任务的风险等级，风险越高的任务，红线判定越严格。"),
        ("Gold Answer", "人工撰写的参考答案，包含核心结论、关键依据与边界条件。"),
        ("必须覆盖点", "这道题必须命中的要点，遗漏即扣风险覆盖分。"),
        ("不可接受错误", "触碰即触发红线的错误，例如重大风险遗漏或无依据定性。"),
    ]


def get_project_brief_items() -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility."""
    return [
        (
            "背景",
            "在投行、财务和法律尽调中，模型的回答经常'写得像对，但漏掉关键风险'——"
            "结论通顺专业，却可能隐藏致命遗漏或无依据的确定性判断。",
        ),
        (
            "问题",
            "尽调是高风险、强合规工作。相比明显的事实错误，'看起来对'的错误更难发现，也更危险。"
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
            "让'能不能用'从主观判断变成可验证的样本内观察。",
        ),
    ]


def get_methodology_items() -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility."""
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
            "把'好的尽调回答'拆成准确性、推理完整性、风险覆盖、证据充分、专业表达五个维度，"
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
    """Deprecated: kept for backward compatibility."""
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
    """Deprecated: kept for backward compatibility."""
    return [
        "先看已有评测结论",
        "再看典型样本拆解",
        "最后可现场发起可复现实验",
    ]


def get_rubric_framework_items() -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility."""
    _RUBRIC_DIM_NOTES = {
        "accuracy_score": "结论与事实、法规、财务口径是否准确，有没有'写得像对'的硬伤。",
        "reasoning_score": "推理是否完整、贴合具体业务场景，而不是套用通用模板。",
        "coverage_score": "该提示的关键风险是否覆盖到位，有没有漏掉致命风险。",
        "evidence_score": "结论是否给出可核查的依据，有没有无依据的定性。",
        "expression_score": "表达是否专业克制、结构清楚，能否直接进入尽调底稿。",
    }
    items = [(label, _RUBRIC_DIM_NOTES.get(key, "")) for key, label in SCORE_DIMENSIONS]
    items.append(
        (
            BOUNDARY_AWARENESS_LABEL,
            "不确定的地方是否明确标注核查边界，而不是给出虚假的确定性。",
        )
    )
    return items


def get_redline_triggers() -> list[str]:
    """Deprecated: kept for backward compatibility."""
    return [
        "重大风险遗漏：该提示的致命风险没有被提示出来。",
        "无依据定性：给出确定性结论，却拿不出可核查的依据。",
        "错误适用规则：套错法规、准则或财务口径，出现方向性错误。",
    ]
