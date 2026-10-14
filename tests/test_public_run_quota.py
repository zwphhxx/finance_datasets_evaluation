"""Offline durable spend limits; never call a model or production database."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine


def ledger(tmp_path, **kwargs):
    from app.services.public_run_quota import PublicRunLedger
    engine = create_engine(f'sqlite:///{tmp_path / "quota.db"}', connect_args={'timeout': 10})
    return PublicRunLedger(engine, **kwargs)


def test_multi_sample_budget_counts_pairs_atomically(tmp_path):
    book = ledger(tmp_path, daily_tasks=10)
    first = book.reserve('owner', 6)
    second = book.reserve('owner2', 4)
    assert first['tasks'] == 6 and second['tasks'] == 4
    with pytest.raises(PermissionError, match='额度'):
        book.reserve('owner3', 1)


def test_concurrent_visitors_cannot_exceed_shared_daily_limit(tmp_path):
    book = ledger(tmp_path, daily_tasks=3)
    book.prepare()
    def reserve(index):
        try:
            book.reserve(str(index), 1)
            return True
        except PermissionError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(12))) == 3


def test_quota_does_not_depend_on_rowcount_after_cursor_close(tmp_path):
    """Emulate psycopg resetting rowcount to -1 when SQLAlchemy closes INSERT cursors."""
    import sqlite3

    from app.services.public_run_quota import PublicRunLedger

    class ClosingCursor:
        def __init__(self,cursor):
            self.cursor=cursor
            self.closed=False

        def __getattr__(self,name):
            return getattr(self.cursor,name)

        @property
        def rowcount(self):
            return -1 if self.closed else self.cursor.rowcount

        def close(self):
            self.closed=True
            self.cursor.close()

    class ClosingConnection:
        def __init__(self,connection):
            self.connection=connection

        def __getattr__(self,name):
            return getattr(self.connection,name)

        def cursor(self,*args,**kwargs):
            return ClosingCursor(self.connection.cursor(*args,**kwargs))

    engine=create_engine('sqlite://',creator=lambda:ClosingConnection(
        sqlite3.connect(str(tmp_path/'closing-cursor.db'))))
    book=PublicRunLedger(engine,daily_tasks=2)
    job=book.reserve('owner',2)
    book.acquire(job['job_id'],'owner')
    for _ in range(5):
        book.consume_request(job['job_id'],'owner',pair=('A','model'))
    with pytest.raises(PermissionError):
        book.consume_request(job['job_id'],'owner',pair=('A','model'))
    for _ in range(5):
        book.consume_request(job['job_id'],'owner',pair=('B','model'))
    assert book.job(job['job_id'],'owner')['requests']==10
    with pytest.raises(PermissionError):
        book.reserve('other',1)
    engine.dispose()


def test_requests_and_retries_consume_hard_job_budget(tmp_path):
    book = ledger(tmp_path)
    job = book.reserve('owner', 2)
    book.acquire(job['job_id'],'owner')
    for _ in range(10):
        book.consume_request(job['job_id'], 'owner')
    with pytest.raises(PermissionError, match='请求'):
        book.consume_request(job['job_id'],'owner')


def test_one_pair_cannot_spend_another_pairs_request_budget(tmp_path):
    book=ledger(tmp_path)
    job=book.reserve('owner',2)
    book.acquire(job['job_id'],'owner')
    for _ in range(5):
        book.consume_request(job['job_id'],'owner',pair=('A','model'))
    with pytest.raises(PermissionError):
        book.consume_request(job['job_id'],'owner',pair=('A','model'))
    for _ in range(5):
        book.consume_request(job['job_id'],'owner',pair=('B','model'))
    with pytest.raises(PermissionError, match='请求'):
        book.consume_request(job['job_id'], 'owner')


def test_restart_does_not_reset_quota_or_allow_wrong_owner(tmp_path):
    book = ledger(tmp_path, daily_tasks=1)
    job = book.reserve('owner', 1)
    restored = ledger(tmp_path, daily_tasks=1)
    assert restored.job(job['job_id'], 'owner')['tasks'] == 1
    with pytest.raises(PermissionError):
        restored.job(job['job_id'], 'other')
    with pytest.raises(PermissionError):
        restored.consume_request(job['job_id'], 'other')
    with pytest.raises(PermissionError):
        restored.reserve('owner', 1)


def test_lease_prevents_duplicate_execution_and_run_binding_is_immutable(tmp_path):
    book = ledger(tmp_path)
    job = book.reserve('owner', 1)
    book.acquire(job['job_id'], 'owner')
    with pytest.raises(PermissionError, match='运行'):
        book.acquire(job['job_id'], 'owner')
    book.bind_run(job['job_id'], 'owner', 'new-run', 'new-score')
    with pytest.raises(PermissionError):
        book.bind_run(job['job_id'], 'owner', 'old-history', 'old-score')
    book.release(job['job_id'], 'owner')
    book.acquire(job['job_id'], 'owner')


def test_expired_holder_cannot_release_or_spend_successor_lease(tmp_path,monkeypatch):
    from datetime import datetime, timedelta

    from app.services import public_run_quota as quota
    now=datetime(2026,10,14,1)
    monkeypatch.setattr(quota,'_now',lambda:now)
    old=ledger(tmp_path)
    job=old.reserve('owner',1)
    old.acquire(job['job_id'],'owner')
    now+=timedelta(minutes=31)
    successor=ledger(tmp_path)
    successor.acquire(job['job_id'],'owner')
    with pytest.raises(PermissionError):
        old.consume_request(job['job_id'],'owner',pair=('A','model'))
    with pytest.raises(PermissionError):
        old.refresh_lease(job['job_id'],'owner')
    old.release(job['job_id'],'owner')
    with pytest.raises(PermissionError):
        ledger(tmp_path).acquire(job['job_id'],'owner')
    successor.consume_request(job['job_id'],'owner',pair=('A','model'))
    assert successor.job(job['job_id'],'owner')['requests']==1
    successor.release(job['job_id'],'owner')
    ledger(tmp_path).acquire(job['job_id'],'owner')


@pytest.mark.parametrize('size', [0, -1, 11, 1.5, True])
def test_invalid_batch_is_rejected_before_creating_ledger(tmp_path, size):
    book = ledger(tmp_path)
    with pytest.raises((PermissionError, ValueError)):
        book.reserve('owner', size)
    assert not (tmp_path / 'quota.db').exists()
