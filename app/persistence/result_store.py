"""Transactional runtime result store for SQLite and PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import create_engine, func, inspect, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from .schema import (
    RUNTIME_TABLES,
    live_evaluation_runs,
    live_run_queue,
    live_run_responses,
    live_run_scores,
    live_score_queue,
    metadata,
)


class ResultStoreError(RuntimeError):
    """Raised when runtime results cannot be stored consistently."""


_CONFLICT_COLUMNS = {
    "live_evaluation_runs": ("run_id",),
    "live_run_responses": ("run_id", "case_id", "model_name"),
    "live_run_queue": ("run_id", "case_id", "model_id"),
    "live_run_scores": ("score_run_id", "case_id", "eval_model"),
    "live_score_queue": ("score_run_id", "case_id", "eval_model"),
}


class ResultStore:
    """Store runtime queues and outcomes with transaction-level consistency."""

    def __init__(self, url: str):
        normalized = self._normalize_url(str(url or "").strip())
        try:
            self.engine: Engine = create_engine(normalized, pool_pre_ping=True, future=True)
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not configure runtime result storage") from exc

    @staticmethod
    def _normalize_url(url: str) -> str:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    @property
    def is_postgresql(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    def ensure_schema(self) -> None:
        try:
            metadata.create_all(self.engine, checkfirst=True)
            with self.engine.begin() as connection:
                for table in RUNTIME_TABLES.values():
                    for index in table.indexes:
                        index.create(connection, checkfirst=True)
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not initialize runtime result storage") from exc

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(select(1)).scalar_one()
            return True
        except SQLAlchemyError:
            return False

    def table_names(self) -> list[str]:
        existing = set(inspect(self.engine).get_table_names())
        return sorted(existing.intersection(RUNTIME_TABLES))

    def initialize_run(self, run: Mapping[str, Any], queue_rows: Iterable[Mapping[str, Any]]) -> bool:
        run_row = self._validated(run, "live_evaluation_runs", ("run_id", "provider", "dataset_hash", "prompt_hash"))
        rows = [self._validated(row, "live_run_queue", ("run_id", "case_id", "model_id")) for row in queue_rows]
        if not rows:
            raise ResultStoreError("run queue cannot be empty")
        try:
            with self.engine.begin() as connection:
                self._upsert(
                    connection,
                    live_evaluation_runs,
                    run_row,
                    update_existing=False,
                )
                for row in rows:
                    self._upsert(
                        connection,
                        live_run_queue,
                        row,
                        update_existing=False,
                    )
                self._refresh_run_counts(connection, str(run_row["run_id"]))
            return True
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not initialize runtime queue") from exc

    def mark_run_item_running(self, run_id: str, case_id: str, model_id: str) -> bool:
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(live_run_queue)
                    .where(
                        live_run_queue.c.run_id == run_id,
                        live_run_queue.c.case_id == case_id,
                        live_run_queue.c.model_id == model_id,
                    )
                    .values(
                        status="running",
                        attempt_count=live_run_queue.c.attempt_count + 1,
                        updated_at=func.now(),
                    )
                )
                if result.rowcount != 1:
                    raise ResultStoreError("runtime queue item does not exist")
            return True
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not mark runtime queue item") from exc

    def save_run_outcome(self, row: Mapping[str, Any], *, queue_status: str) -> bool:
        response = self._validated(
            row,
            "live_run_responses",
            ("run_id", "case_id", "model_name"),
        )
        run_id = str(response["run_id"])
        try:
            with self.engine.begin() as connection:
                self._upsert(connection, live_run_responses, response)
                result = connection.execute(
                    update(live_run_queue)
                    .where(
                        live_run_queue.c.run_id == run_id,
                        live_run_queue.c.case_id == response["case_id"],
                        live_run_queue.c.model_id == response["model_name"],
                    )
                    .values(
                        status=queue_status,
                        error_code=response.get("error_code"),
                        error_message=response.get("error_message"),
                        updated_at=func.now(),
                    )
                )
                if result.rowcount != 1:
                    raise ResultStoreError("runtime queue item does not exist")
                self._refresh_run_counts(connection, run_id)
            return True
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not save runtime outcome") from exc

    def initialize_score_queue(self, rows: Iterable[Mapping[str, Any]]) -> bool:
        payload = [
            self._validated(row, "live_score_queue", ("score_run_id", "case_id", "eval_model"))
            for row in rows
        ]
        if not payload:
            raise ResultStoreError("score queue cannot be empty")
        try:
            with self.engine.begin() as connection:
                for row in payload:
                    self._upsert(
                        connection,
                        live_score_queue,
                        row,
                        update_existing=False,
                    )
            return True
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not initialize score queue") from exc

    def mark_score_item_running(self, score_run_id: str, case_id: str, eval_model: str) -> bool:
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(live_score_queue)
                    .where(
                        live_score_queue.c.score_run_id == score_run_id,
                        live_score_queue.c.case_id == case_id,
                        live_score_queue.c.eval_model == eval_model,
                    )
                    .values(
                        status="running",
                        attempt_count=live_score_queue.c.attempt_count + 1,
                        updated_at=func.now(),
                    )
                )
                if result.rowcount != 1:
                    raise ResultStoreError("score queue item does not exist")
            return True
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not mark score queue item") from exc

    def save_score_outcome(self, row: Mapping[str, Any], *, queue_status: str) -> bool:
        score = self._validated(
            row,
            "live_run_scores",
            ("score_run_id", "case_id", "eval_model"),
        )
        try:
            with self.engine.begin() as connection:
                self._upsert(connection, live_run_scores, score)
                result = connection.execute(
                    update(live_score_queue)
                    .where(
                        live_score_queue.c.score_run_id == score["score_run_id"],
                        live_score_queue.c.case_id == score["case_id"],
                        live_score_queue.c.eval_model == score["eval_model"],
                    )
                    .values(
                        status=queue_status,
                        error_code=score.get("error_code"),
                        error_message=score.get("error_message"),
                        updated_at=func.now(),
                    )
                )
                if result.rowcount != 1:
                    raise ResultStoreError("score queue item does not exist")
            return True
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not save score outcome") from exc

    def list_rows(self, table: str, **filters: object) -> list[dict[str, Any]]:
        target = self._table(table)
        statement = select(target)
        for name, value in filters.items():
            if name not in target.c:
                raise ResultStoreError("unknown runtime result filter")
            statement = statement.where(target.c[name] == value)
        order = target.c.id if "id" in target.c else target.c.created_at
        statement = statement.order_by(order)
        try:
            with self.engine.connect() as connection:
                return [dict(row) for row in connection.execute(statement).mappings()]
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not read runtime results") from exc

    def latest_queue(self, table: str) -> list[dict[str, Any]]:
        if table not in {"live_run_queue", "live_score_queue"}:
            raise ResultStoreError("latest queue requires a queue table")
        target = self._table(table)
        group_column = "run_id" if table == "live_run_queue" else "score_run_id"
        try:
            with self.engine.connect() as connection:
                latest = connection.execute(
                    select(target.c[group_column]).order_by(target.c.id.desc()).limit(1)
                ).scalar_one_or_none()
            return [] if latest is None else self.list_rows(table, **{group_column: latest})
        except SQLAlchemyError as exc:
            raise ResultStoreError("could not read latest runtime queue") from exc

    def _upsert(
        self,
        connection: Connection,
        table,
        row: Mapping[str, Any],
        *,
        update_existing: bool = True,
    ) -> None:
        values = self._filtered(table.name, row)
        conflict = _CONFLICT_COLUMNS[table.name]
        if self.engine.dialect.name == "postgresql":
            statement = postgresql_insert(table).values(**values)
        elif self.engine.dialect.name == "sqlite":
            statement = sqlite_insert(table).values(**values)
        else:
            raise ResultStoreError("unsupported runtime result database")
        if not update_existing:
            connection.execute(
                statement.on_conflict_do_nothing(
                    index_elements=[table.c[name] for name in conflict]
                )
            )
            return
        updates = {
            column: getattr(statement.excluded, column)
            for column in values
            if column not in conflict and column not in {"id", "created_at"}
        }
        if "updated_at" in table.c:
            updates["updated_at"] = func.now()
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[table.c[name] for name in conflict],
                set_=updates,
            )
        )

    def _refresh_run_counts(self, connection: Connection, run_id: str) -> None:
        statuses = connection.execute(
            select(live_run_queue.c.status, func.count().label("count"))
            .where(live_run_queue.c.run_id == run_id)
            .group_by(live_run_queue.c.status)
        ).all()
        counts = {str(status): int(count) for status, count in statuses}
        completed = counts.get("success", 0)
        failed = counts.get("failed", 0)
        pending = sum(counts.get(name, 0) for name in ("queued", "running"))
        status = "completed" if pending == 0 else "running"
        connection.execute(
            update(live_evaluation_runs)
            .where(live_evaluation_runs.c.run_id == run_id)
            .values(
                completed_count=completed,
                failed_count=failed,
                pending_count=pending,
                status=status,
                updated_at=func.now(),
            )
        )

    def _validated(
        self,
        row: Mapping[str, Any],
        table: str,
        required: tuple[str, ...],
    ) -> dict[str, Any]:
        values = self._filtered(table, row)
        if any(values.get(name) in {None, ""} for name in required):
            raise ResultStoreError("runtime result is missing a required key")
        return values

    @staticmethod
    def _filtered(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
        target = RUNTIME_TABLES[table]
        return {name: value for name, value in row.items() if name in target.c}

    @staticmethod
    def _table(table: str):
        try:
            return RUNTIME_TABLES[table]
        except KeyError as exc:
            raise ResultStoreError("unknown runtime result table") from exc
