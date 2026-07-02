from __future__ import annotations

import streamlit as st

from src.ui.case_study import render_case_study_page
from src.ui.samples import render_samples_page
from src.ui.test_run import render_test_run_page
from src.ui.review import render_review_page
from src.ui.conclusions import render_conclusions_page
from src.ui.components import render_html
from src.ui.page_config import DEFAULT_PAGE_KEY, PAGE_CONFIG_BY_KEY


PAGES = {
    "case_study": render_case_study_page,
    "samples": render_samples_page,
    "test_run": render_test_run_page,
    "review": render_review_page,
    "conclusions": render_conclusions_page,
}


# Top nav: exactly 5 main items matching the core evaluation workflow.
# Maps display label -> page_key for the top nav bar.
_TOP_NAV_ITEMS = [
    ("Case Study", "case_study"),
    ("样本库", "samples"),
    ("发起测试", "test_run"),
    ("评测复核", "review"),
    ("评测结论", "conclusions"),
]

# Sidebar shows same 5 items only (no old pages).
_NAV_GROUPS = [
    ("", ["case_study", "samples", "test_run", "review", "conclusions"]),
]


def _set_current_page(page_key: str) -> None:
    st.session_state.current_page = page_key


def render_top_navigation() -> None:
    """Render a sticky top nav bar with 5 portfolio-style links."""
    current = st.session_state.get("current_page", DEFAULT_PAGE_KEY)
    links_html = ""
    for label, page_key in _TOP_NAV_ITEMS:
        active_class = "active" if current == page_key else ""
        links_html += f'<span class="top-nav-link {active_class}">{label}</span>'
    render_html(
        f"""
        <div class="top-nav">
            <div class="top-nav-brand">FinDueEval</div>
            <div class="top-nav-links">{links_html}</div>
        </div>
        """
    )
    # Render actual Streamlit buttons invisibly for navigation
    cols = st.columns(len(_TOP_NAV_ITEMS))
    for col, (label, page_key) in zip(cols, _TOP_NAV_ITEMS):
        with col:
            if st.button(label, key=f"top_nav_{page_key}", use_container_width=False):
                st.session_state.current_page = page_key
                st.rerun()


def render_sidebar_navigation() -> str:
    valid_page_keys = set(PAGE_CONFIG_BY_KEY)
    if st.session_state.get("current_page") not in valid_page_keys:
        st.session_state.current_page = DEFAULT_PAGE_KEY

    # Render top nav first
    render_top_navigation()

    # Weaken sidebar: minimal brand, no group headers
    render_html(
        """
        <div class="nav-brand" style="opacity:0.7;">
            <div class="nav-brand-title" style="font-size:0.9rem;">导航</div>
        </div>
        """,
        container=st.sidebar,
    )

    for group_title, keys in _NAV_GROUPS:
        for key in keys:
            config = PAGE_CONFIG_BY_KEY.get(key)
            if config is None:
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


def get_primary_nav_items() -> list[tuple[str, str]]:
    """Return the primary navigation items (label, page_key)."""
    return _TOP_NAV_ITEMS[:]
