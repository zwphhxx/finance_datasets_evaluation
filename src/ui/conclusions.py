"""评测结论页面。

- 已确认评分计入正式结论。
- 待确认草稿不进入正式结论。
- 展示当前样本内的模型均值与审慎使用边界，不展示示例评价。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from app.services import eval_state
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_compact_hero,
    render_numbered_section,
    render_text_block,
)


def render_conclusions_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    tasks = getattr(base, "tasks", None)

    live_scores = cc.load_live_scores()
    confirmed_live, pending_live = cc.split_live_scores(live_scores)
    responses = cc.load_live_responses()

    config = get_page_config("conclusions")
    render_compact_hero(
        eyebrow="正式结论",
        title=config.title,
        question=config.question,
    )

    _render_current_conclusion(confirmed_live)
    _render_model_boundaries(confirmed_live, tasks)
    _render_drafts(pending_live, responses)


# --------------------------------------------------------------------------- #
# 01 当前结论
# --------------------------------------------------------------------------- #
def _render_current_conclusion(confirmed_live) -> None:
    render_numbered_section(
        "01",
        "当前结论",
        "仅基于已确认评分汇总真实运行结果，不含待确认草稿、暂不采用记录和示例评价。",
    )

    empty_seed = pd.DataFrame()
    summary = cc.summarize_formal(empty_seed, confirmed_live)
    if summary["total_rows"] == 0:
        render_text_block(
            "当前暂无已确认评分",
            "请先在评分确认页完成确认；确认后的评分才会纳入正式结论。",
        )
        return

    avg_text = f"{summary['avg_total']:.1f}" if summary['avg_total'] is not None else "—"
    st.markdown(
        f"已确认评分 **{summary['confirmed_rows']}** 条 · 覆盖模型 **{summary['model_count']}** 个 · "
        f"平均总分 **{avg_text}**"
    )
    st.caption("当前结论只代表当前样本内观察，不构成模型排名或采购建议。")

    conclusions = cc.build_formal_conclusions(empty_seed, confirmed_live)
    rows = [_formal_conclusion_row(item) for item in conclusions]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "模型": st.column_config.TextColumn("模型", width="medium"),
                "平均总分": st.column_config.NumberColumn("平均总分", format="%.1f", width="small"),
                "样本数": st.column_config.NumberColumn("样本数", width="small"),
                "主要观察": st.column_config.TextColumn("主要观察", width="large"),
            },
        )

    combined = cc.combine_formal_scores(empty_seed, confirmed_live)
    all_notes = [note for item in conclusions for note in item.get("review_notes", [])]
    issues = cc.summarize_frequent_issues(combined, pd.DataFrame(), all_notes)
    if issues:
        st.markdown("### 主要观察")
        st.markdown("\n".join(f"- {issue}" for issue in issues))


def _formal_conclusion_row(item: dict) -> dict[str, object]:
    notes = item.get("review_notes") or []
    observation = "；".join(str(note) for note in notes[:2] if str(note).strip())
    if not observation:
        dimensions = item.get("dimensions") or {}
        weakest = _weakest_dimension_text(dimensions)
        observation = weakest or "当前样本内暂无补充说明"
    return {
        "模型": str(item.get("display_name") or item.get("model_name") or "未标注模型"),
        "平均总分": float(item.get("avg_total") or 0),
        "样本数": int(item.get("sample_count") or 0),
        "主要观察": observation,
    }


def _weakest_dimension_text(dimensions: dict) -> str:
    values = []
    for field, value in (dimensions or {}).items():
        if value is None:
            continue
        label = cc.DIMENSION_LABELS.get(field, field)
        values.append((label, float(value)))
    if not values:
        return ""
    label, value = min(values, key=lambda item: item[1])
    return f"相对薄弱维度：{label}（均分 {value:.1f}）"


# --------------------------------------------------------------------------- #
# 02 模型使用边界
# --------------------------------------------------------------------------- #
def _render_model_boundaries(confirmed_live, tasks) -> None:
    render_numbered_section(
        "02",
        "模型使用边界",
        "基于已确认评分，综合平均分、关键维度短板、高风险任务和样本数量判断。",
    )

    boundaries = cc.build_model_boundaries(pd.DataFrame(), confirmed_live, pd.DataFrame(), tasks)
    if not boundaries:
        render_text_block(
            "暂无边界数据",
            "暂无边界数据。确认评分后再生成模型使用边界。",
        )
        return

    rows = [_boundary_row(item) for item in boundaries]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "边界判断": st.column_config.TextColumn("边界判断", width="medium"),
            "平均分": st.column_config.NumberColumn("平均分", format="%.1f", width="small"),
            "样本数": st.column_config.TextColumn("样本数", width="small"),
            "主要短板": st.column_config.TextColumn("主要短板", width="medium"),
            "判断依据": st.column_config.TextColumn("判断依据", width="large"),
        },
    )
    st.caption("模型使用边界不是模型排名；待确认评分未纳入，结论仅代表当前样本内观察。")


def _boundary_row(item: dict) -> dict[str, object]:
    sample_text = f"{int(item.get('sample_count', 0))}"
    if item.get("sample_insufficient"):
        sample_text += "（观察不足）"
    return {
        "模型": str(item.get("display_name") or item.get("model_name") or "未标注模型"),
        "边界判断": str(item.get("boundary") or "待判断"),
        "平均分": float(item.get("avg_total") or 0),
        "样本数": sample_text,
        "主要短板": _format_weaknesses(item.get("major_weaknesses") or []),
        "判断依据": str(item.get("basis_summary") or "当前样本内暂无足够判断依据"),
    }


def _format_weaknesses(weaknesses: list[dict]) -> str:
    if not weaknesses:
        return "暂无明显短板"
    parts = []
    for item in weaknesses[:2]:
        dimension = str(item.get("dimension") or "未标注维度")
        attainment = item.get("attainment")
        if isinstance(attainment, (int, float)):
            parts.append(f"{dimension}（达成率 {attainment:.0%}）")
        else:
            parts.append(dimension)
    return "、".join(parts)


# --------------------------------------------------------------------------- #
# 03 待确认评分草稿
# --------------------------------------------------------------------------- #
def _render_drafts(pending_live, responses) -> None:
    render_numbered_section(
        "03",
        "待确认评分草稿",
        "现场新增评分先进入草稿，未确认前不纳入正式结论。",
    )

    draft_rows = cc.build_draft_rows(pending_live, responses)
    if not draft_rows:
        draft_rows = _session_draft_rows()

    count = len(draft_rows)
    if count == 0:
        st.caption("当前没有待确认评分草稿。请先在发起评测页运行模型回答并生成评分草稿。")
        return

    st.markdown(f"以下 **{count}** 条评分仍待确认，未纳入正式结论。")
    rows = [_draft_row(row) for row in draft_rows]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "样本编号": st.column_config.TextColumn("样本编号", width="small"),
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "总分": st.column_config.TextColumn("总分", width="small"),
            "状态": st.column_config.TextColumn("状态", width="small"),
        },
    )
    if st.button("进入评分确认", key="conc_to_review", type="secondary"):
        st.session_state.current_page = "review"
        st.rerun()


def _draft_row(row: dict) -> dict[str, str]:
    score = row.get("total_score")
    score_text = "—" if score is None else f"{float(score):.0f}"
    return {
        "样本编号": str(row.get("case_id") or ""),
        "模型": str(row.get("display_name") or row.get("model_name") or "未标注模型"),
        "总分": score_text,
        "状态": _review_status_label(row.get("review_status")),
    }


def _review_status_label(status) -> str:
    return {
        "pending": "待确认",
        "confirmed": "已确认",
        "skipped": "暂不采用",
    }.get(str(status or "pending").strip().lower(), "待确认")


# --------------------------------------------------------------------------- #
# Backward-compatible helpers
# --------------------------------------------------------------------------- #
def _session_draft_rows() -> list[dict]:
    """数据库不可用时，从会话内最近一次评分构造草稿行（仅展示，不能确认）。"""
    score_result = eval_state.get_last_score()
    if score_result is None:
        return []
    rows = []
    for outcome in getattr(score_result, "outcomes", []):
        if getattr(outcome, "judge_status", "") != "success":
            continue
        if str(getattr(outcome, "review_status", "pending")) == "confirmed":
            continue
        scores = dict(getattr(outcome, "scores", {}) or {})
        rows.append(
            {
                "row_id": None,
                "model_name": str(getattr(outcome, "eval_model", "")),
                "display_name": cc.display_model_name(getattr(outcome, "eval_model", ""), source="live"),
                "case_id": str(getattr(outcome, "case_id", "")),
                "total_score": _num(getattr(outcome, "total_score", None)),
                "dimensions": {field: _num(scores.get(field)) for field in cc.DIMENSION_FIELDS},
                "review_note": str(getattr(outcome, "review_note", "") or ""),
                "review_status": str(getattr(outcome, "review_status", "pending") or "pending"),
                "error_code": str(getattr(outcome, "error_code", "") or ""),
                "error_message": str(getattr(outcome, "error_message", "") or ""),
                "answer_text": "",
            }
        )
    return rows


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
