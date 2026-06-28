from __future__ import annotations

from src.ui.case_detail import render_case_detail_page
from src.ui.error_analysis import render_error_analysis_page
from src.ui.model_diagnosis import render_model_diagnosis_page
from src.ui.optimization_compare import render_optimization_compare_page
from src.ui.overview import render_overview_page
from src.ui.tasks import render_tasks_page


NAV_ITEMS = [
    {"label": "评测项目总览", "render": render_overview_page},
    {"label": "专业任务集", "render": render_tasks_page},
    {"label": "样板题深度评测", "render": render_case_detail_page},
    {"label": "模型能力诊断", "render": render_model_diagnosis_page},
    {"label": "错误归因与数据补强", "render": render_error_analysis_page},
    {"label": "优化验证", "render": render_optimization_compare_page},
]

PAGES = {item["label"]: item["render"] for item in NAV_ITEMS}


def render_sidebar_navigation() -> str:
    import streamlit as st

    default_page = NAV_ITEMS[0]["label"]
    if "current_page" not in st.session_state:
        st.session_state.current_page = default_page

    st.sidebar.title("FinDueEval")
    st.sidebar.caption("模型评测与数据优化闭环")
    for item in NAV_ITEMS:
        label = item["label"]
        active_prefix = "[当前] " if st.session_state.current_page == label else ""
        if st.sidebar.button(f"{active_prefix}{label}", key=f"nav_{label}"):
            st.session_state.current_page = label

    return st.session_state.current_page
