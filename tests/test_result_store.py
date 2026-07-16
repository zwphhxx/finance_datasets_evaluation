from pathlib import Path

import pytest

from app.persistence.result_store import ResultStore, ResultStoreError


def sqlite_store(tmp_path: Path) -> ResultStore:
    store = ResultStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    store.ensure_schema()
    return store


def run_metadata(run_id: str = "RUN-1") -> dict:
    return {
        "run_id": run_id,
        "provider": "mock",
        "model_ids_json": '["m1"]',
        "generation_parameters_json": "{}",
        "judge_parameters_json": "{}",
        "dataset_version": "1.0.0",
        "dataset_hash": "d" * 64,
        "prompt_hash": "p" * 64,
        "status": "running",
        "completed_count": 0,
        "failed_count": 0,
        "pending_count": 1,
    }


def run_queue_row(run_id: str = "RUN-1") -> dict:
    return {
        "run_id": run_id,
        "case_id": "FD-001",
        "task_type": "Financial Judgment",
        "model_id": "m1",
        "provider": "mock",
        "status": "queued",
        "attempt_count": 0,
    }


def test_schema_contains_all_runtime_tables(tmp_path):
    store = sqlite_store(tmp_path)

    assert set(store.table_names()) == {
        "live_evaluation_runs",
        "live_run_queue",
        "live_run_responses",
        "live_run_scores",
        "live_score_queue",
    }


def test_queue_initialization_is_idempotent(tmp_path):
    store = sqlite_store(tmp_path)

    assert store.initialize_run(run_metadata(), [run_queue_row()]) is True
    assert store.initialize_run(run_metadata(), [run_queue_row()]) is True

    assert len(store.list_rows("live_evaluation_runs", run_id="RUN-1")) == 1
    assert len(store.list_rows("live_run_queue", run_id="RUN-1")) == 1


def test_queue_reinitialization_preserves_completed_status(tmp_path):
    store = sqlite_store(tmp_path)
    metadata = run_metadata()
    queue = [run_queue_row()]
    store.initialize_run(metadata, queue)
    store.save_run_outcome(
        {
            "run_id": "RUN-1",
            "case_id": "FD-001",
            "model_name": "m1",
            "run_status": "success",
            "answer_text": "saved",
        },
        queue_status="success",
    )

    store.initialize_run(metadata, queue)

    assert store.list_rows("live_run_queue", run_id="RUN-1")[0]["status"] == "success"


def test_mark_running_is_persisted_before_call(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(run_metadata(), [run_queue_row()])

    assert store.mark_run_item_running("RUN-1", "FD-001", "m1") is True

    row = store.list_rows("live_run_queue", run_id="RUN-1")[0]
    assert row["status"] == "running"
    assert row["attempt_count"] == 1


def test_response_and_queue_status_commit_together(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(run_metadata(), [run_queue_row()])

    assert store.save_run_outcome(
        {
            "run_id": "RUN-1",
            "case_id": "FD-001",
            "task_type": "Financial Judgment",
            "provider": "mock",
            "model_name": "m1",
            "run_mode": "mock",
            "run_status": "success",
            "answer_text": "saved",
        },
        queue_status="success",
    )

    assert store.list_rows("live_run_responses", run_id="RUN-1")[0]["answer_text"] == "saved"
    assert store.list_rows("live_run_queue", run_id="RUN-1")[0]["status"] == "success"


def test_response_upsert_does_not_duplicate(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(run_metadata(), [run_queue_row()])
    row = {
        "run_id": "RUN-1",
        "case_id": "FD-001",
        "model_name": "m1",
        "run_status": "success",
        "answer_text": "first",
    }

    store.save_run_outcome(row, queue_status="success")
    store.save_run_outcome({**row, "answer_text": "updated"}, queue_status="success")

    responses = store.list_rows("live_run_responses", run_id="RUN-1")
    assert len(responses) == 1
    assert responses[0]["answer_text"] == "updated"


def test_invalid_response_keeps_queue_unfinished(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(run_metadata(), [run_queue_row()])

    with pytest.raises(ResultStoreError):
        store.save_run_outcome(
            {
                "run_id": "RUN-1",
                "case_id": None,
                "model_name": "m1",
                "answer_text": "bad",
            },
            queue_status="success",
        )

    assert store.list_rows("live_run_responses", run_id="RUN-1") == []
    assert store.list_rows("live_run_queue", run_id="RUN-1")[0]["status"] == "queued"


def test_score_and_queue_status_commit_together(tmp_path):
    store = sqlite_store(tmp_path)
    queue = {
        "score_run_id": "SCORE-1",
        "run_id": "RUN-1",
        "case_id": "FD-001",
        "task_type": "Financial Judgment",
        "eval_model": "m1",
        "judge_model": "judge",
        "judge_provider": "mock",
        "status": "queued",
        "attempt_count": 0,
    }
    assert store.initialize_score_queue([queue]) is True
    assert store.mark_score_item_running("SCORE-1", "FD-001", "m1") is True

    assert store.save_score_outcome(
        {
            "score_run_id": "SCORE-1",
            "run_id": "RUN-1",
            "case_id": "FD-001",
            "task_type": "Financial Judgment",
            "eval_model": "m1",
            "judge_provider": "mock",
            "judge_model": "judge",
            "judge_mode": "mock",
            "judge_status": "success",
            "total_score": 80,
        },
        queue_status="success",
    )

    assert store.list_rows("live_run_scores", score_run_id="SCORE-1")[0]["total_score"] == 80
    assert store.list_rows("live_score_queue", score_run_id="SCORE-1")[0]["status"] == "success"


def test_new_store_instance_reads_committed_results(tmp_path):
    url = f"sqlite:///{tmp_path / 'runtime.db'}"
    store = ResultStore(url)
    store.ensure_schema()
    store.initialize_run(run_metadata(), [run_queue_row()])
    store.save_run_outcome(
        {
            "run_id": "RUN-1",
            "case_id": "FD-001",
            "model_name": "m1",
            "run_status": "success",
            "answer_text": "survives",
        },
        queue_status="success",
    )

    restarted = ResultStore(url)
    restarted.ensure_schema()

    assert restarted.list_rows("live_run_responses", run_id="RUN-1")[0]["answer_text"] == "survives"


def test_latest_queue_returns_only_most_recent_run(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(run_metadata("RUN-1"), [run_queue_row("RUN-1")])
    store.initialize_run(run_metadata("RUN-2"), [run_queue_row("RUN-2")])

    rows = store.latest_queue("live_run_queue")

    assert {row["run_id"] for row in rows} == {"RUN-2"}
