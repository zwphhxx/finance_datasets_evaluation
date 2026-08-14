"""Behavioral contracts for the review-first report entry and navigation."""

from contextlib import nullcontext
from html import escape
from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from app.services.conclusion_read_model import ConclusionReport, ReportScope
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


def test_report_semantic_headers_override_hidden_streamlit_chrome():
    masthead_rule = REPORT_STYLE_CSS.split(".report-masthead {", 1)[1].split("}", 1)[0]
    section_heading_rule = REPORT_STYLE_CSS.split(".report-section-heading {", 1)[1].split("}", 1)[0]

    assert "display: block !important" in masthead_rule
    assert "visibility: visible !important" in masthead_rule
    assert "height: auto !important" in masthead_rule
    assert "display: grid !important" in section_heading_rule
    assert "visibility: visible !important" in section_heading_rule
    assert "height: auto !important" in section_heading_rule
    assert '[data-testid="stMarkdownContainer"] .report-masthead-title' in REPORT_STYLE_CSS
    assert '[data-testid="stMarkdownContainer"] .report-section-title' in REPORT_STYLE_CSS


def test_report_primitives_escape_every_dynamic_value_except_trusted_body_html():
    unsafe = '<script data-test="unsafe">x</script>'

    masthead = rc.report_masthead_html(unsafe, unsafe, unsafe)
    ledger = rc.scope_ledger_html([(unsafe, unsafe)])
    section = rc.report_section_html(unsafe, unsafe, unsafe, "<strong>可信正文</strong>")
    index_row = rc.report_index_row_html([unsafe], labels=[unsafe], active=True)
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
    assert f'data-label="{escaped}"' in index_row


def test_evidence_index_escapes_each_displayed_field_and_omits_technical_run_id():
    markers = {
        "case_id": '<case-id data-test="unsafe">',
        "model_name": '<model-name data-test="unsafe">',
        "title": '<title data-test="unsafe">',
        "selection_reason": '<selection-reason data-test="unsafe">',
        "weakest_dimension": '<weakest-dimension data-test="unsafe">',
        "dimension_field": '<dimension-field data-test="unsafe">',
        "rationale_key": "<rationale-key>",
        "rationale_value": "<rationale-value>",
        "review_note": '<review-note data-test="unsafe">',
        "answer_text": '<answer-text data-test="unsafe">',
        "gold_key": "<gold-key>",
        "gold_value": "<gold-value>",
    }
    technical_run_id = "RUN-ID-MUST-NOT-RENDER"
    html = rc.evidence_index_html([
        EvidenceItem(
            run_id=technical_run_id,
            case_id=markers["case_id"],
            model_name=markers["model_name"],
            title=markers["title"],
            total_score=7.25,
            selection_reason=markers["selection_reason"],
            weakest_dimension=markers["weakest_dimension"],
            dimension_scores={markers["dimension_field"]: 3.5},
            rationale={markers["rationale_key"]: markers["rationale_value"]},
            review_note=markers["review_note"],
            answer_text=markers["answer_text"],
            gold_answer={markers["gold_key"]: markers["gold_value"]},
        )
    ])

    for marker in markers.values():
        assert marker not in html
        assert escape(marker, quote=True) in html
    assert "7.25" in html
    assert "3.5" in html
    assert technical_run_id not in html


def test_evidence_dimension_scores_are_a_valid_styled_list_without_raw_html_flag():
    html = rc.evidence_index_html([
        EvidenceItem(
            run_id="R1",
            case_id="C1",
            model_name="M1",
            title="标题",
            total_score=7.0,
            selection_reason="最低总分",
            weakest_dimension="准确性",
            dimension_scores={"准确性": 3.0, "覆盖度": 4.0},
            rationale={},
            review_note="",
            answer_text="回答",
            gold_answer={},
        )
    ])

    assert '<ul class="evidence-index-dimensions">' in html
    assert "<li>准确性：3.0</li>" in html
    assert "<li>覆盖度：4.0</li>" in html
    assert "</li></ul>" in html
    assert "trusted" not in signature(rc._detail_html).parameters


def test_report_primitives_keep_one_semantic_dom_for_report_rows():
    assert 'class="report-masthead"' in rc.report_masthead_html("标题", "说明")
    assert 'class="report-ledger"' in rc.scope_ledger_html([("范围", "13")])
    assert 'class="report-section"' in rc.report_section_html("01", "范围", "标题", "")
    assert 'class="report-index-row report-index-row--active"' in rc.report_index_row_html(
        ["模型", "判断"], active=True
    )
    assert 'class="evidence-index"' in rc.evidence_index_html([])


def test_conclusion_page_is_report_first_and_never_surfaces_excluded_count():
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
    page = source[
        source.index("def render_conclusions_page"):
        source.index("def _render_executive_conclusion")
    ]

    assert page.index("render_report_masthead") < page.index("render_scope_ledger")
    assert page.index("render_scope_ledger") < page.index("_render_executive_conclusion")
    assert page.index("_render_executive_conclusion") < page.index("_render_model_recommendations")
    assert page.index("_render_model_recommendations") < page.index("_render_evidence_index")
    assert page.index("_render_evidence_index") < page.index("_render_all_records")
    assert "排除项" not in source
    assert "_render_mobile_model_cards" not in source


def test_available_conclusion_report_renders_one_ordered_review_flow(monkeypatch):
    from src.ui import conclusions as ui
    from src.ui.conclusions_data import ConclusionSource

    report = ConclusionReport(
        scope=ReportScope(sample_count=0, model_count=0, formal_score_count=0),
        formal_scores=pd.DataFrame(),
        formal_responses=pd.DataFrame(),
        model_summaries=(),
        evidence_by_model={},
    )
    events: list[str] = []
    monkeypatch.setattr(ui.cd, "load_conclusion_source", lambda *_args: ConclusionSource(True, report))
    monkeypatch.setattr(ui.ds, "get_rubric_dimensions", lambda: [])
    monkeypatch.setattr(ui, "render_report_masthead", lambda *_args: events.append("masthead"))
    monkeypatch.setattr(ui, "render_scope_ledger", lambda *_args: events.append("scope"))
    monkeypatch.setattr(ui, "_render_executive_conclusion", lambda *_args: events.append("executive"))
    monkeypatch.setattr(ui, "_render_model_recommendations", lambda *_args: events.append("models") or "")
    monkeypatch.setattr(ui, "_render_evidence_index", lambda *_args: events.append("evidence"))
    monkeypatch.setattr(ui, "_render_all_records", lambda *_args: events.append("records"))
    monkeypatch.setattr(ui, "_render_data_source_notice", lambda *_args: None)

    ui.render_conclusions_page({
        "base": SimpleNamespace(tasks=pd.DataFrame(), gold_answer_map={}),
    })

    assert events == ["masthead", "scope", "executive", "models", "evidence", "records"]


def test_unavailable_conclusion_source_does_not_render_empty_database_state(monkeypatch):
    from src.ui import conclusions as ui
    from src.ui.conclusions_data import ConclusionSource

    events: list[str] = []
    monkeypatch.setattr(ui.cd, "load_conclusion_source", lambda *_args: ConclusionSource(False, None, "offline"))
    monkeypatch.setattr(ui.ds, "get_rubric_dimensions", lambda: [])
    monkeypatch.setattr(ui, "render_report_masthead", lambda *_args: events.append("masthead"))
    monkeypatch.setattr(ui, "render_persistence_status", lambda message: events.append(f"unavailable:{message}"))
    monkeypatch.setattr(ui, "_render_model_recommendations", lambda *_args: events.append("empty"))

    ui.render_conclusions_page({
        "base": SimpleNamespace(tasks=pd.DataFrame(), gold_answer_map={}),
    })

    assert events == ["masthead", "unavailable:offline"]


def test_each_evidence_item_exposes_three_full_record_dialogs():
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")

    for label in ["查看专业标准答案", "查看模型回答全文", "查看评分理由"]:
        assert label in source
    assert "[:900]" not in source
    assert "[: 900]" not in source


def test_evidence_dialog_markdown_preserves_full_source_values():
    from src.ui import conclusions as ui

    long_answer = "回答全文" * 1000
    item = EvidenceItem(
        run_id="RUN-RAW",
        case_id="CASE-RAW",
        model_name="provider/raw-model",
        title="专业任务",
        total_score=72,
        selection_reason="最低总分",
        weakest_dimension="依据可靠性",
        dimension_scores={"evidence_score": 8},
        rationale={"evidence_score": "评分理由原文"},
        review_note="审阅备注原文",
        answer_text=long_answer,
        gold_answer={"core_conclusion": "专业标准答案原文"},
    )

    assert ui._answer_evidence_markdown(item) == long_answer
    rationale = ui._rationale_evidence_markdown(item)
    gold = ui._gold_evidence_markdown(item)
    assert "评分理由原文" in rationale
    assert "审阅备注原文" in rationale
    assert "专业标准答案原文" in gold
    assert len(ui._answer_evidence_markdown(item)) == len(long_answer)


def test_model_evidence_selection_keeps_raw_id_and_requests_evidence_anchor(monkeypatch):
    from src.ui import conclusions as ui

    state: dict[str, object] = {}
    targets: list[str] = []
    monkeypatch.setattr(ui.st, "session_state", state)
    monkeypatch.setattr(ui, "request_scroll", targets.append)

    ui._select_model_evidence("provider/raw-model")

    assert state["conclusion_selected_model_id"] == "provider/raw-model"
    assert targets == ["#fde-evidence-index"]


def test_evidence_summary_hides_full_documents_until_dialog_opened():
    item = EvidenceItem(
        run_id="RUN-1",
        case_id="C1",
        model_name="M1",
        title="标题",
        total_score=7.0,
        selection_reason="最低总分",
        weakest_dimension="准确性",
        dimension_scores={"准确性": 3.0},
        rationale={"仅弹层": "评分理由"},
        review_note="仅弹层备注",
        answer_text="仅弹层回答",
        gold_answer={"仅弹层": "标准答案"},
    )

    html = rc.evidence_index_html([item], include_full_details=False)

    assert "C1" in html
    assert "最低总分" in html
    assert "仅弹层回答" not in html
    assert "标准答案" not in html
    assert "仅弹层备注" not in html


def test_evaluation_page_has_one_product_pipeline_and_no_demo_or_score_action():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

    assert 'key="test_run_start_evaluation"' in source
    assert 'key="test_run_continue_evaluation"' in source
    assert 'key="test_run_score_run"' not in source
    assert "生成 AI 评分" not in source
    assert "演示模式" not in source
    assert "从演示结果文件恢复" not in source


def test_evaluation_page_uses_workflow_and_checkpoint_for_run_state():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

    assert "EvaluationWorkflow" in source
    assert "_PARTIAL_OUTCOMES_KEY" not in source
    assert "_PARTIAL_SCORE_OUTCOMES_KEY" not in source
    assert "build_evaluation_config_from_checkpoint" in source
    assert "workflow.continue_evaluation(status.run_id, checkpoint_config)" in source


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
