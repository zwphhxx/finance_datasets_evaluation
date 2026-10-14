"""Offline regressions for independent phase timeouts and safe attempt diagnostics."""

import json
import urllib.error
from http.client import IncompleteRead

import pytest

from app.models import siliconflow as sf
from app.models.base import GenerationResult
from app.services import request_audit, scorer

MESSAGES = [{"role": "user", "content": "敏感测试材料，不得进入诊断"}]


class Response:
    status = 200
    headers = {"X-Siliconcloud-Trace-Id": "trace-body-42", "Authorization": "secret-header"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        raise TimeoutError("server contains secret-body")


def test_body_timeout_keeps_received_status_and_safe_trace(monkeypatch):
    monkeypatch.setattr(sf.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    provider = sf.SiliconFlowProvider(api_key="sk-secret", timeout_seconds=90)
    result = provider.generate_response("judge", MESSAGES, request_timeout_seconds=180,
                                        request_timeout_source="default:judge")
    assert result.error_code == "timeout"
    assert result.http_status == 200
    assert result.trace_id == "trace-body-42"
    assert result.error_stage == "response_body"
    assert result.timeout_seconds == 180
    assert result.timeout_source == "default:judge"
    assert result.input_chars == len(MESSAGES[0]["content"])
    assert "secret" not in result.error_message


def test_timeout_before_headers_is_identified_without_claiming_connect_only(monkeypatch):
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(sf.urllib.request, "urlopen", fail)
    result = sf.SiliconFlowProvider(api_key="sk-secret").generate_response("judge", MESSAGES)
    assert result.error_code == "timeout"
    assert result.error_stage == "connect_or_headers"
    assert result.http_status is None
    assert result.trace_id is None


def test_independent_judge_default_and_answer_global_fallback(monkeypatch):
    from app.services.evaluation_policy import resolve_phase_timeout

    monkeypatch.setattr(sf, "_read_config_value_with_source", lambda _key: (None, None))
    provider = sf.SiliconFlowProvider(api_key="sk-secret", timeout_seconds=90)
    assert resolve_phase_timeout("answer", provider) == (90, "argument")
    assert resolve_phase_timeout("judge", provider) == (180, "default:judge")


@pytest.mark.parametrize("raw, expected", [("240", 240), ("900", 300), ("nan", 180), ("0", 180)])
def test_independent_judge_config_is_finite_positive_and_bounded(monkeypatch, raw, expected):
    from app.services.evaluation_policy import resolve_phase_timeout

    monkeypatch.setattr(sf, "_read_config_value_with_source", lambda key: (raw, "environment")
                        if key == "SILICONFLOW_JUDGE_TIMEOUT_SECONDS" else (None, None))
    seconds, source = resolve_phase_timeout("judge")
    assert seconds == expected
    assert source == ("environment:SILICONFLOW_JUDGE_TIMEOUT_SECONDS" if expected != 180 else "default:judge")


def test_running_audit_records_plan_and_finished_records_actual_safe_diagnostics(monkeypatch):
    monkeypatch.setattr(sf, "_read_config_value_with_source", lambda _key: (None, None))
    monkeypatch.setattr(sf.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    provider = sf.SiliconFlowProvider(api_key="sk-secret", timeout_seconds=90)
    persisted = []
    attempts = []
    result = request_audit.request(provider, "judge", MESSAGES, phase="judge", attempts=attempts,
                                   callback=persisted.append, max_tokens=1024)
    planned = json.loads(persisted[0]["diagnostics_json"])
    actual = json.loads(persisted[-1]["diagnostics_json"])
    assert planned["timeout_seconds"] == 180
    assert planned["timeout_source"] == "default:judge"
    assert planned["input_chars"] == len(MESSAGES[0]["content"])
    assert actual["http_status"] == 200
    assert actual["trace_id"] == "trace-body-42"
    assert actual["error_stage"] == "response_body"
    assert result.error_code == "timeout"
    assert len(attempts) == 1
    saved = json.dumps(persisted, ensure_ascii=False)
    for secret in ("sk-secret", "secret-header", "secret-body", MESSAGES[0]["content"], "Authorization"):
        assert secret not in saved


def test_scorer_requests_json_and_preserves_override_with_zero_retries(monkeypatch):
    monkeypatch.setattr(sf, "_read_config_value_with_source", lambda _key: (None, None))
    captured = []
    provider = sf.SiliconFlowProvider(api_key="sk-secret", timeout_seconds=90)

    def generate(model_id, messages, **kwargs):
        captured.append((model_id, messages, kwargs))
        return GenerationResult("siliconflow", model_id, "failed", error_code="timeout")

    monkeypatch.setattr(provider, "generate_response", generate)
    outcome = scorer.score_single(provider, scorer.DEFAULT_JUDGE_MODEL, {"case_id": "c"},
                                   "完整回答。", {}, [], retry_delays=(),
                                   request_timeout_seconds=210, request_timeout_source="approved_override")
    assert outcome.judge_status == "failed"
    assert len(captured) == 1
    assert captured[0][0] == "deepseek-ai/DeepSeek-V4-Pro"
    assert captured[0][2]["request_timeout_seconds"] == 210
    assert captured[0][2]["request_timeout_source"] == "approved_override"
    assert captured[0][2]["response_format"] == {"type": "json_object"}
    assert "enable_thinking" not in captured[0][2]
    assert outcome.total_score is None


def test_answer_independent_setting_and_judge_default_are_separate(monkeypatch):
    from app.services.evaluation_policy import resolve_phase_timeout

    monkeypatch.setattr(sf, "_read_config_value_with_source", lambda key: ("120", "st.secrets")
                        if key == "SILICONFLOW_ANSWER_TIMEOUT_SECONDS" else (None, None))
    provider = sf.SiliconFlowProvider(api_key="sk-secret", timeout_seconds=90)
    assert resolve_phase_timeout("answer", provider) == (120, "st.secrets:SILICONFLOW_ANSWER_TIMEOUT_SECONDS")
    assert resolve_phase_timeout("judge", provider) == (180, "default:judge")


@pytest.mark.parametrize("raw", ["nan", "inf", "0", "-1"])
def test_invalid_global_timeout_falls_back_to_finite_default(monkeypatch, raw):
    monkeypatch.setattr(sf, "_read_config_value_with_source", lambda _key: (raw, "environment"))
    provider = sf.SiliconFlowProvider(api_key="sk-secret")
    assert provider.timeout_seconds == sf.DEFAULT_TIMEOUT_SECONDS
    assert provider.timeout_source == "default"


def test_truncated_body_retains_metadata_as_transport_failure(monkeypatch):
    class TruncatedResponse(Response):
        def read(self):
            raise IncompleteRead(b"sensitive-partial-body", 100)

    monkeypatch.setattr(sf.urllib.request, "urlopen", lambda *_args, **_kwargs: TruncatedResponse())
    result = sf.SiliconFlowProvider(api_key="sk-secret").generate_response("judge", MESSAGES)
    assert result.error_code == "connection_error"
    assert result.http_status == 200
    assert result.trace_id == "trace-body-42"
    assert result.error_stage == "response_body"
    assert "sensitive" not in result.error_message


def test_interrupted_attempt_keeps_running_plan_without_fabricating_completion(monkeypatch):
    monkeypatch.setattr(sf, "_read_config_value_with_source", lambda _key: (None, None))
    provider = sf.SiliconFlowProvider(api_key="sk-secret", timeout_seconds=90)

    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(provider, "generate_response", interrupted)
    persisted = []
    attempts = []
    with pytest.raises(KeyboardInterrupt):
        request_audit.request(provider, "judge", MESSAGES, phase="judge", attempts=attempts,
                              callback=persisted.append)
    assert attempts == []
    assert len(persisted) == 1
    assert persisted[0]["status"] == "running"
    assert json.loads(persisted[0]["diagnostics_json"])["timeout_seconds"] == 180


def test_http_error_body_timeout_keeps_nonretryable_status(monkeypatch):
    class BadRequest(urllib.error.HTTPError):
        def read(self):
            raise TimeoutError

    def fail(*_args, **_kwargs):
        raise BadRequest("https://api.siliconflow.cn/v1/chat/completions", 400, "bad", Response.headers, None)

    monkeypatch.setattr(sf.urllib.request, "urlopen", fail)
    result = sf.SiliconFlowProvider(api_key="sk-secret").generate_response("judge", MESSAGES)
    assert result.http_status == 400
    assert result.error_code == "bad_request"
    assert result.error_stage == "response_body"
