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
from src.ui import components, navigation
from src.ui import report_components as rc
from src.ui.page_config import DEFAULT_PAGE_KEY
from src.ui.report_styles import REPORT_STYLE_CSS


def test_project_method_copy_is_preserved_verbatim():
    from inspect import getsource

    from src.ui.case_study import professional_copy_snapshot

    baseline = Path("tests/fixtures/project_method_copy.txt").read_text(encoding="utf-8")

    assert professional_copy_snapshot() == baseline
    assert "PROCESS_STEPS" not in getsource(professional_copy_snapshot)


def test_project_method_sections_do_not_repeat_the_page_level_appendix_label(monkeypatch):
    from src.ui import case_study

    rendered: list[str] = []
    monkeypatch.setattr(case_study, "render_report_masthead", lambda *args: None)
    monkeypatch.setattr(case_study, "render_scope_ledger", lambda *args: None)
    monkeypatch.setattr(case_study, "render_report_contents", lambda *args: None)
    monkeypatch.setattr(case_study, "render_html", rendered.append)
    monkeypatch.setattr(case_study, "_section_body_html", lambda *args: "<p>正文</p>")

    case_study.render_case_study_page({"data": SimpleNamespace(), "base": SimpleNamespace()})

    assert len(rendered) == len(case_study.CASE_STUDY_SECTIONS)
    assert all("report-section-label" not in html for html in rendered)


def test_samples_use_one_index_renderer_and_archive_tabs():
    source = Path("src/ui/samples.py").read_text(encoding="utf-8")

    assert "def _render_sample_index" in source
    assert "_render_mobile_sample_cards" not in source
    assert source[source.index("def _render_sample_index"):].count(
        "build_sample_table_rows("
    ) == 1
    for label in ["任务与模拟数据", "专业标准答案", "质量要求", "评审重点"]:
        assert label in source


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


def test_trusted_markdown_renderer_preserves_document_structure_and_escapes_dynamic_html(
    monkeypatch,
):
    captured: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        components.st,
        "markdown",
        lambda body, unsafe_allow_html=False: captured.append((body, unsafe_allow_html)),
    )
    markdown = (
        "第一段。\n\n第二段。\n\n"
        "```python\ndef evaluate():\n    return '<script>alert(1)</script>'\n```\n\n"
        "| 维度 | 分数 |\n| --- | --- |\n| 准确性 | 8 |"
    )

    components.render_trusted_markdown_html(markdown)

    rendered, unsafe = captured[0]
    assert unsafe is True
    assert "<p>第一段。</p>\n<p>第二段。</p>" in rendered
    assert "def evaluate():\n    return" in rendered
    assert '<table class="markdown-detail-table">' in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_report_primitives_escape_every_dynamic_value_except_trusted_body_html():
    unsafe = '<script data-test="unsafe">x</script>'

    masthead = rc.report_masthead_html(unsafe, unsafe, unsafe)
    ledger = rc.scope_ledger_html([(unsafe, unsafe)])
    contents = rc.report_contents_html([(unsafe, unsafe, unsafe)])
    section = rc.report_section_html(
        unsafe,
        unsafe,
        unsafe,
        "<strong>可信正文</strong>",
        anchor_id=unsafe,
    )
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
    for html in [masthead, ledger, contents, section, index_row, evidence]:
        assert escaped in html
        assert unsafe not in html
    assert "<strong>可信正文</strong>" in section
    assert f'data-label="{escaped}"' in index_row


def test_report_section_can_omit_a_repeated_label_and_index_values_have_a_stable_wrapper():
    section = rc.report_section_html("01", "", "项目定位", "<p>正文</p>")
    row = rc.report_index_row_html(["模型甲"], labels=["模型"])

    assert "report-section-label" not in section
    assert '<span class="report-index-value">模型甲</span>' in row


def test_model_evidence_actions_use_friendly_names_and_disambiguate_duplicates():
    from src.ui.conclusions import _model_evidence_action_labels

    labels = _model_evidence_action_labels([
        {"model_name": "vendor-a/model-x", "display_name": "Model X"},
        {"model_name": "vendor-b/model-x", "display_name": "Model X"},
        {"model_name": "vendor-c/model-y", "display_name": "Model Y"},
    ])

    assert labels == {
        "vendor-a/model-x": "查看 Model X 证据（1）",
        "vendor-b/model-x": "查看 Model X 证据（2）",
        "vendor-c/model-y": "查看 Model Y 证据",
    }
    assert all("vendor-" not in label for label in labels.values())


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
    assert "<li>准确性 3</li>" in html
    assert "<li>覆盖度 4</li>" in html
    assert "</li></ul>" in html
    assert "trusted" not in signature(rc._detail_html).parameters


def test_evidence_index_uses_domain_labels_full_marks_and_clear_model_scope():
    html = rc.evidence_index_html([
        EvidenceItem(
            run_id="R1",
            case_id="CM-001",
            model_name="deepseek-ai/DeepSeek-V4-Pro",
            title="重大资产重组判断",
            total_score=75.0,
            selection_reason="最低总分",
            weakest_dimension="coverage_score",
            dimension_scores={
                "accuracy_score": 20.0,
                "reasoning_score": 16.0,
                "coverage_score": 14.0,
                "evidence_score": 13.0,
                "expression_score": 12.0,
            },
            rationale={},
            review_note="",
            answer_text="回答",
            gold_answer={},
        )
    ])

    assert "DeepSeek-V4-Pro" in html
    assert "deepseek-ai/DeepSeek-V4-Pro" in html
    assert "模型整体最弱维度" in html
    assert "风险覆盖" in html
    assert "75 / 100" in html
    for value in [
        "专业准确性 20 / 30",
        "推理与场景适配 16 / 20",
        "风险覆盖 14 / 20",
        "依据可靠性 13 / 15",
        "专业表达 12 / 15",
    ]:
        assert value in html
    for internal_name in [
        "accuracy_score",
        "reasoning_score",
        "coverage_score",
        "evidence_score",
        "expression_score",
    ]:
        assert internal_name not in html


def test_evidence_selection_reason_translates_internal_dimension_field():
    html = rc.evidence_index_html([
        EvidenceItem(
            run_id="R1",
            case_id="CM-003",
            model_name="deepseek-ai/DeepSeek-V4-Pro",
            title="控制权变更核查",
            total_score=93.0,
            selection_reason="最弱维度：coverage_score",
            weakest_dimension="coverage_score",
            dimension_scores={"coverage_score": 15.0},
            rationale={},
            review_note="",
            answer_text="回答",
            gold_answer={},
        )
    ])

    assert "最弱维度：风险覆盖" in html
    assert "coverage_score" not in html


def test_evidence_index_typography_prioritizes_decision_facts_over_technical_metadata():
    title_selector = '[data-testid="stMarkdownContainer"] .evidence-index-title {'
    assert title_selector in REPORT_STYLE_CSS
    title_rule = REPORT_STYLE_CSS.split(title_selector, 1)[1].split("}", 1)[0]
    metadata_rule = REPORT_STYLE_CSS.split(
        ".evidence-index-case,", 1
    )[1].split("}", 1)[0]
    label_rule = REPORT_STYLE_CSS.split(
        ".evidence-index-details dt {", 1
    )[1].split("}", 1)[0]
    value_rule = REPORT_STYLE_CSS.rsplit(
        ".evidence-index-details dd {", 1
    )[1].split("}", 1)[0]

    assert "font-size: 1.45rem !important" in title_rule
    assert "font-size: 0.95rem" in metadata_rule
    assert "font-size: 0.82rem" in label_rule
    assert "font-size: 1rem" in value_rule
    assert ".evidence-index-total-value" in REPORT_STYLE_CSS
    assert ".evidence-index-weakest-value" in REPORT_STYLE_CSS
    dimension_rule = REPORT_STYLE_CSS.split(
        ".evidence-index-dimensions {", 1
    )[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in dimension_rule


def test_report_primitives_keep_one_semantic_dom_for_report_rows():
    assert 'class="report-masthead"' in rc.report_masthead_html("标题", "说明")
    assert 'class="report-ledger"' in rc.scope_ledger_html([("范围", "13")])
    assert 'class="report-section"' in rc.report_section_html("01", "范围", "标题", "")
    assert 'class="report-index-row report-index-row--active"' in rc.report_index_row_html(
        ["模型", "判断"], active=True
    )
    assert 'class="evidence-index"' in rc.evidence_index_html([])


def test_report_index_rows_expose_independent_review_group_semantics():
    header = rc.report_index_row_html(["模型", "判断"], header=True)
    labels = ("模型", "样本数／平均分", "当前判断", "主要依据")
    inactive = rc.report_index_row_html(
        ["provider/model-a", "13 个／8.2 分", "谨慎使用", "依据 A"],
        labels=labels,
        active=False,
    )
    active = rc.report_index_row_html(
        ["provider/model-b", "13 个／9.1 分", "可作为参考", "依据 B"],
        labels=labels,
        active=True,
    )

    for html in [header, inactive, active]:
        assert 'role="table"' not in html
        assert 'aria-selected=' not in html
    assert 'aria-hidden="true"' in header
    assert 'role="group"' not in header
    assert 'role="group"' in inactive
    assert 'aria-current=' not in inactive
    assert (
        'aria-label="模型：provider/model-a；样本数／平均分：13 个／8.2 分；当前判断：谨慎使用"'
        in inactive
    )
    assert 'aria-current="true"' in active
    assert 'data-label="样本数／平均分"' in active


def test_model_evidence_action_names_are_unique_without_exposing_raw_model_ids():
    from src.ui import conclusions as ui

    labels = ui._model_evidence_action_labels([
        {"model_name": "provider/model-a", "display_name": "模型甲"},
        {"model_name": "provider/model-b", "display_name": "模型乙"},
    ])

    assert labels == {
        "provider/model-a": "查看 模型甲 证据",
        "provider/model-b": "查看 模型乙 证据",
    }
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
    assert "action_labels[raw_model_id]" in source


def test_model_review_group_label_uses_unique_raw_model_id():
    from src.ui import conclusions as ui

    values = ("同名模型", "13 个／8.8 分", "谨慎使用", "依据")
    label = ui._model_review_accessible_label("provider/raw-model", values)
    html = rc.report_index_row_html(
        values,
        labels=("模型", "样本数／平均分", "当前判断", "主要依据"),
        accessible_label=label,
    )

    assert (
        'aria-label="模型：provider/raw-model；样本数／平均分：13 个／8.8 分；当前判断：谨慎使用"'
        in html
    )
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
    assert "accessible_label=_model_review_accessible_label(raw_model_id, values)" in source


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
    dialog_source = source[
        source.index('@st.dialog("专业标准答案"'):
        source.index("def _gold_evidence_markdown")
    ]
    assert dialog_source.count("render_trusted_markdown_html(") == 3
    assert "render_html(render_markdown_block" not in dialog_source


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


def test_all_records_defers_full_response_rendering_until_explicit_action(monkeypatch):
    from src.ui import conclusions as ui

    class DeferredResponses:
        def to_dict(self, *_args, **_kwargs):
            raise AssertionError("完整回答不应在索引阶段读取")

    scores = pd.DataFrame([
        {"run_id": "R1", "case_id": "C1", "eval_model": "M1", "total_score": 70},
        {"run_id": "R1", "case_id": "C2", "eval_model": "M1", "total_score": 80},
    ])
    report = ConclusionReport(
        scope=ReportScope(sample_count=2, model_count=1, formal_score_count=2),
        formal_scores=scores,
        formal_responses=DeferredResponses(),
        model_summaries=(),
        evidence_by_model={},
    )
    selected_options: list[int] = []
    full_render_calls: list[object] = []
    monkeypatch.setattr(ui.st, "expander", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        ui.st,
        "selectbox",
        lambda _label, options, **_kwargs: selected_options.extend(options) or options[-1],
    )
    monkeypatch.setattr(ui.st, "button", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(ui, "render_inline_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ui,
        "render_trusted_markdown_html",
        lambda *_args, **_kwargs: full_render_calls.append((_args, _kwargs)),
    )

    ui._render_all_records(report)

    assert selected_options == [0, 1]
    assert full_render_calls == []


def test_full_record_dialog_renders_only_the_selected_formal_record(monkeypatch):
    from src.ui import conclusions as ui

    score = {
        "run_id": "R1",
        "case_id": "C2",
        "eval_model": "M1",
        "total_score": 80,
        "accuracy_score": 9,
        "rationale": {"accuracy_score": "第二条评分理由"},
        "review_note": "第二条审阅备注",
    }
    report = ConclusionReport(
        scope=ReportScope(sample_count=2, model_count=1, formal_score_count=2),
        formal_scores=pd.DataFrame([score]),
        formal_responses=pd.DataFrame([
            {"run_id": "R1", "case_id": "C1", "model_name": "M1", "answer_text": "第一条回答"},
            {"run_id": "R1", "case_id": "C2", "model_name": "M1", "answer_text": "第二条回答全文"},
        ]),
        model_summaries=(),
        evidence_by_model={},
    )
    rendered: list[str] = []
    monkeypatch.setattr(ui.st, "caption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui.st, "markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui, "render_trusted_markdown_html", rendered.append)

    ui._render_formal_record_dialog.__wrapped__(report, score)

    assert rendered[0] == "第二条回答全文"
    assert "第二条评分理由" in rendered[1]
    assert "第二条审阅备注" in rendered[1]
    assert all("第一条回答" not in value for value in rendered)


def test_conclusion_records_use_one_report_boundary_without_dead_judgment_tone():
    from src.ui import conclusions as ui

    assert list(signature(ui._render_all_records).parameters) == ["report"]
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
    assert "def _judgment_tone(" not in source


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
    assert navigation.OPERATION_NAV_ITEM == ("发起评测", "test_run")
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
