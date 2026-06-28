from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.ui.components import render_empty_state

from src.metrics import (
    get_error_type_counts,
    get_model_average_scores,
    get_model_dimension_scores,
    get_model_domain_scores,
    get_model_error_type_counts,
    get_model_total_scores,
    get_optimization_comparison_metrics,
)


# Unified chart palette so every page shares one visual language instead of the
# default Streamlit colors. Models map to the first colors in declared order.
BRAND_BLUE = "#12345a"
SERIES_PALETTE = ["#12345a", "#3b7dd8", "#9ec3ec", "#c89b3c", "#247a4b"]
AXIS_LABEL_COLOR = "#607089"


def _base_config(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_view(strokeOpacity=0)
        .configure_axis(
            labelColor=AXIS_LABEL_COLOR,
            titleColor=AXIS_LABEL_COLOR,
            grid=False,
            domainColor="#d8dee8",
            tickColor="#d8dee8",
        )
        .configure_legend(labelColor=AXIS_LABEL_COLOR, titleColor=AXIS_LABEL_COLOR)
    )


def themed_bar_chart(
    data: pd.DataFrame,
    x: str,
    y: str,
    x_title: str,
    y_title: str,
    color_field: str | None = None,
    color_title: str | None = None,
) -> None:
    """Render a brand-themed grouped/simple bar chart with Chinese axis titles."""
    encodings = {
        "x": alt.X(f"{x}:N", title=x_title, axis=alt.Axis(labelAngle=0)),
        "y": alt.Y(f"{y}:Q", title=y_title),
        "tooltip": list(data.columns),
    }
    if color_field:
        encodings["color"] = alt.Color(
            f"{color_field}:N",
            title=color_title or color_field,
            scale=alt.Scale(range=SERIES_PALETTE),
        )
        encodings["xOffset"] = alt.XOffset(f"{color_field}:N")
    else:
        encodings["color"] = alt.value(BRAND_BLUE)

    chart = alt.Chart(data).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(**encodings)
    st.altair_chart(_base_config(chart), use_container_width=True)


def render_model_average_score_chart(
    scores_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的评分数据。",
) -> pd.DataFrame:
    chart_data = get_model_average_scores(scores_df)
    if chart_data.empty:
        render_empty_state(empty_message)
        return chart_data

    st.bar_chart(data=chart_data, x="model_name", y="total_score")
    return chart_data


def render_error_type_distribution_chart(
    error_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的错误标签数据。",
) -> pd.DataFrame:
    chart_data = get_error_type_counts(error_df)
    if chart_data.empty:
        render_empty_state(empty_message)
        return chart_data

    st.bar_chart(chart_data, x="error_type", y="count")
    return chart_data


def render_model_total_score_chart(
    scores_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的评分数据。",
) -> pd.DataFrame:
    chart_data = get_model_total_scores(scores_df)
    if chart_data.empty:
        render_empty_state(empty_message)
        return chart_data

    st.bar_chart(chart_data, x="model_name", y="total_score")
    return chart_data


def render_model_dimension_score_chart(
    scores_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的分维度评分数据。",
) -> pd.DataFrame:
    chart_data = get_model_dimension_scores(scores_df)
    if chart_data.empty:
        render_empty_state(empty_message)
        return chart_data

    st.bar_chart(chart_data, x="dimension", y="score", color="model_name")
    return chart_data


def render_model_error_type_chart(
    error_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的错误标签数据。",
) -> pd.DataFrame:
    chart_data = get_model_error_type_counts(error_df)
    if chart_data.empty:
        render_empty_state(empty_message)
        return chart_data

    st.bar_chart(chart_data, x="error_type", y="count", color="model_name")
    return chart_data


def render_model_domain_score_chart(
    scores_df: pd.DataFrame,
    tasks_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的领域得分数据。",
) -> pd.DataFrame:
    chart_data = get_model_domain_scores(scores_df, tasks_df)
    if chart_data.empty:
        render_empty_state(empty_message)
        return chart_data

    st.bar_chart(chart_data, x="domain", y="total_score", color="model_name")
    return chart_data


def render_error_distribution_summary_chart(error_df, empty_message="暂无错误标签数据，无法展示错误分布。"):
    """Render PR-07 error distribution by error type from normalized metrics."""
    import streamlit as st

    from src.metrics import get_error_distribution_summary

    summary = get_error_distribution_summary(error_df)
    if summary.empty:
        render_empty_state(empty_message)
        return

    chart_data = summary.set_index("error_type")[["count"]]
    st.bar_chart(chart_data)


def render_optimization_comparison_chart(
    comparison_df: pd.DataFrame,
    empty_message: str = "暂无优化前后对比数据，无法展示指标变化。",
) -> pd.DataFrame:
    metrics = get_optimization_comparison_metrics(comparison_df)
    if metrics.empty:
        render_empty_state(empty_message)
        return metrics

    score_columns = ["avg_score", "evidence_score", "reasoning_score"]
    rate_columns = ["hallucination_rate", "red_line_error_rate"]

    st.caption("得分指标")
    score_chart = metrics[["version"] + score_columns].melt(
        id_vars="version",
        var_name="metric",
        value_name="value",
    )
    st.bar_chart(score_chart, x="version", y="value", color="metric")

    st.caption("错误率指标")
    rate_chart = metrics[["version"] + rate_columns].melt(
        id_vars="version",
        var_name="metric",
        value_name="value",
    )
    st.line_chart(rate_chart, x="version", y="value", color="metric")
    return metrics
