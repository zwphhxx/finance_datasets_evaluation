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


def test_requests_and_retries_consume_hard_job_budget(tmp_path):
    book = ledger(tmp_path)
    job = book.reserve('owner', 2)
    for _ in range(10):
        book.consume_request(job['job_id'], 'owner')
    with pytest.raises(PermissionError, match='请求'):
        book.consume_request(job['job_id'],'owner')


def test_one_pair_cannot_spend_another_pairs_request_budget(tmp_path):
    book=ledger(tmp_path)
    job=book.reserve('owner',2)
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


@pytest.mark.parametrize('size', [0, -1, 11, 1.5, True])
def test_invalid_batch_is_rejected_before_creating_ledger(tmp_path, size):
    book = ledger(tmp_path)
    with pytest.raises((PermissionError, ValueError)):
        book.reserve('owner', size)
    assert not (tmp_path / 'quota.db').exists()
