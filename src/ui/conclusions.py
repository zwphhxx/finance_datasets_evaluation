"""评测结论页面。

- 已沉淀结论 + 已确认评分计入正式结论。
- 待复核草稿不进入正式结论。
- 展示当前样本内的模型均值与审慎使用边界。
"""

from __future__ import annotations

from html import escape

import pandas as pd
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

    _render_formal_conclusions(confirmed_live)
    _render_model_boundaries(confirmed_live, tasks)
    _render_seed_baseline(seed_scores, seed_errors)
    _render_drafts(pending_live, responses)


# --------------------------------------------------------------------------- #
# 01 正式评测结论
# --------------------------------------------------------------------------- #
def _render_formal_conclusions(confirmed_live) -> None:
    render_numbered_section(
        "01",
        "当前真实评测结论",
        "基于已确认评分汇总真实运行结果，不含待复核草稿和示例历史评价。",
    )

    empty_seed = pd.DataFrame()
    summary = cc.summarize_formal(empty_seed, confirmed_live)
    if summary["total_rows"] == 0:
        render_text_block(
            "当前尚无真实模型评测结论",
            "请先在发起测试页选择模型并运行，评分草稿经人工确认归档后，结论会在这里汇总。",
        )
        return

    avg_text = f"{summary['avg_total']:.1f}" if summary['avg_total'] is not None else "—"
    st.markdown(
        f"纳入 **{summary['model_count']}** 个模型 · 平均总分 **{avg_text}** · "
        f"已确认评分 **{summary['confirmed_rows']}** 条"
    )

    conclusions = cc.build_formal_conclusions(empty_seed, confirmed_live)
    for item in conclusions:
        st.markdown(
            f"- **{item['display_name']}**：平均总分 {item['avg_total']:.1f}，"
            f"样本 {item['sample_count']} 条"
        )

    combined = cc.combine_formal_scores(empty_seed, confirmed_live)
    all_notes = [note for item in conclusions for note in item.get("review_notes", [])]
    issues = cc.summarize_frequent_issues(combined, pd.DataFrame(), all_notes)
    if issues:
        with st.expander("高频问题归纳", expanded=False):
            for issue in issues:
                st.markdown(f"- {issue}")


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
            "当前尚无真实模型评测结论。请先在发起测试页选择模型并运行，经人工确认归档后再查看边界。",
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


def _render_seed_baseline(seed_scores, seed_errors) -> None:
    render_numbered_section(
        "03",
        "示例历史评价",
        "seed 样例用于演示评分、错误归因和数据优化方法，不代表当前实际选择模型。",
    )
    conclusions = cc.build_formal_conclusions(seed_scores, pd.DataFrame())
    if not conclusions:
        st.caption("暂无示例历史评价。")
        return
    rows = ""
    for item in conclusions:
        rows += (
            "<tr>"
            f"<td><strong>{escape(str(item.get('display_name') or item.get('model_name')))}</strong></td>"
            f"<td>{escape(str(item.get('source_label') or '示例历史评价'))}</td>"
            f"<td>{float(item.get('avg_total') or 0):.1f}</td>"
            f"<td>{int(item.get('sample_count') or 0)} 条</td>"
            "</tr>"
        )
    render_evidence_panel(
        "示例基准",
        (
            '<table class="check-table"><thead><tr>'
            "<th>示例模型</th><th>来源</th><th>平均分</th><th>样本数</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        ),
    )
    issues = cc.summarize_frequent_issues(cc.combine_formal_scores(seed_scores, pd.DataFrame()), seed_errors)
    if issues:
        st.caption("示例历史评价中的高频问题：" + "；".join(issues[:3]))


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
        "04",
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
    if st.button("进入评分确认", key="conc_to_review"):
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
