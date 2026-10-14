"""Append-only real-workflow recovery in isolated databases; no paid requests."""

import json

import pytest


@pytest.fixture
def failed_batch(monkeypatch, tmp_path, request):
    from app.models.siliconflow import SiliconFlowProvider, _HttpResponse
    from app.persistence.result_store import ResultStore
    from app.services import dataset_service as ds
    from app.services import public_run, scorer
    from app.services.score_evidence import checkpoints

    monkeypatch.setenv("FINDUEVAL_MODE", "admin")
    url = f"sqlite:///{tmp_path / 'history.db'}"
    store = ResultStore(url)
    store.ensure_schema()
    base = ds.load_evaluation_data()
    dims = ds.get_rubric_dimensions()
    provider = SiliconFlowProvider(api_key="isolated-test-only")
    sent = []
    failure_code = getattr(request, "param", "timeout")
    state = {"fail": True}
    payload = {
        "scores": {d["field"]: 0 for d in dims},
        "rationale": {d["field"]: "隔离回归，不是真实评分。" for d in dims},
        "review_note": "隔离测试",
        "checks": [
            dict(
                point_id=p["point_id"],
                status="unknown",
                quote="",
                error_type="uncertain",
                dimension=dims[0]["field"],
                reason="隔离测试",
            )
            for p in checkpoints(base.gold_answer_map["FD-001"])
        ],
    }

    def send(method, path, data=None, **kwargs):
        if method == "GET":
            return _HttpResponse(
                200, {}, json.dumps({"data": [{"id": m} for m in ["m1", "m2", scorer.DEFAULT_JUDGE_MODEL]]})
            )
        sent.append(data)
        if data["model"] == scorer.DEFAULT_JUDGE_MODEL:
            if state["fail"]:
                if failure_code == "bad_request":
                    return _HttpResponse(400, {}, '{"error":{"message":"isolated invalid request"}}')
                return _HttpResponse(None, {}, "", error="timeout")
            content = json.dumps(payload, ensure_ascii=False)
        else:
            content = "隔离测试的完整原始回答，不得用于展示。"
        return _HttpResponse(
            200, {}, json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
        )

    monkeypatch.setattr(provider, "_send", send)
    monkeypatch.setattr(scorer.time, "sleep", lambda _: None)
    monkeypatch.setenv("FINDUEVAL_MODE", "public")
    monkeypatch.setenv("FINDUEVAL_ALLOW_SQLITE_LIVE", "true")
    monkeypatch.setattr(public_run.sf, "is_configured", lambda: True)
    monkeypatch.setattr(public_run, "configured_models", lambda _: ["m1", "m2"])
    job, status = public_run.run_public_evaluation(
        base, ["FD-001"], ["m1", "m2"], owner="owner", url=url, provider_factory=lambda: provider
    )
    assert status.failed == 2 and len(sent) == (8 if failure_code == "timeout" else 4)
    baseline = {
        t: store.list_rows(t, run_id=job["run_id"])
        for t in [
            "live_evaluation_runs",
            "live_run_responses",
            "live_run_scores",
            "live_run_queue",
            "live_score_queue",
            "request_attempts",
        ]
    }
    return locals()


def test_retry_only_scores_saved_answer_and_appends_without_overwriting(failed_batch):
    from app.services.score_recovery import run_score_retry

    f = failed_batch
    f["state"]["fail"] = False
    ref, status = run_score_retry(
        f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
    )
    assert status.succeeded == 1 and status.failed == 0 and len(f["sent"]) == 9
    assert f["sent"][-1]["model"] == f["scorer"].DEFAULT_JUDGE_MODEL
    assert all(f["baseline"][t] == f["store"].list_rows(t, run_id=f["job"]["run_id"]) for t in f["baseline"])
    copied = f["store"].list_rows("live_run_responses", run_id=ref.run_id)[0]
    assert copied["answer_text"] == f["baseline"]["live_run_responses"][0]["answer_text"]
    metadata = f["store"].list_rows("live_evaluation_runs", run_id=ref.run_id)[0]
    provenance = json.loads(metadata["generation_parameters_json"])["reused_answer"]
    assert provenance["run_id"] == f["job"]["run_id"] and provenance["score_run_id"] == f["job"]["score_run_id"]
    with pytest.raises(PermissionError):
        run_score_retry(
            f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
        )
    assert len(f["sent"]) == 9


def test_retry_rejects_wrong_owner_or_missing_original_context(failed_batch, monkeypatch):
    from sqlalchemy import text

    from app.services.score_recovery import run_score_retry

    f = failed_batch
    with pytest.raises(PermissionError):
        run_score_retry(
            f["job"]["job_id"], "other", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
        )
    monkeypatch.setenv("FINDUEVAL_MODE", "admin")
    with f["store"].engine.begin() as c:
        c.execute(
            text("UPDATE live_evaluation_runs SET evaluation_context_json=NULL WHERE run_id=:run"),
            {"run": f["job"]["run_id"]},
        )
    monkeypatch.setenv("FINDUEVAL_MODE", "public")
    with pytest.raises((PermissionError, ValueError)):
        run_score_retry(
            f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
        )
    assert len(f["sent"]) == 8


def test_retry_has_only_one_remaining_attempt_and_does_not_reset_budget(failed_batch):
    from app.services.public_run_quota import PublicRunLedger
    from app.services.score_recovery import run_score_retry

    f = failed_batch
    ref, status = run_score_retry(
        f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
    )
    assert status.failed == 1 and len(f["sent"]) == 9
    assert PublicRunLedger(f["store"].engine).job(f["job"]["job_id"], "owner")["requests"] == 9
    with pytest.raises(PermissionError):
        run_score_retry(
            f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
        )
    assert len(f["sent"]) == 9


@pytest.mark.parametrize("failed_batch", ["bad_request"], indirect=True)
def test_interrupted_score_only_run_resumes_same_checkpoint_without_generating(failed_batch, monkeypatch):
    from app.services.evaluation_workflow import WorkflowStopped
    from app.services.score_recovery import linked_retry_runs, run_score_retry

    f = failed_batch
    f["state"]["fail"] = False
    original_send = f["provider"]._send

    def interrupted(method, path, *args, **kwargs):
        if method == "POST":
            raise RuntimeError("isolated interruption")
        return original_send(method, path, *args, **kwargs)

    monkeypatch.setattr(f["provider"], "_send", interrupted)
    with pytest.raises(WorkflowStopped):
        run_score_retry(
            f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
        )
    children = linked_retry_runs(f["store"], f["job"]["run_id"])
    assert len(children) == 1
    monkeypatch.setattr(f["provider"], "_send", original_send)
    ref, status = run_score_retry(
        f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
    )
    assert ref.run_id == children[0]["run_id"] and status.succeeded == 1
    assert len(f["sent"]) == 5 and f["sent"][-1]["model"] == f["scorer"].DEFAULT_JUDGE_MODEL
    assert all(f["baseline"][t] == f["store"].list_rows(t, run_id=f["job"]["run_id"]) for t in f["baseline"])


def test_active_parent_lease_rejects_duplicate_without_a_model_call(failed_batch):
    from app.services.public_run_quota import PublicRunLedger
    from app.services.score_recovery import run_score_retry

    f = failed_batch
    book = PublicRunLedger(f["store"].engine)
    book.acquire(f["job"]["job_id"], "owner")
    try:
        with pytest.raises(PermissionError, match="正在运行"):
            run_score_retry(
                f["job"]["job_id"], "owner", ("FD-001", "m1"), url=f["url"], provider_factory=lambda: f["provider"]
            )
        assert len(f["sent"]) == 8
    finally:
        book.release(f["job"]["job_id"], "owner")


@pytest.mark.parametrize("failed_batch", ["bad_request"], indirect=True)
def test_authorized_nonthinking_trial_is_single_request_and_records_configuration(failed_batch):
    from app.services.score_recovery import run_score_retry

    f = failed_batch
    f["state"]["fail"] = False
    ref, status = run_score_retry(
        f["job"]["job_id"], "owner", ("FD-001", "m1"),
        url=f["url"], provider_factory=lambda: f["provider"], nonthinking_trial=True,
    )
    assert status.succeeded == 1
    assert len(f["sent"]) == 5
    assert f["sent"][-1]["enable_thinking"] is False
    assert f["sent"][-1]["max_tokens"] == 3072
    metadata = f["store"].list_rows("live_evaluation_runs", run_id=ref.run_id)[0]
    judge = json.loads(metadata["judge_parameters_json"])
    assert judge["validation_trial"] == "authorized-nonthinking-single-request"
    assert judge["retry_delays"] == []
    assert all(f["baseline"][t] == f["store"].list_rows(t, run_id=f["job"]["run_id"]) for t in f["baseline"])


@pytest.mark.parametrize("failed_batch", ["bad_request"], indirect=True)
def test_authorized_nonthinking_trial_never_retries_timeout(failed_batch, monkeypatch):
    from app.services.score_recovery import run_score_retry

    f = failed_batch
    from app.models.siliconflow import _HttpResponse

    def timeout(method, path, data=None, **kwargs):
        assert method == "POST"
        f["sent"].append(data)
        return _HttpResponse(None, {}, "", error="timeout")

    monkeypatch.setattr(f["provider"], "_send", timeout)
    ref, status = run_score_retry(
        f["job"]["job_id"], "owner", ("FD-001", "m1"),
        url=f["url"], provider_factory=lambda: f["provider"], nonthinking_trial=True,
    )
    assert status.failed == 1
    assert len(f["sent"]) == 5
    assert f["sent"][-1]["enable_thinking"] is False


@pytest.mark.parametrize("failed_batch", ["bad_request"], indirect=True)
def test_nonthinking_trial_rejects_oversized_input_before_writes_or_requests(failed_batch, monkeypatch):
    from app.services import scorer
    from app.services.score_recovery import linked_retry_runs, run_score_retry

    f = failed_batch
    original = scorer.build_judge_messages

    def oversized(*args, **kwargs):
        messages = original(*args, **kwargs)
        messages[-1]["content"] += "x" * 16000
        return messages

    monkeypatch.setattr(scorer, "build_judge_messages", oversized)
    with pytest.raises(ValueError, match="费用"):
        run_score_retry(
            f["job"]["job_id"], "owner", ("FD-001", "m1"),
            url=f["url"], provider_factory=lambda: f["provider"], nonthinking_trial=True,
        )
    assert len(f["sent"]) == 4
    assert not linked_retry_runs(f["store"], f["job"]["run_id"])


def test_quote_rejection_is_presented_as_evidence_failure_not_json_format_error():
    from src.ui.evaluation_feedback import pair_rows

    answer = {"case_id": "FD-001", "model_name": "m1", "run_status": "success"}
    score = {
        "case_id": "FD-001", "eval_model": "m1", "judge_status": "failed",
        "error_code": "judge_parse_error", "error_message": "must:2 引文不在被测回答原文中。",
        "total_score": None,
    }
    record = pair_rows([answer], [score])[0]
    assert "证据" in record["评分状态"] and "格式" not in record["评分状态"]
    assert record["_score"]["total_score"] is None
    malformed = dict(score, error_message="未返回完整JSON对象。")
    assert "格式" in pair_rows([answer], [malformed])[0]["评分状态"]
