"""Optimization comparison page for prompt, RAG, and data improvement changes."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.charts import render_optimization_comparison_chart
from src.metrics import (
    get_optimization_change_summary,
    get_optimization_comparison_metrics,
)


def collect_optimization_compare_tables(data_bundle: dict) -> dict:
    data = data_bundle["data"]
    comparison_df = getattr(data, "optimization_comparison", pd.DataFrame())
    return {
        "metrics": get_optimization_comparison_metrics(comparison_df),
        "summary": get_optimization_change_summary(comparison_df),
    }


def render_optimization_compare_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    comparison_df = getattr(data, "optimization_comparison", pd.DataFrame())

    st.header("优化前后对比")
    st.caption("展示 Prompt、RAG 或数据补强版本在当前评测集中的样例指标变化。")

    if comparison_df.empty:
        st.info("暂无优化前后对比数据，不影响其他页面使用。")
        _render_boundary_note()
        return

    tab_metrics, tab_changes, tab_summary = st.tabs(
        ["指标对比", "变更说明", "摘要与边界"]
    )

    with tab_metrics:
        st.subheader("指标变化")
        metrics = render_optimization_comparison_chart(comparison_df)
        if not metrics.empty:
            st.dataframe(
                metrics[
                    [
                        "version",
                        "avg_score",
                        "hallucination_rate",
                        "evidence_score",
                        "reasoning_score",
                        "red_line_error_rate",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )

    with tab_changes:
        st.subheader("变更类型与说明")
        metrics = get_optimization_comparison_metrics(comparison_df)
        if metrics.empty:
            st.info("暂无可展示的版本变更说明。")
        else:
            st.dataframe(
                metrics[
                    [
                        "experiment_id",
                        "version",
                        "change_type",
                        "change_description",
                        "note",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )

    with tab_summary:
        st.subheader("指标变化摘要")
        summary = get_optimization_change_summary(comparison_df)
        if not summary:
            st.info("至少需要两个版本记录才能形成对比摘要。")
        else:
            for item in summary:
                st.write(f"- {item}")
        _render_boundary_note()


def _render_boundary_note() -> None:
    st.subheader("适用边界")
    st.info(
        "当前结果基于 MVP 样例数据和当前评测集观察，用于展示评测闭环与数据建设方法。"
        "样本量有限，不代表真实生产环境或大规模实验结论。"
    )
