from __future__ import annotations

import streamlit as st

from src.metrics import filter_tasks_by_domain, get_task_domains
from src.ui.common import render_page_context


def render_tasks_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    tasks_df = data.tasks

    st.header("专业任务集")
    render_page_context("专业任务集")
    if tasks_df.empty:
        st.info("当前样本暂无可展示数据。")
        return

    _render_task_coverage(data)
    _render_task_distribution(tasks_df)

    domains = get_task_domains(tasks_df)
    selected_domain = st.selectbox("选择领域", domains)
    filtered_tasks = filter_tasks_by_domain(tasks_df, selected_domain)
    if filtered_tasks.empty:
        st.info("当前样本暂无可展示数据。")
    else:
        display_columns = [
            column
            for column in ["case_id", "domain", "scenario", "task_type", "difficulty", "question"]
            if column in filtered_tasks.columns
        ]
        st.dataframe(filtered_tasks[display_columns], width="stretch", hide_index=True)


def _render_task_coverage(data) -> None:
    tasks_df = data.tasks
    task_ids = set(tasks_df["case_id"].dropna().astype(str)) if "case_id" in tasks_df else set()
    gold_ids = set(data.gold_answer_map.keys())
    output_case_ids = (
        set(data.model_outputs["case_id"].dropna().astype(str))
        if "case_id" in data.model_outputs
        else set()
    )

    st.subheader("样本覆盖")
    cols = st.columns(4)
    cols[0].metric("任务样本", len(tasks_df))
    cols[1].metric("领域数", tasks_df["domain"].nunique() if "domain" in tasks_df else 0)
    cols[2].metric("Gold Answer 覆盖", f"{len(task_ids & gold_ids)}/{len(task_ids)}")
    cols[3].metric("模型回答覆盖", f"{len(task_ids & output_case_ids)}/{len(task_ids)}")


def _render_task_distribution(tasks_df) -> None:
    st.subheader("样本分布")
    if "domain" not in tasks_df:
        st.info("当前样本暂无可展示数据。")
        return

    distribution = tasks_df["domain"].value_counts().reset_index()
    distribution.columns = ["domain", "count"]
    st.bar_chart(distribution, x="domain", y="count")
