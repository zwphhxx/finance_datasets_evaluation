"""Server-only capability for a budgeted new run; never enables admin mode."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_execution = ContextVar('public_execution', default=None)
_generating = ContextVar('public_generating', default=False)
_pair = ContextVar('public_execution_pair', default=None)


@dataclass
class PublicExecution:
    ledger: object
    job_id: str
    owner: str
    pairs: set
    judge: str
    run_id: str | None
    score_run_id: str | None
    store: object = None
    on_event: object = None

    def pair(self, case, model):
        if (str(case), str(model)) not in self.pairs:
            raise PermissionError('任务不在本次预占范围。')

    def run(self, value):
        if not self.run_id or value != self.run_id:
            raise PermissionError('不能修改其他运行批次。')

    def score(self, value):
        if not self.score_run_id or value != self.score_run_id:
            raise PermissionError('不能修改其他评分批次。')

    def config(self, config):
        if {(str(q['case_id']), str(q['model_id'])) for q in config.queue_items} != self.pairs:
            raise PermissionError('配置与预占任务不一致。')
        if (config.provider_name != 'siliconflow' or
                config.judge_parameters.get('judge_model') != self.judge or
                not 1 <= config.generation_parameters.get('max_tokens', 0) <= 4096 or
                not 1 <= config.judge_parameters.get('max_tokens', 0) <= 3072):
            raise PermissionError('配置超出公开运行限制。')

    def store_operation(self, function, args):
        if args[0] is not self.store:
            raise PermissionError('结果存储未授权。')
        name = function.__name__
        if name == 'initialize_evaluation':
            run, answers, scores = args[1:4]
            if self.run_id or self.store.list_rows('live_evaluation_runs', run_id=run['run_id']):
                raise PermissionError('不能重建或覆盖已有运行。')
            if {(str(q['case_id']),str(q['model_id'])) for q in answers} != self.pairs:
                raise PermissionError('回答队列不在预占范围。')
            if {(str(q['case_id']),str(q['eval_model'])) for q in scores} != self.pairs:
                raise PermissionError('评分队列不在预占范围。')
            score_ids = {q['score_run_id'] for q in scores}
            if len(score_ids) != 1:
                raise PermissionError('评分队列不一致。')
            self.run_id, self.score_run_id = run['run_id'], next(iter(score_ids))
            if self.store.list_rows('live_run_scores', score_run_id=self.score_run_id):
                raise PermissionError('不能覆盖已有评分。')
            self.ledger.bind_run(self.job_id,self.owner,self.run_id,self.score_run_id)
        elif name in {'claim_run','mark_run_stopped'}:
            self.run(args[1])
        elif name == 'mark_run_item_running':
            self.run(args[1])
            self.pair(args[2],args[3])
        elif name in {'mark_score_item_running','mark_score_item_skipped'}:
            self.score(args[1])
            self.pair(args[2],args[3])
        elif name in {'save_request_attempt','save_run_outcome','save_score_outcome'}:
            row = args[1]
            self.run(row.get('run_id'))
            self.pair(row.get('case_id'),row.get('model_name') or row.get('eval_model'))
            if row.get('score_run_id'):
                self.score(row['score_run_id'])
        else:
            raise PermissionError('此操作不属于公开评测。')


def current_execution():
    return _execution.get()


@contextmanager
def execution_scope(ledger, job_id, owner, pairs, *, judge='deepseek-ai/DeepSeek-V4-Pro'):
    row = ledger.job(job_id, owner)
    if len(pairs) != row['tasks']:
        raise PermissionError('预占额度与任务数量不一致。')
    grant = PublicExecution(ledger,job_id,owner,pairs,judge,row.get('run_id'),row.get('score_run_id'))
    token = _execution.set(grant)
    try:
        yield grant
    finally:
        _execution.reset(token)


@contextmanager
def authorized_operation(function, args, kwargs):
    grant = current_execution()
    if grant is None:
        raise PermissionError('模型调用仅可由明确启动且已预占额度的任务执行。')
    module, name = function.__module__, function.__name__
    token = None
    pair_token = None
    if module == 'app.persistence.result_store':
        grant.store_operation(function,args)
    elif module == 'app.services.evaluation_workflow':
        if name == 'start_evaluation':
            grant.config(args[1])
        elif name == 'continue_evaluation':
            grant.run(args[1])
            grant.config(args[2])
        elif name in {'_execute_items','_execute_item'}:
            grant.run(args[1].run_id)
            grant.score(args[1].score_run_id)
            grant.config(args[2])
        else:
            raise PermissionError('工作流操作未授权。')
    elif module == 'app.services.eval_runner' and name == 'run_single':
        grant.pair(args[2].get('case_id'),args[1])
        pair_token=_pair.set((str(args[2]['case_id']),str(args[1]),'answer'))
    elif module == 'app.services.scorer' and name == 'score_single':
        grant.pair(args[2].get('case_id'),kwargs.get('eval_model'))
        if args[1] != grant.judge:
            raise PermissionError('裁判模型未授权。')
        pair_token=_pair.set((str(args[2]['case_id']),str(kwargs['eval_model']),'judge'))
    elif module == 'app.services.request_audit' and name == 'request':
        if args[1] not in {m for _,m in grant.pairs} | {grant.judge}:
            raise PermissionError('模型未授权。')
    elif module == 'app.models.siliconflow':
        if name == 'generate_response':
            model = args[1] if len(args)>1 else kwargs.get('model_id')
            if model not in {m for _,m in grant.pairs} | {grant.judge}:
                raise PermissionError('模型未授权。')
            if not 1 <= kwargs.get('max_tokens',1024) <= 4096:
                raise PermissionError('输出长度超出限制。')
            active_pair=_pair.get()
            if active_pair is None:
                if len(grant.pairs)!=1:
                    raise PermissionError('请求缺少对应任务。')
                active_pair=(*next(iter(grant.pairs)),'answer')
            grant.ledger.consume_request(grant.job_id,grant.owner,pair=active_pair[:2])
            if grant.on_event:
                grant.on_event(*active_pair)
            token = _generating.set(True)
        elif name == '_send':
            method, path = args[1:3]
            if (method,path.split('?')[0]) != ('GET','/models') and not ((method,path)==('POST','/chat/completions') and _generating.get()):
                raise PermissionError('模型请求未预占额度。')
        elif name != 'list_models':
            raise PermissionError('服务操作未授权。')
    else:
        raise PermissionError('此操作不属于公开评测。')
    try:
        yield
    finally:
        if token is not None:
            _generating.reset(token)
        if pair_token is not None:
            _pair.reset(pair_token)
