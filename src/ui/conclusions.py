"""评测结论页面。

结论页只汇总成功的 AI 评分；失败、模拟回退和被排除记录不进入结论。
"""

from __future__ import annotations

from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services import scorer as sc
from src.charts import themed_bar_chart
from src.ui import conclusions_data as cd
from src.ui.components import (
    render_badge,
    render_empty_state,
    render_html,
    render_inline_status,
    render_markdown_detail_panel,
    render_numbered_section,
    render_page_heading,
    render_selection_echo,
)
from src.ui.page_config import get_page_config


def render_conclusions_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    tasks = getattr(base, "tasks", None)

    with st.spinner("正在汇总 AI 评分结果，首次加载可能需要半分钟…"):
        live_scores = cd.load_current_cohort_scores()
        live_responses = cd.load_live_responses()
    ai_scores, excluded_scores = cc.split_live_scores(live_scores)
    model_summaries = cc.build_model_issue_summaries(ai_scores, pd.DataFrame(), tasks)
    answer_rows = cc.build_answer_detail_rows(ai_scores, live_responses)

    config = get_page_config("conclusions")
    render_page_heading(config.title, config.question)
    _render_data_source_notice(live_scores, ai_scores, excluded_scores)

    _render_model_recommendations(model_summaries)
    _render_model_issue_details(model_summaries, answer_rows)


# --------------------------------------------------------------------------- #
# 数据源与导入导出
# --------------------------------------------------------------------------- #
def _render_data_source_notice(
    live_scores: pd.DataFrame,
    ai_scores: pd.DataFrame,
    excluded_scores: pd.DataFrame,
) -> None:
    summary = cc.summarize_runtime_scores(live_scores)
    counts = cc.summarize_formal(pd.DataFrame(), ai_scores)
    models = int(counts["model_count"])
    cases = int(counts.get("case_count", 0))
    coverage = f"（{models} 个模型 × {cases} 个样本）" if len(ai_scores) else ""
    source_line = (
        f"当前结论来源：{summary['data_source']}｜"
        f"AI 评分 {len(ai_scores)} 条{coverage}｜"
        f"排除项 {len(excluded_scores)} 条 · "
        "仅代表当前样本范围内的自动评测结果。"
    )
    with st.container(key="conclusion_data_notice"):
        col_text, col_action = st.columns([4.6, 1.0], gap="small")
        with col_text:
            st.caption(source_line)
        with col_action:
            if st.button("数据维护", type="tertiary", key="conclusion_data_maintenance", use_container_width=True):
                _render_score_data_maintenance_dialog()
    if not ds.database_ready():
        st.caption("当前评分数据层不可用。请先在发起评测页运行评测，或通过数据维护导入评分文件。")

    message = st.session_state.get("conclusion_score_io_message")
    if isinstance(message, dict) and message.get("text"):
        level = str(message.get("level") or "info")
        if level == "success":
            st.toast(str(message["text"]))
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
            cd.clear_conclusions_caches()
            st.rerun()

    st.markdown("**演示恢复**")
    st.caption("从仓库中的脱敏演示结果文件恢复 AI 评分，不会删除现有评分。")
    if st.button("从演示结果文件恢复", type="secondary", key="conclusion_restore_demo_scores"):
        result = sc.import_demo_ai_scores(duplicate_action=action_map[duplicate_label])
        _record_score_io_message(result)
        cd.clear_conclusions_caches()
        st.rerun()


def _record_score_io_message(result: dict) -> None:
    level = "success" if result.get("imported_count") or result.get("updated_count") else "warning"
    st.session_state["conclusion_score_io_message"] = {
        "level": level,
        "text": result.get("summary") or "导入已处理。",
    }


# --------------------------------------------------------------------------- #
# 01 模型当前判断
# --------------------------------------------------------------------------- #
def _render_model_recommendations(model_summaries: list[dict]) -> None:
    render_numbered_section(
        "01",
        "模型当前判断",
        "按模型汇总 AI 评分与当前判断。失败评分、模拟回退和被排除记录不进入结论。",
    )

    if not model_summaries:
        render_empty_state("暂无模型判断。请先在发起评测页运行评测。")
        if st.button("去发起评测", key="conclusion_goto_test_run_models", type="secondary"):
            st.session_state.current_page = "test_run"
            st.rerun()
        return

    rows = [_recommendation_row(item) for item in model_summaries]
    st.caption("点击表格任意行选择模型，在下方 02 区查看该模型的使用边界与回答。")
    event = st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="conclusion_model_judgment_table",
        column_config={
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "AI 评分样本数": st.column_config.NumberColumn("AI 评分样本数", width="small"),
            "平均分": st.column_config.NumberColumn("平均分", format="%.1f", width="small"),
            "当前判断": st.column_config.TextColumn("当前判断", width="medium"),
            "主要依据": st.column_config.TextColumn("主要依据", width="large"),
        },
    )
    selected_rows = getattr(getattr(event, "selection", None), "rows", None) or []
    if selected_rows and 0 <= selected_rows[0] < len(model_summaries):
        chosen = model_summaries[selected_rows[0]]
        st.session_state["conclusion_selected_model"] = str(
            chosen.get("display_name") or chosen.get("model_name") or ""
        )
    current_choice = st.session_state.get("conclusion_selected_model")
    if current_choice:
        render_selection_echo(f"已选 {current_choice}", "#fde-model-details", "详情见下方 02 ↓")
    render_html('<div class="mobile-scroll-hint">表格可左右滑动查看完整内容</div>')
    chart_rows = pd.DataFrame(
        {
            "模型": [str(item.get("display_name") or item.get("model_name") or "未标注模型") for item in model_summaries],
            "平均分": [float(item.get("avg_total") or 0) for item in model_summaries],
        }
    )
    themed_bar_chart(chart_rows, x="模型", y="平均分", x_title="模型", y_title="平均分", y_format=".1f")


def _recommendation_row(item: dict) -> dict[str, object]:
    return {
        "模型": str(item.get("display_name") or item.get("model_name") or "未标注模型"),
        "AI 评分样本数": int(item.get("sample_count") or 0),
        "平均分": float(item.get("avg_total") or 0),
        "当前判断": _current_judgment(item),
        "主要依据": _primary_basis(item),
    }


# --------------------------------------------------------------------------- #
# 02 模型回答明细
# --------------------------------------------------------------------------- #
def _render_model_issue_details(
    model_summaries: list[dict],
    answer_rows: list[dict],
) -> None:
    render_html('<a id="fde-model-details"></a>')
    render_numbered_section(
        "02",
        "模型回答明细",
        "点击 01 表格行切换模型，查看该模型在各样本上的回答。",
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
        chosen = st.session_state.get("conclusion_selected_model")
        if chosen in options:
            selected = options[chosen]

    _render_issue_markdown(selected)
    _render_model_answer_details(selected, answer_rows)


def _render_issue_markdown(item: dict) -> None:
    display = str(item.get("display_name") or item.get("model_name") or "未标注模型")
    judgment = _current_judgment(item)
    usage = str(item.get("usage_advice") or "请结合评分依据和业务边界判断。")
    render_html(
        '<div class="model-boundary-line">'
        f"<strong>{escape(display)}</strong>"
        f"{render_badge(judgment, _judgment_tone(judgment))}"
        f'<span class="model-boundary-usage">使用边界：{escape(usage)}</span>'
        "</div>"
    )


def _render_model_answer_details(
    selected_model: dict,
    answer_rows: list[dict],
) -> None:
    model_name = str(selected_model.get("model_name") or "")
    rows = [
        row
        for row in answer_rows
        if str(row.get("model_name") or "") == model_name
    ]
    if not rows:
        st.caption("当前模型暂无可查看的持久化回答。")
        return

    selected_index = st.selectbox(
        "选择样本查看回答",
        options=list(range(len(rows))),
        format_func=lambda index: (
            f"{rows[index]['case_id']}｜{_answer_score_label(rows[index])}"
        ),
        key=f"conclusion_answer_select_{_safe_key(model_name)}",
    )
    row = rows[int(selected_index)]
    answer_text = str(row.get("answer_text") or "").strip()
    render_markdown_detail_panel(
        title=f"{row['case_id']}｜{row['display_name']}",
        meta=f"运行批次：{row['run_id']}",
        markdown_text=(
            f"**模型回答**\n\n{answer_text}"
            if answer_text
            else "**模型回答**\n\n暂无模型回答。"
        ),
    )


def _answer_score_label(row: dict) -> str:
    value = row.get("total_score")
    return "未评分" if value is None else f"{float(value):.0f}分"


def _safe_key(value: object) -> str:
    text = str(value or "")
    return "".join(char if char.isalnum() else "_" for char in text)


def _current_judgment(item: dict) -> str:
    if int(item.get("sample_count") or 0) < 3:
        return "样本不足，暂不形成判断"
    suggestion = str(item.get("current_suggestion") or "暂不形成判断")
    return f"{_judgment_symbol(suggestion)}{suggestion}"


def _judgment_symbol(judgment: str) -> str:
    if "谨慎" in judgment or "不建议" in judgment:
        return "⚠ "
    if "可作为" in judgment:
        return "✓ "
    return ""


def _judgment_tone(judgment: str) -> str:
    if "谨慎" in judgment or "不建议" in judgment:
        return "warning"
    if "可作为" in judgment:
        return "success"
    return "neutral"


def _primary_basis(item: dict) -> str:
    basis = item.get("detail_basis") or []
    if basis:
        return _join_texts(basis[:2], "基于 AI 评分判断")
    return str(item.get("basis_summary") or "基于 AI 评分判断")


def _join_texts(values, fallback: str) -> str:
    texts = [str(value).strip() for value in values if str(value).strip()]
    return "；".join(texts) if texts else fallback
