"""Append a scoring-only run backed by immutable saved inputs and owned budget."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pandas as pd
from sqlalchemy import create_engine

from app.models import siliconflow as sf
from app.persistence import require_durable_live_store, resolve_result_store_settings
from app.persistence.result_store import ResultStore
from app.services import formal_records, public_run, scorer
from app.services.evaluation_policy import resolve_phase_timeout
from app.services.evaluation_workflow import EvaluationConfig, EvaluationWorkflow, WorkflowCheckpointError
from app.services.public_execution import score_retry_scope
from app.services.public_run_quota import PublicRunLedger
from app.services.request_audit import endpoint_identity
from app.services.run_checkpoint import canonical_hash


def _json(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError) as exc:
        raise WorkflowCheckpointError("当次运行上下文不可读取，不能使用当前题库替代。") from exc


def linked_retry_runs(store, source_run_id):
    linked = []
    for row in store.list_rows("live_evaluation_runs"):
        try:
            parameters = json.loads(row.get("generation_parameters_json") or "{}")
        except (TypeError, ValueError):
            continue
        provenance = parameters.get("reused_answer") if isinstance(parameters, dict) else None
        if isinstance(provenance, dict) and provenance.get("run_id") == source_run_id:
            linked.append(row)
    return linked


def saved_config(store, run_id):
    rows = store.list_rows("live_evaluation_runs", run_id=run_id)
    if len(rows) != 1:
        raise WorkflowCheckpointError("原运行批次无法定位。")
    run = rows[0]
    context = _json(run.get("evaluation_context_json"))
    payload = json.loads(run.get("prompt_payload_json") or "null")
    if (
        not context.get("gold")
        or not context.get("dimensions")
        or canonical_hash(context) != run.get("dataset_hash")
        or canonical_hash(payload) != run.get("prompt_hash")
    ):
        raise WorkflowCheckpointError("缺少可验证的当次任务与参考标准，不能自动重评分。")
    tasks = {r["case_id"]: r["task"] for r in context["samples"]}
    gold = {r["case_id"]: r["record"] for r in context["gold"]}
    queues = store.list_rows("live_run_queue", run_id=run_id)
    if not queues or any(not tasks.get(q["case_id"]) or not gold.get(q["case_id"]) for q in queues):
        raise WorkflowCheckpointError("当次材料不完整，不能自动重评分。")
    config = EvaluationConfig(
        run["provider"],
        tuple(_json(run["model_ids_json"])),
        tuple(dict(case_id=q["case_id"], model_id=q["model_id"], task=tasks[q["case_id"]]) for q in queues),
        _json(run["generation_parameters_json"]),
        _json(run["judge_parameters_json"]),
        run["dataset_version"],
        tuple(payload),
        gold,
        tuple(context["dimensions"]),
    )
    return run, config


def _prepare(store, book, job_id, owner, pair, *, nonthinking_trial=False):
    job = book.job(job_id, owner)
    run, config = saved_config(store, job["run_id"])
    pair = tuple(map(str, pair))
    item = next((q for q in config.queue_items if (q["case_id"], q["model_id"]) == pair), None)
    if item is None:
        raise PermissionError("所选记录不属于当前任务。")
    if (
        config.provider_name != "siliconflow"
        or config.judge_parameters.get("judge_model") != scorer.DEFAULT_JUDGE_MODEL
    ):
        raise PermissionError("裁判配置不同，不能静默更换裁判进行恢复。")
    if run.get("service_endpoint") and run["service_endpoint"] != endpoint_identity(sf.SiliconFlowProvider()):
        raise PermissionError("当前服务配置与原运行不一致，不能重评分。")
    responses = store.list_rows("live_run_responses", run_id=job["run_id"], case_id=pair[0], model_name=pair[1])
    accepted = formal_records.filter_formal_responses(pd.DataFrame(responses))
    if len(accepted) != 1:
        raise PermissionError("没有完整成功的原始回答，不能只重评分。")
    original_scores = store.list_rows("live_run_scores", run_id=job["run_id"], case_id=pair[0], eval_model=pair[1])
    if not any(s.get("judge_status") == "failed" for s in original_scores):
        raise PermissionError("所选记录不是失败评分。")
    all_scores = list(original_scores)
    pending_run = None
    for child in linked_retry_runs(store, job["run_id"]):
        child_scores = store.list_rows("live_run_scores", run_id=child["run_id"], case_id=pair[0], eval_model=pair[1])
        all_scores.extend(child_scores)
        child_pairs = store.list_rows("live_run_queue", run_id=child["run_id"], case_id=pair[0], model_id=pair[1])
        if child_pairs and not child_scores:
            queues = store.list_rows("live_score_queue", run_id=child["run_id"], case_id=pair[0], eval_model=pair[1])
            if len(queues) != 1 or queues[0]["status"] not in {"queued", "running"} or pending_run is not None:
                raise PermissionError("已有重评分检查点不完整，不能另建重复请求。")
            pending_run = child["run_id"]
    if any(s.get("judge_status") == "success" for s in all_scores):
        raise PermissionError("该回答已有成功评分，不再重复评分。")
    remaining = book.pair_remaining(job_id, owner, pair)
    if not remaining:
        raise PermissionError("该任务的请求额度已用尽，不能重新评分；不会重置额度。")
    answer = accepted.iloc[0].to_dict()
    digest = hashlib.sha256(answer["answer_text"].encode()).hexdigest()
    seconds, source = resolve_phase_timeout("judge")
    provenance = dict(
        run_id=job["run_id"],
        score_run_id=job["score_run_id"],
        case_id=pair[0],
        model_id=pair[1],
        answer_sha256=digest,
        answer_created_at=str(answer.get("created_at") or ""),
    )
    config = replace(
        config,
        model_ids=(pair[1],),
        queue_items=(item,),
        gold_map={pair[0]: config.gold_map[pair[0]]},
        prompt_payload=tuple(p for p in config.prompt_payload if p.get("case_id") == pair[0]),
        generation_parameters=dict(config.generation_parameters, reused_answer=provenance),
        judge_parameters=dict(
            config.judge_parameters,
            timeout_seconds=seconds,
            timeout_source=source,
            response_format={"type": "json_object"},
            retry_delays=list(scorer.DEFAULT_JUDGE_RETRY_DELAYS[: max(0, min(3, remaining) - 1)]),
        ),
    )
    if pending_run:
        _, config = saved_config(store, pending_run)
        saved_source = config.generation_parameters.get("reused_answer") or {}
        if saved_source.get("run_id") != job["run_id"] or saved_source.get("answer_sha256") != digest:
            raise PermissionError("原回答与重评分检查点不一致，停止恢复。")
        if nonthinking_trial and config.judge_parameters.get("validation_trial") != "authorized-nonthinking-single-request":
            raise PermissionError("已有重评分配置不同，不能改变其推理模式。")
    elif nonthinking_trial:
        messages = scorer.build_judge_messages(item["task"], answer["answer_text"], config.gold_map[pair[0]], config.dimensions)
        if len(messages) != 2 or sum(len(m["content"].encode("utf-8")) for m in messages) > 16000:
            raise ValueError("评分输入超出本次费用验证范围，未发起请求。")
        config = replace(
            config,
            judge_parameters=dict(
                config.judge_parameters,
                enable_thinking=False,
                max_tokens=3072,
                retry_delays=[],
                validation_trial="authorized-nonthinking-single-request",
                validation_cost_bound_cny=0.466944,
                validation_input_token_bound=32768,
                validation_price_as_of="2026-10-14",
                validation_price_cny_per_million={"input": 12, "output": 24},
            ),
        )
    return job, config, answer, remaining, pending_run


def retry_options(job_id, owner, *, url=None):
    settings = (
        public_run._settings() if url is None else resolve_result_store_settings(None, environ={"DATABASE_URL": url})
    )
    store = ResultStore(settings.url)
    book = PublicRunLedger(store.engine, daily_tasks=max(1, public_run.daily_limit()))
    try:
        job = book.job(job_id, owner)
        pairs = [
            (r["case_id"], r["eval_model"])
            for r in store.list_rows("live_run_scores", run_id=job["run_id"])
            if r.get("judge_status") == "failed"
        ]
        options = []
        for pair in pairs:
            try:
                _, config, _, remaining, pending = _prepare(store, book, job_id, owner, pair)
                options.append(
                    dict(
                        pair=pair,
                        eligible=True,
                        remaining=remaining,
                        judge=config.judge_parameters["judge_model"],
                        reason="",
                        resumable=bool(pending),
                    )
                )
            except (PermissionError, ValueError) as exc:
                options.append(dict(pair=pair, eligible=False, remaining=0, reason=str(exc)))
        return options
    finally:
        store.engine.dispose()


def run_score_retry(
    job_id, owner, pair, *, url=None, provider_factory=None, on_event=None, on_created=None,
    nonthinking_trial=False,
):
    # Explicit opt-in for the separately authorized validation; public callers keep defaults.
    if not isinstance(nonthinking_trial, bool):
        raise ValueError("评分验证模式必须显式指定。")
    if not public_run.enabled() or not sf.is_configured():
        raise PermissionError("当前真实评分不可用。")
    settings = (
        public_run._settings() if url is None else resolve_result_store_settings(None, environ={"DATABASE_URL": url})
    )
    require_durable_live_store("siliconflow", settings)
    read = ResultStore(settings.url)
    try:
        _prepare(
            read, PublicRunLedger(read.engine, daily_tasks=public_run.daily_limit()), job_id, owner, pair,
            nonthinking_trial=nonthinking_trial,
        )
    finally:
        read.engine.dispose()
    engine = create_engine(settings.url, pool_pre_ping=True)
    book = PublicRunLedger(engine, daily_tasks=public_run.daily_limit())
    acquired = False
    runtime = None
    try:
        book.acquire(job_id, owner)
        acquired = True
        check = ResultStore(settings.url)
        try:
            job, config, answer, remaining, pending = _prepare(
                check, book, job_id, owner, pair, nonthinking_trial=nonthinking_trial,
            )
        finally:
            check.engine.dispose()
        digest = hashlib.sha256(answer["answer_text"].encode()).hexdigest()
        with score_retry_scope(
            book,
            job_id,
            owner,
            {tuple(pair)},
            judge=config.judge_parameters["judge_model"],
            source={"run_id": job["run_id"], "answer_hashes": {tuple(pair): digest}},
        ) as grant:
            runtime = ResultStore(settings.url, evaluation_writable=True)
            grant.store = runtime
            grant.on_event = on_event
            provider = (provider_factory or sf.SiliconFlowProvider)()
            workflow = EvaluationWorkflow(runtime, provider, provider)
            trial = config.judge_parameters.get("validation_trial") == "authorized-nonthinking-single-request"
            workflow.judge_attempt_limit = 1 if trial else min(3, remaining)
            if pending:
                from app.services.evaluation_workflow import EvaluationRunRef

                queues = runtime.list_rows("live_score_queue", run_id=pending)
                grant.run_id = pending
                grant.score_run_id = queues[0]["score_run_id"]
                if not runtime.list_rows("live_run_responses", run_id=pending):
                    copy = {k: v for k, v in answer.items() if k not in {"id", "created_at", "updated_at"}}
                    copy["run_id"] = pending
                    runtime.save_run_outcome(copy, queue_status="success", combined=True)
                workflow.continue_evaluation(pending, config)
                ref = EvaluationRunRef(pending, grant.score_run_id)
            else:
                ref = workflow.start_evaluation(config, reused_answers=[answer])
            if on_created:
                on_created(ref.run_id)
            return ref, workflow.load_evaluation_status(ref.run_id)
    finally:
        if acquired:
            book.release(job_id, owner)
        if runtime is not None:
            runtime.engine.dispose()
        engine.dispose()
