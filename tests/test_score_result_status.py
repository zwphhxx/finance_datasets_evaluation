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
