"""评测结论页面。

- 只汇总已确认评分。
- 待确认草稿不进入正式结论。
- 按模型展示当前判断和待确认评分，不展示示例评价。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services import eval_state
from app.services import scorer as sc
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_empty_state,
    render_inline_status,
    render_numbered_section,
    render_page_heading,
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
    render_page_heading(config.title, config.question)
    _render_data_source_notice(live_scores)

    _render_current_conclusion(confirmed_live, draft_rows)
    _render_model_recommendations(model_summaries)
    _render_model_issue_details(model_summaries)
    _render_drafts(draft_rows)


# --------------------------------------------------------------------------- #
# 数据源与导入导出
# --------------------------------------------------------------------------- #
def _render_data_source_notice(live_scores: pd.DataFrame) -> None:
    summary = cc.summarize_runtime_scores(live_scores)
    st.caption(
        "当前结论来源：运行期 SQLite；seed 文件只作为示例，不进入正式结论。"
        "正式结论仅包含已确认评分；待确认和暂不采用记录不会纳入。"
    )
    st.caption("运行期 SQLite 不随 Git 提交；重新部署或重建数据库后，可通过导入历史评分恢复演示结论。")
    render_inline_status(
        [
            ("数据源", summary["data_source"]),
            ("已确认评分", f"{summary['confirmed']} 条"),
            ("待确认评分", f"{summary['pending']} 条"),
            ("暂不采用", f"{summary['skipped']} 条"),
        ]
    )
    if not ds.database_ready():
        st.caption("当前 SQLite 尚不可用。请先运行发起评测并生成评分草稿，或导入历史评分。")

    message = st.session_state.get("conclusion_score_io_message")
    if isinstance(message, dict) and message.get("text"):
        level = str(message.get("level") or "info")
        if level == "success":
            st.success(str(message["text"]))
        elif level == "warning":
            st.warning(str(message["text"]))
        else:
            st.info(str(message["text"]))

    include_pending = st.checkbox(
        "导出时包含待确认草稿",
        value=False,
        key="conclusion_export_include_pending",
        help="默认只导出已确认评分；勾选后同时导出待确认草稿，暂不采用记录不会导出。",
    )
    payload = sc.export_score_payload(include_pending=include_pending)
    export_text = sc.serialize_score_export_payload(payload)
    file_name = f"confirmed_scores_{datetime.now():%Y%m%d}.json"
    if include_pending:
        file_name = f"confirmed_and_pending_scores_{datetime.now():%Y%m%d}.json"
    col1, col2 = st.columns([1, 1])
    with col1:
        st.download_button(
            "导出已确认评分",
            data=export_text,
            file_name=file_name,
            mime="application/json",
            type="tertiary",
            disabled=not bool(payload.get("rows")),
            key="conclusion_export_scores",
        )
    with col2:
        if st.button("导入历史评分", type="tertiary", key="conclusion_import_scores"):
            _render_import_scores_dialog()


@st.dialog("导入历史评分", width="large")
def _render_import_scores_dialog() -> None:
    st.markdown("仅导入本项目导出的历史评分文件。导入后，已确认评分会进入评测结论。")
    uploaded = st.file_uploader(
        "上传 JSON 或 CSV 文件",
        type=["json", "csv"],
        key="conclusion_import_scores_file",
    )
    duplicate_label = st.radio(
        "重复记录处理",
        ["跳过重复记录", "更新已有记录", "取消导入"],
        horizontal=True,
        key="conclusion_import_duplicate_action",
    )
    action_map = {
        "跳过重复记录": "skip",
        "更新已有记录": "update",
        "取消导入": "cancel",
    }
    if not uploaded:
        st.caption("重复记录按 score_run_id、case_id 和 eval_model 判断。")
        return

    parsed = sc.parse_score_import_content(uploaded.name, uploaded.getvalue())
    rows = parsed.get("rows") or []
    errors = parsed.get("errors") or []
    render_inline_status(
        [
            ("可导入记录", f"{len(rows)} 条"),
            ("校验问题", f"{len(errors)} 条"),
        ]
    )
    if errors:
        st.warning("；".join(str(error) for error in errors[:3]))
    if not rows:
        st.caption("没有可导入的评分记录。")
        return

    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认导入", type="primary", key="conclusion_import_scores_submit", use_container_width=True):
            result = sc.import_score_rows(rows, duplicate_action=action_map[duplicate_label])
            level = "success" if result.get("imported_count") or result.get("updated_count") else "warning"
            st.session_state["conclusion_score_io_message"] = {
                "level": level,
                "text": result.get("summary") or "导入已处理。",
            }
            st.rerun()
    with col2:
        if st.button("取消", type="tertiary", key="conclusion_import_scores_cancel", use_container_width=True):
            st.rerun()


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
        render_empty_state("当前暂无已确认评分。")
        st.markdown(
            "可能原因：\n"
            "- 尚未在评分确认页确认生效；\n"
            "- 当前部署环境的运行期 SQLite 已重建；\n"
            "- 仅存在示例评价或待确认草稿，未进入正式结论。\n\n"
            "请先在“发起评测”页生成评分草稿，并在“评分确认”页确认生效。"
        )
        return

    confirmed = int(summary["confirmed_rows"])
    models = int(summary["model_count"])
    cases = int(summary.get("case_count", 0))
    sample_note = "当前样本数较少，仅作为当前样本内观察。" if cases < 3 else "结论仅代表当前已确认样本内观察。"
    st.markdown(
        f"已确认评分 **{confirmed}** 条，覆盖 **{models}** 个模型、**{cases}** 个样本。"
    )
    st.caption(f"{sample_note} 待确认评分和暂不采用记录未纳入正式结论。")


# --------------------------------------------------------------------------- #
# 02 模型当前判断
# --------------------------------------------------------------------------- #
def _render_model_recommendations(model_summaries: list[dict]) -> None:
    render_numbered_section(
        "02",
        "模型当前判断",
        "按模型汇总已确认样本、平均分、当前判断和主要依据。",
    )

    if not model_summaries:
        render_empty_state("暂无模型判断。完成评分确认后，此处会生成模型当前判断。")
        return

    rows = [_recommendation_row(item) for item in model_summaries]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "已确认样本数": st.column_config.NumberColumn("已确认样本数", width="small"),
            "平均分": st.column_config.NumberColumn("平均分", format="%.1f", width="small"),
            "当前判断": st.column_config.TextColumn("当前判断", width="medium"),
            "主要依据": st.column_config.TextColumn("主要依据", width="large"),
        },
    )
    st.caption("当前判断只说明模型在当前已确认样本内的使用边界。")


def _recommendation_row(item: dict) -> dict[str, object]:
    return {
        "模型": str(item.get("display_name") or item.get("model_name") or "未标注模型"),
        "已确认样本数": int(item.get("sample_count") or 0),
        "平均分": float(item.get("avg_total") or 0),
        "当前判断": _current_judgment(item),
        "主要依据": _primary_basis(item),
    }


# --------------------------------------------------------------------------- #
# 03 模型详情
# --------------------------------------------------------------------------- #
def _render_model_issue_details(model_summaries: list[dict]) -> None:
    render_numbered_section(
        "03",
        "模型详情",
        "只展示当前选中模型的判断依据和后续建议。",
    )

    if not model_summaries:
        st.caption("暂无模型详情。确认评分后再查看。")
        return

    selected = model_summaries[0]
    if len(model_summaries) > 1:
        options = {
            str(item.get("display_name") or item.get("model_name") or "未标注模型"): item
            for item in model_summaries
        }
        label = st.selectbox("选择模型查看详情", list(options.keys()), key="conclusion_model_issue_select")
        selected = options[label]

    _render_issue_markdown(selected)


def _render_issue_markdown(item: dict) -> None:
    display = str(item.get("display_name") or item.get("model_name") or "未标注模型")
    model_id = str(item.get("model_name") or "")
    st.markdown(f"**{display}**")
    if model_id and model_id != display:
        st.caption(f"模型 ID：{model_id}")

    st.markdown("**当前判断**")
    st.markdown(_current_judgment(item))

    st.markdown("**主要依据**")
    basis_items = item.get("detail_basis") or item.get("main_issues") or []
    st.markdown("\n".join(f"- {text}" for text in basis_items[:4]) or "- 当前样本内暂无补充说明")

    st.markdown("**后续建议**")
    st.markdown(item.get("usage_advice") or "请结合评分依据人工复核。")


def _current_judgment(item: dict) -> str:
    if int(item.get("sample_count") or 0) < 3:
        return "样本不足，暂不形成判断"
    return str(item.get("current_suggestion") or "暂不形成判断")


def _primary_basis(item: dict) -> str:
    basis = item.get("detail_basis") or []
    if basis:
        return _join_texts(basis[:2], "基于已确认评分判断")
    return str(item.get("basis_summary") or "基于已确认评分判断")


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
        st.caption("当前没有待确认评分。")
        return

    st.markdown(f"还有 **{count}** 条评分待确认，未纳入正式结论。")
    rows = [_draft_row(row) for row in draft_rows[:3]]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "样本编号": st.column_config.TextColumn("样本编号", width="small"),
                "模型": st.column_config.TextColumn("模型", width="medium"),
                "总分": st.column_config.TextColumn("总分", width="small"),
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
    }


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
