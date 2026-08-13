from pathlib import Path

import pytest
from sqlalchemy import update

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

    with pytest.raises(ValueError, match="evaluation checkpoint is inconsistent"):
        workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).start_evaluation(config(pair))

    assert events == []
    assert store.list_rows("live_score_queue", score_run_id="SCORE-FIXED")[0]["status"] == "success"


def test_success_answer_queue_without_response_is_rejected_without_calls(tmp_path, monkeypatch):
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

    with pytest.raises(ValueError, match="evaluation checkpoint is inconsistent"):
        workflow(store, RecordingProvider(responses=[], events=events), RecordingProvider(events=events)).start_evaluation(config(pair))

    assert events == []
    assert store.list_rows("live_run_queue", run_id="RUN-FIXED")[0]["status"] == "success"


@pytest.mark.parametrize("provider_name,judge_name", [("mock", "test-live"), ("test-live", "demo")])
def test_mock_or_demo_provider_is_rejected_before_queue_or_model_calls(tmp_path, provider_name, judge_name):
    from app.services.evaluation_workflow import WorkflowStopped

    store = sqlite_store(tmp_path)
    events = []
    with pytest.raises(WorkflowStopped):
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
