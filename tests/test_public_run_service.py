import json

import pytest


@pytest.mark.parametrize('settings,limit,enabled',[
    ({'FINDUEVAL_PUBLIC_DAILY_TASKS':'3'},3,True),
    ({'FINDUEVAL_PUBLIC_DAILY_TASKS':'100'},10,True),
    ({'FINDUEVAL_PUBLIC_RUN_ENABLED':'false'},10,False),
    ({'FINDUEVAL_PUBLIC_DAILY_TASKS':'invalid'},0,False),
])
def test_server_secrets_can_downscale_or_disable_but_not_raise_hard_cap(monkeypatch,settings,limit,enabled):
    from app.services import public_run as service
    monkeypatch.setattr(service.sf,'_read_config_value',settings.get)
    assert service.daily_limit()==limit and service.enabled()==enabled


def test_multi_sample_multi_model_uses_existing_workflow_and_preserves_old_rows(monkeypatch,tmp_path):
    from app.models.siliconflow import SiliconFlowProvider, _HttpResponse
    from app.persistence.result_store import ResultStore
    from app.services import dataset_service as ds
    from app.services import public_run as service
    from app.services import scorer as sc
    from app.services.evaluation_workflow import COMPLETED
    from app.services.public_run_quota import PublicRunLedger
    url=f'sqlite:///{tmp_path / "runtime.db"}'
    store=ResultStore(url)
    store.ensure_schema()
    store.initialize_evaluation(dict(run_id='frozen-old-run',provider='siliconflow',dataset_hash='old',prompt_hash='old'),
        [dict(run_id='frozen-old-run',case_id='FD-001',model_id='old-model')],
        [dict(run_id='frozen-old-run',score_run_id='frozen-old-score',case_id='FD-001',eval_model='old-model')])
    frozen={name:store.list_rows(name,run_id='frozen-old-run') for name in
            ['live_evaluation_runs','live_run_queue','live_score_queue']}
    base=ds.load_evaluation_data()
    monkeypatch.setenv('FINDUEVAL_MODE','public')
    monkeypatch.setenv('FINDUEVAL_ALLOW_SQLITE_LIVE','true')
    monkeypatch.setattr(service,'configured_models',lambda store: ['m1','m2'])
    monkeypatch.setattr(service.sf,'is_configured',lambda: True)
    calls=[]
    provider=SiliconFlowProvider(api_key='offline-test-only')
    def send(method,path,payload=None,**kwargs):
        calls.append((method,path))
        if method=='GET':
            return _HttpResponse(200,{},json.dumps({'data':[{'id':'m1'},{'id':'m2'},{'id':sc.DEFAULT_JUDGE_MODEL}]}))
        return _HttpResponse(200,{},json.dumps({'choices':[{'message':{'content':'这是隔离回归中的完整模型回答。'},'finish_reason':'stop'}]}))
    monkeypatch.setattr(provider,'_send',send)
    scores=[]
    def score(provider,judge,task,answer,gold,dimensions,*,eval_model,**kwargs):
        scores.append((task['case_id'],eval_model))
        return sc.ScoreOutcome(case_id=task['case_id'],task_type=task['task_type'],eval_model=eval_model,
            judge_provider='siliconflow',judge_model=judge,judge_status='success',
            scores={d['field']:d['full_mark'] for d in dimensions},total_score=100)
    monkeypatch.setattr(sc,'score_single',score)
    saved=[]
    job,status=service.run_public_evaluation(base,['FD-001','CM-001'],['m1','m2'],owner='owner',
        url=url,provider_factory=lambda:provider,on_reserved=lambda j:saved.append(j))
    assert status.state==COMPLETED and status.succeeded==4
    assert len(scores)==4 and sum(method=='POST' for method,_ in calls)==4
    assert len(store.list_rows('live_run_responses',run_id=status.run_id))==4
    assert len(store.list_rows('live_run_scores',run_id=status.run_id))==4
    assert saved[0]['job_id']==job['job_id']
    book=PublicRunLedger(store.engine)
    assert book.job(job['job_id'],'owner')['tasks']==4
    assert book.job(job['job_id'],'owner')['requests']==4
    assert frozen=={name:store.list_rows(name,run_id='frozen-old-run') for name in frozen}
    with pytest.raises(PermissionError):
        store.mark_run_stopped('old-run','cannot mutate')


def test_missing_key_and_invalid_selection_never_create_budget_or_call(monkeypatch,tmp_path):
    from app.services import public_run as service
    monkeypatch.setenv('FINDUEVAL_MODE','public')
    monkeypatch.setattr(service.sf,'is_configured',lambda:False)
    with pytest.raises(PermissionError,match='密钥'):
        service.run_public_evaluation(None,['FD-001'],['model'],owner='owner',
            url=f'sqlite:///{tmp_path / "must-not-create.db"}')
    assert not (tmp_path/'must-not-create.db').exists()


@pytest.mark.parametrize('parameters',[{'max_tokens':8192},{'max_tokens':True},
                                      {'temperature':3},{'temperature':float('nan')}])
def test_invalid_parameters_rejected_before_storage_or_provider(monkeypatch,tmp_path,parameters):
    from app.services import public_run as service
    monkeypatch.setenv('FINDUEVAL_MODE','public')
    monkeypatch.setattr(service.sf,'is_configured',lambda:True)
    with pytest.raises(PermissionError,match='生成参数'):
        service.run_public_evaluation(None,['FD-001'],['model'],owner='owner',
            url=f'sqlite:///{tmp_path / "must-not-create.db"}',**parameters)
    assert not (tmp_path/'must-not-create.db').exists()


def test_answer_and_actual_judge_parser_persist_complete_new_evidence(monkeypatch,tmp_path):
    from app.models.siliconflow import SiliconFlowProvider, _HttpResponse
    from app.persistence.result_store import ResultStore
    from app.services import dataset_service as ds
    from app.services import public_run as service
    from app.services import scorer
    from app.services.public_run_quota import PublicRunLedger
    from app.services.score_evidence import checkpoints
    url=f'sqlite:///{tmp_path / "actual-parser.db"}'
    store=ResultStore(url)
    store.ensure_schema()
    base=ds.load_evaluation_data()
    dimensions=ds.get_rubric_dimensions()
    payload={'scores':{d['field']:0 for d in dimensions},
        'rationale':{d['field']:'隔离测试评分依据，不代表真实模型能力。' for d in dimensions},
        'review_note':'隔离测试，未调用真实服务。',
        'checks':[dict(point_id=p['point_id'],status='unknown',quote='',error_type='uncertain',
            dimension=dimensions[0]['field'],reason='隔离测试的未知评价。') for p in checkpoints(base.gold_answer_map['FD-001'])]}
    provider=SiliconFlowProvider(api_key='offline-test-only')
    sent=[]
    def send(method,path,data=None,**kwargs):
        if method=='GET':
            return _HttpResponse(200,{},json.dumps({'data':[{'id':'m1'},{'id':'deepseek-ai/DeepSeek-V4-Pro'}]}))
        sent.append(data)
        content=json.dumps(payload,ensure_ascii=False) if data['model']==scorer.DEFAULT_JUDGE_MODEL else '这是隔离测试中的完整回答。'
        return _HttpResponse(200,{},json.dumps({'choices':[{'message':{'content':content},'finish_reason':'stop'}]}))
    monkeypatch.setattr(provider,'_send',send)
    monkeypatch.setenv('FINDUEVAL_MODE','public')
    monkeypatch.setenv('FINDUEVAL_ALLOW_SQLITE_LIVE','true')
    monkeypatch.setattr(service.sf,'is_configured',lambda:True)
    monkeypatch.setattr(service,'configured_models',lambda store:['m1'])
    job,status=service.run_public_evaluation(base,['FD-001'],['m1'],owner='owner',url=url,provider_factory=lambda:provider,
                                           temperature=0.4,max_tokens=2048)
    assert status.succeeded==1 and status.failed==0
    row=store.list_rows('live_run_scores',run_id=status.run_id)[0]
    assert row['total_score']==0 and row['judge_status']=='success'
    assert len(json.loads(row['checks_json']))==len(payload['checks'])
    run=store.list_rows('live_evaluation_runs',run_id=status.run_id)[0]
    assert run['evaluation_context_json']
    assert PublicRunLedger(store.engine).job(job['job_id'],'owner')['requests']==2
    assert sent[0]['temperature']==0.4 and sent[0]['max_tokens']==2048
    assert json.loads(run['generation_parameters_json'])['max_tokens']==2048


def test_resume_own_interrupted_batch_skips_finished_pairs(monkeypatch,tmp_path):
    from app.models.siliconflow import SiliconFlowProvider, _HttpResponse
    from app.persistence.result_store import ResultStore
    from app.services import dataset_service as ds
    from app.services import public_run as service
    from app.services import scorer as sc
    from app.services.evaluation_workflow import WorkflowStopped
    url=f'sqlite:///{tmp_path / "resume.db"}'
    store=ResultStore(url)
    store.ensure_schema()
    base=ds.load_evaluation_data()
    provider=SiliconFlowProvider(api_key='offline-test-only')
    sent=[]
    def send(method,path,payload=None,**kwargs):
        if method=='GET':
            return _HttpResponse(200,{},json.dumps({'data':[{'id':'m1'},{'id':'deepseek-ai/DeepSeek-V4-Pro'}]}))
        sent.append(payload['model'])
        if len(sent)==2:
            raise RuntimeError('isolated interruption')
        return _HttpResponse(200,{},'{"choices":[{"message":{"content":"完整隔离测试回答。"},"finish_reason":"stop"}]}')
    monkeypatch.setattr(provider,'_send',send)
    def score(provider,judge,task,answer,gold,dimensions,*,eval_model,**kwargs):
        return sc.ScoreOutcome(case_id=task['case_id'],task_type=task['task_type'],eval_model=eval_model,
            judge_provider='siliconflow',judge_model=judge,judge_status='success',
            scores={d['field']:d['full_mark'] for d in dimensions},total_score=100)
    monkeypatch.setattr(sc,'score_single',score)
    monkeypatch.setenv('FINDUEVAL_MODE','public')
    monkeypatch.setenv('FINDUEVAL_ALLOW_SQLITE_LIVE','true')
    monkeypatch.setattr(service.sf,'is_configured',lambda:True)
    monkeypatch.setattr(service,'configured_models',lambda store:['m1'])
    saved=[]
    with pytest.raises(WorkflowStopped):
        service.run_public_evaluation(base,['FD-001','CM-001'],['m1'],owner='owner',url=url,
            provider_factory=lambda:provider,on_reserved=lambda j:saved.append(j))
    first=store.list_rows('live_run_scores',run_id=saved[0].get('run_id')) if saved[0].get('run_id') else store.list_rows('live_run_scores')
    assert len(first)==1
    _,status=service.run_public_evaluation(base,[],[],owner='owner',job_id=saved[0]['job_id'],
        url=url,provider_factory=lambda:provider)
    assert status.succeeded==2 and len(sent)==3
    assert store.list_rows('live_run_scores',run_id=status.run_id)[0]==first[0]
    with pytest.raises(PermissionError):
        service.run_public_evaluation(base,[],[],owner='other',job_id=saved[0]['job_id'],
            url=url,provider_factory=lambda:provider)
    assert len(sent)==3
