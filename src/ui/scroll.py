"""Post-rerun scroll coordination for the single-page Streamlit UI."""

from __future__ import annotations

import json
import re

import streamlit as st
from streamlit.components.v1 import html as render_component_html

_SCROLL_TARGET_KEY = "_fde_pending_scroll_target"
_SCROLL_REQUEST_SEQUENCE_KEY = "_fde_scroll_request_sequence"
_ANCHOR_PATTERN = re.compile(r"^#fde-[a-z0-9-]+$")


def request_scroll(target: str = "top") -> None:
    """Queue a trusted page target to scroll to after the next full render."""
    normalized = str(target or "top").strip()
    if normalized != "top" and not _ANCHOR_PATTERN.fullmatch(normalized):
        raise ValueError(f"unsupported scroll target: {target}")
    request_id = int(st.session_state.get(_SCROLL_REQUEST_SEQUENCE_KEY, 0)) + 1
    st.session_state[_SCROLL_REQUEST_SEQUENCE_KEY] = request_id
    st.session_state[_SCROLL_TARGET_KEY] = {
        "target": normalized,
        "request_id": request_id,
    }


def render_pending_scroll() -> bool:
    """Consume the queued target and scroll the parent Streamlit main region."""
    pending = st.session_state.pop(_SCROLL_TARGET_KEY, None)
    if not pending:
        return False

    if isinstance(pending, dict):
        target = str(pending.get("target") or "top")
        request_id = int(pending.get("request_id") or 0)
    else:
        # A rerun may still contain the previous one-string session value.
        target = str(pending)
        request_id = int(st.session_state.get(_SCROLL_REQUEST_SEQUENCE_KEY, 0))

    if target != "top" and not _ANCHOR_PATTERN.fullmatch(target):
        return False

    target_json = json.dumps(target, ensure_ascii=True)
    script = f"""
    <script>
    (() => {{
        const owner = window.parent;
        const root = owner.document;
        const main = root.querySelector('section[data-testid="stMain"]');
        const target = {target_json};
        const requestId = {request_id};
        if (!main) return;

        owner.__fdeActiveScrollRequestId = requestId;
        let cancelled = false;
        const cancel = () => {{ cancelled = true; }};
        const interactions = [
            [main, "wheel"],
            [main, "touchstart"],
            [main, "touchmove"],
            [root, "keydown"],
        ];
        interactions.forEach(([node, eventName]) =>
            node.addEventListener(eventName, cancel, {{ capture: true, passive: true }})
        );

        const attempt = () => {{
            if (cancelled || owner.__fdeActiveScrollRequestId !== requestId) return;
            const element = target === "top" ? null : root.querySelector(target);
            if (target !== "top" && !element) return;
            const nav = root.querySelector(
                '[data-testid="stLayoutWrapper"]:has(.top-nav-brand)'
            ) || root.querySelector(
                '[data-testid="stHorizontalBlock"]:has(.top-nav-brand)'
            );
            const navHeight = nav ? nav.getBoundingClientRect().height : 0;
            const top = target === "top" ? 0 : Math.max(
                0,
                main.scrollTop + element.getBoundingClientRect().top - navHeight - 12
            );
            main.scrollTo({{ top, left: 0, behavior: "auto" }});
        }};

        [0, 50, 150, 350, 750, 1200].forEach((delay) =>
            window.setTimeout(attempt, delay)
        );
        window.setTimeout(() => {{
            interactions.forEach(([node, eventName]) =>
                node.removeEventListener(eventName, cancel, true)
            );
        }}, 1300);
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
