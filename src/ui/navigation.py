from __future__ import annotations

import streamlit as st

from app.access import management_enabled
from src.ui.case_study import render_case_study_page
from src.ui.components import render_html
from src.ui.conclusions import render_conclusions_page
from src.ui.management import render_management_page
from src.ui.page_config import DEFAULT_PAGE_KEY, PAGE_CONFIG_BY_KEY
from src.ui.review import render_review_page
from src.ui.scroll import request_scroll
from src.ui.test_run import render_test_run_page

PROJECT_DISPLAY_NAME = "财务/法律/投行场景大模型对比评测"


PAGES = {
    "conclusions": render_conclusions_page,
    "review": render_review_page,
    "case_study": render_case_study_page,
    "samples": render_management_page,
    "test_run": render_test_run_page,
}


# Review destinations are peers. Evaluation remains reachable but deliberately
# sits in a separate, lower-emphasis operation entry.
PRIMARY_NAV_ITEMS = [
    ("评测结果", "conclusions"),
    ("案例分析", "review"),
    ("评测方法", "case_study"),
]
OPERATION_NAV_ITEM = ("运行评测", "test_run")
MANAGEMENT_NAV_ITEMS = [OPERATION_NAV_ITEM, ("数据维护", "samples")]


def _render_navigation_button(label: str, page_key: str, current: str, *, key: str) -> None:
    st.button(
        label,
        key=key,
        type="secondary" if current == page_key else "tertiary",
        use_container_width=False,
        on_click=_navigate,
        args=(page_key,),
    )


def _navigate(page_key: str) -> None:
    st.session_state.current_page = page_key
    st.query_params["page"] = page_key
    request_scroll("top")


def render_top_navigation() -> None:
    """Render review navigation separately from the evaluation operation."""
    current = st.session_state.get("current_page", DEFAULT_PAGE_KEY)
    admin = management_enabled()
    columns = st.columns([3.1, 2.6, 0.9] if admin else [1.4, 2.6], gap="medium")
    brand_column, review_column = columns[:2]
    with brand_column:
        render_html('<div class="top-nav-brand">专业模型评测</div>')
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
    if admin:
        with columns[2]:
            with st.container(key="top_nav_operation_region"):
                with st.popover("管理", type="tertiary", width="content"):
                    for label, page_key in MANAGEMENT_NAV_ITEMS:
                        _render_navigation_button(label, page_key, current, key=f"manage_{page_key}")


def render_sidebar_navigation() -> str:
    valid_page_keys = set(PAGE_CONFIG_BY_KEY)
    requested = st.query_params.get("page", DEFAULT_PAGE_KEY)
    st.session_state.current_page = requested if requested in valid_page_keys else DEFAULT_PAGE_KEY

    # Single navigation: top bar only. Sidebar is intentionally empty.
    render_top_navigation()
    return st.session_state.current_page


def get_primary_nav_items() -> list[tuple[str, str]]:
    """Return the primary navigation items (label, page_key)."""
    return PRIMARY_NAV_ITEMS[:]


def get_operation_nav_item() -> tuple[str, str]:
    """Return the secondary operation navigation item."""
    return OPERATION_NAV_ITEM
