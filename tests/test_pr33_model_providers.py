"""PR-33 tests: SiliconFlow / Mock model provider layer.

All HTTP is mocked — no test performs a real outbound request. Coverage:
missing API key → mock fallback, list_models / chat parsing, trace-id and usage
extraction, 401/403/429/503/504 and timeout error mapping, API-key non-leakage,
and registry resolution.
"""

import json
import unittest
import urllib.error
from unittest import mock

from app.models import STATUS_FAILED, STATUS_MOCK, STATUS_SUCCESS
from app.models.base import normalize_messages
from app.models.mock import MockProvider
from app.models.registry import get_text_provider, reset_for_testing
from app.models import siliconflow as sf
from app.models.siliconflow import SiliconFlowProvider, _HttpResponse


_MESSAGES = [{"role": "user", "content": "请概述一笔收购的尽调要点"}]


class _FakeResp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class MockProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = MockProvider()

    def test_list_models_marked_mock(self):
        result = self.provider.list_models()
        self.assertEqual(result.status, STATUS_MOCK)
        self.assertTrue(result.models)
        # Mock 模型命名即表明为占位，不冒充真实模型。
        self.assertTrue(all(m.id.startswith("mock/") for m in result.models))

    def test_generate_response_structure_matches_real(self):
        result = self.provider.generate_response("mock/chat-base", _MESSAGES)
        self.assertEqual(result.status, STATUS_MOCK)
        self.assertIn("MOCK", result.response_text)
        self.assertEqual(result.total_tokens, result.input_tokens + result.output_tokens)
        self.assertIsNone(result.http_status)

    def test_rejects_empty_messages(self):
        result = self.provider.generate_response("mock/chat-base", [])
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.error_code, "bad_request")


class SiliconFlowConfigTests(unittest.TestCase):
    def test_missing_api_key_returns_structured_error(self):
        provider = SiliconFlowProvider(api_key="")
        listing = provider.list_models()
        self.assertEqual(listing.status, STATUS_FAILED)
        self.assertEqual(listing.error_code, "missing_api_key")

        gen = provider.generate_response("any/model", _MESSAGES)
        self.assertEqual(gen.status, STATUS_FAILED)
        self.assertEqual(gen.error_code, "missing_api_key")

    def test_base_url_and_timeout_defaults(self):
        provider = SiliconFlowProvider(api_key="sk-x", base_url=None, timeout_seconds=None)
        self.assertEqual(provider.base_url, sf.DEFAULT_BASE_URL)
        self.assertEqual(provider.timeout_seconds, float(sf.DEFAULT_TIMEOUT_SECONDS))


class SiliconFlowListModelsTests(unittest.TestCase):
    def test_filters_text_chat_and_parses(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            body = {
                "data": [
                    {"id": "Qwen/Qwen2.5-7B-Instruct", "object": "model", "owned_by": "qwen",
                     "context_length": 32768},
                    {"id": "deepseek-ai/DeepSeek-V3", "object": "model", "owned_by": "deepseek"},
                ]
            }
            return _FakeResp(200, {"Content-Type": "application/json"}, json.dumps(body))

        provider = SiliconFlowProvider(api_key="sk-secret")
        with mock.patch.object(sf.urllib.request, "urlopen", fake_urlopen):
            result = provider.list_models()

        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertEqual([m.id for m in result.models], ["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3"])
        # 默认按 type=text、sub_type=chat 过滤。
        self.assertIn("type=text", captured["url"])
        self.assertIn("sub_type=chat", captured["url"])
        # 不假设上下文长度等字段；存在时进入 metadata。
        self.assertEqual(result.models[0].metadata.get("context_length"), 32768)
        self.assertEqual(result.models[1].metadata, {})
        # API Key 不泄露到结果中。
        self.assertNotIn("sk-secret", json.dumps([dict(m.raw) for m in result.models]))


class SiliconFlowGenerateTests(unittest.TestCase):
    def test_success_parses_text_usage_and_trace(self):
        def fake_urlopen(request, timeout=None):
            # 真实请求必须带 model 与 messages。
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["model"], "Qwen/Qwen2.5-7B-Instruct")
            self.assertIn("messages", payload)
            self.assertIs(payload["stream"], False)
            body = {
                "choices": [{"message": {"role": "assistant", "content": "尽调要点如下……"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": 42},
            }
            headers = {"x-siliconcloud-trace-id": "trace-abc-123"}
            return _FakeResp(200, headers, json.dumps(body))

        provider = SiliconFlowProvider(api_key="sk-secret")
        with mock.patch.object(sf.urllib.request, "urlopen", fake_urlopen):
            result = provider.generate_response(
                "Qwen/Qwen2.5-7B-Instruct", _MESSAGES, temperature=0.3, max_tokens=512,
                top_p=0.9, enable_thinking=False,
            )

        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertEqual(result.response_text, "尽调要点如下……")
        self.assertEqual(result.input_tokens, 12)
        self.assertEqual(result.output_tokens, 30)
        self.assertEqual(result.total_tokens, 42)
        self.assertEqual(result.trace_id, "trace-abc-123")
        self.assertEqual(result.http_status, 200)
        # raw_response 不得包含认证信息。
        self.assertNotIn("sk-secret", json.dumps(result.raw_response))
        self.assertNotIn("Authorization", json.dumps(result.raw_response))

    def test_optional_params_only_sent_when_present(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeResp(200, {}, json.dumps({"choices": [], "usage": {}}))

        provider = SiliconFlowProvider(api_key="sk-secret")
        with mock.patch.object(sf.urllib.request, "urlopen", fake_urlopen):
            provider.generate_response("m", _MESSAGES, top_k=20)

        payload = captured["payload"]
        self.assertEqual(payload["top_k"], 20)
        # 未提供的可选参数不应出现在请求体中。
        self.assertNotIn("top_p", payload)
        self.assertNotIn("response_format", payload)


class SiliconFlowErrorMappingTests(unittest.TestCase):
    def _result_for_status(self, status):
        provider = SiliconFlowProvider(api_key="sk-secret")
        fake = _HttpResponse(status, {}, json.dumps({"error": "boom"}))
        with mock.patch.object(SiliconFlowProvider, "_send", return_value=fake):
            return provider.generate_response("m", _MESSAGES)

    def test_unauthorized_and_forbidden(self):
        for status, code in [(401, "unauthorized"), (403, "forbidden")]:
            result = self._result_for_status(status)
            self.assertEqual(result.status, STATUS_FAILED)
            self.assertEqual(result.error_code, code)
            self.assertIn("API Key", result.error_message)

    def test_rate_limited(self):
        result = self._result_for_status(429)
        self.assertEqual(result.error_code, "rate_limited")
        self.assertIn("限流", result.error_message)

    def test_service_unavailable_and_timeout_status(self):
        for status, code in [(503, "service_unavailable"), (504, "gateway_timeout")]:
            result = self._result_for_status(status)
            self.assertEqual(result.error_code, code)

    def test_transport_timeout(self):
        provider = SiliconFlowProvider(api_key="sk-secret")

        def boom(request, timeout=None):
            raise urllib.error.URLError(TimeoutError("timed out"))

        with mock.patch.object(sf.urllib.request, "urlopen", boom):
            result = provider.generate_response("m", _MESSAGES)
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.error_code, "timeout")

    def test_error_message_never_leaks_api_key(self):
        result = self._result_for_status(401)
        self.assertNotIn("sk-secret", result.error_message or "")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        reset_for_testing()

    def tearDown(self):
        reset_for_testing()

    def test_falls_back_to_mock_without_key(self):
        # registry 在导入时绑定了 siliconflow_configured 引用，需在 registry 命名空间打桩，
        # 才能与真实环境（含本地 .env Key）无关地验证回退逻辑。
        with mock.patch("app.models.registry.siliconflow_configured", return_value=False):
            provider = get_text_provider()
        self.assertEqual(provider.name, "mock")

    def test_uses_siliconflow_when_configured(self):
        with mock.patch("app.models.registry.siliconflow_configured", return_value=True):
            provider = get_text_provider()
        self.assertEqual(provider.name, "siliconflow")

    def test_normalize_messages_validation(self):
        with self.assertRaises(ValueError):
            normalize_messages([{"role": "user"}])


if __name__ == "__main__":
    unittest.main()
