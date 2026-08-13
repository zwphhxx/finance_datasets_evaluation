"""Regression contracts for the interview-review-first UI pass."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_primary_navigation_prioritizes_conclusions_without_marker_spacer():
    from src.ui.navigation import OPERATION_NAV_ITEM, PRIMARY_NAV_ITEMS

    assert [page_key for _, page_key in PRIMARY_NAV_ITEMS] == [
        "conclusions",
        "case_study",
        "samples",
    ]
    assert OPERATION_NAV_ITEM == ("评测操作", "test_run")
    navigation = _source("src/ui/navigation.py")
    components = _source("src/ui/components.py")
    assert "top-nav-current-marker" not in navigation
    assert "top-nav-current-marker" not in components
    assert 'button[kind="secondary"]::after' in components


def test_navigation_queues_and_consumes_a_post_render_scroll_reset():
    scroll_path = ROOT / "src/ui/scroll.py"
    assert scroll_path.exists(), "navigation scroll coordination must live in src/ui/scroll.py"
    scroll_source = scroll_path.read_text(encoding="utf-8")
    navigation = _source("src/ui/navigation.py")
    app = _source("app.py")

    assert "def request_scroll(" in scroll_source
    assert "def render_pending_scroll(" in scroll_source
    assert 'section[data-testid="stMain"]' in scroll_source
    assert "scrollTo" in scroll_source
    assert 'request_scroll("top")' in navigation
    assert app.index("PAGES[page](data_bundle)") < app.index("render_pending_scroll()")


def test_mobile_navigation_and_home_facts_use_equal_columns():
    responsive = _source("src/ui/responsive.py")
    mobile = responsive.split("@media (max-width: 760px)", 1)[1]

    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in mobile
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in mobile
    assert "grid-template-columns: repeat(4, max-content)" not in mobile


def test_mobile_sticky_navigation_is_applied_to_streamlit_layout_wrapper():
    responsive = _source("src/ui/responsive.py")
    mobile = responsive.split("@media (max-width: 760px)", 1)[1]

    assert '[data-testid="stLayoutWrapper"]:has(> [data-testid="stHorizontalBlock"]' in mobile
    assert "position: sticky" in mobile
    assert "background: color-mix(in srgb, var(--fde-bg) 92%, transparent)" not in mobile


def test_samples_offer_desktop_table_mobile_cards_and_one_maintenance_entry():
    source = _source("src/ui/samples.py")
    title_bar = source[source.index("def _render_samples_title_bar"): source.index("def render_samples_page")]

    assert 'st.popover("样本维护"' in title_bar
    assert "samples_create_open" in title_bar
    assert "samples_import_csv_open" in title_bar
    assert 'key="samples_desktop_index"' in source
    assert 'key="samples_mobile_index"' in source
    assert "def _render_mobile_sample_cards(" in source
    assert 'request_scroll("#fde-current-sample")' in source
    assert "mobile-scroll-hint" not in source


def test_conclusions_use_responsive_selection_without_duplicate_chart():
    source = _source("src/ui/conclusions.py")

    assert "themed_bar_chart" not in source
    assert "mobile-scroll-hint" not in source
    assert 'key="conclusion_desktop_judgment"' in source
    assert 'key="conclusion_mobile_judgment"' in source
    assert "def _render_mobile_model_cards(" in source
    assert 'request_scroll("#fde-model-details")' in source
    assert 'st.popover("数据维护"' in source


def test_test_run_uses_compact_preview_stage_links_and_contextual_notice():
    source = _source("src/ui/test_run.py")

    assert "_ANSWER_PREVIEW_LIMIT = 900" in source
    assert "def _render_stage_navigation(" in source
    for anchor in ["#fde-test-run-configuration", "#fde-test-run-answers", "#fde-test-run-scores"]:
        assert anchor in source
    assert 'action_type="tertiary"' in source
    assert "_run_is_active()" in source
    run_button = source[source.index("def _render_run_button"): source.index("def _render_live_run_queue")]
    assert "当前未配置模型服务密钥，暂不能发起真实调用。" not in run_button


def test_responsive_css_hides_alternate_views_and_styles_disabled_primary():
    responsive = _source("src/ui/responsive.py")
    components = _source("src/ui/components.py")

    for selector in [
        ".st-key-samples_mobile_index",
        ".st-key-conclusion_mobile_judgment",
        ".st-key-samples_desktop_index",
        ".st-key-conclusion_desktop_judgment",
    ]:
        assert selector in responsive
    assert "button[kind=\"primary\"]:disabled" in components
    assert ".st-key-test_run_score_action" in responsive
