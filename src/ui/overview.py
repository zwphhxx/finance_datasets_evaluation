from __future__ import annotations

import streamlit as st

from src.charts import render_error_type_distribution_chart, render_model_average_score_chart
from src.metrics import get_overview_metrics
from src.ui.common import has_value


def render_data_quality_status(validation_result) -> None:
    st.subheader("数据质量状态")
    if validation_result.is_valid:
        st.success("数据质量检查通过。")
    else:
        st.error("数据质量检查发现需处理的问题。")

    for message in validation_result.errors:
        st.error(message)
    for message in validation_result.warnings:
        st.warning(message)


def render_overview_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    validation_result = data_bundle["validation_result"]
    metrics = get_overview_metrics(data_bundle)

    st.header("项目总览")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("任务数", metrics["task_count"])
    col2.metric("模型数", metrics["model_count"])
    average_score = metrics["average_total_score"]
    col3.metric("平均总分", f"{average_score:.1f}" if has_value(average_score) else "暂无")
    col4.metric("错误标签数", metrics["error_label_count"])
    col5.metric("优化建议数", metrics["optimization_count"])

    render_data_quality_status(validation_result)

    st.subheader("各模型平均得分")
    render_model_average_score_chart(
        data.scores,
        empty_message="暂无评分数据，暂不能展示模型平均得分。",
    )

    st.subheader("错误类型分布")
    render_error_type_distribution_chart(
        data.errors,
        empty_message="暂无错误标签数据，暂不能展示错误类型分布。",
    )
