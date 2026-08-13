"""Runtime result persistence configuration and store factory."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from .config import (
    PersistenceConfigurationError,
    ResultStoreSettings,
    require_durable_live_store,
    resolve_result_store_settings,
)
from .result_store import ResultStore, ResultStoreError


class ResultStoreUnavailableError(ResultStoreError):
    """Raised when the configured runtime result store cannot be reached."""


_request_store_failure: ContextVar[ResultStoreUnavailableError | None | bool] = (
    ContextVar("request_store_failure", default=False)
)


@contextmanager
def result_store_request_scope() -> Iterator[None]:
    """Memoize one persistence failure for the duration of a Streamlit rerun."""

    token = _request_store_failure.set(None)
    try:
        yield
    finally:
        _request_store_failure.reset(token)


@lru_cache(maxsize=8)
def _store_for_url(url: str) -> ResultStore:
    store = ResultStore(url)
    store.ensure_schema()
    return store


def get_result_store(
    db_path: str | Path | None = None,
    *,
    secrets=None,
) -> ResultStore:
    """Return a cached, schema-ready store for the selected backend."""

    request_failure = _request_store_failure.get()
    if isinstance(request_failure, ResultStoreUnavailableError):
        raise request_failure

    if db_path is None and secrets is None and not os.environ.get("DATABASE_URL"):
        try:
            import streamlit as st

            secrets = dict(st.secrets)
        except Exception:
            secrets = None
    settings = resolve_result_store_settings(db_path, secrets=secrets)
    try:
        return _store_for_url(settings.url)
    except ResultStoreUnavailableError:
        raise
    except Exception as exc:
        unavailable = ResultStoreUnavailableError(
            "runtime result storage is unavailable"
        )
        if request_failure is None:
            _request_store_failure.set(unavailable)
        raise unavailable from exc

__all__ = [
    "PersistenceConfigurationError",
    "ResultStore",
    "ResultStoreError",
    "ResultStoreSettings",
    "ResultStoreUnavailableError",
    "get_result_store",
    "require_durable_live_store",
    "resolve_result_store_settings",
    "result_store_request_scope",
]
