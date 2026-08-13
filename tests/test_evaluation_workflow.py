from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import pytest
from sqlalchemy import delete, update

from app.models.base import GenerationResult, ModelListResult, ModelProvider, STATUS_FAILED, STATUS_SUCCESS
from app.persistence.result_store import ResultStore, ResultStoreError
from app.persistence.schema import live_run_queue, live_score_queue
from app.services import scorer as sc
from app.services.run_checkpoint import build_run_metadata


class RecordingProvider(ModelProvider):
    def __init__(self, name="test-live", responses=(), events=None):
        self.name = name
        self.responses = list(responses)
        self.events = events if events is not None else []

    def list_models(self, model_type="text", sub_type="chat"):
        return ModelListResult(self.name, STATUS_SUCCESS)

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        self.events.append(f"answer_call:{model_id}")
        status, text = self.responses.pop(0)
        return GenerationResult(
            self.name,
            model_id,
            status,
            response_text=text,
            error_code="answer_failed" if status == STATUS_FAILED else None,
            error_message="failed" if status == STATUS_FAILED else None,
        )


def sqlite_store(tmp_path: Path) -> ResultStore:
    store = ResultStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    store.ensure_schema()
    return store


def item(case_id: str, model_id: str) -> dict:
    return {
        "case_id": case_id,
        "model_id": model_id,
        "task": {"case_id": case_id, "task_type": "Financial Judgment", "question": f"Q-{case_id}"},
    }


def config(*items_: dict, provider_name="test-live", judge_name="test-live"):
    from app.services.evaluation_workflow import EvaluationConfig

    return EvaluationConfig(
        provider_name=provider_name,
        model_ids=tuple(row["model_id"] for row in items_),
        queue_items=tuple(items_),
        generation_parameters={"temperature": 0.2, "max_tokens": 128},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1",
        prompt_payload=("system", "hint"),
        gold_map={row["case_id"]: {"core_conclusion": "gold"} for row in items_},
        dimensions=({"field": "accuracy_score", "max_score": 5},),
    )


def score_outcome(case_id: str, model_id: str, status=STATUS_SUCCESS):
    return sc.ScoreOutcome(
        case_id=case_id,
        task_type="Financial Judgment",
        eval_model=model_id,
        judge_provider="test-live",
        judge_model="judge-1",
        judge_status=status,
        scores={"accuracy_score": 5 if status == STATUS_SUCCESS else None},
        total_score=5 if status == STATUS_SUCCESS else None,
        error_code="judge_failed" if status == STATUS_FAILED else None,
    )


def workflow(store, answer, judge):
    from app.services.evaluation_workflow import EvaluationWorkflow

    return EvaluationWorkflow(store, answer, judge)


def record_score(monkeypatch, events, statuses=(STATUS_SUCCESS,)):
    outcomes = list(statuses)

    def fake_score(provider, judge_model, task, answer_text, gold, dimensions, *, eval_model, **kwargs):
        events.append(f"score_call:{task['case_id']}")
        status = outcomes.pop(0) if outcomes else STATUS_SUCCESS
        return score_outcome(task["case_id"], eval_model, status)

    monkeypatch.setattr("app.services.evaluation_workflow.sc.score_single", fake_score)


def test_initialization_precedes_first_answer_call(tmp_path, monkeypatch):
    events = []
    store = sqlite_store(tmp_path)
    answer = RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events)
    judge = RecordingProvider(events=events)
    record_score(monkeypatch, events)
    original = store.initialize_evaluation

    def initialize(*args):
        events.append("initialize")
        return original(*args)

    monkeypatch.setattr(store, "initialize_evaluation", initialize)

    workflow(store, answer, judge).start_evaluation(config(item("C1", "m1")))

    assert events.index("initialize") < events.index("answer_call:m1")


def test_successful_pair_persists_answer_then_score_in_order(tmp_path, monkeypatch):
    events = []
    store = sqlite_store(tmp_path)
    answer = RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events)
    record_score(monkeypatch, events)
    original_answer_save = store.save_run_outcome
    original_score_save = store.save_score_outcome
    original_initialize = store.initialize_evaluation

    def initialize(*args):
        events.append("initialize")
        return original_initialize(*args)

    def save_answer(*args, **kwargs):
        events.append("answer_save")
        return original_answer_save(*args, **kwargs)

    def save_score(*args, **kwargs):
        events.append("score_save")
        return original_score_save(*args, **kwargs)

    monkeypatch.setattr(store, "save_run_outcome", save_answer)
    monkeypatch.setattr(store, "save_score_outcome", save_score)
    monkeypatch.setattr(store, "initialize_evaluation", initialize)

    ref = workflow(store, answer, RecordingProvider(events=events)).start_evaluation(config(item("C1", "m1")))

    assert events == ["initialize", "answer_call:m1", "answer_save", "score_call:C1", "score_save"]
    assert workflow(store, answer, RecordingProvider()).load_evaluation_status(ref.run_id).state == "completed"


def test_answer_failure_skips_score_and_marks_run_failed(tmp_path, monkeypatch):
    events = []
    store = sqlite_store(tmp_path)
    answer = RecordingProvider(responses=[(STATUS_FAILED, "")], events=events)
    record_score(monkeypatch, events)

    ref = workflow(store, answer, RecordingProvider(events=events)).start_evaluation(config(item("C1", "m1")))

    assert not any(event.startswith("score_call") for event in events)
    assert store.list_rows("live_score_queue", score_run_id=ref.score_run_id)[0]["status"] == "skipped"
    assert workflow(store, answer, RecordingProvider()).load_evaluation_status(ref.run_id).state == "failed"


def test_score_failure_keeps_answer_and_continues_to_partial_result(tmp_path, monkeypatch):
    events = []
    store = sqlite_store(tmp_path)
    answer = RecordingProvider(
        responses=[(STATUS_SUCCESS, "one"), (STATUS_SUCCESS, "two")], events=events
    )
    record_score(monkeypatch, events, (STATUS_FAILED, STATUS_SUCCESS))

    ref = workflow(store, answer, RecordingProvider(events=events)).start_evaluation(
        config(item("C1", "m1"), item("C2", "m2"))
    )

    assert [row["answer_text"] for row in store.list_rows("live_run_responses", run_id=ref.run_id)] == ["one", "two"]
    assert store.list_rows("live_score_queue", score_run_id=ref.score_run_id)[0]["status"] == "failed"
    assert workflow(store, answer, RecordingProvider()).load_evaluation_status(ref.run_id).state == "partial"


def test_scores_each_case_before_starting_next_answer(tmp_path, monkeypatch):
    events = []
    store = sqlite_store(tmp_path)
    answer = RecordingProvider(
        responses=[(STATUS_SUCCESS, "one"), (STATUS_SUCCESS, "two")], events=events
    )
    record_score(monkeypatch, events)

    workflow(store, answer, RecordingProvider(events=events)).start_evaluation(
        config(item("C1", "m1"), item("C2", "m2"))
    )

    assert events.index("score_call:C1") < events.index("answer_call:m2")


def _prepopulate_successful_answer(store, run_id, score_run_id, pair):
    metadata = build_run_metadata(
        run_id=run_id,
        provider="test-live",
        model_ids=(pair["model_id"],),
        queue_items=(pair,),
        generation_parameters={"temperature": 0.2, "max_tokens": 128},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1",
        prompt_payload=("system", "hint"),
    )
    store.initialize_evaluation(
        metadata,
        [{"run_id": run_id, "case_id": pair["case_id"], "model_id": pair["model_id"], "status": "queued"}],
        [{"score_run_id": score_run_id, "run_id": run_id, "case_id": pair["case_id"], "eval_model": pair["model_id"], "status": "queued"}],
    )
    store.save_run_outcome(
        {"run_id": run_id, "case_id": pair["case_id"], "model_name": pair["model_id"], "run_status": "success", "answer_text": "saved", "run_mode": "live", "provider": "test-live"},
        queue_status="success",
        combined=True,
    )


def _initialize_checkpoint(store, run_id, score_run_id, pair):
    metadata = build_run_metadata(
        run_id=run_id,
        provider="test-live",
        model_ids=(pair["model_id"],),
        queue_items=(pair,),
        generation_parameters={"temperature": 0.2, "max_tokens": 128},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1",
        prompt_payload=("system", "hint"),
    )
    store.initialize_evaluation(
        metadata,
        [{"run_id": run_id, "case_id": pair["case_id"], "model_id": pair["model_id"], "status": "queued"}],
        [{"score_run_id": score_run_id, "run_id": run_id, "case_id": pair["case_id"], "eval_model": pair["model_id"], "status": "queued"}],
    )


def test_persisted_successful_answer_only_calls_judge(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _prepopulate_successful_answer(store, "RUN-FIXED", "SCORE-FIXED", pair)
    events = []
    answer = RecordingProvider(responses=[], events=events)
    record_score(monkeypatch, events)
    monkeypatch.setattr("app.services.evaluation_workflow.er.generate_run_id", lambda: "RUN-FIXED")
    monkeypatch.setattr("app.services.evaluation_workflow.sc.generate_score_run_id", lambda: "SCORE-FIXED")

    workflow(store, answer, RecordingProvider(events=events)).start_evaluation(config(pair))

    assert events == ["score_call:C1"]


def test_successful_answer_and_score_skip_all_model_calls(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _prepopulate_successful_answer(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.save_score_outcome(
        {"score_run_id": "SCORE-FIXED", "case_id": "C1", "eval_model": "m1", "judge_status": "success", "total_score": 5, "judge_mode": "live", "judge_provider": "test-live", "judge_model": "judge-1"},
        queue_status="success",
    )
    events = []
    monkeypatch.setattr("app.services.evaluation_workflow.er.generate_run_id", lambda: "RUN-FIXED")
    monkeypatch.setattr("app.services.evaluation_workflow.sc.generate_score_run_id", lambda: "SCORE-FIXED")

    workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).start_evaluation(config(pair))

    assert events == []


def test_success_score_queue_without_formal_results_is_rejected_without_calls(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowCheckpointError

    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    with store.engine.begin() as connection:
        connection.execute(
            update(live_score_queue)
            .where(live_score_queue.c.score_run_id == "SCORE-FIXED")
            .values(status="success")
        )
    events = []
    monkeypatch.setattr("app.services.evaluation_workflow.er.generate_run_id", lambda: "RUN-FIXED")
    monkeypatch.setattr("app.services.evaluation_workflow.sc.generate_score_run_id", lambda: "SCORE-FIXED")

    with pytest.raises(WorkflowCheckpointError, match="evaluation checkpoint is inconsistent"):
        workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).start_evaluation(config(pair))

    assert events == []
    assert store.list_rows("live_score_queue", score_run_id="SCORE-FIXED")[0]["status"] == "success"


def test_success_answer_queue_without_response_is_rejected_without_calls(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowCheckpointError

    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    with store.engine.begin() as connection:
        connection.execute(
            update(live_run_queue)
            .where(live_run_queue.c.run_id == "RUN-FIXED")
            .values(status="success")
        )
    events = []
    monkeypatch.setattr("app.services.evaluation_workflow.er.generate_run_id", lambda: "RUN-FIXED")
    monkeypatch.setattr("app.services.evaluation_workflow.sc.generate_score_run_id", lambda: "SCORE-FIXED")

    with pytest.raises(WorkflowCheckpointError, match="evaluation checkpoint is inconsistent"):
        workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).start_evaluation(config(pair))

    assert events == []
    assert store.list_rows("live_run_queue", run_id="RUN-FIXED")[0]["status"] == "success"


@pytest.mark.parametrize("provider_name,judge_name", [("mock", "test-live"), ("test-live", "demo")])
def test_mock_or_demo_provider_is_rejected_before_queue_or_model_calls(tmp_path, provider_name, judge_name):
    store = sqlite_store(tmp_path)
    events = []
    with pytest.raises(ValueError, match="mock and demo providers"):
        workflow(
            store,
            RecordingProvider(provider_name, [(STATUS_SUCCESS, "answer")], events),
            RecordingProvider(judge_name, events=events),
        ).start_evaluation(config(item("C1", "m1"), provider_name=provider_name, judge_name=judge_name))

    assert events == []
    assert store.list_rows("live_evaluation_runs") == []


@pytest.mark.parametrize(
    "generation,judge,expected",
    [({}, {}, 900), ({"timeout_seconds": 1000}, {"timeout_seconds": 800}, 1120), ({"timeout_seconds": 600}, {"timeout_seconds": 850}, 970)],
)
def test_inactivity_threshold_uses_larger_timeout_plus_buffer(generation, judge, expected):
    from app.services.evaluation_workflow import inactivity_threshold

    cfg = config(item("C1", "m1"))
    cfg = type(cfg)(**{**cfg.__dict__, "generation_parameters": generation, "judge_parameters": {"judge_model": "judge-1", **judge}})

    assert inactivity_threshold(cfg) == expected


def test_initialization_failure_stops_before_any_provider_call(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowStopped

    events = []
    store = sqlite_store(tmp_path)

    def fail(*args):
        raise ResultStoreError("database unavailable")

    monkeypatch.setattr(store, "initialize_evaluation", fail)
    with pytest.raises(WorkflowStopped):
        workflow(
            store,
            RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events),
            RecordingProvider(events=events),
        ).start_evaluation(config(item("C1", "m1")))

    assert events == []


def test_unexpected_answer_value_error_stops_run_and_prevents_later_calls(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowStopped

    store = sqlite_store(tmp_path)
    events = []

    def invalid_answer(*args, **kwargs):
        events.append("answer_value_error")
        raise ValueError("invalid provider response")

    monkeypatch.setattr("app.services.evaluation_workflow.er.generate_run_id", lambda: "RUN-FIXED")
    monkeypatch.setattr("app.services.evaluation_workflow.sc.generate_score_run_id", lambda: "SCORE-FIXED")
    monkeypatch.setattr("app.services.evaluation_workflow.er.run_single", invalid_answer)

    with pytest.raises(WorkflowStopped, match="could not persist evaluation outcome"):
        workflow(
            store,
            RecordingProvider(responses=[], events=events),
            RecordingProvider(events=events),
        ).start_evaluation(config(item("C1", "m1"), item("C2", "m2")))

    run = store.list_rows("live_evaluation_runs", run_id="RUN-FIXED")[0]
    assert events == ["answer_value_error"]
    assert run["status"] == "stopped"
    assert run["last_persistence_error"] == "could not persist evaluation outcome"


def _queue_state(run_id, score_run_id, answer_status, score_status, *, run_status="running"):
    return (
        {"run_id": run_id, "status": run_status, "last_persistence_error": ""},
        [{"run_id": run_id, "case_id": "C1", "model_id": "m1", "status": answer_status}],
        [{"run_id": run_id, "score_run_id": score_run_id, "case_id": "C1", "eval_model": "m1", "status": score_status}],
    )


@pytest.mark.parametrize(
    "answer_status,score_status,stale,owned,stopped_here,expected,resumable",
    [
        ("success", "success", False, False, False, "completed", False),
        ("success", "failed", False, False, False, "failed", False),
        ("success", "success", False, False, True, "stopped", False),
        ("queued", "queued", False, True, False, "running", False),
        ("queued", "queued", False, False, False, "interrupted", True),
        ("queued", "queued", True, True, False, "interrupted", True),
    ],
)
def test_derive_status_has_mutually_exclusive_combined_states(
    answer_status, score_status, stale, owned, stopped_here, expected, resumable
):
    from app.services.evaluation_workflow import derive_status

    run, answers, scores = _queue_state("RUN-1", "SCORE-1", answer_status, score_status)

    status = derive_status(run, answers, scores, stale, stopped_here=stopped_here, owned=owned)

    assert (status.state, status.resumable) == (expected, resumable)


def test_fresh_workflow_loads_recent_pending_run_as_interrupted_without_provider_calls(tmp_path):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    events = []

    status = workflow(
        store,
        RecordingProvider(responses=[], events=events),
        RecordingProvider(events=events),
    ).load_evaluation_status("RUN-FIXED")

    assert events == []
    assert (status.state, status.resumable) == ("interrupted", True)


def test_status_loading_never_claims_or_writes(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    writes = []
    monkeypatch.setattr(store, "claim_run", lambda *args: writes.append("claim"))
    monkeypatch.setattr(store, "mark_run_stopped", lambda *args: writes.append("stop"))

    workflow(store, RecordingProvider(), RecordingProvider()).load_evaluation_status("RUN-FIXED")

    assert writes == []


def test_continue_claims_stopped_queue_and_runs_answer_then_score(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []
    answer = RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events)
    record_score(monkeypatch, events)

    status = workflow(store, answer, RecordingProvider(events=events)).continue_evaluation(
        "RUN-FIXED", config(pair)
    )

    assert events == ["answer_call:m1", "score_call:C1"]
    assert status.state == "completed"


def test_continue_reuses_persisted_answer_and_only_calls_judge(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _prepopulate_successful_answer(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []
    record_score(monkeypatch, events)

    workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).continue_evaluation(
        "RUN-FIXED", config(pair)
    )

    assert events == ["score_call:C1"]


def test_continue_checkpoint_mismatch_never_claims_or_calls_providers(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    claims = []
    events = []
    monkeypatch.setattr(store, "claim_run", lambda *args: claims.append(args) or True)
    incompatible = type(config(pair))(**{**config(pair).__dict__, "dataset_version": "v2"})

    from app.services.evaluation_workflow import WorkflowCheckpointError

    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).continue_evaluation(
            "RUN-FIXED", incompatible
        )

    assert claims == []
    assert events == []


def test_continue_answer_save_failure_stops_before_score_or_later_pair(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowStopped

    store = sqlite_store(tmp_path)
    first, second = item("C1", "m1"), item("C2", "m2")
    metadata = build_run_metadata(
        run_id="RUN-FIXED",
        provider="test-live",
        model_ids=("m1", "m2"),
        queue_items=(first, second),
        generation_parameters={"temperature": 0.2, "max_tokens": 128},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1",
        prompt_payload=("system", "hint"),
    )
    store.initialize_evaluation(
        metadata,
        [
            {"run_id": "RUN-FIXED", "case_id": "C1", "model_id": "m1", "status": "queued"},
            {"run_id": "RUN-FIXED", "case_id": "C2", "model_id": "m2", "status": "queued"},
        ],
        [
            {"score_run_id": "SCORE-FIXED", "run_id": "RUN-FIXED", "case_id": "C1", "eval_model": "m1", "status": "queued"},
            {"score_run_id": "SCORE-FIXED", "run_id": "RUN-FIXED", "case_id": "C2", "eval_model": "m2", "status": "queued"},
        ],
    )
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []
    monkeypatch.setattr(store, "save_run_outcome", lambda *args, **kwargs: (_ for _ in ()).throw(ResultStoreError("save failed")))
    record_score(monkeypatch, events)

    active = workflow(
        store,
        RecordingProvider(responses=[(STATUS_SUCCESS, "one"), (STATUS_SUCCESS, "two")], events=events),
        RecordingProvider(events=events),
    )
    with pytest.raises(WorkflowStopped):
        active.continue_evaluation("RUN-FIXED", config(first, second))

    assert events == ["answer_call:m1"]
    current = active.load_evaluation_status("RUN-FIXED")
    assert (current.state, current.persistence_failed_in_session) == ("stopped", True)
    assert workflow(store, RecordingProvider(), RecordingProvider()).load_evaluation_status("RUN-FIXED").state == "interrupted"


def test_continue_leaves_complete_pair_without_provider_calls(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _prepopulate_successful_answer(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.save_score_outcome(
        {"score_run_id": "SCORE-FIXED", "case_id": "C1", "eval_model": "m1", "judge_status": "success", "total_score": 5, "judge_mode": "live", "judge_provider": "test-live", "judge_model": "judge-1"},
        queue_status="success",
    )
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []

    status = workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).continue_evaluation(
        "RUN-FIXED", config(pair)
    )

    assert events == []
    assert status.state == "completed"


def test_continue_leaves_failed_and_skipped_pair_terminal_without_provider_calls(tmp_path):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.save_run_outcome(
        {"run_id": "RUN-FIXED", "case_id": "C1", "model_name": "m1", "run_status": "failed", "run_mode": "live", "provider": "test-live"},
        queue_status="failed",
        combined=True,
    )
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []

    status = workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).continue_evaluation(
        "RUN-FIXED", config(pair)
    )

    assert events == []
    assert status.state == "failed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_version", "v2"),
        ("prompt_payload", ("changed",)),
        ("model_ids", ("other",)),
        ("generation_parameters", {"temperature": 0.9, "max_tokens": 128}),
        ("judge_parameters", {"judge_model": "judge-1", "temperature": 0.9, "max_tokens": 128}),
    ],
)
def test_continue_rejects_each_metadata_checkpoint_mismatch_before_claim(tmp_path, monkeypatch, field, value):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    claims = []
    monkeypatch.setattr(store, "claim_run", lambda *args: claims.append(args) or True)
    base = config(pair)
    incompatible = type(base)(**{**base.__dict__, field: value})

    from app.services.evaluation_workflow import WorkflowCheckpointError

    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        workflow(store, RecordingProvider(), RecordingProvider()).continue_evaluation("RUN-FIXED", incompatible)

    assert claims == []


def test_continue_rejects_dataset_hash_mismatch_before_claim(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    claims = []
    monkeypatch.setattr(store, "claim_run", lambda *args: claims.append(args) or True)
    changed_pair = {**pair, "task": {**pair["task"], "question": "changed question"}}

    from app.services.evaluation_workflow import WorkflowCheckpointError

    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        workflow(store, RecordingProvider(), RecordingProvider()).continue_evaluation(
            "RUN-FIXED", config(changed_pair)
        )

    assert claims == []


def test_continue_accepts_equivalent_parameter_json_key_order(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []
    record_score(monkeypatch, events)
    base = config(pair)
    reordered = type(base)(
        **{
            **base.__dict__,
            "generation_parameters": {"max_tokens": 128, "temperature": 0.2},
            "judge_parameters": {"max_tokens": 128, "temperature": 0.0, "judge_model": "judge-1"},
        }
    )

    workflow(
        store,
        RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events),
        RecordingProvider(events=events),
    ).continue_evaluation("RUN-FIXED", reordered)

    assert events == ["answer_call:m1", "score_call:C1"]


def test_only_one_workflow_instance_claims_and_executes_a_stopped_run(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []
    record_score(monkeypatch, events)
    first = workflow(store, RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events), RecordingProvider(events=events))
    second = workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events))

    assert first.continue_evaluation("RUN-FIXED", config(pair)).state == "completed"
    assert second.continue_evaluation("RUN-FIXED", config(pair)).state == "completed"
    assert events == ["answer_call:m1", "score_call:C1"]


def test_fresh_running_run_cannot_claim_but_stale_running_run_can(tmp_path, monkeypatch):
    from sqlalchemy import update
    from app.persistence.schema import live_evaluation_runs

    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    events = []
    fresh = workflow(
        store,
        RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events),
        RecordingProvider(events=events),
    )
    assert fresh.continue_evaluation("RUN-FIXED", config(pair)).state == "interrupted"
    assert events == []
    with store.engine.begin() as connection:
        connection.execute(
            update(live_evaluation_runs)
            .where(live_evaluation_runs.c.run_id == "RUN-FIXED")
            .values(updated_at=datetime.utcnow() - timedelta(hours=1))
        )
    record_score(monkeypatch, events)

    assert fresh.continue_evaluation("RUN-FIXED", config(pair)).state == "completed"
    assert events == ["answer_call:m1", "score_call:C1"]


def test_score_save_failure_stops_before_later_pair_and_retains_answer(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowStopped

    store = sqlite_store(tmp_path)
    first, second = item("C1", "m1"), item("C2", "m2")
    metadata = build_run_metadata(
        run_id="RUN-FIXED", provider="test-live", model_ids=("m1", "m2"), queue_items=(first, second),
        generation_parameters={"temperature": 0.2, "max_tokens": 128},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1", prompt_payload=("system", "hint"),
    )
    store.initialize_evaluation(
        metadata,
        [{"run_id": "RUN-FIXED", "case_id": row["case_id"], "model_id": row["model_id"], "status": "queued"} for row in (first, second)],
        [{"score_run_id": "SCORE-FIXED", "run_id": "RUN-FIXED", "case_id": row["case_id"], "eval_model": row["model_id"], "status": "queued"} for row in (first, second)],
    )
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []
    record_score(monkeypatch, events)
    monkeypatch.setattr(store, "save_score_outcome", lambda *args, **kwargs: (_ for _ in ()).throw(ResultStoreError("score save failed")))

    active = workflow(
        store,
        RecordingProvider(responses=[(STATUS_SUCCESS, "one"), (STATUS_SUCCESS, "two")], events=events),
        RecordingProvider(events=events),
    )
    with pytest.raises(WorkflowStopped):
        active.continue_evaluation("RUN-FIXED", config(first, second))

    assert events == ["answer_call:m1", "score_call:C1"]
    current = active.load_evaluation_status("RUN-FIXED")
    assert (current.state, current.persistence_failed_in_session) == ("stopped", True)
    assert store.list_rows("live_run_responses", run_id="RUN-FIXED", case_id="C1")[0]["answer_text"] == "one"


def test_checkpoint_missing_or_misaligned_queues_raise_checkpoint_error(tmp_path):
    from app.services.evaluation_workflow import WorkflowCheckpointError

    store = sqlite_store(tmp_path)
    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        workflow(store, RecordingProvider(), RecordingProvider()).load_evaluation_status("MISSING")


def test_derive_status_distinguishes_partial_from_all_failed_pairs():
    from app.services.evaluation_workflow import derive_status

    run = {"run_id": "RUN-1", "status": "running"}
    answers = [
        {"run_id": "RUN-1", "case_id": "C1", "model_id": "m1", "status": "success"},
        {"run_id": "RUN-1", "case_id": "C2", "model_id": "m2", "status": "failed"},
    ]
    scores = [
        {"run_id": "RUN-1", "score_run_id": "SCORE-1", "case_id": "C1", "eval_model": "m1", "status": "success"},
        {"run_id": "RUN-1", "score_run_id": "SCORE-1", "case_id": "C2", "eval_model": "m2", "status": "skipped"},
    ]

    status = derive_status(run, answers, scores, stale=False)

    assert (status.state, status.succeeded, status.failed, status.pending) == ("partial", 1, 1, 0)


def test_different_score_run_ids_reject_load_and_continue_before_claim_or_provider_calls(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowCheckpointError

    store = sqlite_store(tmp_path)
    first, second = item("C1", "m1"), item("C2", "m2")
    metadata = build_run_metadata(
        run_id="RUN-FIXED", provider="test-live", model_ids=("m1", "m2"), queue_items=(first, second),
        generation_parameters={"temperature": 0.2, "max_tokens": 128},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1", prompt_payload=("system", "hint"),
    )
    store.initialize_evaluation(
        metadata,
        [{"run_id": "RUN-FIXED", "case_id": row["case_id"], "model_id": row["model_id"]} for row in (first, second)],
        [{"score_run_id": "SCORE-FIXED", "run_id": "RUN-FIXED", "case_id": row["case_id"], "eval_model": row["model_id"]} for row in (first, second)],
    )
    with store.engine.begin() as connection:
        connection.execute(
            update(live_score_queue)
            .where(live_score_queue.c.case_id == "C2")
            .values(score_run_id="OTHER-SCORE")
        )
    claims, events = [], []
    monkeypatch.setattr(store, "claim_run", lambda *args: claims.append(args) or True)
    active = workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events))

    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        active.load_evaluation_status("RUN-FIXED")
    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        active.continue_evaluation("RUN-FIXED", config(first, second))

    assert claims == []
    assert events == []


def test_stop_write_failure_keeps_current_instance_stopped_and_fresh_instance_interrupted(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowStopped

    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.mark_run_stopped("RUN-FIXED", "resume")
    events = []
    active = workflow(
        store,
        RecordingProvider(responses=[(STATUS_SUCCESS, "answer")], events=events),
        RecordingProvider(events=events),
    )
    monkeypatch.setattr(store, "save_run_outcome", lambda *args, **kwargs: (_ for _ in ()).throw(ResultStoreError("save failed")))
    monkeypatch.setattr(store, "mark_run_stopped", lambda *args, **kwargs: (_ for _ in ()).throw(ResultStoreError("stop failed")))

    with pytest.raises(WorkflowStopped):
        active.continue_evaluation("RUN-FIXED", config(pair))

    assert active.load_evaluation_status("RUN-FIXED").state == "stopped"
    assert workflow(store, RecordingProvider(), RecordingProvider()).load_evaluation_status("RUN-FIXED").state == "interrupted"


def test_checkpoint_error_releases_ownership_so_current_load_is_interrupted(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowCheckpointError

    store = sqlite_store(tmp_path)
    original_initialize = store.initialize_evaluation
    monkeypatch.setattr("app.services.evaluation_workflow.er.generate_run_id", lambda: "RUN-FIXED")
    monkeypatch.setattr("app.services.evaluation_workflow.sc.generate_score_run_id", lambda: "SCORE-FIXED")

    def initialize_then_corrupt(*args):
        original_initialize(*args)
        with store.engine.begin() as connection:
            connection.execute(
                update(live_run_queue)
                .where(live_run_queue.c.run_id == "RUN-FIXED")
                .values(status="success")
            )

    monkeypatch.setattr(store, "initialize_evaluation", initialize_then_corrupt)
    active = workflow(store, RecordingProvider(), RecordingProvider())

    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        active.start_evaluation(config(item("C1", "m1")))

    status = active.load_evaluation_status("RUN-FIXED")
    assert (status.state, status.resumable) == ("interrupted", True)


def test_concurrent_continuation_allows_only_claim_winner_to_call_provider(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    store.mark_run_stopped("RUN-FIXED", "resume")
    events, started, release = [], Event(), Event()

    class BlockingProvider(RecordingProvider):
        def generate_response(self, *args, **kwargs):
            self.events.append("answer_call:m1")
            started.set()
            assert release.wait(timeout=5)
            return GenerationResult(self.name, "m1", STATUS_SUCCESS, response_text="answer")

    record_score(monkeypatch, events)
    first = workflow(store, BlockingProvider(events=events), RecordingProvider(events=events))
    second = workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events))
    first_result, first_errors = [], []

    def run_first():
        try:
            first_result.append(first.continue_evaluation("RUN-FIXED", config(pair)))
        except Exception as exc:
            first_errors.append(exc)

    thread = Thread(target=run_first)
    thread.start()
    assert started.wait(timeout=5)
    loser = second.continue_evaluation("RUN-FIXED", config(pair))
    release.set()
    thread.join(timeout=5)

    assert first_errors == []
    assert not thread.is_alive()
    assert loser.state == "interrupted"
    assert first_result[0].state == "completed"
    assert events == ["answer_call:m1", "score_call:C1"]


@pytest.mark.parametrize("queue_table", [live_run_queue, live_score_queue])
def test_missing_queue_rejects_load_and_continue_before_claim_or_provider_calls(tmp_path, monkeypatch, queue_table):
    from app.services.evaluation_workflow import WorkflowCheckpointError

    store = sqlite_store(tmp_path)
    pair = item("C1", "m1")
    _initialize_checkpoint(store, "RUN-FIXED", "SCORE-FIXED", pair)
    with store.engine.begin() as connection:
        connection.execute(delete(queue_table).where(queue_table.c.run_id == "RUN-FIXED"))
    claims, events = [], []
    monkeypatch.setattr(store, "claim_run", lambda *args: claims.append(args) or True)
    active = workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events))

    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        active.load_evaluation_status("RUN-FIXED")
    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        active.continue_evaluation("RUN-FIXED", config(pair))

    assert claims == []
    assert events == []


def test_misaligned_queue_rejects_continue_before_claim_or_provider_calls(tmp_path, monkeypatch):
    from app.services.evaluation_workflow import WorkflowCheckpointError

    store = sqlite_store(tmp_path)
    first, second = item("C1", "m1"), item("C2", "m2")
    metadata = build_run_metadata(
        run_id="RUN-FIXED", provider="test-live", model_ids=("m1", "m2"), queue_items=(first, second),
        generation_parameters={"temperature": 0.2, "max_tokens": 128},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1", prompt_payload=("system", "hint"),
    )
    store.initialize_evaluation(
        metadata,
        [{"run_id": "RUN-FIXED", "case_id": row["case_id"], "model_id": row["model_id"]} for row in (first, second)],
        [{"score_run_id": "SCORE-FIXED", "run_id": "RUN-FIXED", "case_id": row["case_id"], "eval_model": row["model_id"]} for row in (first, second)],
    )
    with store.engine.begin() as connection:
        connection.execute(
            update(live_score_queue)
            .where(live_score_queue.c.case_id == "C2")
            .values(eval_model="different-model")
        )
    claims, events = [], []
    monkeypatch.setattr(store, "claim_run", lambda *args: claims.append(args) or True)

    with pytest.raises(WorkflowCheckpointError, match="checkpoint"):
        workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).continue_evaluation(
            "RUN-FIXED", config(first, second)
        )

    assert claims == []
    assert events == []
