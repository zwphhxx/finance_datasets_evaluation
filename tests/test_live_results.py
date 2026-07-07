"""surface live model-call results and failures.

Covers the visibility/robustness fixes in the live model-call chain:
  - robust answer extraction (content / reasoning_content / choices[].text / list parts);
  - HTTP 200 with an empty answer is a failure (empty_response), not a success;
  - transport/HTTP errors (timeout / 401 / 429) surface as structured outcome fields;
  - run summary counts (success / empty / timeout / auth / other);
  - default task selection is a single task;
  - the persisted flag uses persist_compare_result's real return value.

No test performs a real outbound API call.
"""

import json
import unittest
from pathlib import Path
from unittest import mock

from app.models.base import (
    ERROR_EMPTY_RESPONSE,
    GenerationResult,
    ModelProvider,
    STATUS_FAILED,
    STATUS_SUCCESS,
    extract_answer_text,
)
from app.models import siliconflow as sf
from app.models.siliconflow import SiliconFlowProvider, _HttpResponse
from app.services import eval_runner as er


_MESSAGES = [{"role": "user", "content": "请概述一笔收购的尽调要点"}]


class ExtractAnswerTextTests(unittest.TestCase):
    def test_plain_content(self):
        body = {"choices": [{"message": {"content": "结论如下"}}]}
        self.assertEqual("结论如下", extract_answer_text(body))

    def test_empty_content_returns_empty(self):
        body = {"choices": [{"message": {"content": ""}}]}
        self.assertEqual("", extract_answer_text(body))

    def test_reasoning_content_fallback_when_content_empty(self):
        body = {"choices": [{"message": {"content": "", "reasoning_content": "推理过程文本"}}]}
        self.assertEqual("推理过程文本", extract_answer_text(body))

    def test_content_preferred_over_reasoning(self):
        body = {"choices": [{"message": {"content": "正式回答", "reasoning_content": "推理"}}]}
        self.assertEqual("正式回答", extract_answer_text(body))

    def test_content_as_list_parts(self):
        body = {"choices": [{"message": {"content": [
            {"type": "text", "text": "A"}, {"text": "B"}, "C",
        ]}}]}
        self.assertEqual("ABC", extract_answer_text(body))

    def test_legacy_choices_text(self):
        body = {"choices": [{"text": "旧式补全回答"}]}
        self.assertEqual("旧式补全回答", extract_answer_text(body))

    def test_no_choices_returns_empty(self):
        self.assertEqual("", extract_answer_text({"choices": []}))
        self.assertEqual("", extract_answer_text({}))


class SiliconFlowEmptyResponseTests(unittest.TestCase):
    def _generate(self, body, status=200, headers=None):
        provider = SiliconFlowProvider(api_key="sk-secret")
        fake = _HttpResponse(status, headers or {}, json.dumps(body))
        with mock.patch.object(SiliconFlowProvider, "_send", return_value=fake):
            return provider.generate_response("m", _MESSAGES)

    def test_http_200_empty_answer_is_failed_empty_response(self):
        result = self._generate({"choices": [{"message": {"content": ""}}], "usage": {}},
                                headers={"x-siliconcloud-trace-id": "t-1"})
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.error_code, ERROR_EMPTY_RESPONSE)
        # HTTP 状态与 trace_id 仍保留，便于排查。
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.trace_id, "t-1")
        self.assertFalse(result.ok)

    def test_http_200_reasoning_only_is_success(self):
        result = self._generate({"choices": [{"message": {"content": "", "reasoning_content": "R"}}]})
        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertEqual(result.response_text, "R")

    def test_empty_response_never_leaks_api_key(self):
        result = self._generate({"choices": []})
        self.assertNotIn("sk-secret", result.error_message or "")


class _StaticProvider(ModelProvider):
    """Returns a fixed GenerationResult — for runner-level assertions."""

    name = "static"

    def __init__(self, result: GenerationResult):
        self._result = result

    def list_models(self, model_type="text", sub_type="chat"):
        raise NotImplementedError

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        return self._result


class _SequenceProvider(ModelProvider):
    """Returns GenerationResult objects in order and records max_tokens per call."""

    name = "sequence"

    def __init__(self, *results: GenerationResult):
        self._results = list(results)
        self.max_token_calls: list[int] = []

    def list_models(self, model_type="text", sub_type="chat"):
        raise NotImplementedError

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        self.max_token_calls.append(max_tokens)
        return self._results.pop(0)


class RunnerEmptyGuardTests(unittest.TestCase):
    def test_success_but_empty_answer_downgraded_to_failed(self):
        provider = _StaticProvider(GenerationResult("static", "m", STATUS_SUCCESS, response_text=""))
        outcome = er.run_single(provider, "m", {"case_id": "C1"})
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.run_status, STATUS_FAILED)
        self.assertEqual(outcome.error_code, ERROR_EMPTY_RESPONSE)
        self.assertEqual(outcome.answer_length, 0)

    def test_success_with_answer_stays_success(self):
        provider = _StaticProvider(GenerationResult("static", "m", STATUS_SUCCESS, response_text="ok"))
        outcome = er.run_single(provider, "m", {"case_id": "C1"})
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.answer_length, 2)

    def test_incomplete_generation_result_surfaces_finish_reason_on_outcome(self):
        provider = _StaticProvider(GenerationResult(
            "static",
            "m",
            STATUS_FAILED,
            response_text="初步结论：存在风险。具体测算",
            output_tokens=128,
            trace_id="trace-incomplete",
            error_code="incomplete_response",
            error_message="模型回答因长度限制中断。",
            finish_reason="length",
            incomplete_reason="模型回答因长度限制中断。",
        ))

        outcome = er.run_single(provider, "m", {"case_id": "C1"})

        self.assertFalse(outcome.success)
        self.assertEqual(outcome.run_status, STATUS_FAILED)
        self.assertEqual(outcome.error_code, "incomplete_response")
        self.assertEqual(outcome.finish_reason, "length")
        self.assertEqual(outcome.incomplete_reason, "模型回答因长度限制中断。")
        self.assertEqual(outcome.output_tokens, 128)
        self.assertEqual(outcome.trace_id, "trace-incomplete")

    def test_length_incomplete_retries_once_with_higher_token_budget_and_keeps_success(self):
        provider = _SequenceProvider(
            GenerationResult(
                "sequence",
                "m",
                STATUS_FAILED,
                response_text="初步结论：存在风险。具体测算",
                error_code="incomplete_response",
                error_message="模型回答因长度限制中断。",
                finish_reason="length",
                incomplete_reason="模型回答因长度限制中断。",
            ),
            GenerationResult(
                "sequence",
                "m",
                STATUS_SUCCESS,
                response_text="初步结论：基于已提供数据，存在较高风险。",
                finish_reason="stop",
            ),
        )

        outcome = er.run_single(
            provider,
            "m",
            {"case_id": "CM-001"},
            max_tokens=2048,
            retry_max_tokens=4096,
        )

        self.assertEqual([2048, 4096], provider.max_token_calls)
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.run_status, STATUS_SUCCESS)
        self.assertEqual(outcome.retry_count, 1)
        self.assertEqual(outcome.first_finish_reason, "length")
        self.assertEqual(outcome.final_finish_reason, "stop")
        self.assertEqual(outcome.finish_reason, "stop")
        self.assertIsNone(outcome.error_code)

    def test_length_incomplete_retry_still_length_keeps_incomplete_response(self):
        provider = _SequenceProvider(
            GenerationResult(
                "sequence",
                "m",
                STATUS_FAILED,
                response_text="初步结论：存在风险。具体测算",
                error_code="incomplete_response",
                error_message="模型回答因长度限制中断。",
                finish_reason="length",
                incomplete_reason="模型回答因长度限制中断。",
            ),
            GenerationResult(
                "sequence",
                "m",
                STATUS_FAILED,
                response_text="初步结论：仍存在风险。具体测算",
                error_code="incomplete_response",
                error_message="模型回答因长度限制中断。",
                finish_reason="length",
                incomplete_reason="模型回答因长度限制中断。",
            ),
        )

        outcome = er.run_single(
            provider,
            "m",
            {"case_id": "CM-001"},
            max_tokens=2048,
            retry_max_tokens=4096,
        )

        self.assertEqual([2048, 4096], provider.max_token_calls)
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.error_code, "incomplete_response")
        self.assertEqual(outcome.retry_count, 1)
        self.assertEqual(outcome.first_finish_reason, "length")
        self.assertEqual(outcome.final_finish_reason, "length")


class _CodeProvider(ModelProvider):
    """Maps model_id to a fixed failure error_code (timeout / 401 / 429)."""

    name = "codes"
    _BY_ID = {
        "ok": GenerationResult("codes", "ok", STATUS_SUCCESS, response_text="hi"),
        "timeout": GenerationResult("codes", "timeout", STATUS_FAILED, error_code="timeout",
                                    error_message="请求超时。"),
        "401": GenerationResult("codes", "401", STATUS_FAILED, error_code="unauthorized",
                                error_message="API Key 无效或缺失。"),
        "429": GenerationResult("codes", "429", STATUS_FAILED, error_code="rate_limited",
                                error_message="触发限流。"),
        "empty": GenerationResult("codes", "empty", STATUS_FAILED, error_code=ERROR_EMPTY_RESPONSE),
    }

    def list_models(self, model_type="text", sub_type="chat"):
        raise NotImplementedError

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        return self._BY_ID[model_id]


class ErrorSurfacingTests(unittest.TestCase):
    def test_timeout_401_429_surface_on_outcomes(self):
        result = er.run_models(_CodeProvider(), ["timeout", "401", "429"], [{"case_id": "C1"}])
        by_model = {o.model_id: o for o in result.outcomes}
        self.assertEqual(by_model["timeout"].error_code, "timeout")
        self.assertEqual(by_model["401"].error_code, "unauthorized")
        self.assertEqual(by_model["429"].error_code, "rate_limited")
        for o in result.outcomes:
            self.assertFalse(o.success)
            self.assertTrue(o.error_message or o.error_code)


class RunSummaryTests(unittest.TestCase):
    def test_summary_counts_each_bucket(self):
        result = er.run_models(
            _CodeProvider(), ["ok", "empty", "timeout", "401", "429"], [{"case_id": "C1"}]
        )
        summary = er.summarize_outcomes(result.outcomes)
        self.assertEqual(summary.total, 5)
        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.empty_response, 1)
        self.assertEqual(summary.timeout, 1)
        self.assertEqual(summary.auth, 1)
        self.assertEqual(summary.other, 1)
        # CompareRunResult 自带的同口径计数应一致。
        self.assertEqual(result.summary_counts()["empty_response"], 1)


class ProgressCallbackTests(unittest.TestCase):
    def test_progress_callback_invoked_per_item_and_final(self):
        events = []
        er.run_models(
            _CodeProvider(), ["ok", "timeout"], [{"case_id": "C1"}],
            progress_callback=lambda d, t, m, c: events.append((d, t, m, c)),
        )
        # 2 次开始前回调 + 1 次收尾回调。
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0][0], 0)
        self.assertEqual(events[0][1], 2)
        self.assertEqual(events[-1][0], 2)

    def test_progress_callback_errors_do_not_break_run(self):
        def boom(*_):
            raise RuntimeError("ui exploded")

        result = er.run_models(_CodeProvider(), ["ok"], [{"case_id": "C1"}], progress_callback=boom)
        self.assertEqual(len(result.outcomes), 1)


class DefaultTaskSelectionTests(unittest.TestCase):
    def test_defaults_to_single_first_task(self):
        tasks = [{"case_id": "A"}, {"case_id": "B"}, {"case_id": "C"}]
        self.assertEqual(er.default_task_selection(tasks), [{"case_id": "A"}])

    def test_empty_tasks_yield_empty(self):
        self.assertEqual(er.default_task_selection([]), [])


class PersistFlagTests(unittest.TestCase):
    def test_page_uses_persist_return_not_is_mock_result(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        # 修复点：持久化标记取 persist_compare_result 的真实返回值。
        self.assertIn("persisted = er.persist_compare_result(result)", source)
        self.assertIn('st.session_state["test_run_persisted"] = persisted', source)
        # 不应再用 is_mock_result 充当落库标记。
        self.assertNotIn('test_run_persisted"] = er.is_mock_result', source)


if __name__ == "__main__":
    unittest.main()
