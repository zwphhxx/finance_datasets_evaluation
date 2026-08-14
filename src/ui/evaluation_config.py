"""Selection, queue planning, and prompt-preview helpers for evaluations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.persistence import get_result_store
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services.evaluation_workflow import EvaluationConfig, WorkflowCheckpointError
from app.services.run_checkpoint import build_run_metadata
from src.ui.labels import TASK_TYPE_LABELS, display_label, summarize_text


def eligible_case_ids(
    task_records: list[dict[str, Any]],
    gold_map: Mapping[str, Mapping[str, Any]],
    rubric_dimensions: list[dict[str, Any]] | None,
) -> list[str]:
    return [
        str(row.get("case_id") or "").strip()
        for row in task_records
        if str(row.get("case_id") or "").strip()
        and ds.assess_sample_readiness(
            row,
            gold_map.get(str(row.get("case_id") or "").strip()) or {},
            rubric_dimensions,
        ).is_testable
    ]


def build_sample_options(
    task_records: list[dict[str, Any]],
    gold_map: Mapping[str, Mapping[str, Any]],
    rubric_dimensions: list[dict[str, Any]] | None,
    title_map: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    # Keep the legacy first-match behavior when malformed input contains a
    # duplicate case ID.  The page has always resolved the first task record.
    by_case: dict[str, dict[str, Any]] = {}
    for row in task_records:
        by_case.setdefault(str(row.get("case_id") or "").strip(), row)
    options: list[dict[str, Any]] = []
    for case_id in eligible_case_ids(task_records, gold_map, rubric_dimensions):
        row = by_case[case_id]
        scenario = _dash(row.get("scenario"))
        scene = scenario.split("——")[0].strip() or scenario
        title = summarize_text(
            (title_map or {}).get(case_id)
            or row.get("title")
            or row.get("expected_capability")
            or row.get("question"),
            32,
        )
        task_type = display_label(row.get("task_type"), TASK_TYPE_LABELS)
        options.append({
            "case_id": case_id,
            "label": f"{case_id} · {scene} · {task_type} · {title}",
            "scenario": scene,
            "task_type": task_type,
            "title": title,
            "difficulty": _dash(row.get("difficulty")),
            "task": row,
        })
    return options


def build_run_plan_summary(
    model_ids: list[str], selected_tasks: list[dict[str, Any]]
) -> dict[str, int | bool]:
    model_count = len(_dedupe(model_ids))
    sample_count = len(selected_tasks or [])
    return {
        "sample_count": sample_count,
        "model_count": model_count,
        "planned_responses": sample_count * model_count,
        "can_run": bool(sample_count and model_count),
    }


def build_run_queue_items(
    model_ids: list[str], selected_tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    unique_models = _dedupe(model_ids)
    for selected in selected_tasks or []:
        task = selected.get("task") if isinstance(selected.get("task"), dict) else selected
        for model_id in unique_models:
            items.append({
                "model_id": model_id,
                "case_id": str(selected.get("case_id") or task.get("case_id") or ""),
                "task": task,
            })
    return items


def build_evaluation_config_from_checkpoint(
    run_id: str,
    base: Any,
    *,
    store: Any | None = None,
    dataset_version: str | None = None,
    dimensions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
) -> EvaluationConfig:
    """Rebuild a resumable config exclusively from a durable checkpoint.

    The current task and Gold records supply content, while the persisted queue
    and run metadata remain authoritative for scope, models, and parameters.
    UI form selections are intentionally not accepted by this boundary.
    """

    checkpoint_run_id = _required_checkpoint_text(run_id)
    result_store = store if store is not None else get_result_store()
    run_rows = result_store.list_rows("live_evaluation_runs", run_id=checkpoint_run_id)
    queue_rows = result_store.list_rows("live_run_queue", run_id=checkpoint_run_id)
    if len(run_rows) != 1 or not queue_rows:
        raise WorkflowCheckpointError("evaluation checkpoint is missing")

    saved = dict(run_rows[0])
    if _required_checkpoint_text(saved.get("run_id")) != checkpoint_run_id:
        raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
    provider_name = _required_checkpoint_text(saved.get("provider"))
    model_ids = tuple(_required_checkpoint_models(saved.get("model_ids_json")))
    generation_parameters = _required_checkpoint_mapping(
        saved.get("generation_parameters_json"), "generation parameters"
    )
    judge_parameters = _required_checkpoint_mapping(
        saved.get("judge_parameters_json"), "judge parameters"
    )
    if not generation_parameters or not judge_parameters.get("judge_model"):
        raise WorkflowCheckpointError("evaluation checkpoint is missing parameters")

    current_dataset_version = (
        str(dataset_version).strip()
        if dataset_version is not None
        else next((str(value).strip() for value in ds.list_dataset_versions() if str(value).strip()), "")
    )
    if not current_dataset_version:
        raise WorkflowCheckpointError("evaluation checkpoint is missing dataset version")

    tasks_by_case = _tasks_by_case(base)
    gold_source = _base_value(base, "gold_answer_map")
    if not isinstance(gold_source, Mapping):
        raise WorkflowCheckpointError("evaluation checkpoint has no current Gold records")

    ordered_rows = sorted(
        enumerate(queue_rows),
        key=lambda entry: (_queue_order(entry[1], entry[0]), entry[0]),
    )
    pairs: set[tuple[str, str]] = set()
    queue_items: list[dict[str, Any]] = []
    gold_map: dict[str, Mapping[str, Any]] = {}
    for _index, raw_row in ordered_rows:
        row = dict(raw_row)
        if _required_checkpoint_text(row.get("run_id")) != checkpoint_run_id:
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
        case_id = _required_checkpoint_text(row.get("case_id"))
        model_id = _required_checkpoint_text(row.get("model_id"))
        pair = (case_id, model_id)
        if pair in pairs:
            raise WorkflowCheckpointError("evaluation checkpoint contains a duplicate queue pair")
        pairs.add(pair)
        if model_id not in model_ids:
            raise WorkflowCheckpointError("evaluation checkpoint does not match saved models")
        task = tasks_by_case.get(case_id)
        if task is None:
            raise WorkflowCheckpointError(f"evaluation checkpoint current sample is missing: {case_id}")
        gold = gold_source.get(case_id)
        if not isinstance(gold, Mapping) or not gold:
            raise WorkflowCheckpointError(f"evaluation checkpoint current Gold is missing: {case_id}")
        queue_items.append({"case_id": case_id, "model_id": model_id, "task": dict(task)})
        gold_map.setdefault(case_id, dict(gold))

    if {model_id for _case_id, model_id in pairs} != set(model_ids):
        raise WorkflowCheckpointError("evaluation checkpoint does not match saved models")

    prompt_payload = tuple(
        {
            "case_id": item["case_id"],
            "messages": er.build_messages(item["task"]),
        }
        for item in queue_items
    )
    current = build_run_metadata(
        run_id=checkpoint_run_id,
        provider=provider_name,
        model_ids=model_ids,
        queue_items=queue_items,
        generation_parameters=generation_parameters,
        judge_parameters=judge_parameters,
        dataset_version=current_dataset_version,
        prompt_payload=prompt_payload,
    )
    if any(
        str(saved.get(field) or "") != str(current.get(field) or "")
        for field in ("dataset_version", "dataset_hash", "prompt_hash")
    ):
        raise WorkflowCheckpointError("evaluation checkpoint does not match current samples or prompts")
    for field, default in (
        ("model_ids_json", []),
        ("generation_parameters_json", {}),
        ("judge_parameters_json", {}),
    ):
        if _canonical_checkpoint_json(saved.get(field), default) != _canonical_checkpoint_json(
            current.get(field), default
        ):
            raise WorkflowCheckpointError("evaluation checkpoint does not match current configuration")

    current_dimensions = dimensions if dimensions is not None else ds.get_rubric_dimensions()
    dimension_rows = tuple(dict(row) for row in current_dimensions or [] if isinstance(row, Mapping))
    if not dimension_rows:
        raise WorkflowCheckpointError("evaluation checkpoint has no current scoring dimensions")
    return EvaluationConfig(
        provider_name=provider_name,
        model_ids=model_ids,
        queue_items=tuple(queue_items),
        generation_parameters=generation_parameters,
        judge_parameters=judge_parameters,
        dataset_version=current_dataset_version,
        prompt_payload=prompt_payload,
        gold_map=gold_map,
        dimensions=dimension_rows,
    )


def _base_value(base: Any, name: str) -> Any:
    return base.get(name) if isinstance(base, Mapping) else getattr(base, name, None)


def _tasks_by_case(base: Any) -> dict[str, Mapping[str, Any]]:
    source = _base_value(base, "tasks")
    if source is None:
        raise WorkflowCheckpointError("evaluation checkpoint has no current samples")
    if hasattr(source, "to_dict"):
        records = source.to_dict("records")
    elif isinstance(source, (list, tuple)):
        records = list(source)
    else:
        raise WorkflowCheckpointError("evaluation checkpoint has invalid current samples")
    by_case: dict[str, Mapping[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise WorkflowCheckpointError("evaluation checkpoint has invalid current samples")
        case_id = str(raw.get("case_id") or "").strip()
        if not case_id:
            continue
        if case_id in by_case:
            raise WorkflowCheckpointError("evaluation checkpoint has duplicate current samples")
        by_case[case_id] = dict(raw)
    return by_case


def _required_checkpoint_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkflowCheckpointError("evaluation checkpoint is incomplete")
    return text


def _parse_checkpoint_json(value: Any, label: str) -> Any:
    if value in (None, ""):
        raise WorkflowCheckpointError(f"evaluation checkpoint is missing {label}")
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise WorkflowCheckpointError(f"evaluation checkpoint has invalid {label}") from exc


def _required_checkpoint_models(value: Any) -> list[str]:
    parsed = _parse_checkpoint_json(value, "models")
    if not isinstance(parsed, list):
        raise WorkflowCheckpointError("evaluation checkpoint has invalid models")
    models = [str(model).strip() for model in parsed]
    if not models or any(not model for model in models):
        raise WorkflowCheckpointError("evaluation checkpoint is missing models")
    if len(models) != len(set(models)):
        raise WorkflowCheckpointError("evaluation checkpoint has duplicate models")
    return models


def _required_checkpoint_mapping(value: Any, label: str) -> dict[str, Any]:
    parsed = _parse_checkpoint_json(value, label)
    if not isinstance(parsed, Mapping):
        raise WorkflowCheckpointError(f"evaluation checkpoint has invalid {label}")
    return dict(parsed)


def _canonical_checkpoint_json(value: Any, default: Any) -> str:
    parsed = default if value in (None, "") else _parse_checkpoint_json(value, "metadata")
    try:
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkflowCheckpointError("evaluation checkpoint has invalid metadata") from exc


def _queue_order(row: Mapping[str, Any], fallback: int) -> int:
    try:
        return int(row.get("id"))
    except (TypeError, ValueError):
        return fallback


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    return [value for value in values if str(value) not in seen and not seen.add(str(value))]


def _dash(value: object) -> str:
    return str(value or "").strip() or "—"
