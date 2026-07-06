"""评分确认页的摘要与评分材料弹窗。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from app.services import model_display as md
from app.services import scorer as sc
from src.gold_quality import field_list, field_text
from src.metrics import get_errors_for_output, normalize_optimization_plan
from src.ui.components import render_clean_list, render_inline_status
from src.ui.labels import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    RISK_LABELS,
    TASK_TYPE_LABELS,
    display_label,
    summarize_text,
)
from src.ui.review_scoring import (
    attention_items,
    clean,
    has_value,
    number_text,
    rubric_material_rows,
    safe_key,
    score_text,
    text,
)


def render_score_summary(
    item: dict,
    verdict: dict,
    errors_df: pd.DataFrame,
    optimization_df: pd.DataFrame,
) -> None:
    row = item["output_row"]
    recommendation = item["recommendation"]
    reasons = recommendation.get("reasons") or ["暂无原因"]
    model_id = item["model_name"]
    summary_rows = [
        ("样本", item["case_id"]),
        ("模型", item["display_model"]),
        ("完整模型 ID", model_id),
        ("总分", f"{score_text(row.get('total_score'))} / 100"),
        ("建议处理", str(recommendation.get("recommendation") or "待判断")),
        ("主要原因", summarize_text("；".join(reasons[:3]), 96)),
    ]
    render_inline_status(summary_rows)

    attention = attention_items(row, errors_df, item["gold"], item["task_info"], item.get("rubric_rows") or [])
    if attention:
        st.markdown("**需要关注**")
        render_markdown_bullets(attention)
    else:
        st.caption("当前摘要未发现需额外关注的低分维度或红线提示。")

    if st.button(
        "查看评分材料",
        type="tertiary",
        key=f"review_materials::{item['case_id']}::{safe_key(model_id)}",
    ):
        render_score_materials_dialog(item, verdict, errors_df, optimization_df)


@st.dialog("评分材料", width="large")
def render_score_materials_dialog(
    item: dict,
    verdict: dict,
    errors_df: pd.DataFrame,
    optimization_df: pd.DataFrame,
) -> None:
    row = item["output_row"]
    task_info = item["task_info"]
    gold = item["gold"]
    st.caption(f"样本：{item['case_id']} · 模型：{item['display_model']}")

    st.markdown("**任务背景**")
    render_inline_status([
        ("领域", display_label(task_info.get("domain"), DOMAIN_LABELS)),
        ("类型", display_label(task_info.get("task_type"), TASK_TYPE_LABELS)),
        ("难度", DIFFICULTY_LABELS.get(text(task_info.get("difficulty")), text(task_info.get("difficulty")))),
        ("风险", RISK_LABELS.get(text(task_info.get("risk_level")), text(task_info.get("risk_level")))),
    ])
    st.markdown(text(task_info.get("context"), "暂无背景材料"))
    st.markdown("**任务题**")
    st.markdown(text(task_info.get("question"), text(task_info.get("scenario"), "暂无任务题")))

    st.markdown("**理想回复标准 / Gold Answer**")
    if isinstance(gold, dict):
        render_inline_status([
            ("核心结论", field_text(gold, "core_conclusion", "待补充")),
            ("关键依据", field_text(gold, "key_evidence", "待补充")),
            ("边界条件", field_text(gold, "boundary_conditions", "待补充")),
        ])
        must_points = field_list(gold, "must_have_points")
        red_lines = field_list(gold, "unacceptable_errors")
        if must_points:
            st.markdown("**必须覆盖点**")
            render_clean_list(must_points)
        if red_lines:
            st.markdown("**不可接受错误**")
            render_clean_list(red_lines)
    else:
        st.caption("该任务暂无理想回复标准 / Gold Answer。")

    st.markdown("**模型回答**")
    st.markdown(text(row.get("answer_text"), "暂无回答内容。"))

    st.markdown("**Rubric 原始要求**")
    rubric_rows = rubric_material_rows(ds.get_rubric_dimensions())
    if rubric_rows:
        st.dataframe(pd.DataFrame(rubric_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("暂无 Rubric 评分标准。")

    st.markdown("**错误标签**")
    error_rows = build_error_attribution_rows(errors_df, optimization_df, row.get("output_id"))
    if error_rows:
        st.dataframe(pd.DataFrame(error_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("暂无错误标签。")

    st.markdown("**技术明细**")
    render_inline_status([
        ("评分批次", text(row.get("score_run_id"), "—")),
        ("运行批次", text(row.get("run_id"), "—")),
        ("裁判模型", md.display_model_name(row.get("judge_model") or sc.DEFAULT_JUDGE_MODEL)),
        ("裁判状态", text(row.get("judge_status"), "—")),
        ("耗时", f"{number_text(row.get('latency_ms'))} ms" if has_value(row.get("latency_ms")) else "—"),
        ("使用边界", verdict.get("title") or "待判断"),
    ])


def build_error_attribution_rows(
    errors_df: pd.DataFrame | None,
    optimization_df: pd.DataFrame | None,
    output_id,
) -> list[dict[str, str]]:
    """Build error-attribution rows for the selected answer."""
    errors = get_errors_for_output(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), output_id)
    if errors.empty:
        return []
    optimization_lookup = optimization_plan_lookup(optimization_df)
    rows: list[dict[str, str]] = []
    for _, error in errors.iterrows():
        error_type = text(error.get("error_type"), "未分类错误")
        plan = optimization_lookup.get(error_type, {})
        data_action = (
            clean(plan.get("data_action"))
            or clean(error.get("optimization_action"))
            or "暂无优化建议"
        )
        rows.append({
            "错误类型": error_type,
            "严重程度": text(error.get("severity"), "未标注"),
            "错误表现": text(error.get("error_description"), "暂无错误表现"),
            "修正方向": text(error.get("correction"), "待补充修正方向"),
            "数据优化建议": data_action,
            "可能原因": text(plan.get("root_cause"), "待补充错误原因"),
        })
    return rows


def optimization_plan_lookup(optimization_df: pd.DataFrame | None) -> dict[str, dict]:
    if not isinstance(optimization_df, pd.DataFrame) or optimization_df.empty:
        return {}
    normalized = normalize_optimization_plan(optimization_df)
    lookup: dict[str, dict] = {}
    for _, row in normalized.iterrows():
        error_type = clean(row.get("error_type"))
        if error_type:
            lookup[error_type] = row.to_dict()
    return lookup


def render_markdown_bullets(items: list[str]) -> None:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        st.caption("暂无")
        return
    st.markdown("\n".join(f"- {item}" for item in cleaned))
