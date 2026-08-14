"""Pure, deterministic representative-evidence projection for conclusions."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class EvidenceItem:
    run_id: str
    case_id: str
    model_name: str
    title: str
    total_score: float | None
    selection_reason: str
    weakest_dimension: str
    dimension_scores: Mapping[str, float | None]
    rationale: object
    review_note: str
    answer_text: str
    gold_answer: Mapping[str, object]


def build_evidence_index(
    scores: object,
    responses: object,
    tasks: object,
    gold_map: object,
    dimensions: object,
    model_name: str,
) -> list[EvidenceItem]:
    """Return up to three stable evidence records for one exact evaluator model."""
    if not isinstance(scores, pd.DataFrame) or scores.empty or "eval_model" not in scores.columns:
        return []

    fields = _dimension_fields(dimensions)
    rows = _latest_score_rows(scores, str(model_name))
    if not rows:
        return []

    weakest = _weakest_dimension(rows, fields)
    rankings: list[tuple[str, list[dict[str, Any]]]] = [
        ("最低总分", _rank_total(rows, reverse=False)),
        ("最高总分", _rank_total(rows, reverse=True)),
    ]
    if weakest:
        rankings.append((f"最弱维度：{weakest[0]}", _rank_dimension(rows, weakest)))

    response_by_key = _response_rows(responses)
    task_by_case = _task_rows(tasks)
    gold_by_case = gold_map if isinstance(gold_map, Mapping) else {}
    selected: list[EvidenceItem] = []
    selected_cases: set[str] = set()
    for reason, ranked in rankings:
        for row in ranked:
            case_id = _text(row.get("case_id"))
            if not case_id.strip() or case_id in selected_cases:
                continue
            selected_cases.add(case_id)
            selected.append(_evidence_item(
                row,
                reason=reason,
                weakest_dimension=weakest[0] if weakest else "",
                fields=fields,
                response_by_key=response_by_key,
                task_by_case=task_by_case,
                gold_by_case=gold_by_case,
            ))
            break
    return selected


def _dimension_fields(dimensions: object) -> tuple[tuple[str, float | None], ...]:
    if not isinstance(dimensions, Sequence) or isinstance(dimensions, (str, bytes)):
        return ()
    fields: list[tuple[str, float | None]] = []
    seen: set[str] = set()
    for dimension in dimensions:
        if not isinstance(dimension, Mapping):
            continue
        field = _clean(dimension.get("field"))
        full_mark = _number(dimension.get("full_mark"))
        if not field or field in seen:
            continue
        seen.add(field)
        fields.append((field, full_mark))
    return tuple(fields)


def _latest_score_rows(scores: pd.DataFrame, model_name: str) -> list[dict[str, Any]]:
    candidates = [
        dict(row)
        for row in scores.to_dict("records")
        if _text(row.get("eval_model")) == model_name
    ]
    if not candidates:
        return []
    latest: dict[tuple[str, str, str], tuple[tuple[int, float, int], dict[str, Any]]] = {}
    for position, row in enumerate(candidates):
        key = (_text(row.get("run_id")), _text(row.get("case_id")), _text(row.get("eval_model")))
        rank = _recency_rank(row, position)
        current = latest.get(key)
        if current is None or rank >= current[0]:
            latest[key] = (rank, row)
    return [item[1] for item in latest.values()]


def _weakest_dimension(
    rows: Sequence[Mapping[str, Any]], fields: Sequence[tuple[str, float | None]]
) -> tuple[str, float] | None:
    means: list[tuple[str, float]] = []
    for field, full_mark in fields:
        if full_mark is None or full_mark <= 0:
            continue
        values = [_number(row.get(field)) for row in rows]
        valid = [value for value in values if value is not None]
        if valid:
            means.append((field, sum(valid) / len(valid) / full_mark))
    return min(means, key=lambda item: (item[1], item[0])) if means else None


def _rank_total(rows: Sequence[dict[str, Any]], *, reverse: bool) -> list[dict[str, Any]]:
    ranked = [(row, _number(row.get("total_score"))) for row in rows]
    valid = [(row, total) for row, total in ranked if total is not None]
    return [
        row for row, _ in sorted(
            valid,
            key=lambda item: ((-item[1] if reverse else item[1]), _text(item[0].get("case_id"))),
        )
    ]


def _rank_dimension(rows: Sequence[dict[str, Any]], weakest: tuple[str, float]) -> list[dict[str, Any]]:
    field, full_mark = weakest
    valid = [(row, _number(row.get(field))) for row in rows]
    return [
        row for row, value in sorted(
            ((row, value) for row, value in valid if value is not None),
            key=lambda item: (item[1] / full_mark, _text(item[0].get("case_id"))),
        )
    ]


def _response_rows(responses: object) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    if not isinstance(responses, pd.DataFrame):
        return {}
    keys = {"run_id", "case_id", "model_name"}
    if not keys.issubset(responses.columns):
        return {}
    return {
        (_text(row.get("run_id")), _text(row.get("case_id")), _text(row.get("model_name"))): row
        for row in responses.to_dict("records")
    }


def _task_rows(tasks: object) -> dict[str, Mapping[str, Any]]:
    if isinstance(tasks, pd.DataFrame):
        records: list[Mapping[str, Any]] = [row for row in tasks.to_dict("records")]
    elif isinstance(tasks, Mapping):
        records = []
        for case_id, task in tasks.items():
            if isinstance(task, Mapping):
                record = dict(task)
                record.setdefault("case_id", case_id)
                records.append(record)
    elif isinstance(tasks, Sequence) and not isinstance(tasks, (str, bytes)):
        records = [task for task in tasks if isinstance(task, Mapping)]
    else:
        records = []
    return {_text(record.get("case_id")): record for record in records if _text(record.get("case_id"))}


def _evidence_item(
    row: Mapping[str, Any],
    *,
    reason: str,
    weakest_dimension: str,
    fields: Sequence[tuple[str, float | None]],
    response_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]],
    task_by_case: Mapping[str, Mapping[str, Any]],
    gold_by_case: Mapping[Any, Any],
) -> EvidenceItem:
    run_id = _text(row.get("run_id"))
    case_id = _text(row.get("case_id"))
    model_name = _text(row.get("eval_model"))
    response = response_by_key.get((run_id, case_id, model_name), {})
    task = task_by_case.get(case_id, {})
    nested_task = task.get("task") if isinstance(task.get("task"), Mapping) else {}
    title = _clean(task.get("title")) or _clean(nested_task.get("title"))
    title = title or _clean(task.get("question")) or _clean(nested_task.get("question")) or case_id
    gold = gold_by_case.get(case_id, {})
    return EvidenceItem(
        run_id=run_id,
        case_id=case_id,
        model_name=model_name,
        title=title,
        total_score=_number(row.get("total_score")),
        selection_reason=reason,
        weakest_dimension=weakest_dimension,
        dimension_scores={field: _number(row.get(field)) for field, _ in fields},
        rationale=_rationale(row.get("rationale")),
        review_note=_text(row.get("review_note")),
        answer_text=_text(response.get("answer_text")),
        gold_answer=dict(gold) if isinstance(gold, Mapping) else {},
    )


def _rationale(value: object) -> object:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
        return dict(parsed) if isinstance(parsed, Mapping) else value
    return dict(value) if isinstance(value, Mapping) else value


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _clean(value: object) -> str:
    return _text(value).strip()


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _recency_rank(row: Mapping[str, Any], position: int) -> tuple[int, float, int]:
    updated_at = _timestamp_number(row.get("updated_at"))
    created_at = _timestamp_number(row.get("created_at"))
    timestamp = updated_at if updated_at is not None else created_at
    if timestamp is not None:
        return (2, timestamp, position)
    identifier = _number(row.get("id"))
    if identifier is not None:
        return (1, identifier, position)
    return (0, float(position), position)


def _timestamp_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
        return timestamp.timestamp() if not pd.isna(timestamp) else None
    except (TypeError, ValueError, OverflowError):
        return None
