from __future__ import annotations

import streamlit as st

from src.ui.case_detail import render_case_detail_page
from src.ui.components import render_html
from src.ui.dataset_admin import render_dataset_admin_page
from src.ui.dataset_quality import render_dataset_quality_page
from src.ui.eval_run_page import render_eval_run_page
from src.ui.model_boundary import render_model_boundary_page
from src.ui.model_diagnosis import render_model_diagnosis_page
from src.ui.overview import render_overview_page
from src.ui.page_config import DEFAULT_PAGE_KEY, PAGE_CONFIGS, PAGE_CONFIG_BY_KEY
from src.ui.project_methodology import render_project_methodology_page
from src.ui.tasks import render_tasks_page


PAGES = {
    "project_methodology": render_project_methodology_page,
    "overview": render_overview_page,
    "tasks": render_tasks_page,
    "eval_run": render_eval_run_page,
    "case_detail": render_case_detail_page,
    "model_diagnosis": render_model_diagnosis_page,
    "model_boundary": render_model_boundary_page,
    "dataset_quality": render_dataset_quality_page,
    "dataset_admin": render_dataset_admin_page,
}


_NAV_GROUPS = [
    ("📌 项目", ["project_methodology"]),
    ("📊 概览", ["overview", "tasks"]),
    ("▶️  运行评测", ["eval_run", "case_detail", "model_diagnosis", "model_boundary"]),
    ("🛠️  数据集管理", ["dataset_quality", "dataset_admin"]),
]


def _set_current_page(page_key: str) -> None:
    st.session_state.current_page = page_key


def render_sidebar_navigation() -> str:
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

    for group_title, keys in _NAV_GROUPS:
        render_html(
            f'<div style="margin:0.9rem 0 0.35rem 0;color:var(--fde-muted);font-size:0.75rem;font-weight:750;letter-spacing:0.04em;">{group_title}</div>',
            container=st.sidebar,
        )
        for config in PAGE_CONFIGS:
            if config.page_key not in keys:
                continue
            is_current = st.session_state.current_page == config.page_key
            st.sidebar.button(
                config.title,
                key=f"nav_{config.page_key}",
                on_click=_set_current_page,
                args=(config.page_key,),
                type="primary" if is_current else "secondary",
                use_container_width=True,
            )

    _render_data_context_bar()

    return st.session_state.current_page


def _render_data_context_bar() -> None:
    context = st.session_state.get("data_context") or {}
    if not context:
        return
    rows = [
        ("数据源", context.get("data_source", "—")),
        ("任务", context.get("task_count", "—")),
        ("运行", context.get("run_id", "—")),
        ("评分", context.get("score_status", "—")),
    ]
    html = '<div style="margin-top:1.2rem;padding-top:0.8rem;border-top:1px solid var(--fde-line);">'
    html += '<div style="color:var(--fde-muted);font-size:0.72rem;font-weight:750;margin-bottom:0.4rem;">当前数据上下文</div>'
    html += '<div style="display:flex;flex-direction:column;gap:0.35rem;">'
    for label, value in rows:
        html += (
            f'<div style="display:flex;justify-content:space-between;font-size:0.78rem;">'
            f'<span style="color:var(--fde-muted);">{label}</span>'
            f'<span style="color:var(--fde-text);font-weight:650;text-align:right;">{value}</span>'
            f'</div>'
        )
    html += "</div></div>"
    render_html(html, container=st.sidebar)
