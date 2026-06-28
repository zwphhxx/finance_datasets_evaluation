from __future__ import annotations

import pandas as pd
import streamlit as st

from src.metrics import (
    get_case_ids,
    get_errors_for_output,
    get_optimization_suggestions_for_case,
    get_preference_pair_details_for_case,
    get_task_by_case_id,
    merge_case_outputs_with_scores,
)
from src.ui.common import has_value, show_model_score, write_list_field, write_text_field
from src.ui.common import PAGE_CONTEXTS
from src.ui.components import (
    render_answer_boundary_panel,
    render_context_summary,
    render_empty_state,
    render_model_answer_card,
    render_page_header,
    render_preference_comparison,
    render_score_badge,
    render_section_title,
    render_status_badge,
)


SCORE_COLUMNS = [
    ("accuracy_score", "专业准确性"),
    ("reasoning_score", "推理与场景适配"),
    ("coverage_score", "风险覆盖"),
    ("evidence_score", "依据可靠性"),
    ("expression_score", "专业表达"),
]


def render_case_detail_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    context = PAGE_CONTEXTS["样板题深度评测"]

    render_page_header("样板题深度评测", context["question"], context["boundary"])
    render_context_summary(context)
    case_ids = get_case_ids(data.tasks)
    if not case_ids:
        render_empty_state("暂无可展示数据")
        return

    selected_case = st.selectbox("选择样板题", case_ids)
    task_rows = get_task_by_case_id(data.tasks, selected_case)
    if task_rows.empty:
        st.warning("未找到该案例的任务信息。")
        return

    task_info = task_rows.iloc[0]
    tabs = st.tabs(["题目与 Gold Answer", "模型回答与评分", "错误与数据补强", "偏好样本"])

    with tabs[0]:
        render_task_basic_info(task_info)
        render_gold_answer(data.gold_answer_map, selected_case)
    with tabs[1]:
        render_model_outputs(data.model_outputs, data.scores, selected_case)
    with tabs[2]:
        render_error_labels(data.model_outputs, data.errors, selected_case)
        render_optimization_suggestions(data.errors, data.optimizations, selected_case)
    with tabs[3]:
        render_preference_pairs(data.preference_pairs, data.model_outputs, selected_case)


def render_task_basic_info(task_info: pd.Series) -> None:
    render_section_title("题目基本信息")
    write_text_field("案例 ID", task_info.get("case_id"))
    write_text_field("领域", task_info.get("domain"))
    write_text_field("场景", task_info.get("scenario"))
    write_text_field("任务类型", task_info.get("task_type"))
    write_text_field("难度", task_info.get("difficulty"))
    write_text_field("问题", task_info.get("question"))
    write_text_field("背景", task_info.get("context"))


def render_gold_answer(gold_answer_map: dict, selected_case: str) -> None:
    render_section_title("Gold Answer")
    gold_answer = gold_answer_map.get(selected_case)
    if not gold_answer:
        render_empty_state("该模块用于展示数据闭环，当前暂无对应记录。")
        return

    render_answer_boundary_panel(
        "标准答案边界",
        [
            ("结论", gold_answer.get("conclusion")),
            ("判断依据", gold_answer.get("basis")),
            ("分析逻辑", gold_answer.get("analysis")),
            ("需核查资料", gold_answer.get("materials_to_check")),
            ("风险边界", gold_answer.get("risk_boundary")),
        ],
    )

    st.markdown("**必须覆盖要点**")
    if gold_answer.get("must_have_points"):
        write_list_field("要点", gold_answer.get("must_have_points"))
    else:
        render_empty_state("暂无必须覆盖要点。")

    st.markdown("**红线错误**")
    if gold_answer.get("red_line_errors"):
        write_list_field("错误", gold_answer.get("red_line_errors"))
    else:
        render_empty_state("暂无红线错误配置。")

    st.markdown("**证据与优化备注**")
    if has_value(gold_answer.get("evidence")):
        write_text_field("证据说明", gold_answer.get("evidence"))
    else:
        render_empty_state("暂无证据说明。")
    if has_value(gold_answer.get("optimization_note")):
        write_text_field("优化备注", gold_answer.get("optimization_note"))
    else:
        render_empty_state("暂无优化备注。")


def render_model_outputs(model_outputs_df, scores_df, selected_case: str) -> None:
    render_section_title("多模型回答")
    merged = merge_case_outputs_with_scores(model_outputs_df, scores_df, selected_case)
    if merged.empty:
        render_empty_state("暂无可展示数据")
        return

    for _, row in merged.iterrows():
        output_label = _display_value(row.get("output_id"), "暂无")
        model_label = _display_value(row.get("model_name"), "未知模型")
        title = f"{model_label} · output_id {output_label}"
        with st.expander(title, expanded=True):
            render_model_answer_card(
                model_label,
                _answer_text(row),
                score=row.get("total_score"),
                review_note=None,
                meta=f"output_id {output_label}",
            )
            st.markdown("**Rubric 评分**")
            show_model_score(row)
            render_score_breakdown(row)
            if has_value(row.get("review_note")):
                write_text_field("扣分说明", row.get("review_note"))
            else:
                render_empty_state("当前模型回答尚无评审说明。")


def render_score_breakdown(row: pd.Series) -> None:
    available_scores = [(column, label) for column, label in SCORE_COLUMNS if has_value(row.get(column))]
    if not available_scores:
        render_empty_state("当前模型回答尚未配置分项评分。")
        return

    cols = st.columns(len(available_scores))
    for col, (column, label) in zip(cols, available_scores):
        with col:
            render_score_badge(row.get(column))
            st.caption(label)


def render_error_labels(model_outputs_df, error_df, selected_case: str) -> None:
    render_section_title("错误标签")
    outputs = model_outputs_df[model_outputs_df["case_id"] == selected_case] if "case_id" in model_outputs_df else pd.DataFrame()
    if outputs.empty:
        render_empty_state("暂无可展示数据")
        return

    for _, output in outputs.iterrows():
        raw_output_id = output.get("output_id")
        output_label = _display_value(raw_output_id, "暂无")
        model_name = _display_value(output.get("model_name"), "未知模型")
        errors = get_errors_for_output(error_df, raw_output_id)
        with st.expander(f"{model_name} · output_id {output_label}", expanded=not errors.empty):
            if errors.empty:
                render_empty_state("当前回答暂无错误标签。")
                continue
            for _, error in errors.iterrows():
                write_text_field("错误类型", error.get("error_type"))
                st.markdown("**严重程度**")
                render_status_badge(error.get("severity", "暂无"), error.get("severity", "neutral"))
                write_text_field("问题描述", error.get("error_description"))
                write_text_field("纠正方向", error.get("correction"))
                st.divider()


def render_optimization_suggestions(error_df, optimization_df, selected_case: str) -> None:
    render_section_title("数据补强建议")
    suggestions = get_optimization_suggestions_for_case(error_df, optimization_df, selected_case)
    if suggestions.empty:
        render_empty_state("该模块用于展示数据闭环，当前暂无对应记录。")
        return

    for _, suggestion in suggestions.iterrows():
        title = (
            f"{_display_value(suggestion.get('frequent_error'), '未命名错误')} · "
            f"优先级 {_display_value(suggestion.get('priority'), '暂无')}"
        )
        with st.expander(title, expanded=True):
            write_text_field("典型问题", suggestion.get("typical_problem"))
            write_text_field("可能原因", suggestion.get("likely_cause"))
            write_text_field("数据补强动作", suggestion.get("optimization_action"))
            write_text_field("样本格式", suggestion.get("data_sample_format"))


def render_preference_pairs(preference_pairs_df, model_outputs_df, selected_case: str) -> None:
    render_section_title("偏好样本")
    pairs = get_preference_pair_details_for_case(preference_pairs_df, model_outputs_df, selected_case)
    if pairs.empty:
        render_empty_state("该模块用于展示数据闭环，当前暂无对应记录。")
        return

    for _, pair in pairs.iterrows():
        preferred_output_id = _display_value(pair.get("preferred_output_id"), "暂无")
        rejected_output_id = _display_value(pair.get("rejected_output_id"), "暂无")
        preferred_model = _display_value(pair.get("preferred_model_name"), "未标注模型")
        rejected_model = _display_value(pair.get("rejected_model_name"), "未标注模型")
        title = (
            f"{_display_value(pair.get('pair_id'), '未命名偏好样本')} · "
            f"{_display_value(pair.get('preference_dimension'), '未标注维度')}"
        )
        with st.expander(title, expanded=True):
            write_text_field("偏好维度", pair.get("preference_dimension"))
            write_text_field("偏好理由", pair.get("preference_reason"))
            write_text_field("改进指令", pair.get("improvement_instruction"))
            write_text_field("评审人", pair.get("reviewer"))
            write_text_field("评审状态", pair.get("review_status"))

            render_preference_comparison(
                "偏好回答",
                pair.get("preferred_answer_text"),
                "对照回答",
                pair.get("rejected_answer_text"),
                preferred_meta=f"output_id {preferred_output_id} · {preferred_model}",
                rejected_meta=f"output_id {rejected_output_id} · {rejected_model}",
            )


def _answer_text(row: pd.Series) -> str:
    return _plain_value(row.get("answer_text") or row.get("answer"), "暂无回答内容。")


def _plain_value(value, fallback: str) -> str:
    return value if has_value(value) else fallback


def _display_value(value, fallback: str) -> str:
    if not has_value(value):
        return fallback
    return str(value)
