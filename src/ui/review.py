"""评分确认页面编排。

页面只保留四段主流程：
01 待处理评分 → 02 当前评分摘要 → 03 评分依据 → 04 确认处理。
队列、材料、操作和评分依据的细节分别拆到 review_queue / review_materials /
review_actions / review_scoring，避免页面文件继续承载历史矩阵和风险块实现。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from src.ui.components import render_empty_state, render_numbered_section, render_page_heading
from src.ui.page_config import get_page_config
from src.ui.review_actions import (
    confirm_review as _confirm_review,
    render_confirm_dialog as _render_confirm_dialog,
    render_confirmation_actions as _render_confirmation_actions,
    render_dialog_score_summary as _render_dialog_score_summary,
    render_revision_dialog as _render_revision_dialog,
    render_skip_dialog as _render_skip_dialog,
    review_note_required as _review_note_required,
    scores_from_row as _scores_from_row,
)
from src.ui.review_materials import (
    build_error_attribution_rows,
    optimization_plan_lookup as _optimization_lookup,
    render_markdown_bullets as _render_markdown_bullets,
    render_score_materials_dialog as _render_score_materials_dialog,
    render_score_summary as _render_score_summary,
)
from src.ui.review_queue import (
    REVIEW_ACTION_RESULT_KEY,
    REVIEW_AUTO_SWITCH_KEY,
    REVIEW_FILTER_OPTIONS,
    REVIEW_QUEUE_VERSION_KEY,
    build_live_review_items as _build_live_review_items,
    build_review_action_result,
    build_review_queue_stats,
    build_score_run_summary,
    compact_texts as _compact_texts,
    current_review_action_result as _current_review_action_result,
    default_score_run_id,
    display_review_status as _display_review_status,
    filter_live_score_frame as _filter_live_score_frame,
    filter_review_queue_items,
    has_pending_review_items,
    latest_score_run_id as _latest_score_run_id,
    live_answer_lookup as _live_answer_lookup,
    recommendation_rank as _recommendation_rank,
    record_review_action_result as _record_review_action_result,
    render_review_queue as _render_review_queue,
    render_score_run_summary as _render_score_run_summary,
    review_empty_message,
    review_item_label as _review_item_label,
    review_queue_row,
    review_status_label as _review_status_label,
    review_status_rank as _review_status_rank,
    review_status_value as _review_status_value,
    score_run_created_at as _score_run_created_at,
    score_run_ids as _score_run_ids,
    score_run_label as _score_run_label,
    score_run_option_label,
    select_next_review_index,
    select_score_run_id as _select_score_run_id,
    selected_review_table_index,
    should_show_no_pending_after_action,
    unique_display_models as _unique_display_models,
    unique_texts as _unique_texts,
)
from src.ui.review_scoring import (
    as_float as _as_float,
    as_int as _as_int,
    attention_items as _attention_items,
    build_case_verdict,
    build_point_coverage,
    build_redline_blocks,
    build_review_basis_rows,
    build_review_recommendation,
    build_review_scoring_matrix_rows,
    build_rubric_rows,
    clean as _clean,
    dedupe_texts as _dedupe_texts,
    detect_redline_hits,
    dimension_attention as _dimension_attention,
    errors_by_dimension as _errors_by_dimension,
    errors_by_dimension_field as _errors_by_dimension_field,
    format_datetime as _format_datetime,
    get_rubric_dimensions as _get_rubric,
    has_value,
    normalize_text as _normalize_text,
    number_text as _number_text,
    rationale_for_field as _rationale_for_field,
    rationale_map as _rationale_map,
    render_scoring_basis as _render_scoring_basis,
    rubric_material_rows as _rubric_material_rows,
    rubric_requirement as _rubric_requirement,
    safe_key as _safe_key,
    score_text as _score_text,
    text as _text,
    weakest_rubric as _weakest_rubric,
)


REVIEW_SECTIONS = [
    "待处理评分",
    "当前评分摘要",
    "评分依据",
    "确认处理",
]


def get_review_sections() -> list[str]:
    """Return the review page sections in reader-facing order."""
    return REVIEW_SECTIONS[:]


def render_review_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    eval_status = data_bundle.get("eval_status") or {}
    errors_df = getattr(base, "errors", pd.DataFrame())
    optimizations_df = getattr(base, "optimizations", pd.DataFrame())

    config = get_page_config("review")
    render_page_heading(config.title, config.question)

    items, selected_score_run_id = _load_live_review_items(base, eval_status)
    if not items:
        render_empty_state("暂无待处理评分草稿。请先在发起评测页运行模型回答并生成评分草稿。")
        return

    if st.session_state.get(REVIEW_AUTO_SWITCH_KEY):
        st.session_state["review_queue_filter"] = "待处理"

    render_numbered_section("01", REVIEW_SECTIONS[0], "通过表格选择一条评分草稿，查看摘要和评分依据。")
    visible_items, selected_table_index = _render_review_queue(items, selected_score_run_id)
    if not visible_items:
        st.session_state[REVIEW_AUTO_SWITCH_KEY] = False
        render_empty_state(review_empty_message(items))
        return
    if should_show_no_pending_after_action(items, bool(st.session_state.get(REVIEW_AUTO_SWITCH_KEY))):
        st.session_state[REVIEW_AUTO_SWITCH_KEY] = False
        render_empty_state(review_empty_message(items))
        return
    st.session_state[REVIEW_AUTO_SWITCH_KEY] = False
    action_result = _current_review_action_result()
    if action_result and _as_int(action_result.get("row_id")) is not None:
        selected_table_index = select_next_review_index(
            visible_items,
            handled_row_id=_as_int(action_result.get("row_id")),
        )
    if selected_table_index is None:
        render_empty_state(review_empty_message(items))
        return

    item = visible_items[int(selected_table_index)]
    output_row = item["output_row"]
    task_info = item["task_info"]
    gold = item["gold"]
    verdict = build_case_verdict(output_row, errors_df, gold, task_info)

    render_numbered_section("02", REVIEW_SECTIONS[1], "确认这条评分对应的样本、模型、总分和建议处理。")
    _render_score_summary(item, verdict, errors_df, optimizations_df)

    render_numbered_section("03", REVIEW_SECTIONS[2], "按 Rubric 维度查看得分、评分依据和需关注点。")
    _render_scoring_basis(output_row, errors_df)

    render_numbered_section("04", REVIEW_SECTIONS[3], "人工确认生效、修订后确认，或暂不采用。")
    _render_confirmation_actions(item)


def _load_live_review_items(base, eval_status: dict) -> tuple[list[dict], str | None]:
    scores = _filter_live_score_frame(cc.load_live_scores())
    if scores.empty:
        return [], None
    selected_score_run_id = _select_score_run_id(scores, eval_status)
    if selected_score_run_id:
        scores = scores[scores["score_run_id"].astype(str) == str(selected_score_run_id)]
    responses = cc.load_live_responses()
    items = _build_live_review_items(base, scores, responses)
    return items, selected_score_run_id
