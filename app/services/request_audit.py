"""Capture one provider request at a time, including an interrupted/unknown attempt."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.access import evaluation_operation


def endpoint_identity(provider):
    endpoint = urlsplit(str(getattr(provider, "base_url", "")))
    return (
        (f"{endpoint.scheme}://{endpoint.hostname}" + (f":{endpoint.port}" if endpoint.port else "") + endpoint.path)
        if endpoint.hostname
        else None
    )


@evaluation_operation
def request(provider, model_id, messages, *, phase, attempts, callback=None, **kwargs):
    row = {
        "attempt_id": uuid.uuid4().hex,
        "phase": phase,
        "model_id": model_id,
        "provider": getattr(provider, "name", ""),
        "service_endpoint": endpoint_identity(provider),
        "attempt_index": len(attempts) + 1,
        "requested_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "input_tokens": None,
        "output_tokens": None,
        "latency_ms": None,
        "temperature": kwargs.get("temperature"),
        "max_tokens": kwargs.get("max_tokens"),
    }
    if callback:
        callback(dict(row))  # Persist before calling. Failure stops further spend.
    started = time.monotonic()
    result = provider.generate_response(model_id, messages, **kwargs)
    row.update(
        status=result.status,
        error_code=result.error_code,
        latency_ms=result.latency_ms if result.latency_ms is not None else round((time.monotonic() - started) * 1000),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        finished_at=datetime.now(UTC).isoformat(),
    )
    attempts.append(row)
    if callback:
        callback(dict(row))
    return result


def invalidate_last(attempts, error_code, callback=None):
    attempts[-1].update(status="failed", error_code=error_code)
    if callback:
        callback(dict(attempts[-1]))
