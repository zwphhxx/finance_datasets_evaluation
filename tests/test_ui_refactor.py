"""Source-level wiring guards for the Streamlit conclusion page."""

from pathlib import Path


def test_conclusion_page_uses_only_the_current_compatible_cohort():
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
    render_body = source[
        source.index("def render_conclusions_page"):
        source.index("# --------------------------------------------------------------------------- #")
    ]

    assert "cd.load_current_cohort_scores()" in render_body
    assert "cc.load_live_scores()" not in render_body
