"""Capture one provider request at a time, including an interrupted/unknown attempt."""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.access import evaluation_operation
from app.services.evaluation_policy import resolve_phase_timeout


def endpoint_identity(provider):
    endpoint = urlsplit(str(getattr(provider, "base_url", "")))
    return (
        (f"{endpoint.scheme}://{endpoint.hostname}" + (f":{endpoint.port}" if endpoint.port else "") + endpoint.path)
        if endpoint.hostname
        else None
    )


@evaluation_operation
def request(provider, model_id, messages, *, phase, attempts, callback=None, **kwargs):
    if getattr(provider, "name", "") == "siliconflow" and kwargs.get("request_timeout_seconds") is None:
        seconds, source = resolve_phase_timeout(phase, provider)
        kwargs["request_timeout_seconds"] = seconds
        kwargs["request_timeout_source"] = source
    diagnostics = {
        "timeout_seconds": kwargs.get("request_timeout_seconds", getattr(provider, "timeout_seconds", None)),
        "timeout_source": kwargs.get("request_timeout_source") or (
            "argument" if kwargs.get("request_timeout_seconds") is not None else getattr(provider, "timeout_source", None)
        ),
        "input_chars": sum(len(str(message.get("content", ""))) for message in messages),
    }
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
        "diagnostics_json": json.dumps(diagnostics, ensure_ascii=False),
    }
    if callback:
        callback(dict(row))  # Persist before calling. Failure stops further spend.
    started = time.monotonic()
    result = provider.generate_response(model_id, messages, **kwargs)
    for key in ("timeout_seconds", "timeout_source", "input_chars"):
        value = getattr(result, key, None)
        if value is not None:
            diagnostics[key] = value
    trace_id = str(getattr(result, "trace_id", None) or "")
    diagnostics.update(
        http_status=getattr(result, "http_status", None),
        trace_id=trace_id if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", trace_id) else None,
        error_stage=getattr(result, "error_stage", None),
    )
    row.update(
        status=result.status,
        error_code=result.error_code,
        latency_ms=result.latency_ms if result.latency_ms is not None else round((time.monotonic() - started) * 1000),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        finished_at=datetime.now(UTC).isoformat(),
        diagnostics_json=json.dumps(diagnostics, ensure_ascii=False),
    )
    attempts.append(row)
    if callback:
        callback(dict(row))
    return result


def invalidate_last(attempts, error_code, callback=None):
    attempts[-1].update(status="failed", error_code=error_code)
    if callback:
        callback(dict(attempts[-1]))
