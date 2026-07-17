"""Deterministic metadata for durable evaluation checkpoints."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 hash for JSON-compatible data."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_run_metadata(
    *,
    run_id: str,
    provider: str,
    model_ids: Sequence[str],
    queue_items: Sequence[Mapping[str, Any]],
    generation_parameters: Mapping[str, Any],
    judge_parameters: Mapping[str, Any],
    dataset_version: str,
    prompt_payload: Any,
) -> dict[str, Any]:
    """Build the persisted run record used to validate safe resumption."""

    samples = [
        {"case_id": item.get("case_id"), "task": item.get("task") or {}}
        for item in queue_items
    ]
    return {
        "run_id": run_id,
        "provider": provider,
        "model_ids_json": json.dumps(list(model_ids), ensure_ascii=False),
        "generation_parameters_json": json.dumps(
            dict(generation_parameters), ensure_ascii=False, sort_keys=True
        ),
        "judge_parameters_json": json.dumps(
            dict(judge_parameters), ensure_ascii=False, sort_keys=True
        ),
        "dataset_version": dataset_version,
        "dataset_hash": canonical_hash(samples),
        "prompt_hash": canonical_hash(prompt_payload),
        "status": "running",
        "completed_count": 0,
        "failed_count": 0,
        "pending_count": len(samples),
    }
