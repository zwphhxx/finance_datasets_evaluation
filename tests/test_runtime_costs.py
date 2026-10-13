import pytest

from app.services import runtime_metrics as rm


def price():
    return dict(
        provider="p",
        model_id="m",
        currency="CNY",
        source="https://provider.example/pricing",
        effective_from="2026-10-01",
        effective_until="2026-11-01",
        input_per_million="2",
        output_per_million="4",
    )


def attempt(phase="answer", index=1, **extra):
    return dict(
        attempt_id=f"{phase}{index}",
        run_id="r",
        case_id="c",
        eval_model="m",
        phase=phase,
        model_id="m",
        provider="p",
        requested_at="2026-10-13T00:00:00+00:00",
        input_tokens=100,
        output_tokens=200,
        status="success",
        latency_ms=10,
        attempt_index=index,
        **extra,
    )


def test_retry_usage_and_answer_judge_costs_are_separate():
    summary = rm.cost_summary([attempt(index=1), attempt(index=2), attempt("judge")], [price()], expected=[])
    assert summary["complete"]
    assert summary["phases"]["answer"]["estimated_cost"] == pytest.approx(0.002)
    assert summary["phases"]["judge"]["estimated_cost"] == pytest.approx(0.001)
    assert summary["phases"]["answer"]["input_tokens"] == 200


def test_unknown_usage_is_not_zero_and_prevents_per_passed_task_cost():
    row = attempt()
    row["output_tokens"] = None
    summary = rm.cost_summary([row], [price()], expected=[], passed_tasks=1)
    assert summary["complete"] is False
    assert summary["phases"]["answer"]["estimated_cost"] is None
    assert summary["cost_per_passed_task"] is None
    assert summary["unknown_usage"] == 1


def test_historical_attempt_gaps_disable_complete_cost():
    expected = [dict(run_id="r", case_id="c", eval_model="m", phase="answer", minimum_attempts=2)]
    summary = rm.cost_summary([attempt()], [price()], expected=expected, passed_tasks=1)
    assert summary["complete"] is False
    assert summary["missing_attempt_groups"] == 1


def test_price_dates_overlap_and_currency_cannot_be_ignored():
    expired = price()
    expired["effective_until"] = "2026-10-02"
    assert rm.cost_summary([attempt()], [expired], expected=[])["complete"] is False
    with pytest.raises(ValueError):
        rm.validate_prices([price(), price()])
    for field in ["source", "currency", "model_id", "effective_from"]:
        raw = price()
        raw.pop(field)
        with pytest.raises(ValueError):
            rm.validate_prices([raw])
    raw = price()
    raw["input_per_million"] = "NaN"
    with pytest.raises(ValueError):
        rm.validate_prices([raw])


def test_mixed_currencies_do_not_produce_one_total():
    other = price()
    other.update(model_id="j", currency="USD")
    judge = attempt("judge")
    judge["model_id"] = "j"
    summary = rm.cost_summary([attempt(), judge], [price(), other], expected=[], passed_tasks=1)
    assert summary["complete"] is False
    assert summary["cost_per_passed_task"] is None


def test_all_attempt_timeouts_are_visible_even_after_success():
    row = attempt()
    row.update(status="failed", error_code="timeout")
    metrics = rm.attempt_metrics([row, attempt(index=2)])
    assert metrics["answer"]["attempts"] == 2
    assert metrics["answer"]["timeouts"] == 1
    assert metrics["answer"]["latency_ms"] == 20


def test_partial_token_usage_preserves_known_input_and_marks_unknown_output():
    row = attempt()
    row["output_tokens"] = None
    metrics = rm.attempt_metrics([row])["answer"]
    assert metrics["input_tokens"] == 100
    assert metrics["output_tokens"] is None
    costs = rm.cost_summary([row], [price()], expected=[])["phases"]["answer"]
    assert costs["input_tokens"] == 100
    assert costs["output_tokens"] is None


def test_no_mixed_currency_subtotal_is_presented_as_money():
    other = price()
    other.update(model_id="j", currency="USD")
    second = attempt(index=2)
    second["model_id"] = "j"
    costs = rm.cost_summary([attempt(), second], [price(), other], expected=[])["phases"]["answer"]
    assert costs["known_subtotal"] is None


def test_unfinished_planned_tasks_prevent_complete_run_cost():
    tables={'live_run_queue':[dict(run_id='r',case_id='pending',model_id='m',status='queued')],
            'live_run_responses':[], 'live_run_scores':[], 'live_score_queue':[]}
    summary=rm.cost_summary([attempt()],[price()],expected=rm.expected_attempts(tables),passed_tasks=1)
    assert not summary['complete']
    assert summary['cost_per_passed_task'] is None
