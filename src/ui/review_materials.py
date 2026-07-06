"""评分确认页的摘要与评分材料弹窗。"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from app.services import model_display as md
from app.services import scorer as sc
from src.gold_quality import field_list, field_text
from src.metrics import get_errors_for_output, normalize_optimization_plan
from src.ui.components import (
    render_clean_list,
    render_detail_panel_with_action,
    render_inline_status,
    render_markdown_detail_panel,
)
from src.ui.labels import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    RISK_LABELS,
    TASK_TYPE_LABELS,
    display_label,
)
from src.ui.review_scoring import (
    attention_items,
    build_rubric_material_display,
    clean,
    has_value,
    number_text,
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
    panel = build_score_summary_panel(item, errors_df)
    clicked = render_detail_panel_with_action(
        _score_summary_body_html(panel),
        title=str(panel["title"]),
        meta=f"{panel['meta']}\n模型 ID：{panel['model_id']}",
        action_label="查看评分材料",
        action_key=f"review_materials::{item['case_id']}::{safe_key(panel['model_id'])}",
        action_type="secondary",
    )
    if clicked:
        render_score_materials_dialog(item, verdict, errors_df, optimization_df)


def build_score_summary_panel(item: dict, errors_df: pd.DataFrame | None) -> dict[str, object]:
    row = item["output_row"]
    recommendation = item.get("recommendation") or {}
    reasons = [str(reason).strip() for reason in recommendation.get("reasons") or [] if str(reason).strip()]
    model_id = text(item.get("model_name") or row.get("eval_model"), "—")
    judge_model = md.display_model_name(row.get("judge_model") or sc.DEFAULT_JUDGE_MODEL)
    attention = attention_items(
        row,
        errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(),
        item.get("gold"),
        item.get("task_info"),
        item.get("rubric_rows") or [],
    )
    return {
        "title": f'{text(item.get("case_id"), "—")}｜{text(item.get("display_model"), "—")}',
        "meta": (
            f"总分 {score_text(row.get('total_score'))} / 100｜"
            f"建议处理：{text(recommendation.get('recommendation'), '待判断')}｜"
            f"裁判模型：{judge_model}"
        ),
        "model_id": model_id,
        "reason": "；".join(reasons[:3]) or "暂无明确原因",
        "attention": attention,
        "review_note": text(row.get("review_note"), ""),
    }


def _score_summary_body_html(panel: dict[str, object]) -> str:
    sections = [
        _summary_section_html(
            "主要原因",
            f'<p class="review-summary-text">{escape(str(panel.get("reason") or "暂无明确原因"))}</p>',
        ),
    ]
    review_note = str(panel.get("review_note") or "").strip()
    if review_note:
        sections.append(
            _summary_section_html(
                "复核提示",
                f'<p class="review-summary-text">{escape(review_note)}</p>',
            )
        )
    attention = [str(item).strip() for item in panel.get("attention") or [] if str(item).strip()]
    if attention:
        items = "".join(f"<li>{escape(item)}</li>" for item in attention)
        attention_html = f'<ul class="review-summary-list">{items}</ul>'
    else:
        attention_html = '<p class="review-summary-text">暂无特别关注点。</p>'
    sections.append(_summary_section_html("需要关注", attention_html))
    return f'<div class="review-summary-panel-body">{"".join(sections)}</div>'


def _summary_section_html(title: str, body_html: str) -> str:
    return (
        '<section class="review-summary-section">'
        f'<div class="review-summary-section-title">{escape(title)}</div>'
        f"{body_html}"
        "</section>"
    )


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
        ("专业场景", display_label(task_info.get("domain"), DOMAIN_LABELS)),
        ("类型", display_label(task_info.get("task_type"), TASK_TYPE_LABELS)),
        ("难度", DIFFICULTY_LABELS.get(text(task_info.get("difficulty")), text(task_info.get("difficulty")))),
        ("风险", RISK_LABELS.get(text(task_info.get("risk_level")), text(task_info.get("risk_level")))),
    ])
    st.markdown(text(task_info.get("context"), "暂无背景材料"))
    st.markdown("**任务题**")
    st.markdown(text(task_info.get("question"), text(task_info.get("scenario"), "暂无任务题")))

    st.markdown("**专业标准答案**")
    if isinstance(gold, dict):
        render_inline_status([
            ("标准结论", field_text(gold, "core_conclusion", "待补充")),
            ("关键依据", field_text(gold, "key_evidence", "待补充")),
            ("边界与需核查事项", field_text(gold, "boundary_conditions", "待补充")),
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
        st.caption("该任务暂无专业标准答案。")

    render_markdown_detail_panel("模型回答", text(row.get("answer_text"), "暂无回答内容。"))

    rubric_display = build_rubric_material_display(ds.get_rubric_dimensions())
    st.markdown(f"**{rubric_display['title']}**")
    if rubric_display.get("note"):
        st.caption(str(rubric_display["note"]))
    rubric_rows = list(rubric_display.get("rows") or [])
    if rubric_rows:
        st.dataframe(pd.DataFrame(rubric_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("暂无评分标准。")

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
