"""评测结论页面。

结论页只汇总成功的 AI 评分；失败、模拟回退和被排除记录不进入结论。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services import scorer as sc
from src.ui.components import (
    render_empty_state,
    render_inline_status,
    render_markdown_detail_panel,
    render_numbered_section,
    render_page_heading,
)
from src.ui.page_config import get_page_config


def render_conclusions_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    tasks = getattr(base, "tasks", None)

    live_scores = cc.load_live_scores()
    ai_scores, excluded_scores = cc.split_live_scores(live_scores)
    model_summaries = cc.build_model_issue_summaries(ai_scores, pd.DataFrame(), tasks)

    config = get_page_config("conclusions")
    render_page_heading(config.title, config.question)
    _render_data_source_notice(live_scores, ai_scores, excluded_scores)

    _render_current_conclusion(ai_scores)
    _render_model_recommendations(model_summaries)
    _render_model_issue_details(model_summaries)


# --------------------------------------------------------------------------- #
# 数据源与导入导出
# --------------------------------------------------------------------------- #
def _render_data_source_notice(
    live_scores: pd.DataFrame,
    ai_scores: pd.DataFrame,
    excluded_scores: pd.DataFrame,
) -> None:
    summary = cc.summarize_runtime_scores(live_scores)
    source_line = (
        f"当前结论来源：{summary['data_source']}｜"
        f"AI 评分 {len(ai_scores)} 条｜"
        f"排除项 {len(excluded_scores)} 条"
    )
    col_text, col_action = st.columns([4.6, 1.0], gap="small")
    with col_text:
        st.caption(source_line)
        st.caption(
            "结论基于当前样本、模型回答和 AI 评分生成，仅代表当前样本范围内的自动评测结果。"
        )
    with col_action:
        if st.button("数据维护", type="secondary", key="conclusion_data_maintenance", use_container_width=True):
            _render_score_data_maintenance_dialog()
    if not ds.database_ready():
        st.caption("当前评分数据层不可用。请先在发起评测页运行评测，或通过数据维护导入评分文件。")

    message = st.session_state.get("conclusion_score_io_message")
    if isinstance(message, dict) and message.get("text"):
        level = str(message.get("level") or "info")
        if level == "success":
            st.success(str(message["text"]))
        elif level == "warning":
            st.warning(str(message["text"]))
        else:
            st.info(str(message["text"]))


@st.dialog("AI 评测结果数据", width="large")
def _render_score_data_maintenance_dialog() -> None:
    st.markdown("**导出**")
    st.caption("导出当前已生成的 AI 评分结果；失败评分和模拟回退不会进入结论。")
    payload = sc.export_score_payload(include_pending=False)
    export_text = sc.serialize_score_export_payload(payload)
    file_name = f"ai_scores_{datetime.now():%Y%m%d_%H%M}.json"
    st.download_button(
        "导出 AI 评测结果",
        data=export_text,
        file_name=file_name,
        mime="application/json",
        type="secondary",
        disabled=not bool(payload.get("records")),
        key="conclusion_export_scores",
    )

    st.markdown("**导入**")
    st.caption("仅导入本项目导出的评分 JSON；重复记录按 score_run_id、case_id 和 eval_model 判断。")
    uploaded = st.file_uploader(
        "上传评分 JSON 文件",
        type=["json"],
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
        st.caption("可上传 AI 评测结果导出文件，或使用下方脱敏演示结果文件恢复。")
    else:
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
        if rows and st.button("导入评分文件", type="primary", key="conclusion_import_scores_submit"):
            result = sc.import_score_rows(rows, duplicate_action=action_map[duplicate_label])
            _record_score_io_message(result)
            st.rerun()

    st.markdown("**演示恢复**")
    st.caption("从仓库中的脱敏演示结果文件恢复 AI 评分，不会删除现有评分。")
    if st.button("从演示结果文件恢复", type="secondary", key="conclusion_restore_demo_scores"):
        result = sc.import_demo_ai_scores(duplicate_action=action_map[duplicate_label])
        _record_score_io_message(result)
        st.rerun()


def _record_score_io_message(result: dict) -> None:
    level = "success" if result.get("imported_count") or result.get("updated_count") else "warning"
    st.session_state["conclusion_score_io_message"] = {
        "level": level,
        "text": result.get("summary") or "导入已处理。",
    }


# --------------------------------------------------------------------------- #
# 01 当前结论
# --------------------------------------------------------------------------- #
def _render_current_conclusion(ai_scores: pd.DataFrame) -> None:
    render_numbered_section(
        "01",
        "当前结论",
        "基于当前样本、模型回答和 AI 评分汇总结果。",
    )

    empty_seed = pd.DataFrame()
    summary = cc.summarize_formal(empty_seed, ai_scores)
    if summary["total_rows"] == 0:
        render_empty_state("暂无 AI 评分结果。请先在发起评测页运行评测。")
        st.caption(
            "结论基于当前样本、模型回答和 AI 评分生成，仅代表当前样本范围内的自动评测结果，"
            "不代表模型整体能力或采购建议。"
        )
        return

    ai_score_rows = int(summary.get("ai_score_rows", summary.get("confirmed_rows", 0)))
    models = int(summary["model_count"])
    cases = int(summary.get("case_count", 0))
    sample_note = "当前样本数较少，仅作为当前样本内观察。" if cases < 3 else "结论仅代表当前样本范围内观察。"
    st.markdown(
        f"已生成 AI 评分 **{ai_score_rows}** 条，覆盖 **{models}** 个模型、**{cases}** 个样本。"
    )
    st.caption(
        f"{sample_note} 失败评分、模拟回退和被排除记录不进入评测结论。"
    )


# --------------------------------------------------------------------------- #
# 02 模型当前判断
# --------------------------------------------------------------------------- #
def _render_model_recommendations(model_summaries: list[dict]) -> None:
    render_numbered_section(
        "02",
        "模型当前判断",
        "按模型汇总 AI 评分样本、平均分、当前判断和主要依据。",
    )

    if not model_summaries:
        render_empty_state("暂无模型判断。请先在发起评测页运行评测。")
        return

    rows = [_recommendation_row(item) for item in model_summaries]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "AI 评分样本数": st.column_config.NumberColumn("AI 评分样本数", width="small"),
            "平均分": st.column_config.NumberColumn("平均分", format="%.1f", width="small"),
            "当前判断": st.column_config.TextColumn("当前判断", width="medium"),
            "主要依据": st.column_config.TextColumn("主要依据", width="large"),
        },
    )
    st.caption("当前判断只说明模型在当前样本范围内的使用边界。")


def _recommendation_row(item: dict) -> dict[str, object]:
    return {
        "模型": str(item.get("display_name") or item.get("model_name") or "未标注模型"),
        "AI 评分样本数": int(item.get("sample_count") or 0),
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
        "展示当前选中模型的判断依据和使用边界。",
    )

    if not model_summaries:
        st.caption("暂无模型详情。请先生成 AI 评分。")
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
    basis_items = item.get("detail_basis") or item.get("main_issues") or []
    basis_markdown = "\n".join(f"- {text}" for text in basis_items[:4]) or "- 当前样本内暂无补充说明"
    markdown = "\n\n".join([
        "**当前判断**",
        _current_judgment(item),
        "**主要依据**",
        basis_markdown,
        "**使用边界**",
        str(item.get("usage_advice") or "请结合评分依据和业务边界判断。"),
    ])
    meta = f"模型 ID：{model_id}" if model_id and model_id != display else None
    render_markdown_detail_panel(display, markdown, meta=meta)


def _current_judgment(item: dict) -> str:
    if int(item.get("sample_count") or 0) < 3:
        return "样本不足，暂不形成判断"
    return str(item.get("current_suggestion") or "暂不形成判断")


def _primary_basis(item: dict) -> str:
    basis = item.get("detail_basis") or []
    if basis:
        return _join_texts(basis[:2], "基于 AI 评分判断")
    return str(item.get("basis_summary") or "基于 AI 评分判断")


def _join_texts(values, fallback: str) -> str:
    texts = [str(value).strip() for value in values if str(value).strip()]
    return "；".join(texts) if texts else fallback
