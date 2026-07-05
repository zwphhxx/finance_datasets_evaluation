"""评测结论页面。

- 只汇总已确认评分。
- 待确认草稿不进入正式结论。
- 按模型展示当前建议、主要问题和待确认评分，不展示示例评价。
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
    model_summaries = cc.build_model_issue_summaries(confirmed_live, pd.DataFrame(), tasks)
    draft_rows = cc.build_draft_rows(pending_live, responses)
    if not draft_rows:
        draft_rows = _session_draft_rows()

    config = get_page_config("conclusions")
    render_compact_hero(
        eyebrow="正式结论",
        title=config.title,
        question=config.question,
    )
    st.markdown("本页只汇总已确认评分，用于判断各模型在当前样本内的使用边界。待确认评分不会进入正式结论。")
    st.caption("阅读顺序：先看当前结论，再看各模型当前建议，再看单个模型的问题明细。")

    _render_current_conclusion(confirmed_live, draft_rows)
    _render_model_recommendations(model_summaries)
    _render_model_issue_details(model_summaries)
    _render_drafts(draft_rows)


# --------------------------------------------------------------------------- #
# 01 当前结论
# --------------------------------------------------------------------------- #
def _render_current_conclusion(confirmed_live, draft_rows: list[dict]) -> None:
    render_numbered_section(
        "01",
        "当前结论",
        "仅基于已确认评分汇总真实运行结果，不含待确认草稿、暂不采用记录和示例评价。",
    )

    empty_seed = pd.DataFrame()
    summary = cc.summarize_formal(empty_seed, confirmed_live)
    if summary["total_rows"] == 0:
        description = (
            "请先在评分确认页完成确认。确认后的评分才会纳入正式结论。"
            if draft_rows
            else "当前暂无已确认评分，也没有待确认评分草稿。请先在发起评测页运行模型回答并生成评分草稿。"
        )
        render_text_block(
            "当前暂无已确认评分",
            description,
        )
        return

    avg_text = f"{summary['avg_total']:.1f}" if summary["avg_total"] is not None else "—"
    st.markdown(
        f"已确认评分 **{summary['confirmed_rows']}** 条 · "
        f"覆盖模型 **{summary['model_count']}** 个 · "
        f"覆盖样本 **{summary.get('case_count', 0)}** 个 · "
        f"平均总分 **{avg_text}**"
    )
    st.caption("当前结论只代表当前样本内观察，不构成模型整体能力或采购建议。")


# --------------------------------------------------------------------------- #
# 02 各模型当前建议
# --------------------------------------------------------------------------- #
def _render_model_recommendations(model_summaries: list[dict]) -> None:
    render_numbered_section(
        "02",
        "各模型当前建议",
        "按模型汇总平均分、已确认样本数、主要问题和判断依据。",
    )

    if not model_summaries:
        render_text_block(
            "暂无模型建议",
            "暂无已确认评分。完成评分确认后，此处会生成各模型当前建议。",
        )
        return

    rows = [_recommendation_row(item) for item in model_summaries]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "平均分": st.column_config.NumberColumn("平均分", format="%.1f", width="small"),
            "已确认样本数": st.column_config.NumberColumn("已确认样本数", width="small"),
            "当前建议": st.column_config.TextColumn("当前建议", width="medium"),
            "主要问题": st.column_config.TextColumn("主要问题", width="large"),
            "为什么这样判断": st.column_config.TextColumn("为什么这样判断", width="large"),
        },
    )
    st.caption("当前建议不是模型排名，只说明各模型在当前已确认样本内的使用边界。")


def _recommendation_row(item: dict) -> dict[str, object]:
    return {
        "模型": str(item.get("display_name") or item.get("model_name") or "未标注模型"),
        "平均分": float(item.get("avg_total") or 0),
        "已确认样本数": int(item.get("sample_count") or 0),
        "当前建议": str(item.get("current_suggestion") or "暂不形成判断"),
        "主要问题": _join_texts(item.get("main_issues") or [], "当前样本内暂无补充说明"),
        "为什么这样判断": str(item.get("basis_summary") or "基于已确认评分判断"),
    }


# --------------------------------------------------------------------------- #
# 03 单个模型问题明细
# --------------------------------------------------------------------------- #
def _render_model_issue_details(model_summaries: list[dict]) -> None:
    render_numbered_section(
        "03",
        "单个模型问题明细",
        "查看某个模型的主要问题、涉及样本、低分维度和使用建议。",
    )

    if not model_summaries:
        st.caption("暂无模型问题明细。确认评分后再查看。")
        return

    selected = model_summaries[0]
    if len(model_summaries) > 1:
        options = {
            str(item.get("display_name") or item.get("model_name") or "未标注模型"): item
            for item in model_summaries
        }
        label = st.selectbox("选择模型查看问题明细", list(options.keys()), key="conclusion_model_issue_select")
        selected = options[label]

    _render_issue_markdown(selected)


def _render_issue_markdown(item: dict) -> None:
    display = str(item.get("display_name") or item.get("model_name") or "未标注模型")
    st.markdown(f"### {display} 的主要问题")

    issues = item.get("main_issues") or []
    if issues:
        st.markdown("\n".join(f"- {issue}" for issue in issues))
    else:
        st.markdown("- 当前样本内暂无补充说明")

    affected = _join_texts(item.get("affected_cases") or [], "暂无明确样本")
    low_dimensions = _join_texts(item.get("low_dimensions") or [], "暂无明显低分维度")
    high_errors = _join_texts(item.get("high_severity_errors") or [], "暂无高严重度错误")

    st.markdown("#### 涉及样本")
    st.markdown(f"- {affected}")
    st.markdown("#### 低分维度")
    st.markdown(f"- {low_dimensions}")
    st.markdown("#### 高严重度错误")
    st.markdown(f"- {high_errors}")

    detail_rows = item.get("detail_items") or []
    if detail_rows:
        table_rows = [
            {
                "主要问题": str(row.get("主要问题") or ""),
                "对结论的影响": str(row.get("对结论的影响") or ""),
                "使用建议": str(row.get("使用建议") or ""),
            }
            for row in detail_rows
        ]
        st.dataframe(
            pd.DataFrame(table_rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "主要问题": st.column_config.TextColumn("主要问题", width="medium"),
                "对结论的影响": st.column_config.TextColumn("对结论的影响", width="large"),
                "使用建议": st.column_config.TextColumn("使用建议", width="large"),
            },
        )
    else:
        st.markdown("#### 使用建议")
        st.markdown(f"- {item.get('usage_advice') or '请结合评分依据人工复核。'}")


def _join_texts(values, fallback: str) -> str:
    texts = [str(value).strip() for value in values if str(value).strip()]
    return "；".join(texts) if texts else fallback


# --------------------------------------------------------------------------- #
# 04 待确认评分草稿
# --------------------------------------------------------------------------- #
def _render_drafts(draft_rows: list[dict]) -> None:
    render_numbered_section(
        "04",
        "待确认评分",
        "评分草稿未确认前不纳入正式结论。",
    )

    count = len(draft_rows)
    if count == 0:
        st.caption("当前没有待确认评分草稿。")
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
                "answer_text": "",
            }
        )
    return rows


def _num(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
