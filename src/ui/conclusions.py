"""评测结论页面。

Replaces evaluation_conclusions, merges capabilities from model_diagnosis, model_boundary, overview.
- 已沉淀结论 + 已复核归档结论计入正式结论。
- 待复核草稿不进入正式结论。
- 展示当前样本内的模型均值与使用边界。
"""

from __future__ import annotations

import streamlit as st

from app.services import conclusions as cc
from app.services import eval_state
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_compact_hero,
    render_key_value_list,
    render_numbered_section,
    render_text_block,
)


def render_conclusions_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    seed_scores = getattr(base, "scores", None)
    seed_errors = getattr(base, "errors", None)

    live_scores = cc.load_live_scores()
    confirmed_live, pending_live = cc.split_live_scores(live_scores)
    responses = cc.load_live_responses()

    config = get_page_config("conclusions")
    render_compact_hero(
        eyebrow="FinDueEval",
        title=config.title,
        question=config.question,
    )

    _render_formal_conclusions(seed_scores, confirmed_live, seed_errors)
    _render_model_boundaries(seed_scores, confirmed_live, seed_errors)
    _render_drafts(pending_live, responses)


# --------------------------------------------------------------------------- #
# 01 正式评测结论
# --------------------------------------------------------------------------- #
def _render_formal_conclusions(seed_scores, confirmed_live, seed_errors) -> None:
    render_numbered_section(
        "01",
        "正式评测结论",
        "只统计已沉淀结论与已复核归档结论，不含待复核草稿。",
    )

    summary = cc.summarize_formal(seed_scores, confirmed_live)
    if summary["total_rows"] == 0:
        render_text_block(
            "暂无正式结论",
            "当前没有可纳入正式结论的评分。运行一次真实评测并经人工复核归档后，结论会在这里汇总。",
        )
        return

    avg_text = f"{summary['avg_total']:.1f}" if summary['avg_total'] is not None else "—"
    st.markdown(
        f"纳入 **{summary['model_count']}** 个模型 · 平均总分 **{avg_text}** · "
        f"已沉淀评分 **{summary['seed_rows']}** 条 · 已复核归档 **{summary['confirmed_rows']}** 条"
    )

    conclusions = cc.build_formal_conclusions(seed_scores, confirmed_live)
    for item in conclusions:
        st.markdown(
            f"- **{item['display_name']}**：平均总分 {item['avg_total']:.1f}，"
            f"样本 {item['sample_count']} 条"
        )

    combined = cc.combine_formal_scores(seed_scores, confirmed_live)
    all_notes = [note for item in conclusions for note in item.get("review_notes", [])]
    issues = cc.summarize_frequent_issues(combined, seed_errors, all_notes)
    if issues:
        with st.expander("高频问题归纳", expanded=False):
            for issue in issues:
                st.markdown(f"- {issue}")


# --------------------------------------------------------------------------- #
# 02 模型使用边界
# --------------------------------------------------------------------------- #
def _render_model_boundaries(seed_scores, confirmed_live, seed_errors) -> None:
    render_numbered_section(
        "02",
        "模型使用边界",
        "按风险等级、能力下限与红线错误，将模型归入三类使用边界。",
    )

    combined = cc.combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty or "total_score" not in combined.columns:
        render_text_block(
            "暂无边界数据",
            "运行评测并经人工复核后，此处按当前样本生成三类使用边界。",
        )
        return

    direct_count = 0
    review_count = 0
    not_direct_count = 0
    direct_models = []
    review_models = []
    not_direct_models = []

    for model_name, group in combined.groupby("model_name"):
        avg = float(group["total_score"].mean())
        if avg >= 85:
            direct_count += 1
            direct_models.append((model_name, avg))
        elif avg >= 60:
            review_count += 1
            review_models.append((model_name, avg))
        else:
            not_direct_count += 1
            not_direct_models.append((model_name, avg))

    boundaries = [
        ("可直接使用", direct_models, "总分 ≥85，当前样本内表现稳健。"),
        ("必须人工复核", review_models, "总分 60–85，存在维度短板。"),
        ("不可直接使用", not_direct_models, "总分 <60 或触发红线。"),
    ]

    rows = []
    for title, models, desc in boundaries:
        if not models:
            detail = "当前样本中暂无归入此类的模型。"
        else:
            model_list = "、".join(f"{m}（{a:.1f}）" for m, a in models[:3])
            detail = f"{model_list} 等 {len(models)} 个模型。{desc}"
        rows.append((title, detail))
    render_key_value_list(rows)

    st.caption(
        "红线错误一票否决；边界结论来自当前样本内观察，不代表模型整体能力。"
    )


# --------------------------------------------------------------------------- #
# 03 草稿评测（待复核）
# --------------------------------------------------------------------------- #
def _render_drafts(pending_live, responses) -> None:
    render_numbered_section(
        "03",
        "草稿评测（待复核）",
        "现场新增评测先进入草稿，未进入正式结论；经人工复核确认后才会归档计入。",
    )

    draft_rows = cc.build_draft_rows(pending_live, responses)
    if not draft_rows:
        draft_rows = _session_draft_rows()

    count = len(draft_rows)
    if count == 0:
        st.caption("当前没有待复核的现场评分。发起一次真实评测并评分后，草稿会显示在这里。")
        return

    st.markdown(f"当前有 **{count}** 条待复核草稿。")
    if st.button("去评测复核 →", type="primary", key="conc_to_review"):
        st.session_state.current_page = "review"
        st.rerun()


# --------------------------------------------------------------------------- #
# Backward-compatible helpers
# --------------------------------------------------------------------------- #
def _session_draft_rows() -> list[dict]:
    """数据库不可用时，从会话内最近一次评分构造草稿行（仅展示，不能归档）。"""
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
                "display_name": cc.display_model_name(getattr(outcome, "eval_model", "")),
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
