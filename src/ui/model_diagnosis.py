from __future__ import annotations

import streamlit as st

from src.charts import (
    render_model_dimension_score_chart,
    render_model_domain_score_chart,
    render_model_error_type_chart,
    render_model_total_score_chart,
)
from src.metrics import (
    get_model_capability_summaries,
    get_model_dimension_scores,
    get_model_domain_scores,
    get_model_error_type_counts,
    get_model_total_scores,
)
from src.ui.common import render_page_context


def render_model_diagnosis_page(data_bundle: dict) -> None:
    data = data_bundle["data"]

    st.header("模型能力诊断")
    render_page_context("模型能力诊断")

    if data.model_outputs.empty:
        st.info("当前样本暂无可展示数据。")
        return

    tab_total, tab_dimensions, tab_errors, tab_domains, tab_summary = st.tabs(
        ["综合得分", "分维度得分", "错误类型", "领域/场景", "诊断摘要"]
    )

    with tab_total:
        st.subheader("各模型综合得分对比")
        total_scores = render_model_total_score_chart(
            data.scores,
            empty_message="当前暂无可展示的评分数据。",
        )
        if not total_scores.empty:
            st.dataframe(total_scores, width="stretch")

    with tab_dimensions:
        st.subheader("各模型分维度得分")
        dimension_scores = render_model_dimension_score_chart(
            data.scores,
            empty_message="当前暂无可展示的分维度评分数据。",
        )
        if not dimension_scores.empty:
            st.dataframe(dimension_scores, width="stretch")

    with tab_errors:
        st.subheader("各模型错误类型分布")
        error_counts = render_model_error_type_chart(
            data.errors,
            empty_message="当前暂无可展示的错误标签数据。",
        )
        if not error_counts.empty:
            st.dataframe(error_counts, width="stretch")

    with tab_domains:
        st.subheader("按领域/场景的模型得分对比")
        domain_scores = render_model_domain_score_chart(
            data.scores,
            data.tasks,
            empty_message="当前暂无可展示的领域得分数据。",
        )
        if not domain_scores.empty:
            st.dataframe(domain_scores, width="stretch")

    with tab_summary:
        st.subheader("能力诊断摘要")
        render_capability_summaries(data.scores, data.errors, data.tasks)


def render_capability_summaries(scores_df, error_df, tasks_df) -> None:
    summaries = get_model_capability_summaries(scores_df, error_df, tasks_df)
    if not summaries:
        st.info("当前暂无足够数据生成模型能力诊断摘要。")
        return

    for item in summaries:
        with st.expander(item["model_name"], expanded=True):
            st.write(item["summary"])


def collect_model_diagnosis_tables(data_bundle: dict) -> dict:
    data = data_bundle["data"]
    return {
        "total_scores": get_model_total_scores(data.scores),
        "dimension_scores": get_model_dimension_scores(data.scores),
        "error_counts": get_model_error_type_counts(data.errors),
        "domain_scores": get_model_domain_scores(data.scores, data.tasks),
        "summaries": get_model_capability_summaries(data.scores, data.errors, data.tasks),
    }
