"""Real anonymous evaluation only after an explicit, budgeted start click."""
from __future__ import annotations

import secrets

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.persistence import PersistenceConfigurationError, ResultStoreError
from app.services import public_run as service
from app.services.evaluation_workflow import INTERRUPTED, STOPPED, WorkflowCheckpointError, WorkflowStopped
from app.services.model_display import display_model_name
from src.ui import conclusions_data as cd
from src.ui.review import open_case_review


def _forget_job():
    st.session_state.pop('public_live_job',None)
    st.session_state.pop('public_result_record',None)
    for field in ('public_job','public_ticket'):
        st.query_params.pop(field,None)


def _remember_job(job,owner):
    st.session_state.public_live_job={'job_id':job['job_id'],'owner':owner}
    st.query_params.update(public_job=job['job_id'],public_ticket=owner)


def _execute(base,cases,models,*,owner,job_id=None):
    progress=None
    try:
        with st.status('正在生成回答并自动评分，请保留此页面。',expanded=True) as progress:
            service.run_public_evaluation(base,cases,models,owner=owner,job_id=job_id,
                temperature=st.session_state.get('preview_temperature',0.0),
                max_tokens=st.session_state.get('preview_max_tokens',4096),
                on_reserved=lambda job:_remember_job(job,owner),
                on_event=lambda case,model,phase:progress.write(case+' · '+display_model_name(model,source='live')+
                    ('：正在生成回答' if phase=='answer' else '：正在自动评分')))
            progress.update(label='本批次执行结束',state='complete',expanded=False)
        cd.clear_conclusions_caches()
        st.rerun()
    except PermissionError as exc:
        if progress is not None:
            progress.update(label='评测未启动或已停止',state='error',expanded=False)
        st.warning(str(exc))
    except (PersistenceConfigurationError,ResultStoreError,SQLAlchemyError,WorkflowStopped,WorkflowCheckpointError,ValueError):
        if progress is not None:
            progress.update(label='评测已停止',state='error',expanded=False)
        st.error('评测未完成：服务或结果保存不可用，已停止进一步调用。已保存记录可查看；中断任务可稍后继续。')
        cd.clear_conclusions_caches()


def render_start_action(base,cases,models):
    count=len(cases)*len(models)
    limit=service.daily_limit()
    st.caption(f'使用网站密钥：每日（UTC）全站最多{limit}个任务；每个任务最多5次模型请求，包含重试。额度启动时预占，失败不退还。')
    configured=service.sf.is_configured()
    disabled=not service.enabled() or not configured or not 0<count<=limit
    if st.button('开始评测',key='public_start_evaluation',type='primary',disabled=disabled,width='stretch'):
        _execute(base,cases,models,owner=secrets.token_hex(32))
    if not configured:
        st.caption('网站未配置模型服务密钥，真实调用暂不可用；仍可查看历史结果。')
    elif not service.enabled():
        st.caption('网站已暂停公开真实评测，仍可查看历史结果。')
    elif count>limit:
        st.warning(f'当前选择共{count}个任务，请减少到{limit}个以内。')


def _open_result(row):
    # Shareable case URLs do not carry the private resume capability.
    for field in ('public_job','public_ticket'):
        st.query_params.pop(field,None)
    open_case_review(str(row['case_id']),str(row['eval_model']),str(row['run_id']),str(row['score_run_id']))
    st.query_params['origin']='evaluation_preview'


def render_owned_job(base):
    saved=st.session_state.get('public_live_job') or {}
    job_id=st.query_params.get('public_job') or saved.get('job_id')
    owner=st.query_params.get('public_ticket') or saved.get('owner')
    if not job_id and not owner:
        return False
    try:
        job,status,store=service.read_public_job(job_id,owner)
    except PermissionError as exc:
        st.warning(str(exc))
        st.button('重新选择评测',key='public_reset_job',on_click=_forget_job)
        return True
    except (ResultStoreError,SQLAlchemyError,ValueError):
        st.warning('本次任务暂不可读取，未发起模型调用。请稍后刷新。')
        st.button('重新选择评测',key='public_reset_job',on_click=_forget_job)
        return True
    _remember_job(job,owner)
    st.subheader('本次评测')
    if status:
        st.markdown(f'**共{status.total}个任务 · 完成{status.succeeded} · 失败{status.failed} · 待处理{status.pending}**')
        if status.failed:
            st.warning('本批次包含失败任务，失败项不产生有效评分。')
        answers=store.list_rows('live_run_responses',run_id=job['run_id'])
        scores=store.list_rows('live_run_scores',run_id=job['run_id'])
        if answers:
            st.dataframe([{'样本':r['case_id'],'模型':display_model_name(r['model_name'],source='live'),
                '回答状态':r.get('run_status'),'原因':r.get('error_message') or ''} for r in answers],hide_index=True,width='stretch')
        if scores:
            by_id={(r['case_id'],r['eval_model'],r['score_run_id']):r for r in scores}
            selected=st.selectbox('查看本次案例',list(by_id),format_func=lambda k:
                k[0]+' · '+display_model_name(k[1],source='live')+' · '+('AI评分 '+str(by_id[k].get('total_score')) if by_id[k].get('judge_status')=='success' else '评分失败'),
                key='public_result_record')
            row=by_id[selected]
            if row.get('error_message'):
                st.warning(str(row['error_message']))
            st.button('查看完整案例 →',key='public_open_result',type='primary',on_click=_open_result,args=(row,))
        if status.pending and status.state in {INTERRUPTED,STOPPED}:
            if st.button('继续本次评测',key='public_continue_evaluation',type='primary',
                         disabled=not service.enabled() or not service.sf.is_configured()):
                _execute(base,[],[],owner=owner,job_id=job_id)
        elif status.pending:
            st.info('任务正在运行或等待恢复。请勿重复启动；中断后可稍后刷新继续。')
    else:
        st.warning('额度已预占，但尚未建立运行批次。没有可回放的结果；重新启动会使用新的额度。')
    st.caption('当前链接包含本次任务恢复凭证，请勿分享；可分享完整案例链接。')
    st.button('新建一批评测',key='public_new_batch',on_click=_forget_job,type='secondary')
    return True
