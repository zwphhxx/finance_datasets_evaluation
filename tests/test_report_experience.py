"""Behavioral contracts for the review-first report entry and navigation."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from app.services.evidence_index import EvidenceItem
from src.ui import navigation
from src.ui import report_components as rc
from src.ui.page_config import DEFAULT_PAGE_KEY
from src.ui.report_styles import REPORT_STYLE_CSS


def test_report_styles_are_flat_and_editorial():
    for required in [
        ".report-masthead",
        ".report-ledger",
        ".report-index-row",
        ".evidence-index",
    ]:
        assert required in REPORT_STYLE_CSS
    for banned in ["linear-gradient", "box-shadow:", "border-radius: 12px", ".kpi-card"]:
        assert banned not in REPORT_STYLE_CSS


def test_report_primitives_escape_every_dynamic_value_except_trusted_body_html():
    unsafe = '<script data-test="unsafe">x</script>'

    masthead = rc.report_masthead_html(unsafe, unsafe, unsafe)
    ledger = rc.scope_ledger_html([(unsafe, unsafe)])
    section = rc.report_section_html(unsafe, unsafe, unsafe, "<strong>可信正文</strong>")
    index_row = rc.report_index_row_html([unsafe], active=True)
    evidence = rc.evidence_index_html([
        EvidenceItem(
            run_id=unsafe,
            case_id=unsafe,
            model_name=unsafe,
            title=unsafe,
            total_score=1.0,
            selection_reason=unsafe,
            weakest_dimension=unsafe,
            dimension_scores={unsafe: 1.0},
            rationale={unsafe: unsafe},
            review_note=unsafe,
            answer_text=unsafe,
            gold_answer={unsafe: unsafe},
        )
    ])

    escaped = "&lt;script data-test=&quot;unsafe&quot;&gt;x&lt;/script&gt;"
    for html in [masthead, ledger, section, index_row, evidence]:
        assert escaped in html
        assert unsafe not in html
    assert "<strong>可信正文</strong>" in section


def test_report_primitives_keep_one_semantic_dom_for_report_rows():
    assert 'class="report-masthead"' in rc.report_masthead_html("标题", "说明")
    assert 'class="report-ledger"' in rc.scope_ledger_html([("范围", "13")])
    assert 'class="report-section"' in rc.report_section_html("01", "范围", "标题", "")
    assert 'class="report-index-row report-index-row--active"' in rc.report_index_row_html(
        ["模型", "判断"], active=True
    )
    assert 'class="evidence-index"' in rc.evidence_index_html([])


class _SessionState(dict):
    def __getattr__(self, name: str) -> object:
        return self[name]

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


def test_conclusions_are_default_and_operation_is_secondary():
    assert DEFAULT_PAGE_KEY == "conclusions"
    assert navigation.PRIMARY_NAV_ITEMS == [
        ("评测结论", "conclusions"),
        ("项目说明", "case_study"),
        ("样本库", "samples"),
    ]
    assert navigation.OPERATION_NAV_ITEM == ("评测操作", "test_run")
    assert set(navigation.PAGES) == {"conclusions", "case_study", "samples", "test_run"}


def test_navigation_click_uses_stable_key_and_queues_top_scroll():
    session_state = _SessionState(current_page="case_study")
    button_keys: list[str] = []
    scroll_targets: list[str] = []

    def button(_label: str, *, key: str, **_kwargs: object) -> bool:
        button_keys.append(key)
        return key == "top_nav_conclusions"

    with (
        patch.object(navigation.st, "session_state", session_state),
        patch.object(navigation.st, "columns", side_effect=lambda *_args, **_kwargs: [nullcontext()] * 3),
        patch.object(navigation.st, "button", side_effect=button),
        patch.object(navigation.st, "rerun") as rerun,
        patch.object(navigation, "request_scroll", side_effect=scroll_targets.append),
    ):
        navigation.render_top_navigation()

    assert button_keys == [
        "top_nav_conclusions",
        "top_nav_case_study",
        "top_nav_samples",
        "top_nav_operation",
    ]
    assert session_state["current_page"] == "conclusions"
    assert scroll_targets == ["top"]
    rerun.assert_called_once_with()


def test_navigation_uses_no_separate_current_marker_or_placeholder():
    source = Path("src/ui/navigation.py").read_text(encoding="utf-8")

    assert "top-nav-current-marker" not in source
    assert "top_nav_current_marker" not in source
    assert 'request_scroll("top")' in source


def test_mobile_navigation_keeps_operation_secondary_and_right_aligned():
    responsive = Path("src/ui/responsive.py").read_text(encoding="utf-8")
    mobile = responsive.split("@media (max-width: 760px)", 1)[1]

    assert ".st-key-top_nav_review_region" in mobile
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in mobile
    assert ".st-key-top_nav_operation_region .stButton" in mobile
    operation_button_rule = mobile.split(
        ".st-key-top_nav_operation_region .stButton > button {", 1
    )[1].split("}", 1)[0]
    assert "width: auto !important;" in operation_button_rule
