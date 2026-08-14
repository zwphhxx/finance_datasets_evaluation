"""Read-only renderers for durable answer, score, and queue records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st

from app.services.evaluation_workflow import (
    COMPLETED,
    FAILED,
    INTERRUPTED,
    PARTIAL,
    RUNNING,
    STOPPED,
    EvaluationRunStatus,
)
from src.ui.components import render_markdown_detail_panel
from src.ui.labels import display_label

_STATUS_COPY = {
    RUNNING: ("评测进行中", "正在依次保存模型回答与评分记录。"),
    COMPLETED: ("评测已完成", "所有计划项均已完成回答与评分。"),
    PARTIAL: ("评测部分完成", "已有正式评分，失败项已保留供查证。"),
    FAILED: ("评测失败", "本批次没有可进入正式结论的评分。"),
    INTERRUPTED: ("评测已中断", "未完成项已保留，确认后可继续评测。"),
    STOPPED: ("评测已停止", "持久化失败后已停止后续模型调用。"),
}


def evaluation_status_copy(status: EvaluationRunStatus) -> tuple[str, str]:
    return _STATUS_COPY.get(status.state, _STATUS_COPY[FAILED])


def render_evaluation_status(status: EvaluationRunStatus) -> None:
    title, summary = evaluation_status_copy(status)
    st.markdown(f"**{title}**")
    detail = f" {status.message}" if status.message else ""
    st.caption(
        f"{summary} 计划 {status.total} 项 · 成功 {status.succeeded} 项 · "
        f"失败 {status.failed} 项 · 未完成 {status.pending} 项。{detail}"
    )


def render_run_record(
    answer_rows: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
    dimensions: Sequence[Mapping[str, Any]],
) -> None:
    """Render persisted combined records without offering a second score action."""
    answers = {(str(row.get("case_id") or ""), str(row.get("model_name") or "")): row for row in answer_rows}
    scores = {(str(row.get("case_id") or ""), str(row.get("eval_model") or "")): row for row in score_rows}
    pairs = [*dict.fromkeys([*answers, *scores])]
    if not pairs:
        st.caption("当前批次尚无可展示的评测记录。")
        return
    rows = []
    for case_id, model_id in pairs:
        answer, score = answers.get((case_id, model_id), {}), scores.get((case_id, model_id), {})
        rows.append({
            "样本": case_id,
            "模型": display_label(model_id),
            "回答状态": str(answer.get("run_status") or answer.get("status") or "等待中"),
            "总分": "—" if score.get("total_score") is None else str(score.get("total_score")),
            "评分状态": str(score.get("judge_status") or score.get("status") or "等待中"),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    selected = st.selectbox("查看评测记录", range(len(pairs)), format_func=lambda index: f"{pairs[index][0]}｜{display_label(pairs[index][1])}")
    _render_record_detail(answers.get(pairs[selected], {}), scores.get(pairs[selected], {}), dimensions)


def _render_record_detail(
    answer: Mapping[str, Any], score: Mapping[str, Any], dimensions: Sequence[Mapping[str, Any]]
) -> None:
    if answer:
        render_markdown_detail_panel(
            "模型回答",
            str(answer.get("answer_text") or answer.get("error_message") or "暂无回答。"),
            meta=f"模型 ID：{answer.get('model_name') or '—'}",
            action_label="查看技术明细",
            action_type="secondary",
        )
    if score:
        dimension_lines = "\n".join(
            f"- {dimension.get('name') or dimension.get('field')}：{score.get(dimension.get('field'), '—')}"
            for dimension in dimensions
        )
        rationale = score.get("rationale") or "—"
        render_markdown_detail_panel(
            "评分维度与理由",
            f"{dimension_lines}\n\n评分理由：{rationale}\n\n审阅备注：{score.get('review_note') or '—'}",
            meta=f"裁判模型：{score.get('judge_model') or '—'}",
            action_label="查看评分技术明细",
            action_type="secondary",
        )


def build_technical_detail_rows(row: Mapping[str, Any]) -> list[dict[str, str]]:
    return [{"字段": str(key), "值": "—" if value is None else str(value)} for key, value in row.items()]
