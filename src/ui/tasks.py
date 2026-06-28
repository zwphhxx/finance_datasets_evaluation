from __future__ import annotations

import streamlit as st

from src.metrics import filter_tasks_by_domain, get_task_domains
from src.ui.common import PAGE_CONTEXTS
from src.ui.components import (
    render_empty_state,
    render_info_panel,
    render_metric_card,
    render_page_header,
    render_section_title,
)


def render_tasks_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    tasks_df = data.tasks
    context = PAGE_CONTEXTS["专业任务集"]

    render_page_header("专业任务集", context["question"], context["boundary"])
    render_info_panel("页面核心看点", context["highlights"])
    if tasks_df.empty:
        render_empty_state("暂无可展示数据")
        return

    _render_task_coverage(data)
    _render_task_distribution(tasks_df)

    domains = get_task_domains(tasks_df)
    selected_domain = st.selectbox("选择领域", domains)
    filtered_tasks = filter_tasks_by_domain(tasks_df, selected_domain)
    if filtered_tasks.empty:
        render_empty_state("暂无可展示数据")
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

    render_section_title("样本覆盖")
    cols = st.columns(4)
    with cols[0]:
        render_metric_card("任务样本", len(tasks_df), "脱敏专业任务。")
    with cols[1]:
        render_metric_card("领域数", tasks_df["domain"].nunique() if "domain" in tasks_df else 0, "当前样本覆盖。")
    with cols[2]:
        render_metric_card("Gold Answer 覆盖", f"{len(task_ids & gold_ids)}/{len(task_ids)}", "标准答案覆盖。")
    with cols[3]:
        render_metric_card("模型回答覆盖", f"{len(task_ids & output_case_ids)}/{len(task_ids)}", "回答样本覆盖。")


def _render_task_distribution(tasks_df) -> None:
    render_section_title("样本分布")
    if "domain" not in tasks_df:
        render_empty_state("暂无可展示数据")
        return

    distribution = tasks_df["domain"].value_counts().reset_index()
    distribution.columns = ["domain", "count"]
    st.bar_chart(distribution, x="domain", y="count")
