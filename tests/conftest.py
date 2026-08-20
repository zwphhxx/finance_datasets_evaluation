from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st

from app.persistence import _store_for_url
from src.ui import conclusions_data as cd


@pytest.fixture
def isolated_app_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Keep full Streamlit AppTest renders away from local secrets and Supabase."""
    database_path = tmp_path / "apptest-runtime.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    _clear_app_caches()
    try:
        yield database_path
    finally:
        _clear_app_caches()


def _clear_app_caches() -> None:
    _store_for_url.cache_clear()
    cd.clear_conclusions_caches()
    st.cache_data.clear()
    st.cache_resource.clear()
