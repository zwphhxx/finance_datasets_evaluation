# Persistent Evaluation Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every model answer, judge score, and queue transition before the next Token-consuming call, support SQLite locally and PostgreSQL/Supabase online, resume unfinished work after restart, then generate a fresh run for the current 13 samples.

**Architecture:** Keep the existing SQLite dataset repository unchanged and introduce a focused SQLAlchemy-backed runtime result store for `live_*` tables. The existing runner and scorer APIs remain compatible with `db_path`-based tests, while Streamlit resolves a PostgreSQL URL from environment or Secrets and fails closed before real model calls when durable storage is unavailable.

**Tech Stack:** Python 3.11, Streamlit 1.51, pandas 2.3, SQLAlchemy 2.0 Core, psycopg 3, SQLite, PostgreSQL/Supabase, pytest, Ruff.

---

## File map

- Create `app/persistence/__init__.py`: cached store factory and public persistence exports.
- Create `app/persistence/config.py`: database URL resolution and live-call durability policy.
- Create `app/persistence/schema.py`: SQLAlchemy definitions for five runtime tables and unique indexes.
- Create `app/persistence/result_store.py`: transactional SQLite/PostgreSQL runtime store.
- Create `app/services/run_checkpoint.py`: canonical sample/prompt hashing and run metadata.
- Create `tests/test_result_store_config.py`: configuration and fail-closed policy tests.
- Create `tests/test_result_store.py`: schema, idempotency, transaction, and restart tests.
- Create `tests/test_result_store_postgres.py`: the same critical store contract against PostgreSQL when `TEST_DATABASE_URL` is present.
- Create `tests/test_run_checkpoint.py`: deterministic hash/version tests.
- Create `tests/test_durable_execution.py`: proves persistence happens before the next provider call.
- Modify `app/services/eval_runner.py`: route answer queue/read/write operations through the result store.
- Modify `app/services/scorer.py`: route score queue/read/write/export operations through the result store.
- Modify `app/services/conclusions.py`: read runtime answers and scores from the selected store.
- Modify `src/ui/test_run.py`: enforce preflight, stop on persistence failure, and restore from either backend without changing visible copy.
- Modify `requirements.txt`: pin direct runtime dependencies.
- Create `requirements-dev.txt`: pin test/lint dependencies.
- Create `pyproject.toml`: pytest and Ruff configuration.
- Create `.github/workflows/ci.yml`: Python 3.11 lint, tests, and dataset validation.

### Task 1: Runtime store configuration and dependencies

**Files:**
- Create: `app/persistence/__init__.py`
- Create: `app/persistence/config.py`
- Create: `tests/test_result_store_config.py`
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`

- [ ] **Step 1: Write failing configuration tests**

```python
from pathlib import Path

import pytest

from app.persistence.config import (
    PersistenceConfigurationError,
    resolve_result_store_settings,
    require_durable_live_store,
)


def test_database_url_wins_and_uses_psycopg():
    settings = resolve_result_store_settings(
        db_path=None,
        environ={"DATABASE_URL": "postgresql://user:pass@db.example.com/postgres"},
        secrets={},
    )
    assert settings.url.startswith("postgresql+psycopg://")
    assert settings.is_postgresql is True


def test_explicit_db_path_builds_absolute_sqlite_url(tmp_path: Path):
    settings = resolve_result_store_settings(
        db_path=tmp_path / "runtime.db", environ={}, secrets={}
    )
    assert settings.url == f"sqlite:///{(tmp_path / 'runtime.db').resolve()}"
    assert settings.is_postgresql is False


def test_real_provider_requires_postgresql_by_default(tmp_path: Path):
    settings = resolve_result_store_settings(
        db_path=tmp_path / "runtime.db", environ={}, secrets={}
    )
    with pytest.raises(PersistenceConfigurationError):
        require_durable_live_store("siliconflow", settings, environ={})


def test_sqlite_live_requires_explicit_opt_in(tmp_path: Path):
    settings = resolve_result_store_settings(
        db_path=tmp_path / "runtime.db", environ={}, secrets={}
    )
    require_durable_live_store(
        "siliconflow", settings, environ={"FINDUEVAL_ALLOW_SQLITE_LIVE": "1"}
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_result_store_config.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'app.persistence'`.

- [ ] **Step 3: Implement configuration resolution**

```python
# app/persistence/config.py
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Any


class PersistenceConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResultStoreSettings:
    url: str
    is_postgresql: bool


def _secret_url(secrets: Mapping[str, Any] | None) -> str:
    if not secrets:
        return ""
    direct = secrets.get("DATABASE_URL")
    if direct:
        return str(direct).strip()
    database = secrets.get("database")
    if isinstance(database, Mapping):
        return str(database.get("url") or "").strip()
    return ""


def _normalize_url(value: str) -> str:
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def resolve_result_store_settings(
    db_path: str | Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
) -> ResultStoreSettings:
    env = os.environ if environ is None else environ
    if db_path is not None:
        path = Path(db_path).resolve()
        return ResultStoreSettings(f"sqlite:///{path}", False)
    raw = str(env.get("DATABASE_URL") or "").strip() or _secret_url(secrets)
    if raw:
        normalized = _normalize_url(raw)
        return ResultStoreSettings(normalized, normalized.startswith("postgresql+psycopg://"))
    from app.db import DEFAULT_DB_PATH
    return ResultStoreSettings(f"sqlite:///{DEFAULT_DB_PATH.resolve()}", False)


def require_durable_live_store(
    provider_name: str,
    settings: ResultStoreSettings,
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    if str(provider_name).strip().lower() == "mock" or settings.is_postgresql:
        return
    env = os.environ if environ is None else environ
    if str(env.get("FINDUEVAL_ALLOW_SQLITE_LIVE") or "").strip().lower() in {"1", "true", "yes"}:
        return
    raise PersistenceConfigurationError("durable result storage is required before live model calls")
```

`app/persistence/__init__.py` initially exports the configuration types; Task 2 adds the cached store factory.

- [ ] **Step 4: Pin runtime and development dependencies**

```text
# requirements.txt
streamlit==1.51.0
pandas==2.3.3
pyyaml==6.0.3
altair==5.5.0
SQLAlchemy==2.0.43
psycopg[binary]==3.3.4
```

```text
# requirements-dev.txt
-r requirements.txt
pytest==8.4.2
ruff==0.12.0
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python3 -m pytest tests/test_result_store_config.py -q`

Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/persistence requirements.txt requirements-dev.txt tests/test_result_store_config.py
git commit -m "feat: configure durable result storage"
```

### Task 2: Transactional SQLAlchemy result store

**Files:**
- Create: `app/persistence/schema.py`
- Create: `app/persistence/result_store.py`
- Modify: `app/persistence/__init__.py`
- Create: `tests/test_result_store.py`
- Create: `tests/test_result_store_postgres.py`

- [ ] **Step 1: Write failing store tests**

```python
from pathlib import Path

import pytest

from app.persistence.result_store import ResultStore, ResultStoreError


def sqlite_store(tmp_path: Path) -> ResultStore:
    store = ResultStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    store.ensure_schema()
    return store


def test_queue_initialization_is_idempotent(tmp_path):
    store = sqlite_store(tmp_path)
    metadata = {"run_id": "RUN-1", "provider": "mock", "status": "running"}
    queue = [{"run_id": "RUN-1", "case_id": "FD-001", "model_id": "m1", "status": "queued"}]
    assert store.initialize_run(metadata, queue) is True
    assert store.initialize_run(metadata, queue) is True
    assert len(store.list_rows("live_run_queue", run_id="RUN-1")) == 1


def test_response_and_queue_status_commit_together(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(
        {"run_id": "RUN-1", "provider": "mock", "status": "running"},
        [{"run_id": "RUN-1", "case_id": "FD-001", "model_id": "m1", "status": "queued"}],
    )
    store.save_run_outcome(
        {"run_id": "RUN-1", "case_id": "FD-001", "model_name": "m1", "run_status": "success", "answer_text": "ok"},
        queue_status="success",
    )
    assert store.list_rows("live_run_responses", run_id="RUN-1")[0]["answer_text"] == "ok"
    assert store.list_rows("live_run_queue", run_id="RUN-1")[0]["status"] == "success"


def test_failed_transaction_keeps_queue_unfinished(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_run(
        {"run_id": "RUN-1", "provider": "mock", "status": "running"},
        [{"run_id": "RUN-1", "case_id": "FD-001", "model_id": "m1", "status": "queued"}],
    )
    with pytest.raises(ResultStoreError):
        store.save_run_outcome(
            {"run_id": "RUN-1", "case_id": None, "model_name": "m1", "answer_text": "bad"},
            queue_status="success",
        )
    assert store.list_rows("live_run_responses", run_id="RUN-1") == []
    assert store.list_rows("live_run_queue", run_id="RUN-1")[0]["status"] == "queued"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_result_store.py -q`

Expected: import fails because `ResultStore` does not exist.

- [ ] **Step 3: Define the runtime schema**

Create SQLAlchemy metadata for `live_evaluation_runs`, `live_run_responses`, `live_run_scores`, `live_run_queue`, and `live_score_queue`. Reproduce every existing business column from `app/db/schema.sql`; add non-null natural-key columns and these constraints:

```python
UniqueConstraint("run_id", "case_id", "model_name", name="uq_live_response"),
UniqueConstraint("score_run_id", "case_id", "eval_model", name="uq_live_score"),
UniqueConstraint("run_id", "case_id", "model_id", name="uq_live_run_queue"),
UniqueConstraint("score_run_id", "case_id", "eval_model", name="uq_live_score_queue"),
```

`live_evaluation_runs` must contain the following exact fields:

```python
Table(
    "live_evaluation_runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("provider", String, nullable=False),
    Column("model_ids_json", Text, nullable=False, default="[]"),
    Column("generation_parameters_json", Text, nullable=False, default="{}"),
    Column("judge_parameters_json", Text, nullable=False, default="{}"),
    Column("dataset_version", String),
    Column("dataset_hash", String(64), nullable=False),
    Column("prompt_hash", String(64), nullable=False),
    Column("status", String, nullable=False, default="queued"),
    Column("completed_count", Integer, nullable=False, default=0),
    Column("failed_count", Integer, nullable=False, default=0),
    Column("pending_count", Integer, nullable=False, default=0),
    Column("last_persistence_error", Text),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now(), onupdate=func.now()),
)
```

- [ ] **Step 4: Implement the store with dialect-specific upsert**

The store must expose this complete public surface:

```python
class ResultStoreError(RuntimeError):
    pass


class ResultStore:
    def __init__(self, url: str): ...
    @property
    def is_postgresql(self) -> bool: ...
    def ensure_schema(self) -> None: ...
    def ping(self) -> bool: ...
    def initialize_run(self, run: dict, queue_rows: list[dict]) -> bool: ...
    def mark_run_item_running(self, run_id: str, case_id: str, model_id: str) -> bool: ...
    def save_run_outcome(self, row: dict, *, queue_status: str) -> bool: ...
    def initialize_score_queue(self, rows: list[dict]) -> bool: ...
    def mark_score_item_running(self, score_run_id: str, case_id: str, eval_model: str) -> bool: ...
    def save_score_outcome(self, row: dict, *, queue_status: str) -> bool: ...
    def list_rows(self, table: str, **filters: object) -> list[dict]: ...
    def latest_queue(self, table: str) -> list[dict]: ...
```

Use `engine.begin()` for queue creation and answer/score transitions. Use `sqlalchemy.dialects.sqlite.insert` or `sqlalchemy.dialects.postgresql.insert` and `on_conflict_do_update`; never perform select-then-insert outside the same transaction. Convert SQLAlchemy exceptions to `ResultStoreError` with exception chaining, without embedding the database URL in the message.

- [ ] **Step 5: Add the cached factory**

```python
# app/persistence/__init__.py
from functools import lru_cache
from pathlib import Path

from .config import resolve_result_store_settings
from .result_store import ResultStore, ResultStoreError


@lru_cache(maxsize=8)
def _store_for_url(url: str) -> ResultStore:
    store = ResultStore(url)
    store.ensure_schema()
    return store


def get_result_store(db_path: str | Path | None = None, *, secrets=None) -> ResultStore:
    settings = resolve_result_store_settings(db_path, secrets=secrets)
    return _store_for_url(settings.url)
```

- [ ] **Step 6: Run tests and verify GREEN**

Run: `python3 -m pytest tests/test_result_store.py tests/test_result_store_config.py -q`

Expected: `7 passed`.

Create the PostgreSQL contract test now so it exists before Task 7. It is skipped only when `TEST_DATABASE_URL` is absent:

```python
import os

import pytest

from app.persistence.result_store import ResultStore


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured"
)


def test_postgres_answer_transition_is_idempotent_and_atomic():
    store = ResultStore(os.environ["TEST_DATABASE_URL"])
    store.ensure_schema()
    run_id = "PYTEST-POSTGRES-RUN"
    store.initialize_run(
        {
            "run_id": run_id, "provider": "mock", "status": "running",
            "dataset_hash": "d" * 64, "prompt_hash": "p" * 64,
        },
        [{"run_id": run_id, "case_id": "FD-001", "model_id": "m1", "status": "queued"}],
    )
    row = {
        "run_id": run_id, "case_id": "FD-001", "model_name": "m1",
        "run_status": "success", "answer_text": "saved",
    }
    store.save_run_outcome(row, queue_status="success")
    store.save_run_outcome(row, queue_status="success")
    assert len(store.list_rows("live_run_responses", run_id=run_id)) == 1
    assert store.list_rows("live_run_queue", run_id=run_id)[0]["status"] == "success"
```

- [ ] **Step 7: Commit**

```bash
git add app/persistence tests/test_result_store.py tests/test_result_store_postgres.py
git commit -m "feat: add transactional runtime result store"
```

### Task 3: Version-bound run checkpoints

**Files:**
- Create: `app/services/run_checkpoint.py`
- Create: `tests/test_run_checkpoint.py`

- [ ] **Step 1: Write failing fingerprint tests**

```python
from app.services.run_checkpoint import build_run_metadata, canonical_hash


def test_canonical_hash_ignores_mapping_order():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_sample_change_changes_dataset_hash():
    first = build_run_metadata(
        run_id="RUN-1", provider="mock", model_ids=["m1"],
        queue_items=[{"case_id": "FD-001", "task": {"question": "A", "context": "B"}}],
        generation_parameters={"temperature": 0.1, "max_tokens": 4096},
        judge_parameters={"temperature": 0.0, "max_tokens": 2048},
        dataset_version="1.0.0", prompt_payload={"system": "prompt-v1"},
    )
    second = build_run_metadata(
        run_id="RUN-1", provider="mock", model_ids=["m1"],
        queue_items=[{"case_id": "FD-001", "task": {"question": "changed", "context": "B"}}],
        generation_parameters={"temperature": 0.1, "max_tokens": 4096},
        judge_parameters={"temperature": 0.0, "max_tokens": 2048},
        dataset_version="1.0.0", prompt_payload={"system": "prompt-v1"},
    )
    assert first["dataset_hash"] != second["dataset_hash"]
    assert first["prompt_hash"] == second["prompt_hash"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m pytest tests/test_run_checkpoint.py -q`

Expected: import fails because `run_checkpoint` does not exist.

- [ ] **Step 3: Implement canonical metadata**

```python
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_run_metadata(
    *, run_id: str, provider: str, model_ids: Sequence[str],
    queue_items: Sequence[Mapping[str, Any]],
    generation_parameters: Mapping[str, Any],
    judge_parameters: Mapping[str, Any],
    dataset_version: str, prompt_payload: Any,
) -> dict[str, Any]:
    samples = [
        {"case_id": item.get("case_id"), "task": item.get("task") or {}}
        for item in queue_items
    ]
    return {
        "run_id": run_id,
        "provider": provider,
        "model_ids_json": json.dumps(list(model_ids), ensure_ascii=False),
        "generation_parameters_json": json.dumps(dict(generation_parameters), ensure_ascii=False, sort_keys=True),
        "judge_parameters_json": json.dumps(dict(judge_parameters), ensure_ascii=False, sort_keys=True),
        "dataset_version": dataset_version,
        "dataset_hash": canonical_hash(samples),
        "prompt_hash": canonical_hash(prompt_payload),
        "status": "running",
        "completed_count": 0,
        "failed_count": 0,
        "pending_count": len(samples),
    }
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python3 -m pytest tests/test_run_checkpoint.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/services/run_checkpoint.py tests/test_run_checkpoint.py
git commit -m "feat: bind runs to dataset and prompt versions"
```

### Task 4: Route runner and scorer through the store

**Files:**
- Modify: `app/services/eval_runner.py:537-970`
- Modify: `app/services/scorer.py:416-780, 1040-1070`
- Modify: `tests/test_live_evaluation.py`
- Modify: `tests/test_scoring_workflow.py`

- [ ] **Step 1: Add failing backend-compatible service tests**

Extend existing tests so an explicit temporary `db_path` still works and add assertions that:

```python
assert er.initialize_run_queue(run_id, "mock", queue_items, metadata=run_metadata, db_path=db_path)
assert er.mark_run_queue_item_running(run_id, "FD-001", "m1", db_path=db_path)
assert er.persist_run_outcome(run_id, "mock", outcome, db_path=db_path)
assert er.restore_compare_result_from_db(run_id, db_path=db_path).outcomes[0].answer_text == "saved"

assert sc.initialize_score_queue(score_run_id, run_id, [outcome], "mock", "judge", db_path=db_path)
assert sc.mark_score_queue_item_running(score_run_id, "FD-001", "m1", db_path=db_path)
assert sc.persist_score_outcome(score_run_id, run_id, "mock", "judge", "mock", score, db_path=db_path)
assert sc.restore_score_result_from_db(score_run_id, db_path=db_path).outcomes[0].total_score == 80
```

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python3 -m pytest tests/test_live_evaluation.py tests/test_scoring_workflow.py -q`

Expected: failure because `initialize_run_queue` does not accept `metadata` and services still use SQLite `Repository`.

- [ ] **Step 3: Replace runtime repository calls**

Preserve public function names and `db_path` arguments. Each function obtains `store = get_result_store(db_path)` and delegates to the matching store method. `initialize_run_queue` accepts `metadata: Mapping[str, Any] | None = None`; if omitted by older tests, build a minimal deterministic metadata dictionary with hashes of the queue rows.

Remove `_ensure_live_run_response_columns`; schema creation now belongs exclusively to `ResultStore.ensure_schema()`. Read functions use `store.list_rows(...)`, latest functions use `store.latest_queue(...)`, and reconstruction continues to return existing `RunOutcome`, `CompareRunResult`, `ScoreOutcome`, and `ScoreResult` types.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run: `python3 -m pytest tests/test_live_evaluation.py tests/test_scoring_workflow.py -q`

Expected: all tests in both files pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/eval_runner.py app/services/scorer.py tests/test_live_evaluation.py tests/test_scoring_workflow.py
git commit -m "refactor: persist evaluation queues through result store"
```

### Task 5: Fail-closed execution and durable readers

**Files:**
- Create: `tests/test_durable_execution.py`
- Modify: `src/ui/test_run.py:1160-1735`
- Modify: `app/services/conclusions.py:79-110`
- Modify: `app/services/scorer.py:758-816`
- Modify: `tests/test_test_run_flow.py`
- Modify: `tests/test_conclusions.py`

- [ ] **Step 1: Write failing ordering and stop tests**

Add a pure helper to `src/ui/test_run.py` that is testable without rendering:

```python
def _persistence_gate(result: bool) -> None:
    if not result:
        raise RuntimeError("runtime persistence required")
```

The test records events and verifies no provider event occurs after a failed gate:

```python
def test_persistence_gate_stops_before_provider_call():
    events = []
    with pytest.raises(RuntimeError):
        events.append("initialize")
        test_run._persistence_gate(False)
        events.append("provider")
    assert events == ["initialize"]
```

Also add tests that `conclusions.load_live_scores()` and score export read from a monkeypatched `ResultStore`, not `Repository(DEFAULT_DB_PATH)`.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python3 -m pytest tests/test_durable_execution.py tests/test_test_run_flow.py tests/test_conclusions.py -q`

Expected: missing `_persistence_gate` and reader tests fail.

- [ ] **Step 3: Enforce answer preflight and per-item persistence**

In `_execute_run_queue`:

1. Build run metadata with `build_run_metadata`, `ds.get_dataset_version()`, and `er.build_messages` output.
2. Call `require_durable_live_store` and `er.initialize_run_queue` before the first `er.run_single`.
3. Require `mark_run_queue_item_running` to succeed before each `er.run_single`.
4. Append the returned outcome to session state, then require `persist_run_outcome` to succeed before continuing.
5. On a failed persistence gate, set `interrupted = True`, reuse the existing interruption message, finalize current in-memory state, and do not invoke remaining provider calls.

Apply the same ordering to `_execute_score_queue` and `_execute_retry_score_queue`: queue initialization and running-state persistence happen before `score_single`; score persistence succeeds before the next score call.

- [ ] **Step 4: Use the result store for all runtime readers**

Change `conclusions._load_live_table`, score export, and recovery helpers to call `get_result_store(db_path).list_rows(table)` and construct DataFrames from those rows. Preserve function signatures and empty-DataFrame fallback behavior. Rename private UI helpers from `_recover_latest_*_from_sqlite` to `_recover_latest_*` without changing any displayed strings.

- [ ] **Step 5: Run targeted tests and verify GREEN**

Run: `python3 -m pytest tests/test_durable_execution.py tests/test_test_run_flow.py tests/test_conclusions.py tests/test_live_results.py -q`

Expected: all targeted tests pass and UI text guard assertions remain unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/ui/test_run.py app/services/conclusions.py app/services/scorer.py tests/test_durable_execution.py tests/test_test_run_flow.py tests/test_conclusions.py
git commit -m "fix: stop token calls when persistence fails"
```

### Task 6: Engineering baseline and full verification

**Files:**
- Create: `pyproject.toml`
- Create: `.github/workflows/ci.yml`
- Modify: production files reported by Ruff only when the change is behavior-neutral

- [ ] **Step 1: Add deterministic test and lint configuration**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.ruff.lint.per-file-ignores]
"scripts/validate_dataset.py" = ["E402"]
"tests/*" = ["E402"]
```

- [ ] **Step 2: Add CI**

```yaml
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: ruff check app.py app src scripts tests
      - run: python -m pytest
      - run: python scripts/validate_dataset.py
```

- [ ] **Step 3: Run Ruff, fix only reported production issues, and verify**

Run: `ruff check app.py app src scripts tests`

Expected: `All checks passed!`.

- [ ] **Step 4: Run the complete test and data suites**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider`

Expected: at least the original 507 tests plus new persistence tests pass.

Run: `python3 scripts/validate_dataset.py`

Expected: `20 passed`, `0 warnings`, `0 errors`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml requirements.txt requirements-dev.txt app src scripts tests
git commit -m "chore: add reproducible quality checks"
```

### Task 7: PostgreSQL validation, fresh generation, and Streamlit restart

**Files:**
- No source changes unless verification exposes a tested defect.
- Runtime data: PostgreSQL/Supabase tables only; do not import the old 45 answers, 45 scores, or 6 demo scores.

- [ ] **Step 1: Validate PostgreSQL configuration without printing secrets**

Run a short Python check that reports only backend type, `ping()` result, and table names. It must not print `DATABASE_URL`.

Expected: backend is `postgresql`, ping is `True`, and all five runtime tables exist.

- [ ] **Step 2: Run PostgreSQL integration tests**

Run: `TEST_DATABASE_URL="$DATABASE_URL" python3 -m pytest tests/test_result_store_postgres.py -q`

Expected: schema, idempotency, atomic answer transition, atomic score transition, and restart read tests pass against PostgreSQL.

- [ ] **Step 3: Perform a one-item smoke run**

Use one current sample and one selected model. Confirm in PostgreSQL that one queue row exists before the provider call, then one response row and a `success` or `failed` queue status exist afterward. Generate its judge score and confirm the same ordering for the score queue.

- [ ] **Step 4: Generate the fresh current-sample batch**

Use the current 13 samples and the models selected in the existing Streamlit workflow. Before execution, record the expected answer count as `13 × selected model count`. Run answers and scores through the UI; if interrupted, resume the same run ID. Verify the final database counts, dataset hash, prompt hash, statuses, and Token totals before export.

- [ ] **Step 5: Read verification-before-completion and run final verification**

Run the full pytest, Ruff, dataset validation, SQLite integration, PostgreSQL integration, and Streamlit smoke checks again using fresh command output.

- [ ] **Step 6: Restart Streamlit only after all results are durable**

Stop the three old local instances on ports 8534, 8535, and 8536. Start one Python 3.11 instance on port 8536 from the finalized workspace. Open the page, confirm the new run is reconstructed from PostgreSQL, and verify no model API call occurs during page load.

- [ ] **Step 7: Commit verification-only fixes if any, then finish the branch**

If verification required no source changes, do not create an empty commit. Otherwise commit only tested fixes, then use the finishing-development-branch workflow.
