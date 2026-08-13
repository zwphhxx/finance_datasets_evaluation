"""Durable, synchronous answer-and-score evaluation workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

import pandas as pd

from app.services import eval_runner as er
from app.services import formal_records as formal
from app.services import scorer as sc
from app.services.run_checkpoint import build_run_metadata

RUNNING = "running"
COMPLETED = "completed"
PARTIAL = "partial"
INTERRUPTED = "interrupted"
STOPPED = "stopped"
FAILED = "failed"


class WorkflowStopped(RuntimeError):
    """Raised when a durable workflow cannot safely continue."""


@dataclass(frozen=True)
class EvaluationConfig:
    provider_name: str
    model_ids: tuple[str, ...]
    queue_items: tuple[Mapping[str, Any], ...]
    generation_parameters: Mapping[str, Any]
    judge_parameters: Mapping[str, Any]
    dataset_version: str
    prompt_payload: tuple[Any, ...]
    gold_map: Mapping[str, Mapping[str, Any]]
    dimensions: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class EvaluationRunRef:
    run_id: str
    score_run_id: str


@dataclass(frozen=True)
class EvaluationRunStatus:
    run_id: str
    score_run_id: str
    state: str
    total: int
    succeeded: int
    failed: int
    pending: int
    resumable: bool
    message: str = ""
    persistence_failed_in_session: bool = False


def inactivity_threshold(config: EvaluationConfig) -> float:
    """Return the recovery inactivity timeout for both model calls in a pair."""
    answer_timeout = _positive_number(config.generation_parameters.get("timeout_seconds"))
    score_timeout = _positive_number(config.judge_parameters.get("timeout_seconds"))
    return max(900.0, max(answer_timeout, score_timeout) + 120.0)


def answer_queue_row(run_id: str, item: Mapping[str, Any], provider_name: str) -> dict[str, Any]:
    task = _task(item)
    return {
        "run_id": run_id,
        "case_id": str(item["case_id"]),
        "task_type": str(task.get("task_type") or ""),
        "model_id": str(item["model_id"]),
        "provider": provider_name,
        "status": "queued",
        "attempt_count": 0,
    }


def score_queue_row(
    run_id: str,
    score_run_id: str,
    item: Mapping[str, Any],
    judge_provider: str,
    judge_model: str,
) -> dict[str, Any]:
    task = _task(item)
    return {
        "score_run_id": score_run_id,
        "run_id": run_id,
        "case_id": str(item["case_id"]),
        "task_type": str(task.get("task_type") or ""),
        "eval_model": str(item["model_id"]),
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "status": "queued",
        "attempt_count": 0,
    }


class EvaluationWorkflow:
    """Run each answer and its judge score as one durable queue pair."""

    def __init__(
        self,
        store: Any,
        answer_provider: Any,
        judge_provider: Any,
        now: Callable[[], datetime] = datetime.utcnow,
    ) -> None:
        self.store = store
        self.answer_provider = answer_provider
        self.judge_provider = judge_provider
        self.now = now
        self._session_stopped_run_ids: set[str] = set()

    def start_evaluation(self, config: EvaluationConfig) -> EvaluationRunRef:
        self._validate_providers(config)
        run_id = er.generate_run_id()
        score_run_id = sc.generate_score_run_id()
        ref = EvaluationRunRef(run_id, score_run_id)
        judge_model = _required_text(config.judge_parameters.get("judge_model"), "judge model")
        metadata = build_run_metadata(
            run_id=run_id,
            provider=config.provider_name,
            model_ids=config.model_ids,
            queue_items=config.queue_items,
            generation_parameters=config.generation_parameters,
            judge_parameters=config.judge_parameters,
            dataset_version=config.dataset_version,
            prompt_payload=config.prompt_payload,
        )
        try:
            self.store.initialize_evaluation(
                metadata,
                [answer_queue_row(run_id, item, config.provider_name) for item in config.queue_items],
                [
                    score_queue_row(
                        run_id,
                        score_run_id,
                        item,
                        str(getattr(self.judge_provider, "name", "")),
                        judge_model,
                    )
                    for item in config.queue_items
                ],
            )
        except Exception as exc:
            self._stop(run_id, "could not initialize evaluation queues", exc)

        for item in config.queue_items:
            try:
                self._execute_item(ref, config, item, judge_model)
            except WorkflowStopped:
                raise
            except Exception as exc:
                self._stop(run_id, "could not persist evaluation outcome", exc)
        return ref

    def load_evaluation_status(self, run_id: str) -> EvaluationRunStatus:
        run_rows = self.store.list_rows("live_evaluation_runs", run_id=run_id)
        if not run_rows:
            raise WorkflowStopped("evaluation run does not exist")
        run = run_rows[0]
        answer_rows = self.store.list_rows("live_run_queue", run_id=run_id)
        score_rows = self.store.list_rows("live_score_queue", run_id=run_id)
        score_run_id = str(score_rows[0].get("score_run_id") or "") if score_rows else ""
        score_by_pair = {
            (str(row.get("case_id") or ""), str(row.get("eval_model") or "")): str(row.get("status") or "")
            for row in score_rows
        }
        succeeded = failed = pending = 0
        for row in answer_rows:
            pair = (str(row.get("case_id") or ""), str(row.get("model_id") or ""))
            answer_state = str(row.get("status") or "")
            score_state = score_by_pair.get(pair, "")
            if answer_state == "success" and score_state == "success":
                succeeded += 1
            elif answer_state == "failed" or score_state in {"failed", "skipped"}:
                failed += 1
            else:
                pending += 1
        if pending:
            stored = str(run.get("status") or RUNNING)
            state = stored if stored in {INTERRUPTED, STOPPED} else RUNNING
        elif succeeded and failed:
            state = PARTIAL
        elif succeeded:
            state = COMPLETED
        else:
            state = FAILED
        return EvaluationRunStatus(
            run_id=run_id,
            score_run_id=score_run_id,
            state=state,
            total=len(answer_rows),
            succeeded=succeeded,
            failed=failed,
            pending=pending,
            resumable=state in {INTERRUPTED, STOPPED},
            message=str(run.get("last_persistence_error") or ""),
            persistence_failed_in_session=run_id in self._session_stopped_run_ids,
        )

    def _execute_item(
        self,
        ref: EvaluationRunRef,
        config: EvaluationConfig,
        item: Mapping[str, Any],
        judge_model: str,
    ) -> None:
        case_id = str(item["case_id"])
        model_id = str(item["model_id"])
        task = _task(item)
        answer_queue = self._queue_row("live_run_queue", run_id=ref.run_id, case_id=case_id, model_id=model_id)
        score_queue = self._queue_row(
            "live_score_queue",
            score_run_id=ref.score_run_id,
            case_id=case_id,
            eval_model=model_id,
        )
        answer_rows = self.store.list_rows(
            "live_run_responses", run_id=ref.run_id, case_id=case_id, model_name=model_id
        )
        score_rows = self.store.list_rows(
            "live_run_scores", score_run_id=ref.score_run_id, case_id=case_id, eval_model=model_id
        )
        if self._has_formal_score(score_rows, answer_rows):
            return
        if answer_queue["status"] == "failed" or score_queue["status"] in {"failed", "skipped"}:
            return

        response = self._formal_response(answer_rows)
        if response is None:
            self.store.mark_run_item_running(ref.run_id, case_id, model_id, combined=True)
            outcome = er.run_single(
                self.answer_provider,
                model_id,
                task,
                temperature=_number(config.generation_parameters.get("temperature"), 0.2),
                max_tokens=_integer(config.generation_parameters.get("max_tokens"), 1024),
            )
            self.store.save_run_outcome(
                er.serialize_run_outcome(ref.run_id, "live", outcome),
                queue_status="success" if outcome.success else "failed",
                combined=True,
            )
            answer_rows = self.store.list_rows(
                "live_run_responses", run_id=ref.run_id, case_id=case_id, model_name=model_id
            )
            response = self._formal_response(answer_rows)
        if response is None:
            self.store.mark_score_item_skipped(ref.score_run_id, case_id, model_id, "answer_failed")
            return

        self.store.mark_score_item_running(ref.score_run_id, case_id, model_id)
        score = sc.score_single(
            self.judge_provider,
            judge_model,
            task,
            str(response.get("answer_text") or ""),
            config.gold_map.get(case_id) or {},
            config.dimensions,
            eval_model=model_id,
            temperature=_number(config.judge_parameters.get("temperature"), 0.0),
            max_tokens=_integer(config.judge_parameters.get("max_tokens"), 1024),
        )
        self.store.save_score_outcome(
            sc.serialize_score_outcome(
                ref.score_run_id,
                ref.run_id,
                str(getattr(self.judge_provider, "name", "")),
                judge_model,
                "live",
                score,
            ),
            queue_status="success" if score.ok else "failed",
        )

    def _queue_row(self, table: str, **filters: str) -> Mapping[str, Any]:
        rows = self.store.list_rows(table, **filters)
        if len(rows) != 1:
            raise WorkflowStopped("evaluation queue row is missing")
        return rows[0]

    @staticmethod
    def _formal_response(rows: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
        if not rows:
            return None
        accepted = formal.filter_formal_responses(pd.DataFrame(rows))
        return accepted.iloc[0].to_dict() if not accepted.empty else None

    @staticmethod
    def _has_formal_score(
        score_rows: list[Mapping[str, Any]],
        response_rows: list[Mapping[str, Any]],
    ) -> bool:
        if not score_rows or not response_rows:
            return False
        return not formal.filter_formal_scores(
            pd.DataFrame(score_rows), pd.DataFrame(response_rows)
        ).empty

    def _validate_providers(self, config: EvaluationConfig) -> None:
        for configured, provider in ((config.provider_name, self.answer_provider), ("", self.judge_provider)):
            names = {str(configured or "").strip().lower(), str(getattr(provider, "name", "")).strip().lower()}
            if names.intersection({"mock", "demo"}):
                raise WorkflowStopped("mock and demo providers cannot start a formal evaluation")

    def _stop(self, run_id: str, message: str, cause: Exception) -> None:
        self._session_stopped_run_ids.add(run_id)
        try:
            self.store.mark_run_stopped(run_id, message)
        except Exception:
            pass
        raise WorkflowStopped(message) from cause


def _task(item: Mapping[str, Any]) -> Mapping[str, Any]:
    task = item.get("task")
    if not isinstance(task, Mapping):
        raise WorkflowStopped("evaluation queue item has no task")
    return task


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkflowStopped(f"evaluation configuration is missing {name}")
    return text


def _positive_number(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _number(value: Any, default: float) -> float:
    return _positive_number(value) if _positive_number(value) else default


def _integer(value: Any, default: int) -> int:
    return int(_number(value, float(default)))
