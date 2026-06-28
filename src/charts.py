from __future__ import annotations

import pandas as pd
import streamlit as st

from src.metrics import get_error_type_counts, get_model_average_scores


def render_model_average_score_chart(
    scores_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的评分数据。",
) -> pd.DataFrame:
    chart_data = get_model_average_scores(scores_df)
    if chart_data.empty:
        st.info(empty_message)
        return chart_data

    st.bar_chart(data=chart_data, x="model_name", y="total_score")
    return chart_data


def render_error_type_distribution_chart(
    error_df: pd.DataFrame,
    empty_message: str = "当前暂无可展示的错误标签数据。",
) -> pd.DataFrame:
    chart_data = get_error_type_counts(error_df)
    if chart_data.empty:
        st.info(empty_message)
        return chart_data

    st.bar_chart(chart_data, x="error_type", y="count")
    return chart_data
