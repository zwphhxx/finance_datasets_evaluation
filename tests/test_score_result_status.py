"""Presentation-state contracts for one durable evaluation batch."""

from app.services.evaluation_workflow import (
    COMPLETED,
    FAILED,
    INTERRUPTED,
    PARTIAL,
    RUNNING,
    STOPPED,
    EvaluationRunStatus,
)
from src.ui import evaluation_results
from src.ui.evaluation_results import evaluation_status_copy


def _status(state: str) -> EvaluationRunStatus:
    return EvaluationRunStatus(
        run_id="RUN-1",
        score_run_id="SCORE-1",
        state=state,
        total=3,
        succeeded=1,
        failed=1,
        pending=1,
        resumable=state == INTERRUPTED,
        message="数据库写入失败" if state == STOPPED else "",
        persistence_failed_in_session=state == STOPPED,
    )


def test_evaluation_status_copy_has_one_distinct_title_and_summary_for_each_state():
    copies = {
        state: evaluation_status_copy(_status(state))
        for state in (RUNNING, COMPLETED, PARTIAL, FAILED, INTERRUPTED, STOPPED)
    }

    assert len({title for title, _summary in copies.values()}) == 6
    assert len({summary for _title, summary in copies.values()}) == 6


def test_only_interrupted_status_is_resumable():
    statuses = [_status(state) for state in (RUNNING, COMPLETED, PARTIAL, FAILED, INTERRUPTED, STOPPED)]

    assert [status.state for status in statuses if status.resumable] == [INTERRUPTED]


def test_each_status_renders_exactly_one_title_and_one_summary(monkeypatch):
    class FakeStreamlit:
        def __init__(self):
            self.titles = []
            self.summaries = []

        def markdown(self, value):
            self.titles.append(value)

        def caption(self, value):
            self.summaries.append(value)

    for state in (RUNNING, COMPLETED, PARTIAL, FAILED, INTERRUPTED, STOPPED):
        fake = FakeStreamlit()
        monkeypatch.setattr(evaluation_results, "st", fake)

        evaluation_results.render_evaluation_status(_status(state))

        assert len(fake.titles) == 1
        assert len(fake.summaries) == 1


def _record_app(answers, scores, dimensions):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_string(
        "from src.ui.evaluation_results import render_run_record\n"
        + f"render_run_record({answers!r}, {scores!r}, {dimensions!r})"
    ).run()


def test_persisted_run_records_render_live_model_names_without_losing_full_id():
    answers = [
        {"case_id": f"CM-00{i}", "model_name": name, "answer_text": "回答", "run_status": "success"}
        for i, name in enumerate(["provider/model-alpha", "vendor/unknown-model", ""], 1)
    ]
    scores = [
        {"case_id": a["case_id"], "eval_model": a["model_name"], "total_score": 8, "judge_status": "success"}
        for a in answers
    ]
    at = _record_app(answers, scores, [])
    assert not at.exception
    assert at.dataframe[0].value["模型"].tolist() == ["model-alpha", "unknown-model", "未标注模型"]
    assert at.selectbox[0].options == ["CM-001｜model-alpha", "CM-002｜unknown-model", "CM-003｜未标注模型"]
    assert any("模型 ID：provider/model-alpha" in c.value for c in at.caption)


def test_persisted_record_statuses_and_score_detail_use_reader_facing_language():
    at = _record_app(
        [{"case_id": "C1", "model_name": "vendor/m1", "run_status": "success", "answer_text": "回答"}],
        [
            {
                "case_id": "C1",
                "eval_model": "vendor/m1",
                "judge_status": "success",
                "total_score": 75,
                "accuracy_score": 20,
                "rationale": '{"accuracy_score":"结论正确，但依据可进一步展开。"}',
            }
        ],
        [{"field": "accuracy_score", "name": "专业准确性", "full_mark": 30}],
    )
    assert not at.exception
    assert at.dataframe[0].value.iloc[0]["回答状态"] == "已完成"
    assert at.dataframe[0].value.iloc[0]["评分状态"] == "已评分"
    assert at.dataframe[1].value.iloc[0].tolist() == ["专业准确性", 20, 30]
    assert any("专业准确性：结论正确，但依据可进一步展开。" in t.value for t in at.text)


def test_record_technical_actions_keep_the_complete_raw_answer_and_score_fields():
    import json

    rationale = '{"accuracy_score":"原始评分理由"}'
    at = _record_app(
        [
            {
                "case_id": "C1",
                "model_name": "provider/model-full",
                "run_status": "success",
                "answer_text": "完整回答",
                "latency_ms": 123,
            }
        ],
        [{"case_id": "C1", "eval_model": "provider/model-full", "judge_status": "success", "rationale": rationale}],
        [],
    )
    assert not at.exception
    raw = [json.loads(j.value) for j in at.json]
    assert any(r.get("model_name") == "provider/model-full" and r.get("latency_ms") == 123 for r in raw)
    assert any(r.get("rationale") == rationale for r in raw)
    assert all(not e.proto.expanded for e in at.expander)
