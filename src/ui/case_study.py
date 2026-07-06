"""项目说明页：定位、样本口径、评测流程与主入口。
"""

from __future__ import annotations

import streamlit as st

from src.metrics import SCORE_DIMENSIONS
from src.model_boundary import BOUNDARY_AWARENESS_LABEL
from src.ui.components import (
    render_compact_hero,
    render_clean_list,
    render_inline_status,
    render_numbered_section,
)
from src.ui.page_config import get_page_config


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


def _build_home_stats(base, eval_status: dict | None) -> list[tuple[str, str]]:
    tasks = getattr(base, "tasks", None)
    task_count = len(tasks) if tasks is not None else 0
    domain_count = _distinct_count(tasks, "domain")
    return [
        (str(task_count), "正式样本"),
        (str(domain_count), "尽调场景"),
        (str(len(SCORE_DIMENSIONS)), "评分维度"),
    ]


def _build_sample_scope_text(data) -> str:
    """Describe sample scope as plain text instead of homepage tags."""
    from src.ui.tasks import DOMAIN_LABELS, display_label
    tasks = getattr(data, "tasks", None)
    if tasks is None or tasks.empty or "domain" not in tasks.columns:
        return "样本来自金融尽调场景，已脱敏抽象为可评测任务；不包含真实公司、交易或敏感数据。"
    domains = [
        display_label(domain, DOMAIN_LABELS)
        for domain in tasks["domain"].dropna().astype(str).unique()
    ]
    domains = [domain for domain in domains if domain and domain != "未标注"]
    if domains:
        shown = domains[:4]
        suffix = "等" if len(domains) > len(shown) else ""
        domain_text = "、".join(shown) + suffix
    else:
        domain_text = "金融尽调"
    return f"样本来自{domain_text}场景，已脱敏抽象为可评测任务；不包含真实公司、交易或敏感数据。"


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
            "当前暂无正式评测结论。运行一次真实评测并经人工确认后，结论会在此汇总。",
            ""
        ))
    return items


def render_case_study_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    base = data_bundle.get("base") or data
    eval_status = data_bundle.get("eval_status") or {}
    config = get_page_config("case_study")

    render_compact_hero(
        eyebrow="项目概览",
        title=config.title,
        question=config.question,
        stats=_build_home_stats(base, eval_status),
    )

    render_numbered_section("01", "项目定位")
    st.markdown(
        "这是一个面试演示原型，用脱敏尽调样本评估模型回答的可参考程度、复核需求和使用边界。"
        "页面围绕样本、评分草稿、评分确认和正式结论组织，不替代专业判断。"
    )

    render_numbered_section("02", "评测流程")
    render_inline_status([
        ("1", "维护样本"),
        ("2", "确认可测"),
        ("3", "发起评测"),
        ("4", "评分草稿"),
        ("5", "评分确认"),
        ("6", "正式结论"),
    ])
    st.caption("只有通过样本库准入检查的样本可进入评测；只有人工确认后的分数进入正式结论。")

    render_numbered_section("03", "数据边界")
    st.markdown(_build_sample_scope_text(base))
    st.markdown(
        "每个可测样本由任务题、业务背景、理想回复标准 / Gold Answer、Rubric 评分标准和状态组成；"
        "是否进入评测由样本库中的完整度校验决定。"
    )
    st.markdown("**评分依据**")
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
    render_clean_list(eval_items)
    st.caption("高分只能作为初稿参考，红线错误仍需人工判断。")

    render_numbered_section("04", "进入操作")
    st.caption("先检查样本库，再选择可测样本发起评测。评分草稿进入评分确认后才形成正式结论。")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("查看样本库", type="primary", key="case_study_samples"):
            st.session_state.current_page = "samples"
            st.rerun()
    with col2:
        if st.button("发起评测", type="secondary", key="case_study_try"):
            st.session_state.current_page = "test_run"
            st.rerun()

    # render_story_section is kept in src.ui.components for older imports; the
    # current landing page uses render_numbered_section for the unified shell.


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
        ("Gold Answer", f"{gold_count}/{task_count} 道已配理想回复标准"),
        ("评价维度", f"{dimension_count} 个 Rubric 维度 + {BOUNDARY_AWARENESS_LABEL}"),
    ]


def get_sample_structure_items() -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility."""
    return [
        ("任务题与背景", "每道题给出业务场景、问题与必要背景，对应真实尽调中的一个判断节点。"),
        ("考察能力", "标注这道题主要考察的专业能力，便于按能力维度归类分析。"),
        ("风险等级", "标注任务的风险等级，风险越高的任务，红线判定越严格。"),
        ("Gold Answer", "人工撰写的理想回复标准，包含核心结论、关键依据与边界条件。"),
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
            "把过往尽调经验脱敏抽象成标准化任务，人工撰写理想回复标准 / Gold Answer，"
            "再用 Rubric 多维评分 + 红线错误 + 人工复核，量化模型的可用边界。",
        ),
        (
            "项目输出",
            "一套可复用的评测样本库、评分草稿、人工复核和正式结论入口，"
            "让'能不能用'从主观判断变成当前样本内观察。",
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
            "每道题人工撰写理想回复标准 / Gold Answer：核心结论、关键依据、边界条件与必须覆盖点，"
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
            "再高分也只能作为初稿参考，必须人工复核或判为不可用。",
        ),
        (
            "评分确认",
            "裁判分数为建议分；现场评测结果默认进入评分草稿，"
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
        "先检查样本库",
        "再选择可测样本发起评测",
        "最后确认评分并纳入正式结论",
    ]


def get_rubric_framework_items() -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility."""
    _RUBRIC_DIM_NOTES = {
        "accuracy_score": "结论与关键计算是否准确，并对照判断依据。",
        "reasoning_score": "分析逻辑是否完整，是否贴合任务场景。",
        "coverage_score": "是否覆盖必须关注的风险点与核查事项。",
        "evidence_score": "是否提供法规、数据等可靠依据支撑结论。",
        "expression_score": "表达是否清晰、审慎，符合专业报告风格。",
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
