from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.components import render_context_summary, render_score_badge
from src.ui.page_config import PAGE_CONTEXTS


def render_page_context(page_name: str) -> None:
    context = PAGE_CONTEXTS.get(page_name)
    if not context:
        return

    with st.container():
        st.markdown("**本页回答什么问题**")
        st.write(context["question"])
        st.markdown("**当前数据边界**")
        st.write(context["boundary"])
        st.markdown("**页面核心看点**")
        st.write(context["highlights"])


def has_value(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except TypeError:
        return True


def write_text_field(label: str, value) -> None:
    st.write(f"**{label}：** {value if has_value(value) else '暂无'}")


def write_list_field(label: str, value) -> None:
    st.write(f"**{label}：**")
    if isinstance(value, list) and value:
        for item in value:
            st.write(f"- {item}")
    elif has_value(value):
        st.write(value)
    else:
        st.write("暂无")


def show_model_score(row: pd.Series) -> None:
    total_score = row.get("total_score")
    if not has_value(total_score):
        st.write("**评分：** 当前模型回答尚未评分。")
        return

    render_score_badge(total_score)
    accuracy = row.get("accuracy_score", "暂无")
    reasoning = row.get("reasoning_score", "暂无")
    coverage = row.get("coverage_score", "暂无")
    evidence = row.get("evidence_score", "暂无")
    expression = row.get("expression_score", "暂无")
    st.write(
        f"**得分：** 总分 {float(total_score):.0f}"
        f"（专业准确性 {accuracy}，推理与场景适配 {reasoning}，风险覆盖 {coverage}，"
        f"依据可靠性 {evidence}，专业表达 {expression}）"
    )
