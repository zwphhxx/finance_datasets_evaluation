import pytest
from sqlalchemy import create_engine


def test_grant_does_not_enable_management_or_historical_writes(monkeypatch, tmp_path):
    from app.access import management_enabled
    from app.persistence.result_store import ResultStore
    from app.services.public_execution import execution_scope
    from app.services.public_run_quota import PublicRunLedger
    monkeypatch.setenv('FINDUEVAL_MODE', 'admin')
    url = f'sqlite:///{tmp_path / "runtime.db"}'
    store = ResultStore(url)
    store.ensure_schema()
    monkeypatch.setenv('FINDUEVAL_MODE', 'public')
    book = PublicRunLedger(create_engine(url))
    job = book.reserve('owner', 1)
    with execution_scope(book, job['job_id'], 'owner', {('TEST', 'model')}) as grant:
        writable = ResultStore(url,evaluation_writable=True)
        grant.store = writable
        assert not management_enabled()
        with pytest.raises(PermissionError):
            writable.ensure_schema()
        with pytest.raises(PermissionError):
            writable.import_formal_scores([])
        with pytest.raises(PermissionError):
            writable.mark_run_item_running('old-history', 'TEST', 'model')
        from app.services import sample_repository
        with pytest.raises(PermissionError):
            sample_repository.save_samples([])
    with pytest.raises(PermissionError):
        writable.mark_run_stopped('any', 'stopped')


def test_provider_guard_meters_every_generation_and_rejects_unselected_models(monkeypatch, tmp_path):
    from app.models.siliconflow import SiliconFlowProvider
    from app.services.public_execution import execution_scope
    from app.services.public_run_quota import PublicRunLedger
    monkeypatch.setenv('FINDUEVAL_MODE', 'public')
    book = PublicRunLedger(create_engine(f'sqlite:///{tmp_path / "quota.db"}'))
    job = book.reserve('owner', 1)
    provider = SiliconFlowProvider(api_key='test-only')
    sent = []
    from app.models.siliconflow import _HttpResponse
    monkeypatch.setattr(provider, '_send', lambda *a, **k: sent.append(a) or
                        _HttpResponse(200, {}, '{"choices":[{"message":{"content":"这是测试回答。"},"finish_reason":"stop"}]}'))
    with execution_scope(book, job['job_id'], 'owner', {('TEST', 'model')}, judge='judge'):
        with pytest.raises(PermissionError):
            provider.generate_response('unselected', [{'role':'user','content':'task'}])
        for _ in range(5):
            provider.generate_response('model', [{'role':'user','content':'task'}],max_tokens=1024)
        with pytest.raises(PermissionError):
            provider.generate_response('model', [{'role':'user','content':'task'}])
    assert len(sent) == 5


def test_frontend_flags_cannot_enable_scope(monkeypatch):
    from app.access import evaluation_writes_enabled
    monkeypatch.setenv('FINDUEVAL_MODE', 'public')
    assert not evaluation_writes_enabled()


def test_factory_never_caches_a_writable_public_engine_inside_run(monkeypatch,tmp_path):
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app.persistence import _store_for_url, get_result_store
    from app.persistence.result_store import ResultStore
    from app.services.public_execution import execution_scope
    from app.services.public_run_quota import PublicRunLedger
    path=tmp_path/'readonly.db'
    admin=ResultStore(f'sqlite:///{path}')
    admin.ensure_schema()
    monkeypatch.setenv('FINDUEVAL_MODE','public')
    book=PublicRunLedger(admin.engine)
    job=book.reserve('owner',1)
    _store_for_url.cache_clear()
    try:
        with execution_scope(book,job['job_id'],'owner',{('TEST','m')}):
            cached=get_result_store(path,secrets={})
        with pytest.raises(SQLAlchemyError):
            with cached.engine.begin() as connection:
                connection.execute(text('CREATE TABLE forbidden (id INTEGER)'))
    finally:
        _store_for_url.cache_clear()
