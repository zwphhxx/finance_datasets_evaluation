from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services import eval_runner as er
from app.services.evaluation_workflow import WorkflowCheckpointError
from app.services.run_checkpoint import build_run_metadata
from src.ui.evaluation_config import build_evaluation_config_from_checkpoint


def _task(case_id: str, question: str | None = None) -> dict:
    return {
        "case_id": case_id,
        "task_type": "Financial Judgment",
        "question": question or f"Q-{case_id}",
    }


def _base(*tasks: dict) -> SimpleNamespace:
    return SimpleNamespace(
        tasks=pd.DataFrame(tasks),
        gold_answer_map={
            str(task["case_id"]): {"case_id": str(task["case_id"]), "core_conclusion": "gold"}
            for task in tasks
        },
        # Form state is deliberately irrelevant to checkpoint reconstruction.
        selected_tasks=[{"case_id": "FORM-ONLY"}],
        selected_model_ids=["form/model"],
    )


class FakeStore:
    def __init__(self, metadata: dict, queue: list[dict]):
        self.metadata = deepcopy(metadata)
        self.queue = deepcopy(queue)

    def list_rows(self, table: str, **filters):
        assert filters == {"run_id": "RUN-1"}
        if table == "live_evaluation_runs":
            return [deepcopy(self.metadata)]
        if table == "live_run_queue":
            return deepcopy(self.queue)
        raise AssertionError(f"unexpected table: {table}")


def _checkpoint(tasks: list[dict], queue: list[dict] | None = None) -> tuple[dict, list[dict]]:
    rows = queue or [
        {"id": 1, "run_id": "RUN-1", "case_id": "C1", "model_id": "m1", "status": "queued"},
        {"id": 2, "run_id": "RUN-1", "case_id": "C2", "model_id": "m1", "status": "queued"},
    ]
    by_case = {str(task["case_id"]): task for task in tasks}
    items = [
        {
            "case_id": str(row["case_id"]),
            "model_id": str(row["model_id"]),
            "task": by_case[str(row["case_id"])],
        }
        for row in sorted(rows, key=lambda row: int(row.get("id") or 0))
    ]
    prompt_payload = [
        {"case_id": item["case_id"], "messages": er.build_messages(item["task"])}
        for item in items
    ]
    metadata = build_run_metadata(
        run_id="RUN-1",
        provider="test-live",
        model_ids=("m1",),
        queue_items=items,
        generation_parameters={"temperature": 0.2, "max_tokens": 128, "timeout_seconds": 30},
        judge_parameters={"judge_model": "judge-1", "temperature": 0.0, "max_tokens": 128},
        dataset_version="v1",
        prompt_payload=prompt_payload,
    )
    return metadata, rows


def _rebuild(base, store):
    return build_evaluation_config_from_checkpoint(
        "RUN-1",
        base,
        store=store,
        dataset_version="v1",
        dimensions=({"field": "accuracy_score", "max_score": 5},),
    )


def test_checkpoint_config_rebuilds_tasks_gold_prompts_and_saved_parameters():
    tasks = [_task("C1"), _task("C2")]
    metadata, queue = _checkpoint(tasks)

    config = _rebuild(_base(*tasks), FakeStore(metadata, queue))

    assert config.provider_name == "test-live"
    assert config.model_ids == ("m1",)
    assert [(item["case_id"], item["model_id"]) for item in config.queue_items] == [
        ("C1", "m1"),
        ("C2", "m1"),
    ]
    assert config.generation_parameters == {
        "temperature": 0.2,
        "max_tokens": 128,
        "timeout_seconds": 30,
    }
    assert config.judge_parameters["judge_model"] == "judge-1"
    assert config.gold_map == {
        "C1": {"case_id": "C1", "core_conclusion": "gold"},
        "C2": {"case_id": "C2", "core_conclusion": "gold"},
    }
    assert config.prompt_payload == tuple(
        {"case_id": item["case_id"], "messages": er.build_messages(item["task"])}
        for item in config.queue_items
    )


def test_current_form_selection_does_not_change_checkpoint_config():
    tasks = [_task("C1"), _task("C2")]
    metadata, queue = _checkpoint(tasks)
    base = _base(*tasks)
    first = _rebuild(base, FakeStore(metadata, queue))

    base.selected_tasks = [{"case_id": "OTHER"}]
    base.selected_model_ids = ["other/model"]
    second = _rebuild(base, FakeStore(metadata, queue))

    assert second == first


def test_missing_current_case_rejects_checkpoint():
    tasks = [_task("C1"), _task("C2")]
    metadata, queue = _checkpoint(tasks)

    with pytest.raises(WorkflowCheckpointError, match="current sample"):
        _rebuild(_base(tasks[0]), FakeStore(metadata, queue))


def test_changed_current_task_hash_rejects_checkpoint():
    original = [_task("C1"), _task("C2")]
    metadata, queue = _checkpoint(original)
    changed = [_task("C1", "changed"), _task("C2")]

    with pytest.raises(WorkflowCheckpointError, match="does not match"):
        _rebuild(_base(*changed), FakeStore(metadata, queue))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_ids_json", "[]", "models"),
        ("generation_parameters_json", "{}", "parameters"),
        ("judge_parameters_json", "{}", "parameters"),
    ],
)
def test_missing_models_or_parameters_reject_checkpoint(field, value, message):
    tasks = [_task("C1"), _task("C2")]
    metadata, queue = _checkpoint(tasks)
    metadata[field] = value

    with pytest.raises(WorkflowCheckpointError, match=message):
        _rebuild(_base(*tasks), FakeStore(metadata, queue))


def test_queue_order_uses_persisted_ids_and_duplicate_pairs_are_rejected():
    tasks = [_task("C1"), _task("C2")]
    metadata, queue = _checkpoint(tasks)
    reversed_rows = list(reversed(queue))

    config = _rebuild(_base(*tasks), FakeStore(metadata, reversed_rows))
    assert [item["case_id"] for item in config.queue_items] == ["C1", "C2"]

    duplicate = [*queue, {**queue[0], "id": 3}]
    with pytest.raises(WorkflowCheckpointError, match="duplicate"):
        _rebuild(_base(*tasks), FakeStore(metadata, duplicate))


def test_checkpoint_rebuild_does_not_mutate_base_or_store_rows():
    tasks = [_task("C1"), _task("C2")]
    metadata, queue = _checkpoint(tasks)
    base = _base(*tasks)
    store = FakeStore(metadata, queue)
    tasks_before = base.tasks.copy(deep=True)
    gold_before = deepcopy(base.gold_answer_map)
    metadata_before, queue_before = deepcopy(store.metadata), deepcopy(store.queue)

    _rebuild(base, store)

    pd.testing.assert_frame_equal(base.tasks, tasks_before)
    assert base.gold_answer_map == gold_before
    assert store.metadata == metadata_before
    assert store.queue == queue_before
