"""Read-only renderers for durable answer, score, and queue records."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st

from app.persistence import ResultStoreError, ResultStoreUnavailableError
from app.services.evaluation_workflow import (
    COMPLETED,
    FAILED,
    INTERRUPTED,
    PARTIAL,
    RUNNING,
    STOPPED,
    EvaluationRunStatus,
)
from app.services.model_display import display_model_name
from src.ui.components import render_markdown_detail_panel

_STATUS_COPY = {
    RUNNING: ("评测进行中", "正在依次保存模型回答与评分记录。"),
    COMPLETED: ("评测已完成", "所有计划项均已完成回答与评分。"),
    PARTIAL: ("评测部分完成", "已有正式评分，失败项已保留供查证。"),
    FAILED: ("评测失败", "本批次没有可进入正式结论的评分。"),
    INTERRUPTED: ("评测已中断", "未完成项已保留，确认后可继续评测。"),
    STOPPED: ("评测已停止", "持久化失败后已停止后续模型调用。"),
}

_RUN_STATUS_LABELS = {
    "success": "已完成",
    "completed": "已完成",
    "running": "进行中",
    "pending": "等待中",
    "queued": "等待中",
    "failed": "失败",
    "error": "失败",
}
_SCORE_STATUS_LABELS = {
    "success": "已评分",
    "completed": "已评分",
    "running": "评分中",
    "pending": "等待评分",
    "queued": "等待评分",
    "failed": "评分失败",
    "error": "评分失败",
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


def _live_model_name(model_id: Any) -> str:
    return display_model_name(model_id, source="live")


def _record_status_label(value: Any, *, score: bool = False) -> str:
    raw = str(value or "").strip().lower()
    labels = _SCORE_STATUS_LABELS if score else _RUN_STATUS_LABELS
    return labels.get(raw, "未标注" if not raw else str(value))


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
            "模型": _live_model_name(model_id),
            "回答状态": _record_status_label(
                answer.get("run_status") or answer.get("status") or "pending"
            ),
            "总分": "—" if score.get("total_score") is None else str(score.get("total_score")),
            "评分状态": _record_status_label(
                score.get("judge_status") or score.get("status") or "pending",
                score=True,
            ),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    selected = st.selectbox(
        "查看评测记录",
        range(len(pairs)),
        format_func=lambda index: f"{pairs[index][0]}｜{_live_model_name(pairs[index][1])}",
    )
    _render_record_detail(answers.get(pairs[selected], {}), scores.get(pairs[selected], {}), dimensions)


def _render_record_detail(
    answer: Mapping[str, Any], score: Mapping[str, Any], dimensions: Sequence[Mapping[str, Any]]
) -> None:
    if answer:
        technical_clicked = render_markdown_detail_panel(
            "模型回答",
            str(answer.get("answer_text") or answer.get("error_message") or "暂无回答。"),
            meta=f"模型 ID：{answer.get('model_name') or '—'}",
            action_label="查看技术明细",
            action_type="secondary",
        )
        if technical_clicked:
            st.dataframe(build_technical_detail_rows(answer), use_container_width=True, hide_index=True)
    if score:
        score_detail = _score_detail_markdown(score, dimensions)
        technical_clicked = render_markdown_detail_panel(
            "评分维度与理由",
            score_detail,
            meta=f"裁判模型：{score.get('judge_model') or '—'}",
            action_label="查看评分技术明细",
            action_type="secondary",
        )
        if technical_clicked:
            st.dataframe(build_technical_detail_rows(score), use_container_width=True, hide_index=True)


def _score_detail_markdown(
    score: Mapping[str, Any], dimensions: Sequence[Mapping[str, Any]]
) -> str:
    labels = {
        str(dimension.get("field") or ""): str(
            dimension.get("name") or dimension.get("field") or "未标注维度"
        )
        for dimension in dimensions
    }
    dimension_lines = "\n".join(
        f"- {labels.get(str(dimension.get('field') or ''), '未标注维度')}："
        f"{_display_number(score.get(dimension.get('field')))} / "
        f"{_display_number(dimension.get('full_mark'))}"
        for dimension in dimensions
    ) or "—"
    rationale = _rationale_markdown(score.get("rationale"), labels)
    return (
        f"{dimension_lines}\n\n**评分理由**\n\n{rationale}\n\n"
        f"**审阅备注**\n\n{score.get('review_note') or '—'}"
    )


def _rationale_markdown(value: Any, labels: Mapping[str, str]) -> str:
    parsed: Any = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = value
    if isinstance(parsed, Mapping):
        lines = [
            f"- {labels.get(str(field), str(field))}：{detail or '—'}"
            for field, detail in parsed.items()
        ]
        return "\n".join(lines) or "—"
    return str(parsed or "—")


def _display_number(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def load_evaluation_records(store, status: EvaluationRunStatus) -> tuple[list[dict], list[dict]]:
    """Read exactly one persisted answer batch and its matching score batch."""
    answers = list(store.list_rows("live_run_responses", run_id=status.run_id))
    scores = list(store.list_rows("live_run_scores", score_run_id=status.score_run_id))
    return answers, scores


@st.dialog("本批次评测记录", width="large")
def render_evaluation_records_dialog(
    store,
    status: EvaluationRunStatus,
    dimensions: Sequence[Mapping[str, Any]],
) -> None:
    """Load the long record body only after the user requests the dialog."""
    try:
        answers, scores = load_evaluation_records(store, status)
    except (ResultStoreError, ResultStoreUnavailableError):
        st.warning("评测记录暂时无法读取，请在数据库恢复后重试。")
        return
    render_run_record(answers, scores, dimensions)


def build_technical_detail_rows(row: Mapping[str, Any]) -> list[dict[str, str]]:
    return [{"字段": str(key), "值": "—" if value is None else str(value)} for key, value in row.items()]
