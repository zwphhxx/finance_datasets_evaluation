"""评分确认页的确认、修订和暂不采用操作。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from app.services import scorer as sc
from src.ui.components import render_empty_state
from src.ui.review_queue import record_review_action_result, review_status_label
from src.ui.review_scoring import as_float, as_int, clean, score_text


def render_confirmation_actions(item: dict) -> None:
    row = item.get("score_row") or {}
    row_id = as_int(item.get("score_row_id"))
    if not row or row_id is None:
        st.caption("未找到可确认的评分草稿。")
        return

    review_status = str(row.get("review_status") or "pending")
    if review_status == "confirmed":
        st.caption("本条评分已确认，已纳入正式结论。")
        return
    if review_status == "skipped":
        st.caption("本条评分已暂不采用，未纳入正式结论。")
        return
    if review_status != "pending":
        st.caption(f"本条评分状态为 {review_status_label(review_status)}，仅待确认草稿可在此确认。")
        return

    st.caption("确认后才纳入正式结论；暂不采用的评分会保留记录，但不会进入正式结论。")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("确认生效", type="primary", key=f"review_confirm::{row_id}", use_container_width=True):
            render_confirm_dialog(item)
    with col2:
        if st.button("修订后确认", type="secondary", key=f"review_confirm_edit::{row_id}", use_container_width=True):
            render_revision_dialog(item)
    with col3:
        if st.button("暂不采用", type="tertiary", key=f"review_skip::{row_id}", use_container_width=True):
            render_skip_dialog(item)


@st.dialog("确认生效", width="medium")
def render_confirm_dialog(item: dict) -> None:
    row = item.get("score_row") or {}
    row_id = as_int(item.get("score_row_id"))
    if row_id is None:
        render_empty_state("未找到可确认的评分草稿。")
        return
    recommendation = item.get("recommendation") or {}
    required = review_note_required(recommendation)

    st.markdown("你将确认当前评分草稿。确认后，该评分将纳入正式结论。")
    render_dialog_score_summary(item)
    note = st.text_area("复核说明", value=str(row.get("review_note") or ""), key=f"review_confirm_note::{row_id}")
    if required:
        st.caption("建议复核或不建议采用的评分，需要填写复核说明。")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认生效", type="primary", key=f"review_confirm_dialog_submit::{row_id}", use_container_width=True):
            confirm_review(row_id, scores_from_row(row, ds.get_rubric_dimensions()), note, required, "confirm")
    with col2:
        if st.button("取消", type="tertiary", key=f"review_confirm_dialog_cancel::{row_id}", use_container_width=True):
            st.rerun()


@st.dialog("修订后确认", width="large")
def render_revision_dialog(item: dict) -> None:
    row = item.get("score_row") or {}
    row_id = as_int(item.get("score_row_id"))
    if row_id is None:
        render_empty_state("未找到可确认的评分草稿。")
        return
    st.markdown("请修订维度分数，并填写复核说明。保存后，该评分将纳入正式结论。")
    render_dialog_score_summary(item)
    dimensions = ds.get_rubric_dimensions()
    edited: dict[str, int] = {}
    for dim in dimensions:
        field_name = dim["field"]
        full_mark = int(dim.get("full_mark") or 0)
        current = row.get(field_name)
        value = int(current) if current is not None and str(current) != "nan" else 0
        edited[field_name] = st.number_input(
            dim["name"],
            min_value=0,
            max_value=full_mark,
            value=min(value, full_mark),
            step=1,
            key=f"review_revision_score::{row_id}::{field_name}",
        )
    note = st.text_area("复核说明", value=str(row.get("review_note") or ""), key=f"review_revision_note::{row_id}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("保存并确认", type="primary", key=f"review_revision_submit::{row_id}", use_container_width=True):
            confirm_review(row_id, edited, note, True, "revision")
    with col2:
        if st.button("取消", type="tertiary", key=f"review_revision_cancel::{row_id}", use_container_width=True):
            st.rerun()


@st.dialog("暂不采用", width="medium")
def render_skip_dialog(item: dict) -> None:
    row_id = as_int(item.get("score_row_id"))
    if row_id is None:
        render_empty_state("未找到可处理的评分草稿。")
        return
    st.markdown("该评分草稿不会纳入正式结论，但会保留记录，便于后续追溯。")
    render_dialog_score_summary(item)
    reason = st.text_area("原因", key=f"review_skip_reason::{row_id}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认暂不采用", type="primary", key=f"review_skip_submit::{row_id}", use_container_width=True):
            cleaned = clean(reason)
            if not cleaned:
                st.warning("请填写暂不采用原因。")
                return
            if sc.skip_score_review(row_id, f"暂不采用：{cleaned}"):
                record_review_action_result("skip", row_id)
                st.rerun()
            else:
                st.warning("暂不采用失败：请刷新页面后重试，或检查 SQLite 数据层是否已初始化。")
    with col2:
        if st.button("取消", type="tertiary", key=f"review_skip_cancel::{row_id}", use_container_width=True):
            st.rerun()


def render_dialog_score_summary(item: dict) -> None:
    row = item["output_row"]
    recommendation = item.get("recommendation") or {}
    st.markdown(f"**样本：** {item['case_id']}")
    st.markdown(f"**模型：** {item['display_model']}")
    st.markdown(f"**总分：** {score_text(row.get('total_score'))} / 100")
    st.markdown(f"**建议处理：** {recommendation.get('recommendation') or '待判断'}")


def review_note_required(recommendation: dict) -> bool:
    return str(recommendation.get("recommendation") or "") != "建议确认"


def scores_from_row(row: dict | pd.Series, dimensions: list[dict]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for dim in dimensions:
        field_name = str(dim.get("field") or "")
        if not field_name:
            continue
        full_mark = int(dim.get("full_mark") or 0)
        value = row.get(field_name) if hasattr(row, "get") else None
        number = as_float(value)
        score = 0 if number is None else int(round(number))
        scores[field_name] = max(0, min(full_mark, score))
    return scores


def confirm_review(
    row_id: int,
    edited: dict[str, int],
    note: str,
    requires_note: bool,
    action_type: str = "confirm",
) -> None:
    if requires_note and not clean(note):
        st.warning("建议复核或不建议采用的评分，需要填写复核说明后再确认。")
        return
    if sc.confirm_score_review(row_id, edited, note):
        record_review_action_result(action_type, row_id)
        st.rerun()
    else:
        st.warning("确认失败：请刷新页面后重试，或检查 SQLite 数据层是否已初始化。")
