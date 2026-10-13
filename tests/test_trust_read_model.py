import json

import pandas as pd

from app.services.conclusion_read_model import build_conclusion_report
from app.services.formal_records import filter_formal_scores


def test_invalid_evidence_status_is_never_formal():
    scores = pd.DataFrame(
        [
            dict(
                run_id="r",
                case_id="c",
                eval_model="m",
                judge_status="success",
                total_score=90,
                evidence_status="invalid",
            )
        ]
    )
    assert filter_formal_scores(scores).empty


def test_out_of_range_legacy_score_is_never_formal():
    scores = pd.DataFrame(
        [dict(run_id="r", case_id="c", eval_model="m", judge_status="success", total_score=90, accuracy_score=100)]
    )
    assert filter_formal_scores(scores).empty


def test_unverified_quote_flag_cannot_be_trusted_from_storage():
    scores = pd.DataFrame(
        [
            dict(
                run_id="r",
                case_id="c",
                eval_model="m",
                judge_status="success",
                total_score=90,
                evidence_status="verified_quotes",
                checks_json=json.dumps([dict(quote="invented", quote_verified=True)]),
            )
        ]
    )
    answers = pd.DataFrame([dict(run_id="r", case_id="c", model_name="m", run_status="success", answer_text="actual")])
    assert filter_formal_scores(scores, answers).empty


def test_report_carries_common_denominator_and_keeps_all_evidence():
    scores = pd.DataFrame(
        [
            dict(run_id="r", case_id=case, eval_model=model, judge_status="success", total_score=total)
            for model, case, total in [("a", "easy", 95), ("b", "easy", 90), ("b", "hard", 40)]
        ]
    )
    answers = pd.DataFrame(
        [
            dict(
                run_id="r", case_id=r["case_id"], model_name=r["eval_model"], run_status="success", answer_text="answer"
            )
            for r in scores.to_dict("records")
        ]
    )
    report = build_conclusion_report(
        scores_df=scores,
        responses_df=answers,
        tasks_df=pd.DataFrame([{"case_id": "easy"}, {"case_id": "hard"}]),
        gold_map={},
        dimensions=[],
    )
    assert len(report.formal_scores) == 3
    assert report.comparison["common_count"] == 1
    assert report.comparison["models"][1]["avg_total"] == 90
