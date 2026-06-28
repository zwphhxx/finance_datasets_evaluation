"""Error attribution and data improvement workflow page."""

import streamlit as st

from src.charts import render_error_distribution_summary_chart
from src.metrics import (
    get_error_attribution_actions,
    get_error_distribution_summary,
    get_priority_error_samples,
    normalize_optimization_plan,
)


def _display_table(df, columns, empty_message):
    if df is None or df.empty:
        st.info(empty_message)
        return

    available_columns = [column for column in columns if column in df.columns]
    if not available_columns:
        st.info(empty_message)
        return

    st.dataframe(df[available_columns], use_container_width=True, hide_index=True)


def _show_error_distribution(error_df):
    st.subheader("错误分布")
    st.caption("按 error_type 汇总错误次数，并展示最高严重程度、涉及模型与题目。")
    render_error_distribution_summary_chart(error_df)

    distribution = get_error_distribution_summary(error_df)
    _display_table(
        distribution,
        ["error_type", "count", "severity", "models", "cases"],
        "暂无错误标签数据，无法展示错误分布。",
    )


def _show_error_attribution(error_df, optimization_df):
    st.subheader("错误归因")
    st.caption("将错误类型关联到可能原因。缺少匹配记录时保留错误类型，并提示暂无归因。")

    actions = get_error_attribution_actions(error_df, optimization_df)
    if actions.empty:
        st.info("暂无错误标签数据，无法展示错误归因。")
        return

    attribution = actions.copy()
    attribution["root_cause"] = attribution["root_cause"].fillna("")
    attribution["root_cause"] = attribution["root_cause"].where(
        attribution["root_cause"].astype(str).str.strip() != "",
        "暂无匹配归因记录。",
    )
    _display_table(
        attribution,
        ["error_type", "count", "severity", "root_cause", "models", "cases"],
        "暂无错误归因数据。",
    )


def _show_data_actions(error_df, optimization_df):
    st.subheader("数据优化动作")
    st.caption("数据补强建议以“补什么数据”为核心，并保留验证指标用于后续复测。")

    normalized_plan = normalize_optimization_plan(optimization_df)
    if normalized_plan.empty:
        st.info("暂无 optimization_plan 数据，无法展示数据补强建议。")
        return

    actions = get_error_attribution_actions(error_df, optimization_df)
    if actions.empty:
        _display_table(
            normalized_plan,
            [
                "action_id",
                "error_type",
                "data_action",
                "sample_format",
                "priority",
                "expected_effect",
                "validation_metric",
                "status",
            ],
            "暂无数据补强建议。",
        )
        return

    action_view = actions.copy()
    for column in ["data_action", "sample_format", "expected_effect", "validation_metric", "status"]:
        action_view[column] = action_view[column].fillna("")
        action_view[column] = action_view[column].where(
            action_view[column].astype(str).str.strip() != "",
            "暂无匹配优化动作。" if column == "data_action" else "暂无记录。",
        )

    _display_table(
        action_view,
        [
            "error_type",
            "count",
            "data_action",
            "sample_format",
            "priority",
            "expected_effect",
            "validation_metric",
            "status",
        ],
        "暂无数据补强建议。",
    )


def _show_priority_samples(error_df, optimization_df):
    st.subheader("重点错误样本")
    st.caption("优先展示高严重程度样本，帮助定位需要补强的数据类型。")

    samples = get_priority_error_samples(error_df, optimization_df)
    if samples.empty:
        st.info("暂无错误样本，无法展示重点错误样本。")
        return

    sample_view = samples.copy()
    sample_view["data_action"] = sample_view["data_action"].fillna("")
    sample_view["data_action"] = sample_view["data_action"].where(
        sample_view["data_action"].astype(str).str.strip() != "",
        "暂无匹配优化动作。",
    )
    _display_table(
        sample_view,
        [
            "case_id",
            "model_name",
            "error_type",
            "severity",
            "error_description",
            "data_action",
            "validation_metric",
        ],
        "暂无重点错误样本。",
    )


def render_error_analysis(data_bundle):
    st.header("错误归因与数据优化")
    st.caption("基于当前样本观察，将错误标签转化为数据补强动作和后续验证指标。")

    data = data_bundle["data"]
    error_df = data.errors
    optimization_df = data.optimizations

    tab_distribution, tab_attribution, tab_actions, tab_samples = st.tabs(
        ["错误分布", "错误归因", "数据优化动作", "重点错误样本"]
    )

    with tab_distribution:
        _show_error_distribution(error_df)

    with tab_attribution:
        _show_error_attribution(error_df, optimization_df)

    with tab_actions:
        _show_data_actions(error_df, optimization_df)

    with tab_samples:
        _show_priority_samples(error_df, optimization_df)


def render_error_analysis_page(data_bundle):
    render_error_analysis(data_bundle)
