import pytest
from test_final_review_ux import review_app, visible  # noqa: F401


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
