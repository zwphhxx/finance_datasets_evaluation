"""Saved-feedback regression: missing labels must never become a clean bill of health."""

import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app.services import conclusions as cc
from app.services.conclusion_read_model import ConclusionReport, ReportScope


def scores():
    return pd.DataFrame([
        dict(run_id="test-run", case_id=f"TEST-{i}", eval_model="test-model", judge_status="success",
             total_score=100, accuracy_score=30, reasoning_score=20, coverage_score=20,
             evidence_score=15, expression_score=15, review_note="")
        for i in range(3)
    ])


def render_overview(monkeypatch, frame):
    from src.ui import workbench

    def forbidden(*args, **kwargs):
        raise AssertionError("Overview must not call a provider or database")

    monkeypatch.setattr("app.persistence.get_result_store", forbidden)
    monkeypatch.setattr("app.models.registry.get_text_provider", forbidden)
    summaries = tuple(cc.build_model_issue_summaries(frame))
    report = ConclusionReport(ReportScope(3, 1, 3), frame, pd.DataFrame(), summaries, {})
    monkeypatch.setattr(workbench, "load_workbench_source", lambda _: workbench.cd.ConclusionSource(True, report))
    before = frame.copy(deep=True)
    app = AppTest.from_string("""
from types import SimpleNamespace
import pandas as pd
from src.ui.case_study import render_case_study_page
render_case_study_page({'base':SimpleNamespace(tasks=pd.DataFrame())})
""").run()
    assert not app.exception
    pd.testing.assert_frame_equal(frame, before)
    return app


def test_high_scores_do_not_turn_missing_error_labels_into_no_issues():
    summary = cc.build_model_issue_summaries(scores())[0]
    assert "当前样本内未见突出问题" not in summary["main_issues"]
    assert any("未形成稳定的问题归纳" in text for text in summary["main_issues"])


def test_homepage_shows_saved_lowest_feedback_not_first_positive_note(monkeypatch):
    frame = scores()
    frame.loc[0, "review_note"] = "测试回答覆盖完整。"
    frame.loc[1, "total_score"] = 96
    frame.loc[1, "coverage_score"] = 16
    frame.loc[1, "review_note"] = "测试回答遗漏了合同履行条件，结论过于绝对。"
    app = render_overview(monkeypatch, frame)
    text = "\n".join(t.value for t in app.text)
    assert "TEST-1" in text
    assert "遗漏了合同履行条件，结论过于绝对" in text
    assert "当前样本内未见突出问题" not in text
    assert any("未保存结构化引文" in c.value for c in app.caption)
    assert any("单题反馈" in c.value for c in app.caption)


@pytest.mark.parametrize("encoded", [False, True])
def test_homepage_can_show_rationale_without_review_note(monkeypatch, encoded):
    frame = scores()
    reason = {"coverage_score": "测试回答未说明材料核查范围。"}
    frame["rationale"] = pd.Series([json.dumps(reason, ensure_ascii=False) if encoded else reason, None, None])
    app = render_overview(monkeypatch, frame)
    text = "\n".join(t.value for t in app.text)
    assert "TEST-0" in text
    assert "coverage_score：测试回答未说明材料核查范围。" in text
    assert "当前样本内未见突出问题" not in text


def test_missing_feedback_stays_unknown(monkeypatch):
    app = render_overview(monkeypatch, scores())
    text = "\n".join(t.value for t in app.text)
    assert "未保存可展示的评分说明或维度理由" in text
    assert "不能据此判断没有问题" in text
    assert "当前样本内未见突出问题" not in text
