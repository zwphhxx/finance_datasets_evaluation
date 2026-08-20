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


def test_persisted_run_records_render_live_model_names_without_losing_full_id(monkeypatch):
    class FakeStreamlit:
        def __init__(self):
            self.rows = []
            self.option_labels = []

        def dataframe(self, rows, **_kwargs):
            self.rows = rows

        def selectbox(self, _label, options, *, format_func):
            self.option_labels = [format_func(index) for index in options]
            return 0

    fake = FakeStreamlit()
    rendered_panels = []
    monkeypatch.setattr(evaluation_results, "st", fake)
    monkeypatch.setattr(
        evaluation_results,
        "render_markdown_detail_panel",
        lambda *args, **kwargs: rendered_panels.append((args, kwargs)),
    )
    answers = [
        {
            "case_id": "CM-001",
            "model_name": "provider/model-alpha",
            "answer_text": "回答一",
            "run_status": "success",
        },
        {
            "case_id": "CM-002",
            "model_name": "vendor/unknown-model",
            "answer_text": "回答二",
            "run_status": "success",
        },
        {
            "case_id": "CM-003",
            "model_name": "",
            "answer_text": "回答三",
            "run_status": "success",
        },
    ]
    scores = [
        {
            "case_id": answer["case_id"],
            "eval_model": answer["model_name"],
            "total_score": 8,
            "judge_status": "success",
        }
        for answer in answers
    ]

    evaluation_results.render_run_record(answers, scores, [])

    assert [row["模型"] for row in fake.rows] == [
        "model-alpha",
        "unknown-model",
        "未标注模型",
    ]
    assert fake.option_labels == [
        "CM-001｜model-alpha",
        "CM-002｜unknown-model",
        "CM-003｜未标注模型",
    ]
    assert rendered_panels[0][1]["meta"] == "模型 ID：provider/model-alpha"


def test_persisted_record_statuses_and_score_detail_use_reader_facing_language(monkeypatch):
    class FakeStreamlit:
        def __init__(self):
            self.rows = []

        def dataframe(self, rows, **_kwargs):
            self.rows = rows

        def selectbox(self, _label, options, *, format_func):
            list(map(format_func, options))
            return 0

    fake = FakeStreamlit()
    panels = []
    monkeypatch.setattr(evaluation_results, "st", fake)
    monkeypatch.setattr(
        evaluation_results,
        "render_markdown_detail_panel",
        lambda *args, **kwargs: panels.append((args, kwargs)),
    )

    evaluation_results.render_run_record(
        [{"case_id": "C1", "model_name": "vendor/m1", "run_status": "success", "answer_text": "回答"}],
        [{
            "case_id": "C1",
            "eval_model": "vendor/m1",
            "judge_status": "success",
            "total_score": 75,
            "accuracy_score": 20,
            "rationale": '{"accuracy_score": "结论正确，但依据可进一步展开。"}',
        }],
        [{"field": "accuracy_score", "name": "专业准确性", "full_mark": 30}],
    )

    assert fake.rows[0]["回答状态"] == "已完成"
    assert fake.rows[0]["评分状态"] == "已评分"
    score_markdown = panels[1][0][1]
    assert "专业准确性：20 / 30" in score_markdown
    assert "专业准确性：结论正确，但依据可进一步展开。" in score_markdown
    assert '{"accuracy_score"' not in score_markdown


def test_record_technical_actions_keep_the_complete_raw_answer_and_score_fields(monkeypatch):
    class FakeStreamlit:
        def __init__(self):
            self.tables = []

        def dataframe(self, rows, **_kwargs):
            self.tables.append(rows)

        def selectbox(self, _label, options, *, format_func):
            list(map(format_func, options))
            return 0

    fake = FakeStreamlit()
    monkeypatch.setattr(evaluation_results, "st", fake)
    monkeypatch.setattr(
        evaluation_results,
        "render_markdown_detail_panel",
        lambda *args, **kwargs: True,
    )
    raw_rationale = '{"accuracy_score": "原始评分理由"}'

    evaluation_results.render_run_record(
        [{
            "case_id": "C1",
            "model_name": "provider/model-full",
            "run_status": "success",
            "answer_text": "完整回答",
            "latency_ms": 123,
        }],
        [{
            "case_id": "C1",
            "eval_model": "provider/model-full",
            "judge_status": "success",
            "rationale": raw_rationale,
        }],
        [],
    )

    assert len(fake.tables) == 3
    answer_detail = {row["字段"]: row["值"] for row in fake.tables[1]}
    score_detail = {row["字段"]: row["值"] for row in fake.tables[2]}
    assert answer_detail["model_name"] == "provider/model-full"
    assert answer_detail["latency_ms"] == "123"
    assert score_detail["rationale"] == raw_rationale
