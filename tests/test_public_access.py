"""Public deployment must reject side effects before touching providers or storage."""
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def public_mode(monkeypatch):
    monkeypatch.delenv('FINDUEVAL_MODE', raising=False)


def test_default_public_navigation_has_only_reading_destinations(public_mode):
    at = AppTest.from_string('''
from src.ui.navigation import render_sidebar_navigation
render_sidebar_navigation()
''').run()
    assert not at.exception
    assert [b.label for b in at.button] == ['评测结果', '评测流程', '样本库']
    assert [e.proto.label for e in at.get('link_button')] == ['GitHub 源码']
    assert not at.get('popover')


@pytest.mark.parametrize('page', ['test_run','samples'])
def test_public_direct_management_route_never_renders_operations(public_mode, page, monkeypatch):
    from src.ui import navigation
    original = navigation.PAGES[page]
    # Exercise the actual registered destination, not only the hidden navigation.
    at = AppTest.from_string('''
from src.ui.navigation import PAGES, render_sidebar_navigation
page = render_sidebar_navigation()
PAGES[page]({'data':None,'base':None})
''')
    at.query_params['page'] = page
    at.session_state['admin'] = True
    at.session_state['FINDUEVAL_MODE'] = 'admin'
    at.run()
    assert not at.exception
    assert any('只读' in e.value for e in at.info)
    assert not at.get('file_uploader')
    assert all(b.label not in {'开始评测','继续评测','新增样本','确认导入'} for b in at.button)
    assert navigation.PAGES[page] is original


def test_public_workflow_start_and_resume_do_not_touch_store_or_provider(public_mode):
    from app.services.evaluation_workflow import EvaluationWorkflow
    store, provider = Mock(), Mock()
    workflow = EvaluationWorkflow(store, provider, provider)
    for operation, args in [(workflow.start_evaluation, (None,)), (workflow.continue_evaluation, ('old-run',None))]:
        with pytest.raises(PermissionError):
            operation(*args)
    assert not store.mock_calls
    assert not provider.mock_calls


def test_public_provider_generation_listing_and_connectivity_never_send(public_mode, monkeypatch):
    from app.models.siliconflow import SiliconFlowProvider
    provider = SiliconFlowProvider(api_key='test-only-key')
    send = Mock(side_effect=AssertionError('network reached'))
    monkeypatch.setattr(provider, '_send', send)
    for operation, args in [(provider.generate_response,('model',[{'role':'user','content':'task'}])),
                            (provider.list_models,()), (provider.check_connectivity,())]:
        with pytest.raises(PermissionError):
            operation(*args)
    send.assert_not_called()


def test_public_request_wrapper_cannot_call_custom_provider_or_audit_callback(public_mode):
    from app.services.request_audit import request
    provider, callback, attempts = Mock(), Mock(), []
    with pytest.raises(PermissionError):
        request(provider,'model',[],phase='judge',attempts=attempts,callback=callback)
    assert not provider.mock_calls
    callback.assert_not_called()
    assert attempts == []


@pytest.mark.parametrize('method,args', [
    ('ensure_schema',()), ('save_request_attempt',({},)), ('initialize_run',({},[])),
    ('initialize_evaluation',({},[],[])), ('mark_run_item_running',('r','c','m')),
    ('save_run_outcome',({},)), ('initialize_score_queue',([],)),
    ('mark_score_item_running',('s','c','m')), ('mark_score_item_skipped',('s','c','m','skip')),
    ('save_score_outcome',({},)), ('import_formal_scores',([],)),
    ('claim_run',('r',None)), ('mark_run_stopped',('r','reason'))])
def test_public_result_store_mutations_rejected_before_connection(public_mode, tmp_path, method,args):
    from app.persistence.result_store import ResultStore
    store=ResultStore(f'sqlite:///{tmp_path / "must-not-create.db"}')
    kwargs={'queue_status':'success'} if method in {'save_run_outcome','save_score_outcome'} else {}
    with pytest.raises(PermissionError):
        getattr(store,method)(*args,**kwargs)
    assert not (tmp_path/'must-not-create.db').exists()
    store.engine.dispose()


def test_public_sqlite_connections_reject_raw_writes_and_keep_file_unchanged(monkeypatch,tmp_path):
    import hashlib

    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.repository import Repository
    from app.persistence.result_store import ResultStore
    monkeypatch.setenv('FINDUEVAL_MODE','admin')
    path=tmp_path/'history.db'
    store=ResultStore(f'sqlite:///{path}')
    store.ensure_schema()
    store.engine.dispose()
    original=hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.delenv('FINDUEVAL_MODE')
    readonly=ResultStore(f'sqlite:///{path}')
    assert readonly.list_rows('live_evaluation_runs') == []
    with pytest.raises((PermissionError,SQLAlchemyError)):
        with readonly.engine.begin() as connection:
            connection.execute(text('CREATE TABLE forbidden (id INTEGER)'))
    with Repository(path).connect() as connection:
        with pytest.raises(Exception, match='readonly|只读'):
            connection.execute('CREATE TABLE forbidden (id INTEGER)')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==original
    readonly.engine.dispose()


def test_public_seed_init_and_sample_file_write_are_blocked(public_mode,tmp_path,monkeypatch):
    from app.db.init_db import initialize_database
    from app.services import sample_repository as sr
    path=tmp_path/'no-seed.db'
    with pytest.raises(PermissionError):
        initialize_database(path)
    assert not path.exists()
    sample_path=tmp_path/'samples.json'
    monkeypatch.setattr(sr,'_SAMPLES_PATH',sample_path)
    with pytest.raises(PermissionError):
        sr.save_samples([])
    # Reading missing current task assets may derive in memory, never persist.
    sr.load_samples()
    assert not sample_path.exists()


def test_public_scoring_import_and_sample_sync_rejected_before_mutation(public_mode):
    from app.services import sample_repository as sr
    from app.services import scorer as sc
    store=Mock()
    with pytest.raises(PermissionError):
        sc.import_score_rows([],result_store=store)
    with pytest.raises(PermissionError):
        sr.sync_all_samples_to_formal_assets()
    assert not store.mock_calls


def test_public_factory_does_not_initialize_schema_or_create_missing_database(public_mode,tmp_path):
    from app.persistence import _store_for_url, get_result_store
    path=tmp_path/'no-public-init.db'
    _store_for_url.cache_clear()
    store=get_result_store(path,secrets={})
    assert not path.exists()
    assert not store.ping()
    assert not path.exists()
    store.engine.dispose()
    _store_for_url.cache_clear()


def test_public_postgres_connection_requests_read_only_transactions(public_mode,monkeypatch):
    from sqlalchemy import event

    from app.persistence import result_store as module
    factory=Mock()
    listener=Mock()
    monkeypatch.setattr(event,'listen',listener)
    monkeypatch.setattr(module,'create_engine',factory)
    module.ResultStore('postgresql://test:test@invalid.example/test')
    kwargs=factory.call_args.kwargs
    assert kwargs['connect_args']['options'] == '-c default_transaction_read_only=on'
    # Transaction poolers can ignore/reset session defaults. Apply READ ONLY
    # for every new transaction, before any caller statement.
    listener.assert_called_once()
    assert listener.call_args.args[1] == 'begin'
    connection=Mock()
    listener.call_args.args[2](connection)
    connection.exec_driver_sql.assert_called_once_with('SET TRANSACTION READ ONLY')


def test_admin_navigation_retains_existing_operations(monkeypatch):
    monkeypatch.setenv('FINDUEVAL_MODE','admin')
    at=AppTest.from_string('''
from src.ui.navigation import render_sidebar_navigation
render_sidebar_navigation()
''').run()
    assert not at.exception
    assert {'运行评测','数据维护'} <= {b.label for b in at.button}


def test_invalid_server_mode_and_frontend_state_cannot_enable_admin(monkeypatch):
    from app.access import management_enabled
    for value in ['', 'public','true','1','invalid']:
        monkeypatch.setenv('FINDUEVAL_MODE',value)
        assert not management_enabled()


def test_public_cold_start_without_runtime_database_has_empty_state_and_no_writes(public_mode,isolated_app_database,monkeypatch):
    monkeypatch.setenv('FINDUEVAL_DB_PATH',str(isolated_app_database))
    monkeypatch.setenv('FINDUEVAL_AUTO_INIT_DB','1')
    from app.models.siliconflow import SiliconFlowProvider
    calls=Mock(side_effect=AssertionError('public browser tried network'))
    monkeypatch.setattr(SiliconFlowProvider,'_send',calls)
    at=AppTest.from_file('app.py').run(timeout=30)
    assert not at.exception
    assert any('任务设计示例，尚无完整实测记录' in e.value for e in at.caption)
    assert not isolated_app_database.exists()
    assert not [b for b in at.button if b.key and str(b.key).startswith('top_nav_')]
    assert [b.label for b in at.button] == ['评测结果', '评测流程', '样本库', '查看专业任务 →']
    assert not at.metric and not at.multiselect
    calls.assert_not_called()


def test_invalid_public_snapshot_has_visible_warning_without_upload_controls(public_mode,tmp_path,monkeypatch):
    from src.ui import history_view
    path=tmp_path/'bad.json'
    path.write_text('{broken')
    monkeypatch.setattr(history_view,'PUBLIC_SNAPSHOT',path)
    at=AppTest.from_string('''
from src.ui.history_view import active_snapshot
assert active_snapshot() is None
''').run()
    assert not at.exception
    assert any('快照不可读取' in e.value for e in at.warning)
    assert not at.get('file_uploader')
