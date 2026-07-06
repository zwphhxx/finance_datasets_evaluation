"""项目说明页：定位、样本口径、评测流程与主入口。
"""

from __future__ import annotations

import streamlit as st

from src.metrics import SCORE_DIMENSIONS
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
    from src.ui.labels import DOMAIN_LABELS, display_label
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
        "页面围绕样本、评分草稿、评分确认和正式结论组织；结论仅代表当前样本内观察，不替代专业判断。"
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
