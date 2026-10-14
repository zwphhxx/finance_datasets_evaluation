import pytest


def test_catalogue_scope_allows_only_model_get_and_no_paid_or_storage(monkeypatch):
    from app.models.siliconflow import SiliconFlowProvider, _HttpResponse
    from app.services.public_execution import catalogue_scope

    monkeypatch.setenv("FINDUEVAL_MODE", "public")
    provider = SiliconFlowProvider(api_key="isolated-only")
    sent = []
    monkeypatch.setattr(provider, "_send", lambda *a, **k: sent.append(a) or _HttpResponse(200, {}, '{"data":[]}'))
    with catalogue_scope():
        assert provider.list_models().ok
        with pytest.raises(PermissionError):
            provider.generate_response("model", [{"role": "user", "content": "not sent"}])
    assert len(sent) == 1 and sent[0][0] == "GET"


def test_missing_key_preflight_cannot_open_database_or_catalogue(monkeypatch):
    from app.services import public_run
    from app.services.public_preflight import check_run_configuration

    monkeypatch.setattr(public_run.sf, "is_configured", lambda: False)
    report = check_run_configuration(None, ["FD-001"], ["m1"], check_catalogue=True)
    assert not report["ready"] and any("密钥" in e for e in report["errors"])


def test_usage_is_read_only_without_creating_ledger(tmp_path):
    from sqlalchemy import create_engine, inspect

    from app.services.public_run_quota import PublicRunLedger

    engine = create_engine(f"sqlite:///{tmp_path / 'usage.db'}")
    report = PublicRunLedger(engine, daily_tasks=4).usage()
    assert report["tasks_remaining"] == 4 and report["calls_remaining"] == 20
    assert inspect(engine).get_table_names() == []


def test_missing_durable_database_returns_safe_error(monkeypatch):
    from app.persistence import PersistenceConfigurationError
    from app.services import public_preflight as preflight

    monkeypatch.setattr(preflight.public_run.sf, "is_configured", lambda: True)
    monkeypatch.setattr(preflight.public_run, "enabled", lambda: True)
    monkeypatch.setattr(preflight.public_run, "_settings", lambda: None)
    def unavailable(*args):
        raise PersistenceConfigurationError("private connection information")
    monkeypatch.setattr(preflight, "require_durable_live_store", unavailable)
    report = preflight.check_run_configuration(None, ["FD-001"], ["m1"], check_catalogue=True)
    assert not report["ready"]
    assert report["errors"] == ["尚未配置可持久保存结果的数据库，未发起模型调用。"]
