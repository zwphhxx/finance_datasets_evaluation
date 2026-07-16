import os
import uuid

import pytest

from app.persistence.result_store import ResultStore

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not configured",
)


def test_postgres_answer_transition_is_idempotent_and_atomic():
    store = ResultStore(os.environ["TEST_DATABASE_URL"])
    store.ensure_schema()
    run_id = f"PYTEST-{uuid.uuid4().hex}"
    metadata = {
        "run_id": run_id,
        "provider": "mock",
        "dataset_hash": "d" * 64,
        "prompt_hash": "p" * 64,
        "status": "running",
    }
    queue = {
        "run_id": run_id,
        "case_id": "FD-001",
        "model_id": "m1",
        "provider": "mock",
        "status": "queued",
    }
    store.initialize_run(metadata, [queue])
    row = {
        "run_id": run_id,
        "case_id": "FD-001",
        "model_name": "m1",
        "run_status": "success",
        "answer_text": "saved",
    }

    store.save_run_outcome(row, queue_status="success")
    store.save_run_outcome(row, queue_status="success")

    assert len(store.list_rows("live_run_responses", run_id=run_id)) == 1
    assert store.list_rows("live_run_queue", run_id=run_id)[0]["status"] == "success"
