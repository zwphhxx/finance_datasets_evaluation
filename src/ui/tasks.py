from __future__ import annotations

import streamlit as st

from src.metrics import filter_tasks_by_domain, get_task_domains


def render_tasks_page(data_bundle: dict) -> None:
    tasks_df = data_bundle["data"].tasks

    st.header("任务列表")
    if tasks_df.empty:
        st.info("暂无任务数据。")
        return

    domains = get_task_domains(tasks_df)
    selected_domain = st.selectbox("选择领域", domains)
    filtered_tasks = filter_tasks_by_domain(tasks_df, selected_domain)
    if filtered_tasks.empty:
        st.info("当前筛选条件下无匹配任务。")
    else:
        st.dataframe(filtered_tasks, width="stretch")
