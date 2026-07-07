"""模型适配层（model providers）。

对外暴露统一接口与 registry，使页面层只通过 registry/provider 接口调用，
不直接依赖任何具体供应商实现。
"""

from __future__ import annotations

from app.models.base import (
    ConnectivityResult,
    ERROR_EMPTY_RESPONSE,
    ERROR_INCOMPLETE_RESPONSE,
    GenerationResult,
    ModelClient,
    ModelInfo,
    ModelListResult,
    ModelProvider,
    STATUS_FAILED,
    STATUS_MOCK,
    STATUS_SUCCESS,
    extract_answer_text,
    extract_finish_reason,
)
from app.models.registry import (
    available_providers,
    get_provider,
    get_text_provider,
    register_provider,
)

__all__ = [
    "ConnectivityResult",
    "ERROR_EMPTY_RESPONSE",
    "ERROR_INCOMPLETE_RESPONSE",
    "GenerationResult",
    "ModelClient",
    "ModelInfo",
    "ModelListResult",
    "ModelProvider",
    "STATUS_FAILED",
    "STATUS_MOCK",
    "STATUS_SUCCESS",
    "extract_answer_text",
    "extract_finish_reason",
    "available_providers",
    "get_provider",
    "get_text_provider",
    "register_provider",
]
