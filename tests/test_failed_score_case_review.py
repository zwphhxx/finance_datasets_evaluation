import pytest
from test_final_review_ux import review_app, visible  # noqa: F401


def test_deleted_score_link_returns_to_case_display_without_stale_selection(review_app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINDUEVAL_MODE", "public")
    at, report = review_app
    queue = dict(report.runtime_tables["live_run_scores"][0], score_run_id="deleted-score", status="failed")
    report.runtime_tables["live_score_queue"] = [queue]
    try:
        at.query_params.update(page="review", case="TEST-1", run="test-r1", model="model-a",
                               score="deleted-score", origin="evaluation_preview")
        at.run()
        assert not at.exception
        assert not at.error
        assert "该评分记录已删除" in visible(at)
        assert "原始回答" not in visible(at)
        assert not at.metric
        at.run()  # Refresh keeps the explicit deleted-record state.
        assert "该评分记录已删除" in visible(at)
        at.button(key="portfolio_deleted_return_home").click().run()
        assert not at.exception
        assert not at.error
        assert at.query_params["page"] == ["conclusions"]
        assert at.query_params.get("origin") is None
        assert at.query_params.get("score") != ["deleted-score"]
        assert at.selectbox(key="portfolio_home_record").value is not None
    finally:
        report.runtime_tables.pop("live_score_queue")


@pytest.mark.parametrize("changes", [
    {"status": "running"}, {"score_run_id": "other"}, {"run_id": "other"},
    {"case_id": "other"}, {"eval_model": "other"},
])
def test_missing_score_without_matching_failed_queue_is_not_marked_deleted(review_app, monkeypatch, changes):  # noqa: F811
    monkeypatch.setenv("FINDUEVAL_MODE", "public")
    at, report = review_app
    queue = dict(report.runtime_tables["live_run_scores"][0], score_run_id="deleted-score", status="failed")
    queue.update(changes)
    report.runtime_tables["live_score_queue"] = [queue]
    try:
        at.query_params.update(page="review", case="TEST-1", run="test-r1", model="model-a", score="deleted-score")
        at.run()
        assert not at.exception
        assert "该评分记录已删除" not in visible(at)
        assert any("无法定位" in e.value for e in at.error)
    finally:
        report.runtime_tables.pop("live_score_queue")


def test_deleted_detection_requires_saved_answer_and_absent_outcome(review_app):  # noqa: F811
    import pandas as pd

    from src.ui.portfolio import _is_deleted_score
    from src.ui.review import _review_records

    _, report = review_app
    queue = dict(report.runtime_tables["live_run_scores"][0], score_run_id="deleted-score", status="failed")
    report.runtime_tables["live_score_queue"] = [queue]
    route = ("TEST-1", "test-r1", "model-a", "deleted-score")
    _, responses = _review_records(report)
    try:
        assert _is_deleted_score(report, route, responses)
        assert not _is_deleted_score(None, route, responses)
        assert not _is_deleted_score(report, route[:-1] + ("",), responses)
        assert not _is_deleted_score(report, route, pd.DataFrame())
        # A non-formal outcome still exists; it must not be called deleted.
        report.runtime_tables["live_run_scores"].append(dict(queue, judge_status="mock"))
        try:
            assert not _is_deleted_score(report, route, responses)
        finally:
            report.runtime_tables["live_run_scores"].pop()
    finally:
        report.runtime_tables.pop("live_score_queue")


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_failed_score_exact_link_keeps_answer_and_shows_no_fabricated_score(review_app, monkeypatch, missing):  # noqa: F811
    monkeypatch.setenv("FINDUEVAL_MODE", "public")
    at, report = review_app
    failed = dict(
        report.runtime_tables["live_run_scores"][0],
        score_run_id="failed-score",
        judge_status="failed",
        total_score=missing,
        error_code="timeout",
        evidence_status="invalid",
        checks_json="[]",
        rationale="{}",
        review_note="",
    )
    report.runtime_tables["live_run_scores"].append(failed)
    try:
        at.query_params.update(
            page="review",
            case=failed["case_id"],
            run=failed["run_id"],
            model=failed["eval_model"],
            score="failed-score",
        )
        at.run()
        assert not at.exception
        assert not at.error
        assert "原始回答" in visible(at)
        assert any("AI评分超时" in warning.value for warning in at.warning)
        assert at.metric[0].value == "—"
    finally:
        report.runtime_tables["live_run_scores"].pop()
