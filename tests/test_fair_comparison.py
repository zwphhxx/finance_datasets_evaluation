import pandas as pd

from app.services import comparison as cp


def scores():
    return pd.DataFrame(
        [
            {"run_id": "r", "case_id": case, "eval_model": model, "total_score": value, "judge_status": "success"}
            for model, case, value in [("a", "easy", 98), ("b", "easy", 95), ("b", "hard", 30)]
        ]
    )


def test_means_compare_only_shared_tasks():
    result = cp.common_sample_comparison(scores(), ["a", "b"])
    assert result["case_ids"] == ["easy"]
    assert result["models"][1]["avg_total"] == 95
    assert result["sufficient"] is False
    assert result["common_count"] == 1


def test_model_without_valid_scores_prevents_spurious_ranking():
    result = cp.common_sample_comparison(scores(), ["a", "b", "c"])
    assert result["common_count"] == 0
    assert all(row["avg_total"] is None for row in result["models"])


def test_runtime_failures_have_separate_denominators():
    queue = [dict(run_id="r", case_id=str(i), model_id="m") for i in range(4)]
    answers = [
        dict(run_id="r", case_id=str(i), model_name="m", run_status=status)
        for i, status in [(0, "success"), (1, "success"), (2, "failed")]
    ]
    judgments = [
        dict(run_id="r", case_id=str(i), eval_model="m", judge_status=status)
        for i, status in [(0, "success"), (1, "failed")]
    ]
    row = cp.runtime_counts(queue, answers, judgments)[0]
    assert [
        row[k] for k in ["planned", "answer_success", "answer_failed", "judge_success", "judge_failed", "unfinished"]
    ] == [4, 2, 1, 1, 1, 1]
    assert row["answer_success_rate"] == 0.5
    assert row["judge_success_rate"] == 0.5


def test_service_endpoints_are_distinct_comparison_units():
    frame = scores()
    frame.loc[frame.eval_model == "b", "eval_model"] = "a"
    frame.loc[frame.index > 0, "run_id"] = "r2"
    runs = [
        dict(run_id="r", provider="p", service_endpoint="endpoint-one"),
        dict(run_id="r2", provider="p", service_endpoint="endpoint-two"),
    ]
    result = cp.comparison_for_runs(frame, runs)
    assert result["kind"] == "service_endpoint"
    assert result["common_count"] == 1
    assert len(result["models"]) == 2
    assert result["models"][0]["model_id"] != result["models"][1]["model_id"]


def test_cohort_keeps_scores_for_same_model_distinct_endpoints():
    from app.services.conclusions import select_current_cohort_scores

    runs = pd.DataFrame(
        [
            dict(
                run_id=rid,
                provider="p",
                service_endpoint=endpoint,
                model_ids_json='["m"]',
                dataset_version="v",
                dataset_hash="d" * 64,
                prompt_hash="p" * 64,
                generation_parameters_json="{}",
                judge_parameters_json="{}",
                status="completed",
                created_at="2026-10-13T00:00:00",
                updated_at="2026-10-13T00:00:00",
            )
            for rid, endpoint in [("r", "one"), ("r2", "two")]
        ]
    )
    frame = pd.DataFrame(
        [
            dict(run_id=rid, eval_model="m", case_id="c", total_score=total, judge_status="success")
            for rid, total in [("r", 80), ("r2", 90)]
        ]
    )
    selected = select_current_cohort_scores(runs, frame)
    assert len(selected) == 2
    assert cp.comparison_for_runs(selected, runs.to_dict("records"))["common_count"] == 1
