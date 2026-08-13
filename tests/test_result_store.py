from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.result_store import ResultStore, ResultStoreError
from app.persistence.schema import live_evaluation_runs


def sqlite_store(tmp_path: Path) -> ResultStore:
    store = ResultStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    store.ensure_schema()
    return store


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def test_postgresql_engine_receives_bounded_connect_timeout(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return object()

    monkeypatch.setattr("app.persistence.result_store.create_engine", fake_create_engine)
    monkeypatch.setenv("FINDUEVAL_DATABASE_CONNECT_TIMEOUT_SECONDS", "5")

    ResultStore("postgresql://user:pass@db.example.com/postgres")

    assert captured["url"].startswith("postgresql+psycopg://")
    assert captured["kwargs"]["connect_args"] == {"connect_timeout": 5}


def test_sqlite_engine_does_not_receive_postgresql_connect_timeout(monkeypatch, tmp_path):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return object()

    monkeypatch.setattr("app.persistence.result_store.create_engine", fake_create_engine)

    ResultStore(f"sqlite:///{tmp_path / 'runtime.db'}")

    assert "connect_args" not in captured["kwargs"]


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


def score_queue_row(run_id: str = "RUN-1", score_run_id: str = "SCORE-1", *, case_id: str = "FD-001", model_id: str = "m1") -> dict:
    return {
        "score_run_id": score_run_id,
        "run_id": run_id,
        "case_id": case_id,
        "task_type": "Financial Judgment",
        "eval_model": model_id,
        "judge_model": "judge",
        "judge_provider": "vendor",
        "status": "queued",
        "attempt_count": 0,
    }


def response_row(run_id: str = "RUN-1", *, case_id: str = "FD-001", model_id: str = "m1", status: str = "success") -> dict:
    return {
        "run_id": run_id,
        "case_id": case_id,
        "model_name": model_id,
        "run_status": status,
        "answer_text": "saved" if status == "success" else "",
        "error_code": "answer_failed" if status != "success" else None,
    }


def score_row(run_id: str = "RUN-1", score_run_id: str = "SCORE-1", *, case_id: str = "FD-001", model_id: str = "m1", status: str = "success") -> dict:
    return {
        "score_run_id": score_run_id,
        "run_id": run_id,
        "case_id": case_id,
        "eval_model": model_id,
        "judge_status": status,
        "total_score": 80 if status == "success" else None,
        "error_code": "score_failed" if status != "success" else None,
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


def test_initialize_evaluation_creates_run_and_both_queues(tmp_path):
    store = sqlite_store(tmp_path)

    assert store.initialize_evaluation(
        run_metadata(),
        [run_queue_row()],
        [score_queue_row()],
    ) is True

    assert len(store.list_rows("live_evaluation_runs", run_id="RUN-1")) == 1
    assert len(store.list_rows("live_run_queue", run_id="RUN-1")) == 1
    assert len(store.list_rows("live_score_queue", score_run_id="SCORE-1")) == 1


def test_initialize_evaluation_rejects_misaligned_pairs_before_writing(tmp_path):
    store = sqlite_store(tmp_path)

    with pytest.raises(ResultStoreError):
        store.initialize_evaluation(
            run_metadata(),
            [run_queue_row()],
            [score_queue_row(case_id="FD-999")],
        )

    assert store.list_rows("live_evaluation_runs") == []
    assert store.list_rows("live_run_queue") == []
    assert store.list_rows("live_score_queue") == []


def test_initialize_evaluation_rolls_back_all_writes_when_score_queue_insert_fails(tmp_path, monkeypatch):
    store = sqlite_store(tmp_path)
    original = store._upsert

    def failing_upsert(connection, table, row, *, update_existing=True):
        if table.name == "live_score_queue":
            raise SQLAlchemyError("forced score queue failure")
        return original(connection, table, row, update_existing=update_existing)

    monkeypatch.setattr(store, "_upsert", failing_upsert)

    with pytest.raises(ResultStoreError):
        store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])

    assert store.list_rows("live_evaluation_runs") == []
    assert store.list_rows("live_run_queue") == []
    assert store.list_rows("live_score_queue") == []


def test_combined_failed_answer_skips_its_score_item(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])

    store.save_run_outcome(response_row(status="failed"), queue_status="failed", combined=True)

    assert store.list_rows("live_score_queue", score_run_id="SCORE-1")[0]["status"] == "skipped"


def test_mark_score_item_skipped_updates_combined_counts(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])

    assert store.mark_score_item_skipped("SCORE-1", "FD-001", "m1", "judge_unavailable") is True

    queue = store.list_rows("live_score_queue", score_run_id="SCORE-1")[0]
    run = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]
    assert (queue["status"], queue["error_code"]) == ("skipped", "judge_unavailable")
    assert (run["status"], run["failed_count"], run["pending_count"]) == ("failed", 1, 0)


def test_marking_score_running_refreshes_combined_pending_state(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])
    store.save_run_outcome(response_row(), queue_status="success", combined=True)
    store.mark_run_stopped("RUN-1", "interrupted before judging")
    old = utcnow() - timedelta(days=1)
    with store.engine.begin() as connection:
        connection.execute(
            update(live_evaluation_runs)
            .where(live_evaluation_runs.c.run_id == "RUN-1")
            .values(updated_at=old)
        )

    assert store.mark_score_item_running("SCORE-1", "FD-001", "m1") is True

    run = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]
    score = store.list_rows("live_score_queue", score_run_id="SCORE-1")[0]
    assert (run["status"], run["pending_count"], run["updated_at"] > old) == ("running", 1, True)
    assert (score["status"], score["attempt_count"]) == ("running", 1)


def test_claim_run_claims_stale_running_once_and_rejects_fresh_running(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(run_metadata(), [run_queue_row()])
    stale = utcnow() - timedelta(hours=1)
    with store.engine.begin() as connection:
        connection.execute(
            update(live_evaluation_runs)
            .where(live_evaluation_runs.c.run_id == "RUN-1")
            .values(status="running", updated_at=stale)
        )

    assert store.claim_run("RUN-1", utcnow() - timedelta(minutes=1)) is True
    assert store.claim_run("RUN-1", utcnow() - timedelta(minutes=1)) is False
    assert store.claim_run("RUN-1", utcnow() - timedelta(minutes=1)) is False


def test_claim_run_accepts_interrupted_and_stopped_runs(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(run_metadata(), [run_queue_row()])
    with store.engine.begin() as connection:
        connection.execute(
            update(live_evaluation_runs)
            .where(live_evaluation_runs.c.run_id == "RUN-1")
            .values(status="interrupted")
        )
    assert store.claim_run("RUN-1", utcnow()) is True
    assert store.mark_run_stopped("RUN-1", "paused") is True
    assert store.claim_run("RUN-1", utcnow()) is True


def test_combined_reinitialization_preserves_terminal_queue_rows(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])
    store.save_run_outcome(response_row(), queue_status="success", combined=True)
    store.save_score_outcome(score_row(), queue_status="success")

    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])

    assert store.list_rows("live_run_queue", run_id="RUN-1")[0]["status"] == "success"
    assert store.list_rows("live_score_queue", score_run_id="SCORE-1")[0]["status"] == "success"


def test_combined_answer_success_remains_running_until_score_success(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])

    store.save_run_outcome(response_row(), queue_status="success", combined=True)
    running = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]

    assert (running["status"], running["completed_count"], running["failed_count"], running["pending_count"]) == (
        "running", 0, 0, 1,
    )
    store.save_score_outcome(score_row(), queue_status="success")
    completed = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]
    assert (completed["status"], completed["completed_count"], completed["failed_count"], completed["pending_count"]) == (
        "completed", 1, 0, 0,
    )


def test_combined_counts_distinguish_partial_and_failed_runs(tmp_path):
    store = sqlite_store(tmp_path)
    answers = [run_queue_row(), {**run_queue_row(), "case_id": "FD-002"}]
    scores = [score_queue_row(), score_queue_row(case_id="FD-002")]
    store.initialize_evaluation(run_metadata(), answers, scores)
    store.save_run_outcome(response_row(), queue_status="success", combined=True)
    store.save_score_outcome(score_row(), queue_status="success")
    store.save_run_outcome(response_row(case_id="FD-002", status="failed"), queue_status="failed", combined=True)
    partial = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]
    assert (partial["status"], partial["completed_count"], partial["failed_count"], partial["pending_count"]) == (
        "partial", 1, 1, 0,
    )

    failed_store = sqlite_store(tmp_path)
    failed_store.initialize_evaluation(
        run_metadata("RUN-2"),
        [run_queue_row("RUN-2")],
        [score_queue_row("RUN-2", "SCORE-2")],
    )
    failed_store.save_run_outcome(
        response_row("RUN-2", status="failed"), queue_status="failed", combined=True
    )
    failed = failed_store.list_rows("live_evaluation_runs", run_id="RUN-2")[0]
    assert (failed["status"], failed["completed_count"], failed["failed_count"], failed["pending_count"]) == (
        "failed", 0, 1, 0,
    )


def test_mark_stopped_records_error_and_marking_items_heartbeats_run(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])
    old = utcnow() - timedelta(days=1)
    with store.engine.begin() as connection:
        connection.execute(
            update(live_evaluation_runs)
            .where(live_evaluation_runs.c.run_id == "RUN-1")
            .values(updated_at=old)
        )
    store.mark_run_item_running("RUN-1", "FD-001", "m1", combined=True)
    assert store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]["updated_at"] != old
    with store.engine.begin() as connection:
        connection.execute(
            update(live_evaluation_runs)
            .where(live_evaluation_runs.c.run_id == "RUN-1")
            .values(updated_at=old)
        )
    store.mark_score_item_running("SCORE-1", "FD-001", "m1")
    assert store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]["updated_at"] != old
    assert store.mark_run_stopped("RUN-1", "persistence unavailable") is True
    stopped = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]
    assert stopped["status"] == "stopped"
    assert stopped["last_persistence_error"] == "persistence unavailable"


def test_save_score_outcome_rolls_back_when_queue_row_is_missing(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(run_metadata(), [run_queue_row()], [score_queue_row()])

    with pytest.raises(ResultStoreError):
        store.save_score_outcome(score_row(model_id="missing"), queue_status="success")

    assert store.list_rows("live_run_scores", score_run_id="SCORE-1") == []
