from __future__ import annotations

from src.ui.case_detail import render_case_detail_page
from src.ui.components import render_html
from src.ui.dataset_admin import render_dataset_admin_page
from src.ui.dataset_quality import render_dataset_quality_page
from src.ui.error_analysis import render_error_analysis_page
from src.ui.model_boundary import render_model_boundary_page
from src.ui.model_diagnosis import render_model_diagnosis_page
from src.ui.optimization_compare import render_optimization_compare_page
from src.ui.overview import render_overview_page
from src.ui.page_config import DEFAULT_PAGE_KEY, PAGE_CONFIGS, PAGE_CONFIG_BY_KEY
from src.ui.tasks import render_tasks_page


PAGES = {
    "overview": render_overview_page,
    "tasks": render_tasks_page,
    "case_detail": render_case_detail_page,
    "model_diagnosis": render_model_diagnosis_page,
    "model_boundary": render_model_boundary_page,
    "error_analysis": render_error_analysis_page,
    "optimization_compare": render_optimization_compare_page,
    "dataset_quality": render_dataset_quality_page,
    "dataset_admin": render_dataset_admin_page,
}


def _set_current_page(page_key: str) -> None:
    import streamlit as st

    st.session_state.current_page = page_key


def render_sidebar_navigation() -> str:
    import streamlit as st

    valid_page_keys = set(PAGE_CONFIG_BY_KEY)
    if st.session_state.get("current_page") not in valid_page_keys:
        st.session_state.current_page = DEFAULT_PAGE_KEY

    render_html(
        """
        <div class="nav-brand">
            <div class="nav-brand-title">FinDueEval</div>
            <div class="nav-brand-subtitle">模型评测与数据优化 Demo</div>
        </div>
        """,
        container=st.sidebar,
    )

    for config in PAGE_CONFIGS:
        is_current = st.session_state.current_page == config.page_key
        st.sidebar.button(
            config.title,
            key=f"nav_{config.page_key}",
            on_click=_set_current_page,
            args=(config.page_key,),
            type="primary" if is_current else "secondary",
            use_container_width=True,
        )

    return st.session_state.current_page
