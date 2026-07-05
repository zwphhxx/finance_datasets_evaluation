"""评测结论页面。

- 已沉淀结论 + 已复核归档结论计入正式结论。
- 待复核草稿不进入正式结论。
- 展示当前样本内的模型均值与审慎使用边界。
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app.services import conclusions as cc
from app.services import eval_state
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_compact_hero,
    render_evidence_panel,
    render_html,
    render_numbered_section,
    render_text_block,
)


def render_conclusions_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    seed_scores = getattr(base, "scores", None)
    seed_errors = getattr(base, "errors", None)
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

    _render_formal_conclusions(seed_scores, confirmed_live, seed_errors)
    _render_model_boundaries(seed_scores, confirmed_live, seed_errors, tasks)
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
def _render_model_boundaries(seed_scores, confirmed_live, seed_errors, tasks) -> None:
    render_numbered_section(
        "02",
        "模型使用边界",
        "综合平均分、红线错误、关键维度短板、高风险任务和样本数量判断。",
    )

    boundaries = cc.build_model_boundaries(seed_scores, confirmed_live, seed_errors, tasks)
    if not boundaries:
        render_text_block(
            "暂无边界数据",
            "运行评测并经人工复核后，此处按当前样本生成三类使用边界。",
        )
        return

    body = ""
    for item in boundaries:
        weakness = _format_weaknesses(item.get("major_weaknesses") or [])
        high_errors = f"{int(item.get('high_severity_count', 0))} 条" if item.get("has_high_severity_error") else "无"
        sample_text = f"{int(item.get('sample_count', 0))} 条"
        if item.get("sample_insufficient"):
            sample_text += "（观察不足）"
        body += (
            "<tr>"
            f"<td><strong>{escape(str(item.get('display_name') or item.get('model_name') or '未标注模型'))}</strong></td>"
            f"<td><span class=\"status-badge status-{escape(str(item.get('boundary_level', 'neutral')))}\">"
            f"{escape(str(item.get('boundary') or '待判断'))}</span></td>"
            f"<td>{float(item.get('avg_total') or 0):.1f}</td>"
            f"<td>{escape(sample_text)}</td>"
            f"<td>{escape(weakness)}</td>"
            f"<td>{escape(high_errors)}</td>"
            f"<td>{escape(str(item.get('basis_summary') or '当前样本内暂无足够判断依据'))}</td>"
            "</tr>"
        )

    render_evidence_panel(
        "边界判断明细",
        (
            '<table class="check-table"><thead><tr>'
            "<th>模型</th><th>边界分类</th><th>平均分</th><th>样本数</th>"
            "<th>主要短板</th><th>高严重度错误</th><th>判断依据摘要</th>"
            f"</tr></thead><tbody>{body}</tbody></table>"
        ),
    )
    render_html(
        '<div class="review-risk-note review-risk-note-muted">'
        "<strong>使用边界</strong>"
        "<span>模型边界不是排行榜；待复核草稿不进入正式结论，结论仅代表当前样本内观察。</span>"
        "</div>"
    )


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
    if st.button("进入评测复核", key="conc_to_review"):
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
