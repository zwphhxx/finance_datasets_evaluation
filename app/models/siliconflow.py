"""SiliconFlow（硅基流动）模型供应商接入（PR-33）。

仅依赖标准库 urllib 发起 HTTP 请求，不引入第三方 SDK 或重依赖。负责：
  - 从 st.secrets / 环境变量 / .env 读取 API Key 与可选配置；
  - 调用 GET /v1/models（默认筛选 type=text、sub_type=chat）；
  - 调用 POST /v1/chat/completions 生成回答；
  - 将 HTTP 状态码与异常转为结构化错误，绝不泄露 API Key、Authorization 头或异常堆栈。

官方文档：
  Chat Completion  POST https://api.siliconflow.cn/v1/chat/completions
  List Models      GET  https://api.siliconflow.cn/v1/models
  认证             Authorization: Bearer <API_KEY>
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.models.base import (
    ConnectivityResult,
    ERROR_EMPTY_RESPONSE,
    ERROR_INCOMPLETE_RESPONSE,
    GenerationResult,
    ModelInfo,
    ModelListResult,
    ModelProvider,
    STATUS_FAILED,
    STATUS_SUCCESS,
    detect_incomplete_answer,
    extract_answer_text,
    extract_finish_reason,
    normalize_messages,
)

PROVIDER_NAME = "siliconflow"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_TIMEOUT_SECONDS = 180

# 配置项名称，按 st.secrets → 环境变量 → .env 顺序解析。
_API_KEY_KEY = "SILICONFLOW_API_KEY"
_BASE_URL_KEY = "SILICONFLOW_BASE_URL"
_TIMEOUT_KEY = "SILICONFLOW_TIMEOUT_SECONDS"

# 响应头中的链路追踪 ID（小写匹配，HTTP 头不区分大小写）。
_TRACE_HEADER = "x-siliconcloud-trace-id"

# generate_response 透传到请求体的可选参数（存在才发送，不强制页面暴露）。
_OPTIONAL_PAYLOAD_KEYS = (
    "top_p",
    "top_k",
    "frequency_penalty",
    "stop",
    "enable_thinking",
    "thinking_budget",
    "reasoning_effort",
    "response_format",
)

# HTTP 状态码 → (error_code, 面向用户的中文提示)。不暴露供应商堆栈。
_HTTP_ERROR_MESSAGES: dict[int, tuple[str, str]] = {
    400: ("bad_request", "请求参数有误，请检查模型 ID 与请求内容。"),
    401: ("unauthorized", "API Key 无效或缺失，请检查 SILICONFLOW_API_KEY 或账户权限。"),
    403: ("forbidden", "无访问权限，请检查 API Key 或账户权限。"),
    404: ("not_found", "模型或接口不存在，请检查模型 ID。"),
    429: ("rate_limited", "请求过于频繁，已触发限流，请稍后重试。"),
    503: ("service_unavailable", "模型服务繁忙，请稍后重试。"),
    504: ("gateway_timeout", "模型服务响应超时，请稍后重试。"),
}


@dataclass(frozen=True)
class _HttpResponse:
    """底层 HTTP 调用的归一化结果。

    status 为 None 表示传输层失败（超时 / 连接错误）；此时 error 非空。
    headers 仅保留响应头（不含我们发送的认证头）。
    """

    status: int | None
    headers: Mapping[str, str]
    text: str
    error: str | None = None


@dataclass(frozen=True)
class _HttpErrorDetails:
    error_code: str
    error_message: str
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    provider_error_body_excerpt: str | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_env_file(key: str) -> str | None:
    """从项目根 .env 读取单个键，仅做最简 KEY=VALUE 解析，不引入 dotenv 依赖。"""
    env_path = _project_root() / ".env"
    if not env_path.exists():
        return None
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _read_config_value(key: str) -> str | None:
    value, _source = _read_config_value_with_source(key)
    return value


def _read_config_value_with_source(key: str) -> tuple[str | None, str | None]:
    """按 st.secrets → 环境变量 → .env 顺序解析配置值。读 secrets 不得因缺失而崩溃。"""
    try:
        import streamlit as st

        # st.secrets 在无 secrets.toml 时访问会抛异常，需整体兜底。
        if key in st.secrets:
            value = str(st.secrets[key]).strip()
            if value:
                return value, "st.secrets"
    except Exception:
        pass

    import os

    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value, "environment"

    file_value = _read_env_file(key)
    if file_value:
        return file_value, ".env"
    return None, None


def is_configured() -> bool:
    """是否已配置 API Key（决定 registry 是否回退 mock）。"""
    return bool(_read_config_value(_API_KEY_KEY))


class SiliconFlowProvider(ModelProvider):
    """硅基流动 OpenAI 兼容供应商。"""

    name = PROVIDER_NAME

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.api_key = api_key if api_key is not None else _read_config_value(_API_KEY_KEY)
        self.base_url = (base_url or _read_config_value(_BASE_URL_KEY) or DEFAULT_BASE_URL).rstrip("/")
        if timeout_seconds is not None:
            self.timeout_seconds = float(timeout_seconds)
            self.timeout_source = "argument"
        else:
            self.timeout_seconds, self.timeout_source = self._resolve_timeout()

    @staticmethod
    def _resolve_timeout() -> tuple[float, str]:
        raw, source = _read_config_value_with_source(_TIMEOUT_KEY)
        if raw:
            try:
                return float(raw), str(source or "default")
            except ValueError:
                pass
        return float(DEFAULT_TIMEOUT_SECONDS), "default"

    # -- 公共接口 -------------------------------------------------------------
    def list_models(self, model_type: str = "text", sub_type: str = "chat") -> ModelListResult:
        if not self.api_key:
            return ModelListResult(
                self.name, STATUS_FAILED, error_code="missing_api_key",
                error_message="未配置 API Key，请改用 mock 模式或设置 SILICONFLOW_API_KEY。",
            )

        params = {}
        if model_type:
            params["type"] = model_type
        if sub_type:
            params["sub_type"] = sub_type
        path = "/models"
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"

        response = self._send("GET", path)
        if response.error is not None:
            code, message = self._describe_transport_error(response.error)
            return ModelListResult(self.name, STATUS_FAILED, error_code=code, error_message=message)
        if response.status != 200:
            code, message = self._describe_http_error(response.status, response.text)
            return ModelListResult(self.name, STATUS_FAILED, error_code=code, error_message=message)

        try:
            body = json.loads(response.text or "{}")
        except json.JSONDecodeError:
            return ModelListResult(
                self.name, STATUS_FAILED, error_code="invalid_response",
                error_message="模型列表响应解析失败。",
            )

        models = tuple(self._to_model_info(item) for item in body.get("data", []) if isinstance(item, Mapping))
        return ModelListResult(self.name, STATUS_SUCCESS, models=models)

    def generate_response(
        self,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        stream: bool = False,
        **kwargs: Any,
    ) -> GenerationResult:
        if not self.api_key:
            return GenerationResult(
                self.name, model_id, STATUS_FAILED, error_code="missing_api_key",
                error_message="未配置 API Key，请改用 mock 模式或设置 SILICONFLOW_API_KEY。",
            )
        if not str(model_id).strip():
            return GenerationResult(
                self.name, model_id, STATUS_FAILED, error_code="bad_request",
                error_message="model 不能为空。",
            )
        try:
            normalized = normalize_messages(messages)
        except ValueError as exc:
            return GenerationResult(
                self.name, model_id, STATUS_FAILED, error_code="bad_request", error_message=str(exc)
            )
        request_timeout = _as_positive_float(kwargs.pop("request_timeout_seconds", None))
        effective_timeout = request_timeout if request_timeout is not None else self.timeout_seconds
        timeout_meta = {
            "timeout_seconds": effective_timeout,
            "timeout_source": self.timeout_source,
        }

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": normalized,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # PR-33 不实现流式输出，固定 False（保留 stream 参数仅作接口兼容）。
            "stream": False,
        }
        for key in _OPTIONAL_PAYLOAD_KEYS:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        started = time.perf_counter()
        response = self._send("POST", "/chat/completions", payload, timeout_seconds=effective_timeout)
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.error is not None:
            code, message = self._describe_transport_error(response.error)
            return GenerationResult(
                self.name, model_id, STATUS_FAILED, latency_ms=latency_ms,
                error_code=code, error_message=message, **timeout_meta,
            )

        trace_id = response.headers.get(_TRACE_HEADER) or response.headers.get(_TRACE_HEADER.title())
        if response.status != 200:
            details = self._describe_http_error_details(response.status, response.text)
            return GenerationResult(
                self.name, model_id, STATUS_FAILED, latency_ms=latency_ms,
                http_status=response.status, trace_id=trace_id,
                error_code=details.error_code, error_message=details.error_message,
                provider_error_code=details.provider_error_code,
                provider_error_message=details.provider_error_message,
                provider_error_body_excerpt=details.provider_error_body_excerpt,
                **timeout_meta,
            )

        try:
            body = json.loads(response.text or "{}")
        except json.JSONDecodeError:
            return GenerationResult(
                self.name, model_id, STATUS_FAILED, latency_ms=latency_ms,
                http_status=response.status, trace_id=trace_id,
                error_code="invalid_response", error_message="对话响应解析失败。",
                **timeout_meta,
            )

        usage = body.get("usage") or {}
        answer_text = extract_answer_text(body)
        finish_reason = extract_finish_reason(body)
        common = dict(
            latency_ms=latency_ms,
            input_tokens=_as_int(usage.get("prompt_tokens")),
            output_tokens=_as_int(usage.get("completion_tokens")),
            total_tokens=_as_int(usage.get("total_tokens")),
            http_status=response.status,
            trace_id=trace_id,
            finish_reason=finish_reason,
            **timeout_meta,
        )
        finish_incomplete_reason = _incomplete_reason_for_finish(finish_reason)
        if finish_incomplete_reason:
            return GenerationResult(
                provider=self.name,
                model_id=model_id,
                status=STATUS_FAILED,
                response_text=answer_text,
                raw_response=body,
                error_code=ERROR_INCOMPLETE_RESPONSE,
                error_message=finish_incomplete_reason,
                incomplete_reason=finish_incomplete_reason,
                **common,
            )
        # HTTP 成功但未提取到任何回答文本：判为「空回答」失败，绝不当成成功。
        if not answer_text.strip():
            return GenerationResult(
                provider=self.name,
                model_id=model_id,
                status=STATUS_FAILED,
                raw_response=body,
                error_code=ERROR_EMPTY_RESPONSE,
                error_message="模型返回成功但回答为空（content / reasoning_content / text 均为空）。",
                **common,
            )
        incomplete_reason = detect_incomplete_answer(answer_text, normalized)
        if incomplete_reason:
            return GenerationResult(
                provider=self.name,
                model_id=model_id,
                status=STATUS_FAILED,
                response_text=answer_text,
                raw_response=body,
                error_code=ERROR_INCOMPLETE_RESPONSE,
                error_message=incomplete_reason,
                incomplete_reason=incomplete_reason,
                **common,
            )
        return GenerationResult(
            provider=self.name,
            model_id=model_id,
            status=STATUS_SUCCESS,
            response_text=answer_text,
            raw_response=body,
            **common,
        )

    def check_connectivity(self) -> ConnectivityResult:
        if not self.api_key:
            return ConnectivityResult(self.name, reachable=False, mode="live", message="未配置 API Key。")
        result = self.list_models()
        message = result.error_message or "连接正常。"
        return ConnectivityResult(self.name, reachable=result.ok, mode="live", message=message)

    def get_balance(self) -> str | None:
        """Return account balance when supported by the adapter.

        The current MVP adapter does not rely on a balance endpoint. Returning
        None keeps the UI deterministic and avoids guessing provider-specific
        paths or exposing request details.
        """
        return None

    # -- 解析与映射 -----------------------------------------------------------
    def _to_model_info(self, item: Mapping[str, Any]) -> ModelInfo:
        # 不假设上下文长度、价格、是否推理模型等字段存在；存在则作为可选 metadata。
        reserved = {"id", "object", "owned_by"}
        metadata = {k: v for k, v in item.items() if k not in reserved}
        return ModelInfo(
            id=str(item.get("id", "")),
            provider=self.name,
            object=str(item.get("object", "model")),
            owned_by=str(item.get("owned_by", "")),
            raw=dict(item),
            metadata=metadata,
        )

    @staticmethod
    def _describe_http_error(status: int | None, body: str) -> tuple[str, str]:
        details = SiliconFlowProvider._describe_http_error_details(status, body)
        return details.error_code, details.error_message

    @staticmethod
    def _describe_http_error_details(status: int | None, body: str) -> _HttpErrorDetails:
        if status in _HTTP_ERROR_MESSAGES:
            code, message = _HTTP_ERROR_MESSAGES[status]
        else:
            code, message = ("http_error", f"请求失败（HTTP {status}）。")
        provider_code, provider_message = _extract_provider_error(body)
        body_excerpt = _body_excerpt(body)
        if status == 400 and provider_message:
            message = f"请求参数有误：{provider_message}"
        return _HttpErrorDetails(
            error_code=code,
            error_message=message,
            provider_error_code=provider_code,
            provider_error_message=provider_message,
            provider_error_body_excerpt=body_excerpt,
        )

    @staticmethod
    def _describe_transport_error(error: str) -> tuple[str, str]:
        if error == "timeout":
            return ("timeout", "请求超时，请稍后重试或调大 SILICONFLOW_TIMEOUT_SECONDS。")
        return ("connection_error", "无法连接模型服务，请检查网络或服务地址。")

    # -- 底层 HTTP（测试通过 monkeypatch 替换本方法，避免真实外呼） -----------
    def _send(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> _HttpResponse:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return _HttpResponse(resp.status, _header_map(resp.headers), body)
        except urllib.error.HTTPError as exc:  # 4xx / 5xx：仍带状态码与响应体。
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            return _HttpResponse(exc.code, _header_map(getattr(exc, "headers", {})), body)
        except (TimeoutError, urllib.error.URLError) as exc:
            reason = getattr(exc, "reason", exc)
            is_timeout = isinstance(reason, TimeoutError) or "timed out" in str(reason).lower()
            return _HttpResponse(None, {}, "", error="timeout" if is_timeout else "connection")


def _header_map(headers: Any) -> dict[str, str]:
    """将 HTTP 响应头转为小写键字典，便于大小写无关查找。"""
    result: dict[str, str] = {}
    try:
        items = headers.items()
    except AttributeError:
        items = list(headers) if headers else []
    for key, value in items:
        result[str(key).lower()] = str(value)
    return result


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _extract_provider_error(body: str) -> tuple[str | None, str | None]:
    """Extract provider error code/message from a JSON error body without leaking secrets."""
    if not str(body or "").strip():
        return None, None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(parsed, Mapping):
        return None, None

    error_obj = parsed.get("error")
    code: Any = None
    message: Any = None
    if isinstance(error_obj, Mapping):
        code = error_obj.get("code")
        message = error_obj.get("message")
    elif isinstance(error_obj, str):
        message = error_obj

    if message is None:
        message = parsed.get("message")
    if code is None:
        code = parsed.get("code")
    if message is None:
        message = parsed.get("detail")

    clean_code = _safe_provider_text(code, limit=120) if code is not None else None
    clean_message = _safe_provider_text(message, limit=300) if message is not None else None
    return clean_code, clean_message


def _body_excerpt(body: str, limit: int = 500) -> str | None:
    text = str(body or "").strip()
    if not text:
        return None
    return _safe_provider_text(text, limit=limit)


def _safe_provider_text(value: Any, *, limit: int) -> str:
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = _redact_sensitive_text(text).strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def _redact_sensitive_text(text: str) -> str:
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", str(text or ""), flags=re.I)
    redacted = re.sub(r"sk-[A-Za-z0-9._~+/=-]+", "[REDACTED]", redacted)
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*)([^,;\\n\\r]+)",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*)([^,;\\n\\r]+)",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted


def _incomplete_reason_for_finish(finish_reason: str | None) -> str | None:
    reason = str(finish_reason or "").strip()
    if not reason:
        return None
    normalized = reason.lower()
    if normalized == "stop":
        return None
    if normalized == "length":
        return "回答超过输出长度限制。"
    if normalized == "content_filter":
        return "模型回答被内容过滤中断。"
    if normalized in {"tool_calls", "function_call"}:
        return "模型回答转入工具调用，未返回完整文本回答。"
    return f"模型回答未正常结束（finish_reason={reason}）。"
