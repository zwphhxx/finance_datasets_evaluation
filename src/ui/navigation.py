from __future__ import annotations

from html import escape

from src.ui.case_detail import render_case_detail_page
from src.ui.error_analysis import render_error_analysis_page
from src.ui.model_diagnosis import render_model_diagnosis_page
from src.ui.optimization_compare import render_optimization_compare_page
from src.ui.overview import render_overview_page
from src.ui.tasks import render_tasks_page


NAV_ITEMS = [
    {"label": "评测项目总览", "description": "项目目标与数据资产", "render": render_overview_page},
    {"label": "专业任务集", "description": "样本覆盖与任务分布", "render": render_tasks_page},
    {"label": "样板题深度评测", "description": "单题评测闭环", "render": render_case_detail_page},
    {"label": "模型能力诊断", "description": "能力短板观察", "render": render_model_diagnosis_page},
    {"label": "错误归因与数据补强", "description": "错误到数据动作", "render": render_error_analysis_page},
    {"label": "优化验证", "description": "前后指标对比", "render": render_optimization_compare_page},
]

PAGES = {item["label"]: item["render"] for item in NAV_ITEMS}


def render_sidebar_navigation() -> str:
    import streamlit as st

    default_page = NAV_ITEMS[0]["label"]
    if "current_page" not in st.session_state:
        st.session_state.current_page = default_page

    st.sidebar.title("模型评测/数据优化")
    st.sidebar.caption("金融/财务/法律等数据的专业评测与优化")
    for item in NAV_ITEMS:
        label = item["label"]
        is_current = st.session_state.current_page == label
        active_prefix = "[当前] " if is_current else ""
        if st.sidebar.button(f"{active_prefix}{label}", key=f"nav_{label}"):
            st.session_state.current_page = label
            is_current = True
        note_class = "nav-note nav-note-active" if is_current else "nav-note"
        note_prefix = "当前页面 · " if is_current else ""
        st.sidebar.markdown(
            f'<div class="{note_class}">{escape(note_prefix + item["description"])}</div>',
            unsafe_allow_html=True,
        )

    return st.session_state.current_page
