"""评测结论页（PR-B）。

把评测结果分成三层呈现，并严格区分「可计入正式结论」与「仅为草稿」：

  - 正式评测结论（首屏）：只统计 seed 已有结论 + 已复核归档（confirmed）的 live 结论；
  - 草稿评测（待复核）：现场 live run 产生、review_status 仍为 pending 的评分，明确标注「未进入正式结论」；
  - 人工复核后归档：说明如何修改分数与复核说明、确认后 review_status 置为 confirmed 计入正式结论。

本页定位是「当前专业样本内的可用边界观察」，不是模型排行榜。seed 已有结论默认只读，
新增与复核仅写入 SQLite 运行时数据层；SQLite 不可用时仍可展示 seed 已有结论。
"""

from __future__ import annotations

import streamlit as st

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services import eval_state
from app.services import scorer as sc
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_action_cards,
    render_compact_hero,
    render_context_grid,
    render_info_panel,
    render_metric_card,
    render_numbered_section,
    render_section_title,
    render_status_badge,
    render_status_summary,
)


def _set_page(page_key: str) -> None:
    st.session_state.current_page = page_key


def render_evaluation_conclusions_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    seed_scores = getattr(base, "scores", None)
    seed_errors = getattr(base, "errors", None)

    db_ready = _safe_db_ready()
    live_scores = cc.load_live_scores()
    confirmed_live, pending_live = cc.split_live_scores(live_scores)
    responses = cc.load_live_responses()

    config = get_page_config("evaluation_conclusions")
    render_compact_hero(
        eyebrow="FinDueEval",
        title=config.title,
        question=config.question,
    )
    render_info_panel(
        "本页定位",
        "这是当前专业样本内的“可用边界观察”，不是模型排行榜。正式结论只纳入已人工沉淀的"
        "基准结论与现场已复核归档的结论；现场新增评测先进入草稿，经人工复核确认后才计入正式结论。",
    )

    _render_formal_conclusions(seed_scores, confirmed_live, seed_errors)
    _render_drafts(pending_live, responses, db_ready)
    _render_archive_explainer(db_ready)


# --------------------------------------------------------------------------- #
# 01 正式评测结论
# --------------------------------------------------------------------------- #
def _render_formal_conclusions(seed_scores, confirmed_live, seed_errors) -> None:
    render_numbered_section(
        "01",
        "正式评测结论",
        "只统计 seed 已有结论与已复核归档（confirmed）的现场结论，不含待复核草稿。",
    )

    summary = cc.summarize_formal(seed_scores, confirmed_live)
    if summary["total_rows"] == 0:
        render_info_panel(
            "暂无正式结论",
            "当前没有可纳入正式结论的评分。运行一次真实评测并经人工复核归档后，结论会在这里汇总。",
        )
        return

    # Conclusion cards first (metric cards as narrative cards)
    cols = st.columns(4)
    with cols[0]:
        render_metric_card("纳入模型", summary["model_count"], "参与正式结论的模型数")
    with cols[1]:
        avg = summary["avg_total"]
        render_metric_card("平均总分", f"{avg:.1f}" if avg is not None else "—", "样本内平均，不代表整体能力")
    with cols[2]:
        render_metric_card("已有结论", summary["seed_rows"], "seed 人工沉淀基准")
    with cols[3]:
        render_metric_card("已复核归档", summary["confirmed_rows"], "现场复核后计入")

    # Evidence: per-model conclusion cards
    conclusions = cc.build_formal_conclusions(seed_scores, confirmed_live)
    for item in conclusions:
        _render_model_conclusion(item)

    # Evidence: frequent issues table
    combined = cc.combine_formal_scores(seed_scores, confirmed_live)
    all_notes = [note for item in conclusions for note in item.get("review_notes", [])]
    issues = cc.summarize_frequent_issues(combined, seed_errors, all_notes)
    render_section_title("高频问题归纳", "由低分维度、错误标签与人工复核说明动态归纳，仅为样本内观察。")
    if issues:
        for issue in issues:
            st.markdown(f"- {issue}")
    else:
        st.caption("当前样本内暂无足以归纳的高频问题。")


def _render_model_conclusion(item: dict) -> None:
    render_section_title(
        f"{item['display_name']} · 平均总分 {item['avg_total']:.1f}",
        f"样本 {item['sample_count']} 条（已有结论 {item['seed_count']} · 已复核 {item['confirmed_count']}）。",
    )
    grid_items: list[tuple[str, str]] = [("平均总分", f"{item['avg_total']:.1f}")]
    for field in cc.DIMENSION_FIELDS:
        label = cc.DIMENSION_LABELS.get(field, field)
        value = item["dimensions"].get(field)
        grid_items.append((label, f"{value:.1f}" if value is not None else "暂无"))
    render_context_grid(grid_items)

    notes = item.get("review_notes") or []
    if notes:
        st.caption("人工点评摘要：" + "；".join(notes[:3]))
    else:
        st.caption("暂无人工点评说明。")
    st.caption(
        "边界意识与红线表现已并入“风险覆盖 / 专业表达”维度与高频问题归纳，单独的硬性红线在红线评测台呈现。"
    )


# --------------------------------------------------------------------------- #
# 02 草稿评测（待复核）
# --------------------------------------------------------------------------- #
def _render_drafts(pending_live, responses, db_ready: bool) -> None:
    render_numbered_section(
        "02",
        "草稿评测（待复核）",
        "现场新增评测先进入草稿，未进入正式结论；经人工复核确认后才会归档计入。",
    )

    draft_rows = cc.build_draft_rows(pending_live, responses)
    has_row_ids = bool(draft_rows)
    if not draft_rows:
        # 数据库无 pending 时，回退展示会话内本次评分（仅展示，归档需 SQLite）。
        draft_rows = _session_draft_rows()
        has_row_ids = False

    if not draft_rows:
        if db_ready:
            st.caption("当前没有待复核的现场评分。发起一次真实评测并评分后，草稿会显示在这里。")
        else:
            render_info_panel(
                "尚未初始化 SQLite",
                "初始化 SQLite 运行时数据层后，现场新增评测可在此暂存为草稿并归档；当前仅展示 seed 已有结论。",
            )
        _render_draft_entries()
        return

    render_status_badge("未进入正式结论", "warning")
    for row in draft_rows:
        _render_draft_row(row, db_ready and has_row_ids)
    _render_draft_entries()


def _render_draft_row(row: dict, can_confirm: bool) -> None:
    score_text = f"{row['total_score']:.0f}" if row.get("total_score") is not None else "无建议分"
    title = f"{row['display_name']} · {row['case_id']} · 建议分 {score_text} · {row['review_status']}"
    with st.expander(title, expanded=False):
        dims = [
            (cc.DIMENSION_LABELS.get(field, field),
             f"{value:.0f}" if value is not None else "暂无")
            for field, value in row["dimensions"].items()
        ]
        render_context_grid(dims)
        if row.get("error_code") or row.get("error_message"):
            st.warning(f"调用/评分异常：{row.get('error_code') or ''} {row.get('error_message') or ''}".strip())
        if row.get("review_note"):
            st.caption("裁判复核提示：" + row["review_note"])
        if row.get("answer_text"):
            st.markdown("**模型回答（节选）**")
            st.markdown(row["answer_text"][:600] + ("…" if len(row["answer_text"]) > 600 else ""))
        else:
            st.caption("暂无对应模型回答记录。")

        if can_confirm and row.get("row_id") is not None:
            _render_inline_confirm(row)
        else:
            st.caption("如需复核归档，请在已初始化 SQLite 的环境下，从“可复现实验”或“典型样本拆解”页确认。")


def _render_inline_confirm(row: dict) -> None:
    dimensions = ds.get_rubric_dimensions()
    row_id = int(row["row_id"])
    cols = st.columns(len(dimensions))
    edited: dict[str, int] = {}
    for i, dim in enumerate(dimensions):
        field = dim["field"]
        full_mark = int(dim.get("full_mark") or 0)
        current = row["dimensions"].get(field)
        value = int(current) if current is not None else 0
        edited[field] = cols[i].number_input(
            dim["name"], min_value=0, max_value=full_mark, value=min(value, full_mark),
            step=1, key=f"conc_edit::{row_id}::{field}",
        )
    note = st.text_area("复核说明", value=row.get("review_note", ""), key=f"conc_note::{row_id}")
    if st.button("确认并归档（计入正式结论）", key=f"conc_confirm::{row_id}"):
        if sc.confirm_score_review(row_id, edited, note):
            st.success("已归档为已复核（confirmed），下次进入正式评测结论汇总。")
            st.rerun()
        else:
            st.warning("归档失败：请确认 SQLite 数据层已初始化。")


def _render_draft_entries() -> None:
    render_action_cards([
        ("去典型样本拆解复核 →", "case_detail"),
        ("去可复现实验 / 批量复核 →", "eval_run"),
    ], key_prefix="conc")


# --------------------------------------------------------------------------- #
# 03 人工复核后归档
# --------------------------------------------------------------------------- #
def _render_archive_explainer(db_ready: bool) -> None:
    render_numbered_section("03", "人工复核后归档", "把现场草稿转为正式结论的处理方式。")
    render_info_panel(
        "复核与归档流程",
        "人工可在草稿条目中修改各维度分数与复核说明；点击“确认并归档”后，该条 review_status "
        "变为 confirmed，下次进入正式评测结论汇总。seed 已有结论默认只读，新增与复核结果只写入 "
        "SQLite 运行时数据层，不回写 data/ 下的 seed 文件。",
    )
    if not db_ready:
        st.caption("当前 SQLite 未初始化：仅可浏览 seed 已有结论；初始化后即可归档现场新增评测。")


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


def _safe_db_ready() -> bool:
    try:
        return ds.database_ready()
    except Exception:
        return False
