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
    ("项目说明", "case_study"),
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
    """Render a lightweight tab-style top navigation."""
    current = st.session_state.get("current_page", DEFAULT_PAGE_KEY)
    render_html(
        """
        <div class="top-nav">
            <span class="top-nav-kicker">尽调评测工作台</span>
            <span class="top-nav-flow">样本库 → 测试 → 复核 → 结论</span>
        </div>
        """
    )
    cols = st.columns(len(_TOP_NAV_ITEMS))
    for col, (label, page_key) in zip(cols, _TOP_NAV_ITEMS):
        with col:
            if st.button(
                label,
                key=f"top_nav_{page_key}",
                type="secondary" if current == page_key else "tertiary",
                use_container_width=True,
            ):
                st.session_state.current_page = page_key
                st.rerun()


def render_sidebar_navigation() -> str:
    valid_page_keys = set(PAGE_CONFIG_BY_KEY)
    if st.session_state.get("current_page") not in valid_page_keys:
        st.session_state.current_page = DEFAULT_PAGE_KEY

    # Single navigation: top bar only. Sidebar is intentionally empty.
    render_top_navigation()
    return st.session_state.current_page


def get_primary_nav_items() -> list[tuple[str, str]]:
    """Return the primary navigation items (label, page_key)."""
    return _TOP_NAV_ITEMS[:]
