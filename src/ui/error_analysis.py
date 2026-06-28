"""Error attribution and data improvement workflow page."""

import pandas as pd
import streamlit as st

from src.charts import render_error_distribution_summary_chart
from src.metrics import (
    get_error_attribution_actions,
    get_error_distribution_summary,
    get_priority_error_samples,
    normalize_optimization_plan,
)
from src.ui.common import PAGE_CONTEXTS
from src.ui.components import (
    render_context_summary,
    render_empty_state,
    render_page_header,
    render_section_title,
)


ACTION_PATH_COLUMNS = ["错误表现", "可能原因", "数据补强动作", "验证指标"]


def build_error_action_path(actions_df):
    if actions_df is None or actions_df.empty:
        return pd.DataFrame(columns=ACTION_PATH_COLUMNS)

    path_df = pd.DataFrame(
        {
            "错误表现": actions_df.get("error_type", ""),
            "可能原因": actions_df.get("root_cause", ""),
            "数据补强动作": actions_df.get("data_action", ""),
            "验证指标": actions_df.get("validation_metric", ""),
        }
    )
    for column in ACTION_PATH_COLUMNS:
        path_df[column] = path_df[column].fillna("")
        path_df[column] = path_df[column].where(
            path_df[column].astype(str).str.strip() != "",
            "暂无对应记录",
        )
    return path_df[ACTION_PATH_COLUMNS]


def _display_table(df, columns, empty_message):
    if df is None or df.empty:
        render_empty_state(empty_message)
        return

    available_columns = [column for column in columns if column in df.columns]
    if not available_columns:
        render_empty_state(empty_message)
        return

    st.dataframe(df[available_columns], width="stretch", hide_index=True)


def _show_error_distribution(error_df):
    render_section_title("错误分布", "按 error_type 汇总错误次数，并展示最高严重程度、涉及模型与题目。")
    render_error_distribution_summary_chart(error_df)

    distribution = get_error_distribution_summary(error_df)
    if not distribution.empty:
        top_error = distribution.iloc[0]
        st.caption(
            f"当前样本观察：{top_error['error_type']} 出现 {top_error['count']} 次，"
            "后续应结合错误归因和数据补强动作复核。"
        )
    _display_table(
        distribution,
        ["error_type", "count", "severity", "models", "cases"],
        "暂无错误标签数据，无法展示错误分布。",
    )


def _show_error_action_path(error_df, optimization_df):
    render_section_title(
        "错误表现 → 可能原因 → 数据补强动作",
        "将错误标签收敛成可执行的数据建设路径。",
    )
    actions = get_error_attribution_actions(error_df, optimization_df)
    path_df = build_error_action_path(actions)
    _display_table(
        path_df,
        ACTION_PATH_COLUMNS,
        "该模块用于展示数据闭环，当前暂无对应记录。",
    )


def _show_error_attribution(error_df, optimization_df):
    render_section_title("错误归因", "将错误类型关联到可能原因。缺少匹配记录时保留错误类型，并提示暂无归因。")

    actions = get_error_attribution_actions(error_df, optimization_df)
    if actions.empty:
        render_empty_state("暂无可展示数据")
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
    render_section_title("数据补强动作", "数据补强建议以“补什么数据”为核心，并保留验证指标用于后续复测。")

    normalized_plan = normalize_optimization_plan(optimization_df)
    if normalized_plan.empty:
        render_empty_state("该模块用于展示数据闭环，当前暂无对应记录。")
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
    render_section_title("重点错误样本", "优先展示高严重程度样本，帮助定位需要补强的数据类型。")

    samples = get_priority_error_samples(error_df, optimization_df)
    if samples.empty:
        render_empty_state("暂无可展示数据")
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
    context = PAGE_CONTEXTS["错误归因与数据补强"]
    render_page_header("错误归因与数据补强", context["question"], context["boundary"])
    render_context_summary(context)

    data = data_bundle["data"]
    error_df = data.errors
    optimization_df = data.optimizations

    tab_path, tab_distribution, tab_attribution, tab_actions, tab_samples = st.tabs(
        ["错误到数据动作", "错误分布", "错误归因", "数据补强动作", "重点错误样本"]
    )

    with tab_path:
        _show_error_action_path(error_df, optimization_df)

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
