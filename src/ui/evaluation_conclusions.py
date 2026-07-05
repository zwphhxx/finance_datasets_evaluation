"""评测结论页（PR-B）。

把评测结果分成三层呈现，并严格区分「可计入正式结论」与「仅为草稿」：

  - 正式评测结论（首屏）：只统计已确认（confirmed）的 live 结论；
  - 评分草稿（待确认）：现场 live run 产生、review_status 仍为 pending 的评分，明确标注「未进入正式结论」；
  - 评分确认：说明如何修改分数与复核说明、确认后 review_status 置为 confirmed 计入正式结论。

本页定位是「当前专业样本内的可用边界观察」，不是模型排行榜。seed 已有结论默认只读，
新增与复核仅写入 SQLite 运行时数据层；SQLite 不可用时仍可展示 seed 已有结论。

PR-LOGIC1: 合并 红线评测台、模型能力指纹、模型边界报告 的内容到本页。
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
    render_conclusion_list,
    render_context_grid,
    render_editorial_list,
    render_empty_state,
    render_evidence_block,
    render_info_panel,
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

    _render_formal_conclusions(seed_scores, confirmed_live, seed_errors)
    _render_model_boundaries(seed_scores, confirmed_live, seed_errors)
    _render_model_capability_fingerprint(seed_scores, confirmed_live, seed_errors)
    _render_drafts(pending_live, responses, db_ready)
    _render_archive_explainer(db_ready)


# --------------------------------------------------------------------------- #
# 01 正式评测结论
# --------------------------------------------------------------------------- #
def _render_formal_conclusions(seed_scores, confirmed_live, seed_errors) -> None:
    render_numbered_section(
        "01",
        "正式评测结论",
        "只统计已确认（confirmed）的现场结论，不含待确认评分草稿。",
    )

    summary = cc.summarize_formal(seed_scores, confirmed_live)
    if summary["total_rows"] == 0:
        render_info_panel(
            "暂无正式结论",
            "当前没有可纳入正式结论的评分。运行一次真实评测并经人工确认后，结论会在这里汇总。",
        )
        return

    # Status summary as inline pills, not metric cards
    render_status_summary([
        ("纳入模型", str(summary["model_count"]), "accent"),
        ("平均总分", f"{summary['avg_total']:.1f}" if summary['avg_total'] is not None else "—", "neutral"),
        ("示例基准", str(summary["seed_rows"]), "muted"),
        ("已确认", str(summary["confirmed_rows"]), "success"),
    ])

    # Editorial list: model + one-sentence judgment + small dimension bars
    conclusions = cc.build_formal_conclusions(seed_scores, confirmed_live)
    editorial_items = []
    for item in conclusions:
        name = item['display_name']
        avg = item['avg_total']
        bar_count = min(5, max(0, int(avg / 20))) if avg is not None else 0
        judgment = f"平均总分 {avg:.1f}，样本 {item['sample_count']} 条"
        editorial_items.append((name, judgment, bar_count))
    render_editorial_list(editorial_items)

    # Evidence: frequent issues sink below
    combined = cc.combine_formal_scores(seed_scores, confirmed_live)
    all_notes = [note for item in conclusions for note in item.get("review_notes", [])]
    issues = cc.summarize_frequent_issues(combined, seed_errors, all_notes)
    if issues:
        with st.expander("高频问题归纳（支撑数据）", expanded=False):
            for issue in issues:
                st.markdown(f"- {issue}")
    else:
        st.caption("当前样本内暂无足以归纳的高频问题。")


# --------------------------------------------------------------------------- #
# 02 模型使用边界（合并自 红线评测台 + 模型边界报告）
# --------------------------------------------------------------------------- #
def _render_model_boundaries(seed_scores, confirmed_live, seed_errors) -> None:
    render_numbered_section(
        "02",
        "模型使用边界",
        "按风险等级、能力下限与红线错误，将模型归入三类使用边界。",
    )

    combined = cc.combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty or "total_score" not in combined.columns:
        render_info_panel(
            "暂无边界数据",
            "运行评测并经人工复核后，此处按当前样本生成三类使用边界。",
        )
        return

    # Three-tier boundary classification
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
        ("可作为初稿参考", "success", direct_count, direct_models, "总分 ≥85，当前样本内表现稳健，仍需结合业务材料确认。"),
        ("必须人工复核", "warning", review_count, review_models, "总分 60–85，存在维度短板，需人工复核后使用。"),
        ("不可作为依据", "danger", not_direct_count, not_direct_models, "总分 <60 或触发红线，不应作为判断依据。"),
    ]

    for title, level, count, models, desc in boundaries:
        if count == 0:
            detail = "当前样本中暂无归入此类的模型。"
        else:
            model_list = "、".join(f"{m}（{a:.1f}）" for m, a in models[:3])
            detail = f"{model_list} 等 {count} 个模型。{desc}"
        render_info_panel(f"{title} ({count})", detail)

    st.caption("红线错误一票否决：触发高严重度红线错误的模型不计入「可作为初稿参考」。边界结论来自当前样本内观察，不代表模型整体能力。")


# --------------------------------------------------------------------------- #
# 03 模型能力指纹（合并自 模型能力指纹）
# --------------------------------------------------------------------------- #
def _render_model_capability_fingerprint(seed_scores, confirmed_live, seed_errors) -> None:
    render_numbered_section(
        "03",
        "模型能力指纹",
        "各模型在当前样本内的强项、短板与频繁弱点。",
    )

    combined = cc.combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty or "model_name" not in combined.columns:
        render_info_panel(
            "暂无指纹数据",
            "运行评测并经人工复核后，此处生成各模型能力指纹。",
        )
        return

    from src.metrics import get_dimension_gap_ranking, get_model_dimension_scores

    dimension_scores = get_model_dimension_scores(combined)
    if not dimension_scores.empty:
        st.caption("各维度达成率（按模型分组）")
        for model_name, group in dimension_scores.groupby("model_name"):
            with st.expander(f"{model_name} 维度详情", expanded=False):
                for _, row in group.iterrows():
                    dim = str(row["dimension"])
                    score = float(row["score"])
                    st.markdown(f"- {dim}：{score:.1f}")

    # Weakness summary
    gap_ranking = get_dimension_gap_ranking(combined)
    if not gap_ranking.empty:
        weakest = gap_ranking.iloc[0]
        st.caption(
            f"当前样本内最弱维度：{weakest['dimension']}（达成率约 {float(weakest['attainment']):.0%}）"
        )

    st.caption("上述均为当前评测样本内观察，样本量有限，不构成绝对排名或采购建议。")


# --------------------------------------------------------------------------- #
# 04 草稿评测（待复核）
# --------------------------------------------------------------------------- #
def _render_drafts(pending_live, responses, db_ready: bool) -> None:
    render_numbered_section(
        "04",
        "评分草稿（待确认）",
        "现场新增评测先进入草稿，未进入正式结论；经人工确认后才会纳入正式结论。",
    )

    draft_rows = cc.build_draft_rows(pending_live, responses)
    has_row_ids = bool(draft_rows)
    if not draft_rows:
        # 数据库无 pending 时，回退展示会话内本次评分（仅展示，确认需 SQLite）。
        draft_rows = _session_draft_rows()
        has_row_ids = False

    if not draft_rows:
        if db_ready:
            st.caption("当前没有待确认的现场评分。发起一次真实评测并评分后，草稿会显示在这里。")
        else:
            render_info_panel(
                "尚未初始化 SQLite",
                "初始化 SQLite 运行时数据层后，现场新增评测可在此暂存为草稿并确认生效；当前仅展示示例数据。",
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
            st.caption("如需确认生效，请在已初始化 SQLite 的环境下，从「评分确认」页确认。")


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
    if st.button("确认生效（纳入正式结论）", key=f"conc_confirm::{row_id}"):
        if sc.confirm_score_review(row_id, edited, note):
            st.success("已确认（confirmed），下次进入正式评测结论汇总。")
            st.rerun()
        else:
            st.warning("确认失败：请确认 SQLite 数据层已初始化。")


def _render_draft_entries() -> None:
    render_action_cards([
        ("去评测复核 →", "case_detail"),
        ("去发起评测 / 批量确认 →", "eval_run"),
    ], key_prefix="conc")


# --------------------------------------------------------------------------- #
# 05 评分确认
# --------------------------------------------------------------------------- #
def _render_archive_explainer(db_ready: bool) -> None:
    render_numbered_section("05", "评分确认", "把现场草稿转为正式结论的处理方式。")
    render_info_panel(
        "确认流程",
        "人工可在草稿条目中修改各维度分数与复核说明；点击「确认生效」后，该条 review_status "
        "变为 confirmed，下次进入正式评测结论汇总。seed 已有结论默认只读，新增与复核结果只写入 "
        "SQLite 运行时数据层，不回写 data/ 下的 seed 文件。",
    )
    if not db_ready:
        st.caption("当前 SQLite 未初始化：仅可浏览 seed 已有结论；初始化后即可确认现场新增评测。")


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
