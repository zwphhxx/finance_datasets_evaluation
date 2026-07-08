"""Mock 模型供应商。

无 API Key 时自动启用，返回与真实供应商一致的结构，但 status 统一标记为 mock，
回答内容明确标注为模拟生成，不冒充任何真实模型结果。仅用于在缺少密钥时让
provider 接口、列表读取与调用链路可端到端跑通。
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from app.models.base import (
    ConnectivityResult,
    GenerationResult,
    ModelInfo,
    ModelListResult,
    ModelProvider,
    STATUS_FAILED,
    STATUS_MOCK,
    normalize_messages,
)

PROVIDER_NAME = "mock"

# 占位模型，命名即表明为 mock，不与真实模型 ID 混淆。
_MOCK_MODELS = (
    ("mock/chat-base", "mock"),
    ("mock/chat-reasoning", "mock"),
)


class MockProvider(ModelProvider):
    """无密钥时的占位供应商。"""

    name = PROVIDER_NAME

    def list_models(self, model_type: str = "text", sub_type: str = "chat") -> ModelListResult:
        models = tuple(
            ModelInfo(
                id=model_id,
                provider=self.name,
                object="model",
                owned_by=owner,
                raw={"id": model_id, "object": "model", "owned_by": owner},
                metadata={"mock": True, "model_type": model_type, "sub_type": sub_type},
            )
            for model_id, owner in _MOCK_MODELS
        )
        return ModelListResult(self.name, STATUS_MOCK, models=models)

    def generate_response(
        self,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> GenerationResult:
        try:
            normalized = normalize_messages(messages)
        except ValueError as exc:
            return GenerationResult(
                self.name, model_id, STATUS_FAILED, error_code="bad_request", error_message=str(exc)
            )

        started = time.perf_counter()
        last_user = next(
            (str(m["content"]) for m in reversed(normalized) if m.get("role") == "user"),
            "",
        )
        preview = last_user.strip().replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:80] + "…"
        response_text = (
            "【MOCK 模拟回答 · 非真实模型结果】"
            f"当前未配置 SiliconFlow API Key，以下为占位响应，仅用于打通链路。"
            f"收到的最后一条用户消息：{preview or '（空）'}"
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        # token 数为基于词数的粗略估算，明确并非供应商计费口径。
        input_tokens = sum(len(str(m["content"]).split()) for m in normalized)
        output_tokens = len(response_text.split())
        return GenerationResult(
            provider=self.name,
            model_id=model_id,
            status=STATUS_MOCK,
            response_text=response_text,
            raw_response={"mock": True, "model": model_id, "choices": [
                {"message": {"role": "assistant", "content": response_text}}
            ]},
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            http_status=None,
            trace_id=None,
        )

    def check_connectivity(self) -> ConnectivityResult:
        return ConnectivityResult(self.name, reachable=True, mode="mock", message="当前为 mock 模式，无需外部连接。")
