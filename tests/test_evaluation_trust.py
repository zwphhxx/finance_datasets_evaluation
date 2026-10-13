"""Offline regressions for strict scoring and verifiable answer evidence."""

import json

import pytest

from app.models.base import GenerationResult
from app.services import scorer as sc

DIMS = [{"field": "accuracy_score", "full_mark": 30}]
GOLD = {"must_have_points": ["应收增速更高"], "unacceptable_errors": ["认定回款正常"]}
ANSWER = "应收增速170%，回款风险较高。"


def payload(value=25, quote="回款风险较高", status="met"):
    return json.dumps(
        {
            "scores": {"accuracy_score": value},
            "rationale": {"accuracy_score": "识别回款风险"},
            "review_note": "样本内判断",
            "checks": [
                {
                    "point_id": "must:1",
                    "status": status,
                    "quote": quote,
                    "error_type": "none",
                    "dimension": "accuracy_score",
                    "reason": "覆盖判断",
                },
                {
                    "point_id": "forbidden:1",
                    "status": "met",
                    "quote": "回款风险较高",
                    "error_type": "none",
                    "dimension": "accuracy_score",
                    "reason": "未作正常判断",
                },
            ],
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize("value", [40, -1, 2.5, True, "25分", float("nan"), float("inf")])
def test_invalid_scores_are_rejected_instead_of_clamped(value):
    assert not sc.parse_judge_output(payload(value), DIMS).ok


def test_each_dimension_requires_a_nonempty_reason():
    raw = json.loads(payload())
    raw["rationale"] = {}
    assert not sc.parse_judge_output(json.dumps(raw), DIMS).ok


class Judge:
    name = "fixture"

    def __init__(self, texts):
        self.texts = iter(texts)
        self.calls = 0

    def generate_response(self, model_id, messages, **kwargs):
        self.calls += 1
        return GenerationResult(self.name, model_id, "success", next(self.texts), input_tokens=10, output_tokens=20)


def score(provider):
    return sc.score_single(
        provider, "judge", {"case_id": "X"}, ANSWER, GOLD, DIMS, retry_delays=(0,), sleep_fn=lambda _: None
    )


def test_hallucinated_quote_fails_and_raw_responses_survive_finite_retry():
    provider = Judge([payload(quote="不存在的引文"), payload(quote="不存在的引文")])
    result = score(provider)
    assert not result.ok
    assert result.total_score is None
    assert provider.calls == 2
    assert len(result.raw_responses) == 2
    assert result.evidence_status == "invalid"
    assert "引文" in result.error_message


def test_invalid_format_can_recover_and_original_response_is_kept():
    provider = Judge(["not JSON", payload()])
    result = score(provider)
    assert result.ok and result.review_status == "ai_final"
    assert len(result.raw_responses) == 2
    assert result.checks[0]["quote_verified"] is True
    assert result.evidence_status == "verified_quotes"


def test_missing_or_duplicate_points_cannot_enter_formal_results():
    raw = json.loads(payload())
    raw["checks"] = [raw["checks"][0], raw["checks"][0]]
    result = score(Judge([json.dumps(raw), json.dumps(raw)]))
    assert not result.ok


def test_unmet_point_may_have_no_quote_but_is_not_verified():
    raw = json.loads(payload())
    raw["checks"][0].update(status="not_met", quote="", error_type="omission")
    result = score(Judge([json.dumps(raw)]))
    assert result.ok
    assert result.checks[0]["quote_verified"] is False


def test_boundaries_allow_unknown_conditions_without_avoiding_known_facts():
    from app.services.eval_runner import build_messages

    text = build_messages({"question": "Q"})[0]["content"]
    assert "缺失必要条件" in text


def test_score_import_rejects_invalid_evidence_fractional_and_missing_scores():
    valid = dict(
        score_run_id="s",
        run_id="r",
        case_id="c",
        eval_model="m",
        judge_model="j",
        judge_status="success",
        review_status="ai_final",
        accuracy_score=25,
        reasoning_score=15,
        coverage_score=15,
        evidence_score=12,
        expression_score=13,
        total_score=80,
    )
    for changed in [
        dict(valid, evidence_status="invalid"),
        dict(valid, accuracy_score=1.6),
        dict(valid, total_score=99),
        {k: v for k, v in valid.items() if k != "coverage_score"},
    ]:
        assert not sc.validate_score_import_rows([changed])["ok"]


def test_new_score_export_import_preserves_all_evidence():
    valid = dict(
        score_run_id="s",
        run_id="r",
        case_id="c",
        eval_model="m",
        judge_model="j",
        judge_status="success",
        review_status="ai_final",
        accuracy_score=25,
        reasoning_score=15,
        coverage_score=15,
        evidence_score=12,
        expression_score=13,
        total_score=80,
        evidence_status="verified_quotes",
        checks_json="[]",
        raw_responses_json='["original"]',
        numeric_checks_json="[]",
    )
    exported = sc.build_score_export_payload([valid])["records"][0]
    restored = sc.validate_score_import_rows([exported])["rows"][0]
    for field in ["evidence_status", "checks_json", "raw_responses_json", "numeric_checks_json"]:
        assert restored[field] == valid[field]


def test_verified_score_cannot_have_invalid_reason_or_duplicate_json_fields():
    raw = json.loads(payload())
    raw["rationale"]["accuracy_score"] = ""
    assert not sc.parse_judge_output(json.dumps(raw), DIMS).ok
    assert not sc.parse_judge_output(
        '{"scores":{"accuracy_score":25,"accuracy_score":30},"rationale":{"accuracy_score":"r"},"review_note":"r"}',
        DIMS,
    ).ok
