"""Runtime result persistence configuration and store factory."""

from functools import lru_cache
from pathlib import Path

from .config import (
    PersistenceConfigurationError,
    ResultStoreSettings,
    require_durable_live_store,
    resolve_result_store_settings,
)
from .result_store import ResultStore, ResultStoreError


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

    if db_path is None and secrets is None:
        try:
            import streamlit as st

            secrets = dict(st.secrets)
        except Exception:
            secrets = None
    settings = resolve_result_store_settings(db_path, secrets=secrets)
    return _store_for_url(settings.url)

__all__ = [
    "PersistenceConfigurationError",
    "ResultStore",
    "ResultStoreError",
    "ResultStoreSettings",
    "get_result_store",
    "require_durable_live_store",
    "resolve_result_store_settings",
]
