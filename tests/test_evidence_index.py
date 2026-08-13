from __future__ import annotations

from copy import deepcopy

import pandas as pd
from pandas.testing import assert_frame_equal

from app.services.evidence_index import build_evidence_index


DIMENSIONS = (
    {"field": "accuracy", "full_mark": 10},
    {"field": "reasoning", "full_mark": 20},
)


def _score(case_id: str, *, total=50, run_id="RUN-1", model="model/full", **values):
    return {
        "run_id": run_id,
        "case_id": case_id,
        "eval_model": model,
        "total_score": total,
        "accuracy": values.get("accuracy", 5),
        "reasoning": values.get("reasoning", 10),
        "rationale": values.get("rationale", {"note": case_id}),
        "review_note": values.get("review_note", f"review-{case_id}"),
        **{key: value for key, value in values.items() if key not in {"accuracy", "reasoning", "rationale", "review_note"}},
    }


def _response(case_id: str, *, run_id="RUN-1", model="model/full", text=None):
    return {
        "run_id": run_id,
        "case_id": case_id,
        "model_name": model,
        "answer_text": text or f"answer-{case_id}",
    }


def _tasks(*case_ids):
    return [{"case_id": case_id, "title": f"title-{case_id}"} for case_id in case_ids]


def test_basic_index_selects_low_high_and_weak_dimension_with_exact_evidence():
    scores = pd.DataFrame([
        _score("C1", total=20, accuracy=3, reasoning=10, rationale='{"why": "low"}'),
        _score("C2", total=90, accuracy=9, reasoning=18),
        _score("C3", total=50, accuracy=2, reasoning=15),
        _score("C4", total=60, accuracy=7, reasoning=8),
    ])
    responses = pd.DataFrame([_response(case_id) for case_id in ("C1", "C2", "C3", "C4")])

    result = build_evidence_index(
        scores, responses, _tasks("C1", "C2", "C3", "C4"), {"C1": {"gold": 1}}, DIMENSIONS, "model/full"
    )

    assert [item.case_id for item in result] == ["C1", "C2", "C3"]
    assert [item.selection_reason for item in result] == ["最低总分", "最高总分", "最弱维度：accuracy"]
    assert result[0].answer_text == "answer-C1"
    assert result[0].gold_answer == {"gold": 1}
    assert result[0].rationale == {"why": "low"}
    assert result[0].dimension_scores == {"accuracy": 3.0, "reasoning": 10.0}


def test_candidates_deduplicate_and_tie_break_by_case_id():
    scores = pd.DataFrame([
        _score("C2", total=10, accuracy=1),
        _score("C1", total=10, accuracy=1),
        _score("C3", total=80, accuracy=8),
        _score("C4", total=80, accuracy=4),
    ])

    result = build_evidence_index(scores, pd.DataFrame(), _tasks("C1", "C2", "C3", "C4"), {}, DIMENSIONS, "model/full")

    assert [item.case_id for item in result] == ["C1", "C3", "C2"]
    assert [item.selection_reason for item in result] == ["最低总分", "最高总分", "最弱维度：accuracy"]


def test_weakest_dimension_uses_mean_attainment_ratio_and_ties_by_field_name():
    dimensions = (
        {"field": "alpha", "full_mark": 100},
        {"field": "zeta", "full_mark": 10},
    )
    scores = pd.DataFrame([
        _score("C1", total=10, alpha=20, zeta=3),
        _score("C2", total=20, alpha=20, zeta=3),
        _score("C3", total=30, alpha=20, zeta=3),
    ])

    result = build_evidence_index(scores, pd.DataFrame(), _tasks("C1", "C2", "C3"), {}, dimensions, "model/full")

    assert result[-1].weakest_dimension == "alpha"
    assert result[-1].selection_reason == "最弱维度：alpha"

    tied = build_evidence_index(
        pd.DataFrame([_score("C1", total=1, alpha=10, zeta=1), _score("C2", total=2, alpha=10, zeta=1)]),
        pd.DataFrame(), _tasks("C1", "C2"), {}, dimensions, "model/full",
    )
    assert tied[0].weakest_dimension == "alpha"


def test_duplicate_score_row_selects_latest_and_exact_run_answer_join_prevents_leakage():
    scores = pd.DataFrame([
        _score("C1", total=10, updated_at="2025-01-01T00:00:00Z", rationale="old"),
        _score("C1", total=20, updated_at="2025-01-02T00:00:00Z", rationale="new"),
        _score("C2", total=30, run_id="RUN-2"),
    ])
    responses = pd.DataFrame([
        _response("C1", run_id="RUN-OTHER", text="wrong-batch"),
        _response("C1", text="right-batch"),
        _response("C2", run_id="RUN-1", text="also-wrong-batch"),
    ])

    result = build_evidence_index(scores, responses, _tasks("C1", "C2"), {}, DIMENSIONS, "model/full")

    c1 = next(item for item in result if item.case_id == "C1")
    c2 = next(item for item in result if item.case_id == "C2")
    assert c1.total_score == 20.0
    assert c1.rationale == "new"
    assert c1.answer_text == "right-batch"
    assert c2.answer_text == ""

    by_id = build_evidence_index(
        pd.DataFrame([_score("C3", total=8, id=2), _score("C3", total=7, id=1)]),
        pd.DataFrame(), _tasks("C3"), {}, DIMENSIONS, "model/full",
    )
    assert by_id[0].total_score == 8.0


def test_rationale_title_fallbacks_and_input_objects_remain_unchanged():
    scores = pd.DataFrame([
        _score("C1", total=1, rationale='{"mapped": true}'),
        _score("C2", total=2, rationale="not json"),
        _score("C3", total=3),
    ])
    responses = pd.DataFrame([_response("C1"), _response("C2"), _response("C3")])
    tasks = [
        {"case_id": "C1", "title": "Preferred", "question": "ignored"},
        {"case_id": "C2", "question": "Question fallback"},
    ]
    gold = {"C1": {"answer": "a"}}
    scores_before, responses_before, tasks_before, gold_before = scores.copy(deep=True), responses.copy(deep=True), deepcopy(tasks), deepcopy(gold)

    result = build_evidence_index(scores, responses, tasks, gold, DIMENSIONS, "model/full")

    by_case = {item.case_id: item for item in result}
    assert by_case["C1"].title == "Preferred"
    assert by_case["C2"].title == "Question fallback"
    assert by_case["C3"].title == "C3"
    assert by_case["C1"].rationale == {"mapped": True}
    assert by_case["C2"].rationale == "not json"
    assert_frame_equal(scores, scores_before)
    assert_frame_equal(responses, responses_before)
    assert tasks == tasks_before
    assert gold == gold_before


def test_invalid_values_empty_inputs_exact_model_and_maximum_three():
    scores = pd.DataFrame([
        _score("C1", total="bad", accuracy=0, model="model/full"),
        _score("C2", total=2, accuracy="bad", model="model/full"),
        _score("C3", total=3, accuracy=1, model="model/full"),
        _score("C4", total=4, accuracy=4, model="model/full"),
        _score("C5", total=0, accuracy=0, model="model/short"),
    ])

    result = build_evidence_index(scores, pd.DataFrame(), _tasks("C1", "C2", "C3", "C4", "C5"), {}, DIMENSIONS, "model/full")

    assert len(result) == 3
    assert {item.case_id for item in result}.isdisjoint({"C5"})
    assert all("accuracy" in item.dimension_scores for item in result)
    by_case = {item.case_id: item for item in result}
    assert by_case["C1"].total_score is None
    assert by_case["C2"].dimension_scores["accuracy"] is None
    assert build_evidence_index(pd.DataFrame(), pd.DataFrame(), [], {}, DIMENSIONS, "model/full") == []
    assert build_evidence_index(None, pd.DataFrame(), [], {}, DIMENSIONS, "model/full") == []
