"""Durable atomic limits for anonymous, explicitly started evaluations.

These additive tables are separate from historical runtime data. Creating them
is permitted only on an explicit start, never on public page rendering.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, and_, or_, select, update

metadata = MetaData()
budget = Table('public_evaluation_budget', metadata,
    Column('day', String, primary_key=True),
    Column('tasks', Integer, nullable=False), Column('calls', Integer, nullable=False))
jobs = Table('public_evaluation_jobs', metadata,
    Column('job_id', String, primary_key=True), Column('owner_hash', String, nullable=False),
    Column('tasks', Integer, nullable=False), Column('requests', Integer, nullable=False),
    Column('run_id', String, unique=True), Column('score_run_id', String, unique=True),
    Column('active_until', DateTime), Column('created_at', DateTime, nullable=False))
pair_budget = Table('public_evaluation_pair_budget', metadata,
    Column('job_id', String, primary_key=True), Column('pair_hash', String, primary_key=True),
    Column('calls', Integer, nullable=False))


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _owner(value):
    if not isinstance(value, str) or not value:
        raise PermissionError('任务凭证缺失。')
    return hashlib.sha256(value.encode()).hexdigest()


class PublicRunLedger:
    def __init__(self, engine, *, daily_tasks=10):
        if type(daily_tasks) is not int or not 1 <= daily_tasks <= 10:
            raise ValueError('public daily limit must be 1..10')
        self.engine = engine
        self.daily_tasks = daily_tasks

    def prepare(self):
        # Avoid concurrent PostgreSQL CREATE TABLE check/create races.
        with self.engine.begin() as connection:
            if self.engine.dialect.name == 'postgresql':
                connection.exec_driver_sql('SELECT pg_advisory_xact_lock(73465120261013)')
            metadata.create_all(connection)

    def _consume_day(self, connection, *, tasks=0, calls=0):
        if self.engine.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        elif self.engine.dialect.name == 'sqlite':
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise PermissionError('额度存储类型不支持。')
        statement = insert(budget).values(day=_now().date().isoformat(), tasks=tasks, calls=calls)
        statement = statement.on_conflict_do_update(index_elements=[budget.c.day],
            set_={'tasks': budget.c.tasks + tasks, 'calls': budget.c.calls + calls},
            where=and_(budget.c.tasks + tasks <= self.daily_tasks,
                       budget.c.calls + calls <= self.daily_tasks * 5))
        # psycopg resets cursor.rowcount on close; INSERT may already be closed
        # by SQLAlchemy. RETURNING distinguishes accepted writes from the cap
        # WHERE rejecting an UPSERT, without relying on driver cursor lifetime.
        if connection.execute(statement.returning(budget.c.day)).scalar_one_or_none() is None:
            raise PermissionError('今日全站评测额度已不足，请减少任务数量或明日再试。')

    def reserve(self, owner, tasks):
        if type(tasks) is not int or not 1 <= tasks <= self.daily_tasks:
            raise PermissionError(f'单次任务数须在1至{self.daily_tasks}之间。')
        owner_hash = _owner(owner)
        self.prepare()
        row = dict(job_id=secrets.token_hex(24), owner_hash=owner_hash,
                   tasks=tasks, requests=0, created_at=_now())
        with self.engine.begin() as connection:
            self._consume_day(connection, tasks=tasks)
            connection.execute(jobs.insert().values(**row))
        return row

    def job(self, job_id, owner):
        with self.engine.connect() as connection:
            row = connection.execute(select(jobs).where(
                jobs.c.job_id == job_id, jobs.c.owner_hash == _owner(owner))).mappings().first()
        if row is None:
            raise PermissionError('任务不属于当前会话，不能运行或恢复。')
        return dict(row)

    def consume_request(self, job_id, owner, *, pair=None):
        with self.engine.begin() as connection:
            statement = update(jobs).where(jobs.c.job_id == job_id,
                jobs.c.owner_hash == _owner(owner), jobs.c.requests < jobs.c.tasks * 5
            ).values(requests=jobs.c.requests + 1,active_until=_now()+timedelta(minutes=30))
            if connection.execute(statement).rowcount != 1:
                raise PermissionError('本次任务请求额度已用尽，停止模型调用。')
            if pair is not None:
                if self.engine.dialect.name == 'postgresql':
                    from sqlalchemy.dialects.postgresql import insert
                else:
                    from sqlalchemy.dialects.sqlite import insert
                import json
                pair_hash=hashlib.sha256(json.dumps(pair,ensure_ascii=False).encode()).hexdigest()
                statement=insert(pair_budget).values(job_id=job_id,pair_hash=pair_hash,calls=1)
                statement=statement.on_conflict_do_update(index_elements=[pair_budget.c.job_id,pair_budget.c.pair_hash],
                    set_={'calls':pair_budget.c.calls+1},where=pair_budget.c.calls<5)
                if connection.execute(statement.returning(pair_budget.c.calls)).scalar_one_or_none() is None:
                    raise PermissionError('该样本与模型的请求额度已用尽，停止进一步调用。')
            self._consume_day(connection, calls=1)

    def acquire(self, job_id, owner):
        now = _now()
        with self.engine.begin() as connection:
            result = connection.execute(update(jobs).where(jobs.c.job_id == job_id,
                jobs.c.owner_hash == _owner(owner),
                or_(jobs.c.active_until.is_(None), jobs.c.active_until <= now)
            ).values(active_until=now + timedelta(minutes=30)))
        if result.rowcount != 1:
            raise PermissionError('任务正在运行，请勿重复启动；中断后等待30分钟可恢复。')

    def release(self, job_id, owner):
        with self.engine.begin() as connection:
            connection.execute(update(jobs).where(jobs.c.job_id == job_id,
                jobs.c.owner_hash == _owner(owner)).values(active_until=None))

    def bind_run(self, job_id, owner, run_id, score_run_id):
        with self.engine.begin() as connection:
            result = connection.execute(update(jobs).where(jobs.c.job_id == job_id,
                jobs.c.owner_hash == _owner(owner), jobs.c.run_id.is_(None)
            ).values(run_id=run_id, score_run_id=score_run_id))
        if result.rowcount != 1:
            raise PermissionError('已有任务批次不能替换。')
