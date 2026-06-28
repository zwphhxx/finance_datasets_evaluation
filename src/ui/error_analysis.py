from __future__ import annotations

import streamlit as st

from src.charts import render_error_type_distribution_chart, render_model_average_score_chart


def render_error_analysis_page(data_bundle: dict) -> None:
    data = data_bundle["data"]

    st.header("错误归因与优化建议")

    st.subheader("错误类型分布")
    render_error_type_distribution_chart(
        data.errors,
        empty_message="暂无错误标签数据，暂不能展示错误类型分布。",
    )

    st.subheader("各模型平均得分对比")
    render_model_average_score_chart(
        data.scores,
        empty_message="暂无评分数据，暂不能展示模型平均得分。",
    )

    st.subheader("优化建议")
    if data.optimizations.empty:
        st.info("暂无优化建议数据。")
    else:
        st.dataframe(data.optimizations, width="stretch")
