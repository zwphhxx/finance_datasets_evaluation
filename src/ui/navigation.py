from __future__ import annotations

import streamlit as st

from src.ui.case_study import render_case_study_page
from src.ui.components import render_html
from src.ui.conclusions import render_conclusions_page
from src.ui.page_config import DEFAULT_PAGE_KEY, PAGE_CONFIG_BY_KEY
from src.ui.samples import render_samples_page
from src.ui.scroll import request_scroll
from src.ui.test_run import render_test_run_page

PROJECT_DISPLAY_NAME = "财务/法律/投行场景大模型对比评测"


PAGES = {
    "case_study": render_case_study_page,
    "samples": render_samples_page,
    "test_run": render_test_run_page,
    "conclusions": render_conclusions_page,
}


# Review destinations are peers. Evaluation remains reachable but deliberately
# sits in a separate, lower-emphasis operation entry.
PRIMARY_NAV_ITEMS = [
    ("评测结论", "conclusions"),
    ("项目说明", "case_study"),
    ("样本库", "samples"),
]
OPERATION_NAV_ITEM = ("评测操作", "test_run")


def _render_navigation_button(label: str, page_key: str, current: str, *, key: str) -> None:
    if st.button(
        label,
        key=key,
        type="secondary" if current == page_key else "tertiary",
        use_container_width=False,
    ):
        st.session_state.current_page = page_key
        request_scroll("top")
        st.rerun()


def render_top_navigation() -> None:
    """Render review navigation separately from the evaluation operation."""
    current = st.session_state.get("current_page", DEFAULT_PAGE_KEY)
    brand_column, review_column, operation_column = st.columns([3.1, 2.6, 0.9], gap="medium")
    with brand_column:
        render_html(f'<div class="top-nav-brand">{PROJECT_DISPLAY_NAME}</div>')
    with review_column:
        with st.container(key="top_nav_review_region"):
            review_columns = st.columns(len(PRIMARY_NAV_ITEMS), gap="small")
            for column, (label, page_key) in zip(review_columns, PRIMARY_NAV_ITEMS):
                with column:
                    _render_navigation_button(
                        label,
                        page_key,
                        current,
                        key=f"top_nav_{page_key}",
                    )
    with operation_column:
        with st.container(key="top_nav_operation_region"):
            label, page_key = OPERATION_NAV_ITEM
            _render_navigation_button(label, page_key, current, key="top_nav_operation")


def render_sidebar_navigation() -> str:
    valid_page_keys = set(PAGE_CONFIG_BY_KEY)
    if st.session_state.get("current_page") not in valid_page_keys:
        st.session_state.current_page = DEFAULT_PAGE_KEY

    # Single navigation: top bar only. Sidebar is intentionally empty.
    render_top_navigation()
    return st.session_state.current_page


def get_primary_nav_items() -> list[tuple[str, str]]:
    """Return the primary navigation items (label, page_key)."""
    return PRIMARY_NAV_ITEMS[:]


def get_operation_nav_item() -> tuple[str, str]:
    """Return the secondary operation navigation item."""
    return OPERATION_NAV_ITEM
