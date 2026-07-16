"""Resolve runtime-result storage without exposing connection secrets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


class PersistenceConfigurationError(RuntimeError):
    """Raised when a live model call has no durable result store."""


@dataclass(frozen=True)
class ResultStoreSettings:
    """Connection settings reduced to the properties consumers need."""

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
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def resolve_result_store_settings(
    db_path: str | Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    secrets: Mapping[str, Any] | None = None,
) -> ResultStoreSettings:
    """Resolve PostgreSQL first and fall back to the local SQLite runtime DB."""

    env = os.environ if environ is None else environ
    if db_path is not None:
        path = Path(db_path).resolve()
        return ResultStoreSettings(f"sqlite:///{path}", False)

    raw = str(env.get("DATABASE_URL") or "").strip() or _secret_url(secrets)
    if raw:
        normalized = _normalize_url(raw)
        return ResultStoreSettings(
            normalized,
            normalized.startswith("postgresql+psycopg://"),
        )

    from app.db import DEFAULT_DB_PATH

    return ResultStoreSettings(f"sqlite:///{DEFAULT_DB_PATH.resolve()}", False)


def require_durable_live_store(
    provider_name: str,
    settings: ResultStoreSettings,
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Fail before live Token usage unless PostgreSQL or explicit SQLite opt-in exists."""

    if str(provider_name or "").strip().lower() == "mock" or settings.is_postgresql:
        return
    env = os.environ if environ is None else environ
    allow_sqlite = str(env.get("FINDUEVAL_ALLOW_SQLITE_LIVE") or "").strip().lower()
    if allow_sqlite in {"1", "true", "yes"}:
        return
    raise PersistenceConfigurationError(
        "durable result storage is required before live model calls"
    )
