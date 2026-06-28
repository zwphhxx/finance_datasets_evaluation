from __future__ import annotations

import streamlit as st

from src.metrics import get_case_ids, get_errors_for_output, get_task_by_case_id, merge_case_outputs_with_scores
from src.ui.common import show_model_score, write_list_field, write_text_field


def render_gold_answer(gold_answer_map: dict, selected_case: str) -> None:
    st.subheader("Gold Answer")
    ga = gold_answer_map.get(selected_case)
    if not ga:
        st.info("该题暂未配置 Gold Answer，不影响查看模型回答，但无法展示标准答案对照。")
        return

    write_text_field("结论", ga.get("conclusion"))
    write_text_field("判断依据", ga.get("basis"))
    write_text_field("分析逻辑", ga.get("analysis"))
    write_text_field("需核查资料", ga.get("materials_to_check"))
    write_text_field("风险边界", ga.get("risk_boundary"))
    write_list_field("必须覆盖要点", ga.get("must_have_points"))
    write_list_field("红线错误", ga.get("red_line_errors"))


def render_model_outputs(model_outputs_df, scores_df, error_df, selected_case: str) -> None:
    st.subheader("模型回答与评分")
    merged = merge_case_outputs_with_scores(model_outputs_df, scores_df, selected_case)
    if merged.empty:
        st.info("该题暂无模型回答。")
        return

    for _, row in merged.iterrows():
        st.write(f"### {row['model_name']}")
        st.write(row["answer_text"])
        show_model_score(row)

        errors = get_errors_for_output(error_df, row["output_id"])
        if not errors.empty:
            st.write("**错误标签：**")
            for _, error in errors.iterrows():
                st.write(
                    f"- [{error['error_type']} - {error['severity']}] {error['error_description']} "
                    f"=> **纠正:** {error['correction']}；**优化:** {error['optimization_action']}"
                )
        else:
            st.write("**错误标签：** 该题暂无错误标签。")


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
    st.subheader("题目与背景")
    write_text_field("领域", task_info.get("domain"))
    write_text_field("场景", task_info.get("scenario"))
    write_text_field("难度", task_info.get("difficulty"))
    write_text_field("问题", task_info.get("question"))
    write_text_field("背景", task_info.get("context"))
    write_text_field("期望能力", task_info.get("expected_capability"))
    write_text_field("风险级别", task_info.get("risk_level"))

    render_gold_answer(data.gold_answer_map, selected_case)
    render_model_outputs(data.model_outputs, data.scores, data.errors, selected_case)
