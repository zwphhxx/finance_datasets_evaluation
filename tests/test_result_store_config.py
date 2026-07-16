from pathlib import Path

import pytest

from app.persistence.config import (
    PersistenceConfigurationError,
    require_durable_live_store,
    resolve_result_store_settings,
)


def test_database_url_wins_and_uses_psycopg():
    settings = resolve_result_store_settings(
        db_path=None,
        environ={"DATABASE_URL": "postgresql://user:pass@db.example.com/postgres"},
        secrets={},
    )

    assert settings.url.startswith("postgresql+psycopg://")
    assert settings.is_postgresql is True


def test_streamlit_database_secret_is_supported():
    settings = resolve_result_store_settings(
        db_path=None,
        environ={},
        secrets={"database": {"url": "postgres://user:pass@db.example.com/postgres"}},
    )

    assert settings.url.startswith("postgresql+psycopg://")
    assert settings.is_postgresql is True


def test_explicit_db_path_builds_absolute_sqlite_url(tmp_path: Path):
    settings = resolve_result_store_settings(
        db_path=tmp_path / "runtime.db",
        environ={},
        secrets={},
    )

    assert settings.url == f"sqlite:///{(tmp_path / 'runtime.db').resolve()}"
    assert settings.is_postgresql is False


def test_real_provider_requires_postgresql_by_default(tmp_path: Path):
    settings = resolve_result_store_settings(
        db_path=tmp_path / "runtime.db",
        environ={},
        secrets={},
    )

    with pytest.raises(PersistenceConfigurationError):
        require_durable_live_store("siliconflow", settings, environ={})


def test_sqlite_live_requires_explicit_opt_in(tmp_path: Path):
    settings = resolve_result_store_settings(
        db_path=tmp_path / "runtime.db",
        environ={},
        secrets={},
    )

    require_durable_live_store(
        "siliconflow",
        settings,
        environ={"FINDUEVAL_ALLOW_SQLITE_LIVE": "1"},
    )


def test_mock_provider_can_use_sqlite_without_opt_in(tmp_path: Path):
    settings = resolve_result_store_settings(
        db_path=tmp_path / "runtime.db",
        environ={},
        secrets={},
    )

    require_durable_live_store("mock", settings, environ={})
