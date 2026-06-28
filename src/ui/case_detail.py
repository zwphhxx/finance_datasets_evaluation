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


SCORE_COLUMNS = [
    ("accuracy_score", "专业准确性"),
    ("reasoning_score", "推理与场景适配"),
    ("coverage_score", "风险覆盖"),
    ("evidence_score", "依据可靠性"),
    ("expression_score", "专业表达"),
]


def render_case_detail_page(data_bundle: dict) -> None:
    data = data_bundle["data"]

    st.header("单题详情")
    case_ids = get_case_ids(data.tasks)
    if not case_ids:
        st.info("暂无任务数据，无法展示单题详情。")
        return

    selected_case = st.selectbox("选择案例 ID", case_ids)
    task_rows = get_task_by_case_id(data.tasks, selected_case)
    if task_rows.empty:
        st.warning("未找到该案例的任务信息。")
        return

    task_info = task_rows.iloc[0]
    tabs = st.tabs(["题目与 Gold Answer", "模型回答与评分", "错误与优化建议", "Preference Pair"])

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
    st.subheader("题目基本信息")
    write_text_field("案例 ID", task_info.get("case_id"))
    write_text_field("领域", task_info.get("domain"))
    write_text_field("场景", task_info.get("scenario"))
    write_text_field("任务类型", task_info.get("task_type"))
    write_text_field("难度", task_info.get("difficulty"))
    write_text_field("问题", task_info.get("question"))
    write_text_field("背景", task_info.get("context"))


def render_gold_answer(gold_answer_map: dict, selected_case: str) -> None:
    st.subheader("Gold Answer")
    gold_answer = gold_answer_map.get(selected_case)
    if not gold_answer:
        st.info("该题暂未配置 Gold Answer，不影响查看模型回答，但无法展示标准答案对照。")
        return

    st.markdown("**标准答案**")
    write_text_field("结论", gold_answer.get("conclusion"))
    write_text_field("判断依据", gold_answer.get("basis"))
    write_text_field("分析逻辑", gold_answer.get("analysis"))
    write_text_field("需核查资料", gold_answer.get("materials_to_check"))
    write_text_field("风险边界", gold_answer.get("risk_boundary"))

    st.markdown("**必须覆盖要点**")
    if gold_answer.get("must_have_points"):
        write_list_field("要点", gold_answer.get("must_have_points"))
    else:
        st.info("暂无必须覆盖要点。")

    st.markdown("**红线错误**")
    if gold_answer.get("red_line_errors"):
        write_list_field("错误", gold_answer.get("red_line_errors"))
    else:
        st.info("暂无红线错误配置。")

    st.markdown("**证据与优化备注**")
    if has_value(gold_answer.get("evidence")):
        write_text_field("证据说明", gold_answer.get("evidence"))
    else:
        st.info("暂无证据说明。")
    if has_value(gold_answer.get("optimization_note")):
        write_text_field("优化备注", gold_answer.get("optimization_note"))
    else:
        st.info("暂无优化备注。")


def render_model_outputs(model_outputs_df, scores_df, selected_case: str) -> None:
    st.subheader("多模型回答")
    merged = merge_case_outputs_with_scores(model_outputs_df, scores_df, selected_case)
    if merged.empty:
        st.info("该题暂无模型回答。")
        return

    for _, row in merged.iterrows():
        title = f"{row.get('model_name', '未知模型')} · output_id {row.get('output_id', '暂无')}"
        with st.expander(title, expanded=True):
            st.markdown("**回答内容**")
            st.write(_answer_text(row))
            st.markdown("**Rubric 评分**")
            show_model_score(row)
            render_score_breakdown(row)
            if has_value(row.get("review_note")):
                write_text_field("扣分说明", row.get("review_note"))
            else:
                st.info("当前模型回答尚无评审说明。")


def render_score_breakdown(row: pd.Series) -> None:
    available_scores = [(column, label) for column, label in SCORE_COLUMNS if has_value(row.get(column))]
    if not available_scores:
        st.info("当前模型回答尚未配置分项评分。")
        return

    cols = st.columns(len(available_scores))
    for col, (column, label) in zip(cols, available_scores):
        col.metric(label, row.get(column))


def render_error_labels(model_outputs_df, error_df, selected_case: str) -> None:
    st.subheader("错误标签")
    outputs = model_outputs_df[model_outputs_df["case_id"] == selected_case] if "case_id" in model_outputs_df else pd.DataFrame()
    if outputs.empty:
        st.info("该题暂无模型回答，无法展示错误标签。")
        return

    for _, output in outputs.iterrows():
        output_id = output.get("output_id")
        model_name = output.get("model_name", "未知模型")
        errors = get_errors_for_output(error_df, output_id)
        with st.expander(f"{model_name} · output_id {output_id}", expanded=not errors.empty):
            if errors.empty:
                st.info("当前回答暂无错误标签。")
                continue
            for _, error in errors.iterrows():
                write_text_field("错误类型", error.get("error_type"))
                write_text_field("严重程度", error.get("severity"))
                write_text_field("问题描述", error.get("error_description"))
                write_text_field("纠正方向", error.get("correction"))
                st.divider()


def render_optimization_suggestions(error_df, optimization_df, selected_case: str) -> None:
    st.subheader("数据优化建议")
    suggestions = get_optimization_suggestions_for_case(error_df, optimization_df, selected_case)
    if suggestions.empty:
        st.info("暂无对应优化建议。")
        return

    for _, suggestion in suggestions.iterrows():
        title = f"{suggestion.get('frequent_error', '未命名错误')} · 优先级 {suggestion.get('priority', '暂无')}"
        with st.expander(title, expanded=True):
            write_text_field("典型问题", suggestion.get("typical_problem"))
            write_text_field("可能原因", suggestion.get("likely_cause"))
            write_text_field("优化动作", suggestion.get("optimization_action"))
            write_text_field("样本格式", suggestion.get("data_sample_format"))


def render_preference_pairs(preference_pairs_df, model_outputs_df, selected_case: str) -> None:
    st.subheader("Preference Pair")
    pairs = get_preference_pair_details_for_case(preference_pairs_df, model_outputs_df, selected_case)
    if pairs.empty:
        st.info("该题暂无偏好样本。")
        return

    for _, pair in pairs.iterrows():
        title = f"{pair.get('pair_id', '未命名偏好样本')} · {pair.get('preference_dimension', '未标注维度')}"
        with st.expander(title, expanded=True):
            write_text_field("偏好维度", pair.get("preference_dimension"))
            write_text_field("偏好理由", pair.get("preference_reason"))
            write_text_field("改进指令", pair.get("improvement_instruction"))
            write_text_field("评审人", pair.get("reviewer"))
            write_text_field("评审状态", pair.get("review_status"))

            preferred_col, rejected_col = st.columns(2)
            with preferred_col:
                st.markdown("**Preferred**")
                write_text_field("output_id", pair.get("preferred_output_id"))
                write_text_field("模型", pair.get("preferred_model_name"))
                st.write(_plain_value(pair.get("preferred_answer_text"), "暂无回答内容。"))
            with rejected_col:
                st.markdown("**Rejected**")
                write_text_field("output_id", pair.get("rejected_output_id"))
                write_text_field("模型", pair.get("rejected_model_name"))
                st.write(_plain_value(pair.get("rejected_answer_text"), "暂无回答内容。"))


def _answer_text(row: pd.Series) -> str:
    return _plain_value(row.get("answer_text") or row.get("answer"), "暂无回答内容。")


def _plain_value(value, fallback: str) -> str:
    return value if has_value(value) else fallback
