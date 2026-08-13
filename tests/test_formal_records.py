"""Formal-record eligibility is one policy shared by product readers."""

from __future__ import annotations

import pandas as pd

from app.services import formal_records as fr


def _response(**overrides):
    row = {
        "run_id": "RUN-1",
        "case_id": "FD-001",
        "model_name": "vendor/full-model",
        "status": "active",
        "run_status": "success",
        "run_mode": "live",
        "provider": "vendor",
        "answer_text": "正式回答",
    }
    row.update(overrides)
    return row


def _score(**overrides):
    row = {
        "run_id": "RUN-1",
        "case_id": "FD-001",
        "eval_model": "vendor/full-model",
        "status": "active",
        "judge_status": "success",
        "judge_mode": "live",
        "judge_provider": "judge-vendor",
        "review_status": "ai_final",
    }
    row.update(overrides)
    return row


def test_valid_score_with_matching_live_success_response_is_formal():
    responses = pd.DataFrame([_response()])
    scores = pd.DataFrame([_score()])

    assert fr.formal_response_mask(responses).tolist() == [True]
    assert fr.formal_score_mask(scores, responses=responses).tolist() == [True]
    assert fr.filter_formal_scores(scores, responses=responses).to_dict("records") == [_score()]


def test_scores_require_exact_full_model_id_not_short_name_alias():
    responses = pd.DataFrame([_response(model_name="vendor/full-model")])
    scores = pd.DataFrame([_score(eval_model="full-model")])

    assert fr.formal_score_mask(scores, responses=responses).tolist() == [False]


def test_nonformal_modes_statuses_and_scope_are_excluded():
    responses = pd.DataFrame([_response(case_id="FD-001")])
    scores = pd.DataFrame(
        [
            _score(case_id="FD-001"),
            _score(case_id="FD-001", judge_mode="demo"),
            _score(case_id="FD-001", judge_provider="mock"),
            _score(case_id="FD-001", judge_status="failed"),
            _score(case_id="FD-001", review_status="skipped"),
            _score(case_id="FD-001", status="inactive"),
            _score(case_id="FD-999"),
        ]
    )

    assert fr.formal_score_mask(scores, responses=responses, allowed_case_ids={"FD-001"}).tolist() == [
        True,
        False,
        False,
        False,
        False,
        False,
        False,
    ]


def test_historical_demo_and_mock_responses_are_hidden():
    responses = pd.DataFrame(
        [
            _response(run_mode="demo"),
            _response(run_id="RUN-2", provider="mock"),
            _response(run_id="RUN-3", run_status="failed"),
            _response(run_id="RUN-4", status="inactive"),
        ]
    )

    assert fr.filter_formal_responses(responses).empty


def test_export_policy_excludes_orphan_score_without_formal_answer():
    scores = pd.DataFrame([_score()])

    assert fr.filter_formal_score_rows(scores, pd.DataFrame()).copy() == []


def test_legacy_live_records_without_provider_columns_remain_eligible():
    responses = pd.DataFrame([_response()]).drop(columns=["provider"])
    scores = pd.DataFrame([_score()]).drop(columns=["judge_provider"])

    assert fr.formal_response_mask(responses).tolist() == [True]
    assert fr.formal_score_mask(scores, responses=responses).tolist() == [True]

