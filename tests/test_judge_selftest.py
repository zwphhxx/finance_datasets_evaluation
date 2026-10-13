import pytest

from app.services import judge_selftest as jt
from app.services.scorer import ScoreOutcome


def test_fixtures_are_nine_labeled_answers_for_existing_domains():
    cases = jt.load_cases()
    assert {c["case_id"] for c in cases} == {"FD-002", "LD-001", "CM-001"}
    assert len(cases) == 3
    for case in cases:
        assert set(case["answers"]) == {"correct", "major_error", "concise"}
        assert case["data_kind"] == "synthetic_judge_selftest"
        assert case["fault_quote"] in case["answers"]["major_error"]
        assert case["answers"]["concise"] != case["answers"]["major_error"]


def test_selftest_cannot_silently_run_without_budget_or_on_mock():
    class Provider:
        name = "mock"

        def generate_response(self, *args, **kwargs):
            pytest.fail("selftest must not call provider")

    with pytest.raises(ValueError):
        jt.run_selftest(Provider(), "j", [], max_calls=8)
    with pytest.raises(ValueError):
        jt.run_selftest(Provider(), "j", [], max_calls=9)


def test_known_error_detection_requires_offending_verified_quote():
    case = jt.load_cases()[0]
    outcomes = {
        kind: ScoreOutcome(
            case["case_id"],
            "",
            "m",
            "p",
            "j",
            "success",
            total_score=value,
            scores={"accuracy_score": 28 if kind != "major_error" else 15},
            evidence_status="verified_quotes",
        )
        for kind, value in [("correct", 90), ("major_error", 60), ("concise", 89)]
    }
    result = jt.assess(case, outcomes)
    assert result["passed"] is False
    assert "未识别" in " ".join(result["reasons"])


def test_selftest_only_calls_judge_nine_times_without_retries_or_formal_persistence(monkeypatch):
    calls = []

    def fake_score(provider, model, task, answer, gold, dimensions, **kwargs):
        assert kwargs["retry_delays"] == ()
        calls.append(answer)
        return ScoreOutcome(task["case_id"], "", "", "fixture", model, "failed")

    monkeypatch.setattr(jt, "score_single", fake_score)

    class Provider:
        name = "fixture"

    result = jt.run_selftest(Provider(), "j", [], max_calls=9)
    assert len(calls) == 9
    assert result["export_type"] == "judge_selftest"
    assert result["data_kind"] == "synthetic_judge_selftest"
    assert all(not r["passed"] for r in result["results"])
