from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _script() -> str:
    return '''
import pandas as pd

from app.services.conclusion_read_model import ConclusionReport, ReportScope
from app.services.evidence_index import EvidenceItem
from src.ui import conclusions as ui
from src.ui.conclusions_data import ConclusionSource


def evidence(run_id, case_id, model_id, reason, score):
    return EvidenceItem(
        run_id=run_id,
        case_id=case_id,
        model_name=model_id,
        title=f"{case_id} 的完整专业任务标题",
        total_score=score,
        selection_reason=reason,
        weakest_dimension="coverage_score",
        dimension_scores={
            "accuracy_score": 20,
            "reasoning_score": 14,
            "coverage_score": 12,
            "evidence_score": 10,
            "expression_score": 11,
        },
        rationale={"coverage_score": "评分理由全文"},
        review_note="审阅备注全文",
        answer_text="模型回答全文",
        gold_answer={"core_conclusion": "专业标准答案全文"},
    )


model_a = (
    evidence("R1", "C-low", "vendor/a", "最低总分", 61),
    evidence("R1", "C-high", "vendor/a", "最高总分", 98),
    evidence("R1", "C-risk", "vendor/a", "最弱维度：coverage_score", 75),
)
model_b = (
    evidence("R2", "B-low", "vendor/b", "最低总分", 70),
    evidence("R2", "B-high", "vendor/b", "最高总分", 96),
)
summaries = (
    {"model_name": "vendor/a", "display_name": "模型 A", "sample_count": 3, "avg_total": 78, "current_suggestion": "谨慎参考", "main_issues": ["依据不足"]},
    {"model_name": "vendor/b", "display_name": "模型 B", "sample_count": 2, "avg_total": 83, "current_suggestion": "可作为参考", "main_issues": ["风险覆盖"]},
)
report = ConclusionReport(
    scope=ReportScope(sample_count=3, model_count=2, formal_score_count=5),
    formal_scores=pd.DataFrame(),
    formal_responses=pd.DataFrame(),
    model_summaries=summaries,
    evidence_by_model={"vendor/a": model_a, "vendor/b": model_b},
)
originals = {
    "source": ui.cd.load_conclusion_source,
    "rubric": ui.ds.get_rubric_dimensions,
    "store": ui.get_result_store,
    "records": ui._render_all_records,
    "notice": ui._render_data_source_notice,
}
ui.cd.load_conclusion_source = lambda *_args: ConclusionSource(True, report)
ui.ds.get_rubric_dimensions = lambda: []
ui.get_result_store = lambda: None
ui._render_all_records = lambda *_args: None
ui._render_data_source_notice = lambda *_args: None
try:
    ui.render_conclusions_page({"base": type("Base", (), {"tasks": pd.DataFrame(), "gold_answer_map": {}})()})
finally:
    ui.cd.load_conclusion_source = originals["source"]
    ui.ds.get_rubric_dimensions = originals["rubric"]
    ui.get_result_store = originals["store"]
    ui._render_all_records = originals["records"]
    ui._render_data_source_notice = originals["notice"]
'''


def test_conclusion_evidence_controls_share_state_and_render_one_detail():
    at = AppTest.from_string(_script()).run(timeout=30)

    assert list(at.exception) == []
    assert next(widget for widget in at.radio if widget.key == "conclusion_model_selector_desktop").value == "vendor/a"
    assert next(widget for widget in at.selectbox if widget.key == "conclusion_model_selector_mobile").value == "vendor/a"
    assert len([button for button in at.button if str(button.key).startswith("conclusion_evidence_open_")]) == 1
    assert len([button for button in at.button if str(button.key).startswith("conclusion_select_evidence_")]) == 3

    model = next(widget for widget in at.radio if widget.key == "conclusion_model_selector_desktop")
    model.set_value("vendor/b").run(timeout=30)

    assert list(at.exception) == []
    assert at.session_state["conclusion_selected_model_id"] == "vendor/b"
    assert tuple(at.session_state["conclusion_selected_evidence_key"]) == ("R2", "B-low", "vendor/b")
    assert next(widget for widget in at.selectbox if widget.key == "conclusion_model_selector_mobile").value == "vendor/b"
    assert len([button for button in at.button if str(button.key).startswith("conclusion_select_evidence_")]) == 2
    assert len([button for button in at.button if str(button.key).startswith("conclusion_evidence_open_")]) == 1


def test_full_evidence_dialog_opens_without_duplicate_widget_errors():
    at = AppTest.from_string(_script()).run(timeout=30)
    open_button = next(
        button for button in at.button if str(button.key).startswith("conclusion_evidence_open_")
    )

    open_button.click().run(timeout=30)

    assert list(at.exception) == []
    assert [tab.label for tab in at.tabs] == ["评分理由", "专业标准答案", "模型回答"]
