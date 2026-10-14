"""Resolve phase-specific request limits without changing persisted settings."""

from __future__ import annotations

from app.models import siliconflow as sf

MAX_PHASE_TIMEOUT_SECONDS = 300.0
DEFAULT_JUDGE_TIMEOUT_SECONDS = 180.0


def resolve_phase_timeout(phase: str, provider=None) -> tuple[float, str]:
    """Answer falls back to provider configuration; judge has its own default.

    Phase settings retain the provider's st.secrets/environment/.env precedence.
    The request limit is a socket timeout, not an overall workflow deadline.
    """
    if phase not in {"answer", "judge"}:
        raise ValueError("Unsupported evaluation phase")
    key = f"SILICONFLOW_{phase.upper()}_TIMEOUT_SECONDS"
    raw, source = sf._read_config_value_with_source(key)
    seconds = sf._as_positive_float(raw)
    if seconds is not None:
        return min(seconds, MAX_PHASE_TIMEOUT_SECONDS), f"{source or 'configuration'}:{key}"
    if phase == "judge":
        return DEFAULT_JUDGE_TIMEOUT_SECONDS, "default:judge"
    if provider is not None:
        seconds = sf._as_positive_float(getattr(provider, "timeout_seconds", None))
        if seconds is not None:
            return min(seconds, MAX_PHASE_TIMEOUT_SECONDS), str(getattr(provider, "timeout_source", "default"))
    seconds, source = sf.SiliconFlowProvider._resolve_timeout()
    return min(seconds, MAX_PHASE_TIMEOUT_SECONDS), source
