import os
import uuid

import pytest
from sqlalchemy import delete, or_

from app.persistence.result_store import ResultStore, ResultStoreError
from app.persistence.schema import (
    live_evaluation_runs,
    live_run_queue,
    live_run_responses,
    live_run_scores,
    live_score_queue,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not configured",
)


@pytest.fixture
def store():
    store = ResultStore(os.environ["TEST_DATABASE_URL"])
    store.ensure_schema()
    yield store
    with store.engine.begin() as connection:
        connection.execute(
            delete(live_run_scores).where(
                or_(
                    live_run_scores.c.score_run_id.like("PYTEST-%"),
                    live_run_scores.c.run_id.like("PYTEST-%"),
                )
            )
        )
        connection.execute(
            delete(live_score_queue).where(
                or_(
                    live_score_queue.c.score_run_id.like("PYTEST-%"),
                    live_score_queue.c.run_id.like("PYTEST-%"),
                )
            )
        )
        connection.execute(
            delete(live_run_responses).where(
                live_run_responses.c.run_id.like("PYTEST-%")
            )
        )
        connection.execute(
            delete(live_run_queue).where(live_run_queue.c.run_id.like("PYTEST-%"))
        )
        connection.execute(
            delete(live_evaluation_runs).where(
                live_evaluation_runs.c.run_id.like("PYTEST-%")
            )
        )


def test_postgres_schema_contains_all_runtime_tables(store):
    assert set(store.table_names()) == {
        "live_evaluation_runs",
        "live_run_queue",
        "live_run_responses",
        "live_run_scores",
        "live_score_queue",
    }


def test_postgres_answer_transition_is_idempotent_and_atomic(store):
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


def test_postgres_failed_answer_transition_rolls_back(store):
    run_id = f"PYTEST-{uuid.uuid4().hex}"
    store.initialize_run(
        {
            "run_id": run_id,
            "provider": "mock",
            "dataset_hash": "d" * 64,
            "prompt_hash": "p" * 64,
        },
        [
            {
                "run_id": run_id,
                "case_id": "FD-001",
                "model_id": "m1",
                "status": "queued",
            }
        ],
    )

    with pytest.raises(ResultStoreError):
        store.save_run_outcome(
            {
                "run_id": run_id,
                "case_id": None,
                "model_name": "m1",
                "answer_text": "invalid",
            },
            queue_status="success",
        )

    assert store.list_rows("live_run_responses", run_id=run_id) == []
    assert store.list_rows("live_run_queue", run_id=run_id)[0]["status"] == "queued"


def test_postgres_score_transition_is_idempotent_and_atomic(store):
    score_run_id = f"PYTEST-SCORE-{uuid.uuid4().hex}"
    queue = {
        "score_run_id": score_run_id,
        "run_id": f"PYTEST-RUN-{uuid.uuid4().hex}",
        "case_id": "FD-001",
        "eval_model": "m1",
        "judge_provider": "mock",
        "judge_model": "judge",
        "status": "queued",
    }
    store.initialize_score_queue([queue])
    row = {
        "score_run_id": score_run_id,
        "run_id": queue["run_id"],
        "case_id": "FD-001",
        "eval_model": "m1",
        "judge_provider": "mock",
        "judge_model": "judge",
        "judge_status": "success",
        "total_score": 88,
    }

    store.save_score_outcome(row, queue_status="success")
    store.save_score_outcome(row, queue_status="success")

    assert len(store.list_rows("live_run_scores", score_run_id=score_run_id)) == 1
    assert store.list_rows("live_score_queue", score_run_id=score_run_id)[0]["status"] == "success"


def test_postgres_new_store_instance_reads_committed_answer(store):
    run_id = f"PYTEST-{uuid.uuid4().hex}"
    store.initialize_run(
        {
            "run_id": run_id,
            "provider": "mock",
            "dataset_hash": "d" * 64,
            "prompt_hash": "p" * 64,
        },
        [
            {
                "run_id": run_id,
                "case_id": "FD-001",
                "model_id": "m1",
                "status": "queued",
            }
        ],
    )
    store.save_run_outcome(
        {
            "run_id": run_id,
            "case_id": "FD-001",
            "model_name": "m1",
            "run_status": "success",
            "answer_text": "survives restart",
        },
        queue_status="success",
    )

    restarted = ResultStore(os.environ["TEST_DATABASE_URL"])
    rows = restarted.list_rows("live_run_responses", run_id=run_id)

    assert rows[0]["answer_text"] == "survives restart"
