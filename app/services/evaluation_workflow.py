"""Durable, synchronous answer-and-score evaluation workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


class WorkflowCheckpointError(ValueError):
    """Raised when persisted queue state cannot represent a safe checkpoint."""


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


def derive_status(
    run: Mapping[str, Any],
    answers: list[Mapping[str, Any]],
    scores: list[Mapping[str, Any]],
    stale: bool,
    stopped_here: bool = False,
    *,
    owned: bool = False,
) -> EvaluationRunStatus:
    """Derive a safe combined state from one persisted answer/score checkpoint."""
    run_id = _required_checkpoint_text(run.get("run_id"))
    if not answers or not scores:
        raise WorkflowCheckpointError("evaluation checkpoint is incomplete")
    answer_pairs: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in answers:
        if _required_checkpoint_text(row.get("run_id")) != run_id:
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
        pair = (_required_checkpoint_text(row.get("case_id")), _required_checkpoint_text(row.get("model_id")))
        if pair in answer_pairs:
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
        answer_pairs[pair] = row
    score_pairs: dict[tuple[str, str], Mapping[str, Any]] = {}
    score_run_ids: set[str] = set()
    for row in scores:
        if _required_checkpoint_text(row.get("run_id")) != run_id:
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
        pair = (_required_checkpoint_text(row.get("case_id")), _required_checkpoint_text(row.get("eval_model")))
        if pair in score_pairs:
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
        score_pairs[pair] = row
        score_run_ids.add(_required_checkpoint_text(row.get("score_run_id")))
    if set(answer_pairs) != set(score_pairs) or len(score_run_ids) != 1:
        raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")

    succeeded = failed = pending = 0
    for pair, answer in answer_pairs.items():
        answer_status = _queue_status(answer)
        score_status = _queue_status(score_pairs[pair])
        if answer_status == "success" and score_status == "success":
            succeeded += 1
        elif answer_status == "failed" or score_status in {"failed", "skipped"}:
            failed += 1
        else:
            pending += 1
    if stopped_here:
        state = STOPPED
    elif pending and owned and not stale and str(run.get("status") or "").lower() == RUNNING:
        state = RUNNING
    elif pending:
        state = INTERRUPTED
    elif succeeded and failed:
        state = PARTIAL
    elif succeeded:
        state = COMPLETED
    else:
        state = FAILED
    return EvaluationRunStatus(
        run_id=run_id,
        score_run_id=next(iter(score_run_ids)),
        state=state,
        total=len(answer_pairs),
        succeeded=succeeded,
        failed=failed,
        pending=pending,
        resumable=state == INTERRUPTED,
        message=str(run.get("last_persistence_error") or ""),
        persistence_failed_in_session=stopped_here,
    )


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
        self._owned_run_ids: set[str] = set()

    def start_evaluation(self, config: EvaluationConfig) -> EvaluationRunRef:
        judge_model = self._validate_config(config)
        run_id = er.generate_run_id()
        score_run_id = sc.generate_score_run_id()
        ref = EvaluationRunRef(run_id, score_run_id)
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
        self._owned_run_ids.add(run_id)
        try:
            self._execute_items(ref, config, judge_model)
        finally:
            self._owned_run_ids.discard(run_id)
        return ref

    def load_evaluation_status(self, run_id: str) -> EvaluationRunStatus:
        run, answers, scores = self._checkpoint_rows(run_id)
        return derive_status(
            run,
            answers,
            scores,
            self._run_is_stale(run),
            stopped_here=run_id in self._session_stopped_run_ids,
            owned=run_id in self._owned_run_ids,
        )

    def continue_evaluation(self, run_id: str, config: EvaluationConfig) -> EvaluationRunStatus:
        """Claim a compatible persisted run and execute only its unfinished pairs."""
        judge_model = self._validate_config(config)
        run, answers, scores = self._checkpoint_rows(run_id)
        self._assert_checkpoint_matches(run, config)
        self._assert_config_pairs_match(config, answers)
        stale_before = _naive_utc(self.now()) - timedelta(seconds=inactivity_threshold(config))
        try:
            claimed = self.store.claim_run(run_id, stale_before)
        except Exception as exc:
            self._stop(run_id, "could not claim evaluation run", exc)
        if not claimed:
            return self.load_evaluation_status(run_id)
        ref = EvaluationRunRef(run_id, derive_status(run, answers, scores, self._run_is_stale(run)).score_run_id)
        self._session_stopped_run_ids.discard(run_id)
        self._owned_run_ids.add(run_id)
        try:
            self._execute_items(ref, config, judge_model)
        finally:
            self._owned_run_ids.discard(run_id)
        return self.load_evaluation_status(run_id)

    def _execute_items(
        self,
        ref: EvaluationRunRef,
        config: EvaluationConfig,
        judge_model: str,
    ) -> None:
        for item in config.queue_items:
            try:
                self._execute_item(ref, config, item, judge_model)
            except WorkflowCheckpointError:
                raise
            except WorkflowStopped:
                raise
            except Exception as exc:
                self._stop(ref.run_id, "could not persist evaluation outcome", exc)

    def _checkpoint_rows(
        self, run_id: str
    ) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
        run_rows = self.store.list_rows("live_evaluation_runs", run_id=run_id)
        answers = self.store.list_rows("live_run_queue", run_id=run_id)
        scores = self.store.list_rows("live_score_queue", run_id=run_id)
        if len(run_rows) != 1:
            raise WorkflowCheckpointError("evaluation checkpoint is missing")
        # Validation is deliberately done by the pure state derivation before any write.
        derive_status(run_rows[0], answers, scores, stale=False)
        return run_rows[0], answers, scores

    def _run_is_stale(self, run: Mapping[str, Any]) -> bool:
        threshold = max(
            900.0,
            max(
                _positive_number(_checkpoint_parameters(run, "generation_parameters_json").get("timeout_seconds")),
                _positive_number(_checkpoint_parameters(run, "judge_parameters_json").get("timeout_seconds")),
            )
            + 120.0,
        )
        updated_at = _checkpoint_datetime(run.get("updated_at"))
        return updated_at <= _naive_utc(self.now()) - timedelta(seconds=threshold)

    def _assert_checkpoint_matches(self, run: Mapping[str, Any], config: EvaluationConfig) -> None:
        current = build_run_metadata(
            run_id=_required_checkpoint_text(run.get("run_id")),
            provider=config.provider_name,
            model_ids=config.model_ids,
            queue_items=config.queue_items,
            generation_parameters=config.generation_parameters,
            judge_parameters=config.judge_parameters,
            dataset_version=config.dataset_version,
            prompt_payload=config.prompt_payload,
        )
        scalar_keys = ("dataset_version", "dataset_hash", "prompt_hash")
        json_keys = ("model_ids_json", "generation_parameters_json", "judge_parameters_json")
        if any(str(run.get(key) or "") != str(current.get(key) or "") for key in scalar_keys):
            raise WorkflowCheckpointError("evaluation checkpoint does not match current configuration")
        if any(_canonical_json(run.get(key), [] if key == "model_ids_json" else {}) != _canonical_json(current[key], [] if key == "model_ids_json" else {}) for key in json_keys):
            raise WorkflowCheckpointError("evaluation checkpoint does not match current configuration")

    @staticmethod
    def _assert_config_pairs_match(config: EvaluationConfig, answers: list[Mapping[str, Any]]) -> None:
        configured = [(str(item["case_id"]), str(item["model_id"])) for item in config.queue_items]
        persisted = [(str(row["case_id"]), str(row["model_id"])) for row in answers]
        if len(configured) != len(set(configured)) or set(configured) != set(persisted):
            raise WorkflowCheckpointError("evaluation checkpoint does not match current queue")

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
        response = self._formal_response(answer_rows)
        if score_queue["status"] == "success" or (
            answer_queue["status"] == "success" and response is None
        ):
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
        if answer_queue["status"] == "failed" or score_queue["status"] in {"failed", "skipped"}:
            return

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
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
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

    def _validate_config(self, config: EvaluationConfig) -> str:
        self._validate_providers(config)
        _required_text(config.provider_name, "provider name")
        _required_text(getattr(self.judge_provider, "name", ""), "judge provider")
        if not config.queue_items:
            raise ValueError("evaluation configuration requires queue items")
        for item in config.queue_items:
            if not isinstance(item, Mapping):
                raise ValueError("evaluation queue item must be a mapping")
            _required_text(item.get("case_id"), "case id")
            _required_text(item.get("model_id"), "model id")
            _task(item)
        return _required_text(config.judge_parameters.get("judge_model"), "judge model")

    def _validate_providers(self, config: EvaluationConfig) -> None:
        for configured, provider in ((config.provider_name, self.answer_provider), ("", self.judge_provider)):
            names = {str(configured or "").strip().lower(), str(getattr(provider, "name", "")).strip().lower()}
            if names.intersection({"mock", "demo"}):
                raise ValueError("mock and demo providers cannot start a formal evaluation")

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
        raise ValueError("evaluation queue item has no task")
    return task


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"evaluation configuration is missing {name}")
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


def _required_checkpoint_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkflowCheckpointError("evaluation checkpoint is incomplete")
    return text


def _queue_status(row: Mapping[str, Any]) -> str:
    status = str(row.get("status") or "").strip().lower()
    if status not in {"queued", "running", "success", "failed", "skipped"}:
        raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
    return status


def _canonical_json(value: Any, default: Any) -> str:
    if value in (None, ""):
        parsed = default
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise WorkflowCheckpointError("evaluation checkpoint has invalid metadata") from exc
    else:
        parsed = value
    try:
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkflowCheckpointError("evaluation checkpoint has invalid metadata") from exc


def _checkpoint_parameters(run: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    default: dict[str, Any] = {}
    canonical = _canonical_json(run.get(name), default)
    parsed = json.loads(canonical)
    if not isinstance(parsed, Mapping):
        raise WorkflowCheckpointError("evaluation checkpoint has invalid metadata")
    return parsed


def _checkpoint_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _naive_utc(value)
    if isinstance(value, str):
        try:
            return _naive_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError as exc:
            raise WorkflowCheckpointError("evaluation checkpoint has invalid timestamp") from exc
    raise WorkflowCheckpointError("evaluation checkpoint has invalid timestamp")


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
