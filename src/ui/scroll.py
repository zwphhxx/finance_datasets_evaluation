"""Post-rerun scroll coordination for the single-page Streamlit UI."""

from __future__ import annotations

import json
import re

import streamlit as st
from streamlit.components.v1 import html as render_component_html

_SCROLL_TARGET_KEY = "_fde_pending_scroll_target"
_ANCHOR_PATTERN = re.compile(r"^#fde-[a-z0-9-]+$")


def request_scroll(target: str = "top") -> None:
    """Queue a trusted page target to scroll to after the next full render."""
    normalized = str(target or "top").strip()
    if normalized != "top" and not _ANCHOR_PATTERN.fullmatch(normalized):
        raise ValueError(f"unsupported scroll target: {target}")
    st.session_state[_SCROLL_TARGET_KEY] = normalized


def render_pending_scroll() -> bool:
    """Consume the queued target and scroll the parent Streamlit main region."""
    target = st.session_state.pop(_SCROLL_TARGET_KEY, None)
    if not target:
        return False

    target_json = json.dumps(str(target), ensure_ascii=True)
    script = f"""
    <script>
    (() => {{
        const root = window.parent.document;
        const main = root.querySelector('section[data-testid="stMain"]');
        const target = {target_json};
        if (!main) return;
        if (target === "top") {{
            main.scrollTo({{ top: 0, left: 0, behavior: "auto" }});
            return;
        }}
        const element = root.querySelector(target);
        if (element) element.scrollIntoView({{ block: "start", behavior: "auto" }});
    }})();
    </script>
    """
    render_component_html(
        script,
        width=0,
        height=0,
        scrolling=False,
        tab_index=-1,
    )
    return True

