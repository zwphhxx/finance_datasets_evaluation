"""Explicit anonymous evaluation using a server key and durable shared quotas."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
from sqlalchemy import create_engine

from app.models import siliconflow as sf
from app.persistence import get_result_store, require_durable_live_store, resolve_result_store_settings
from app.persistence.result_store import ResultStore, ResultStoreError
from app.persistence.schema import RUNTIME_TABLES
from app.services import dataset_service as ds
from app.services import formal_records, scorer
from app.services.evaluation_policy import resolve_phase_timeout
from app.services.evaluation_workflow import EvaluationWorkflow
from app.services.public_execution import execution_scope
from app.services.public_run_quota import PublicRunLedger


def daily_limit():
    try:
        return max(0,min(10,int(sf._read_config_value('FINDUEVAL_PUBLIC_DAILY_TASKS') or '10')))
    except ValueError:
        return 0


def enabled():
    return daily_limit()>0 and (sf._read_config_value('FINDUEVAL_PUBLIC_RUN_ENABLED') or 'true').lower() not in {'0','false','off'}


def configured_models(store):
    """Only server-saved real SiliconFlow model IDs; never browser-provided IDs."""
    responses = formal_records.filter_formal_responses(pd.DataFrame(store.list_rows('live_run_responses')))
    if responses.empty:
        return []
    return sorted(set(str(r['model_name']) for r in responses.to_dict('records')
                      if r.get('provider')=='siliconflow'))


def _settings():
    try:
        import streamlit as st
        secrets = dict(st.secrets)
    except Exception:
        secrets = None
    return resolve_result_store_settings(None,secrets=secrets)


def read_public_job(job_id,owner):
    """No DDL, writable connections or provider creation on page render."""
    store=get_result_store()
    book=PublicRunLedger(store.engine,daily_tasks=max(1,daily_limit()))
    job=book.job(job_id,owner)
    status=EvaluationWorkflow(store,None,None).load_evaluation_status(job['run_id']) if job.get('run_id') else None
    return job,status,store


def run_public_evaluation(base,case_ids,model_ids,*,owner,job_id=None,url=None,
                          provider_factory=None,on_reserved=None,on_event=None,
                          temperature=0.0,max_tokens=4096):
    """Called only after the explicit Start/Continue button, not while rendering."""
    if not enabled():
        raise PermissionError('公开真实评测暂未开放。')
    if not sf.is_configured():
        raise PermissionError('网站未配置模型服务密钥，无法开始真实评测。')
    if not job_id and (type(max_tokens) is not int or not 128<=max_tokens<=4096 or
                       type(temperature) not in {int,float} or not 0<=temperature<=2):
        raise PermissionError('生成参数超出范围：Temperature 为0至2，输出上限为128至4096 Token。')
    settings=_settings() if url is None else resolve_result_store_settings(None,environ={'DATABASE_URL':url})
    require_durable_live_store('siliconflow',settings)
    readonly=ResultStore(settings.url)
    try:
        if not readonly.ping() or set(readonly.table_names()) != set(RUNTIME_TABLES):
            raise ResultStoreError('评测结果数据库未就绪，已停止模型调用。')
        from src.ui.evaluation_config import build_evaluation_config_from_checkpoint, build_sample_options
        from src.ui.test_run import build_evaluation_config
        if job_id:
            book_reader=PublicRunLedger(readonly.engine,daily_tasks=daily_limit())
            saved=book_reader.job(job_id,owner)
            if not saved.get('run_id'):
                raise PermissionError('任务尚未建立运行批次，请重新选择。')
            config=build_evaluation_config_from_checkpoint(saved['run_id'],base,store=readonly)
        else:
            options=build_sample_options(base.tasks.to_dict('records'),base.gold_answer_map,ds.get_testable_rubric_dimensions())
            tasks={r['case_id']:r['task'] for r in options}
            allowed=configured_models(readonly)
            case_ids=list(dict.fromkeys(case_ids))
            model_ids=list(dict.fromkeys(model_ids))
            if not case_ids or not model_ids or not set(case_ids)<=set(tasks) or not set(model_ids)<=set(allowed):
                raise PermissionError('请选择已发布的可评测样本和允许的模型。')
            count=len(case_ids)*len(model_ids)
            if count>daily_limit():
                raise PermissionError(f'本次共{count}个任务，超过每日{daily_limit()}个任务上限。')
            config=build_evaluation_config(base,[tasks[c] for c in case_ids],model_ids)
            answer_timeout,answer_source=resolve_phase_timeout('answer')
            judge_timeout,judge_source=resolve_phase_timeout('judge')
            config=replace(config,generation_parameters=dict(config.generation_parameters,max_tokens=max_tokens,
                                                             temperature=temperature,timeout_seconds=answer_timeout,timeout_source=answer_source),
                           judge_parameters=dict(config.judge_parameters,max_tokens=3072,timeout_seconds=judge_timeout,
                                                 timeout_source=judge_source,response_format={'type':'json_object'}))
    finally:
        readonly.engine.dispose()
    provider=(provider_factory or sf.SiliconFlowProvider)()
    if not job_id:
        from app.services.public_preflight import check_run_configuration
        checked=check_run_configuration(base,case_ids,model_ids,temperature=temperature,max_tokens=max_tokens,
                                        check_catalogue=True,url=settings.url,provider_factory=lambda:provider)
        if not checked['ready']:
            raise PermissionError('；'.join(checked['errors']))
    engine=create_engine(settings.url,pool_pre_ping=True)
    book=PublicRunLedger(engine,daily_tasks=daily_limit())
    pairs={(str(q['case_id']),str(q['model_id'])) for q in config.queue_items}
    job=book.job(job_id,owner) if job_id else book.reserve(owner,len(pairs))
    if on_reserved:
        on_reserved(job)
    acquired=False
    runtime=None
    try:
        book.acquire(job['job_id'],owner)
        acquired=True
        with execution_scope(book,job['job_id'],owner,pairs,judge=scorer.DEFAULT_JUDGE_MODEL) as grant:
            runtime=ResultStore(settings.url,evaluation_writable=True)
            grant.store=runtime
            grant.on_event=on_event
            workflow=EvaluationWorkflow(runtime,provider,provider)
            if job_id:
                workflow.continue_evaluation(job['run_id'],config)
                run_id=job['run_id']
            else:
                run_id=workflow.start_evaluation(config).run_id
            status=workflow.load_evaluation_status(run_id)
        return book.job(job['job_id'],owner),status
    finally:
        if acquired:
            book.release(job['job_id'],owner)
        if runtime is not None:
            runtime.engine.dispose()
        engine.dispose()
