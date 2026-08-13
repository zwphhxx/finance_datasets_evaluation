"""Deterministic contracts for post-rerun scroll coordination."""

from unittest.mock import patch

import pytest

from src.ui import scroll


def test_scroll_request_uses_monotonic_request_ids_and_replaces_target():
    state: dict[str, object] = {}

    with patch.object(scroll.st, "session_state", state):
        scroll.request_scroll("top")
        first = dict(state[scroll._SCROLL_TARGET_KEY])
        scroll.request_scroll("#fde-current-sample")
        second = dict(state[scroll._SCROLL_TARGET_KEY])

    assert first == {"target": "top", "request_id": 1}
    assert second == {"target": "#fde-current-sample", "request_id": 2}


def test_scroll_request_rejects_untrusted_selectors():
    with patch.object(scroll.st, "session_state", {}):
        with pytest.raises(ValueError):
            scroll.request_scroll("body > script")


def test_rendered_scroll_retries_with_sticky_offset_and_user_cancellation():
    state = {
        scroll._SCROLL_TARGET_KEY: {
            "target": "#fde-model-details",
            "request_id": 7,
        }
    }
    rendered: list[str] = []

    def capture(script: str, **_kwargs: object) -> None:
        rendered.append(script)

    with (
        patch.object(scroll.st, "session_state", state),
        patch.object(scroll, "render_component_html", capture),
    ):
        assert scroll.render_pending_scroll() is True

    assert scroll._SCROLL_TARGET_KEY not in state
    script = rendered[0]
    assert "[0, 50, 150, 350, 750, 1200]" in script
    assert "main.scrollTop + element.getBoundingClientRect().top" in script
    assert "navHeight - 12" in script
    assert "scrollIntoView" not in script
    for event_name in ["wheel", "touchstart", "touchmove", "keydown"]:
        assert event_name in script
    assert "cancelled = true" in script


def test_rendered_top_scroll_always_targets_zero():
    state = {
        scroll._SCROLL_TARGET_KEY: {
            "target": "top",
            "request_id": 2,
        }
    }
    rendered: list[str] = []

    with (
        patch.object(scroll.st, "session_state", state),
        patch.object(
            scroll,
            "render_component_html",
            lambda script, **_kwargs: rendered.append(script),
        ),
    ):
        assert scroll.render_pending_scroll() is True

    assert 'target === "top" ? 0' in rendered[0]


def test_no_pending_scroll_renders_nothing():
    with (
        patch.object(scroll.st, "session_state", {}),
        patch.object(scroll, "render_component_html") as render,
    ):
        assert scroll.render_pending_scroll() is False
        render.assert_not_called()
