"""模型适配层的统一接口与返回结构（PR-33）。

定义 ModelProvider 抽象接口与统一的返回数据结构，使页面层只依赖该接口，
不感知具体供应商实现（SiliconFlow / Mock / 其他 OpenAI 兼容供应商）。

本模块不发起任何网络请求、不读取任何密钥，仅声明契约与数据载体。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


# 统一的状态取值：成功 / 失败 / mock（占位回退）。
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_MOCK = "mock"


@dataclass(frozen=True)
class ModelInfo:
    """单个模型的统一描述。

    仅 id / provider / object / owned_by / raw 为约定字段；上下文长度、价格、
    是否推理模型等不保证存在，存在时放入 metadata 作为可选信息。
    """

    id: str
    provider: str
    object: str
    owned_by: str
    raw: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelListResult:
    """list_models 的统一返回。失败时 models 为空并带结构化错误。"""

    provider: str
    status: str
    models: Sequence[ModelInfo] = field(default_factory=tuple)
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {STATUS_SUCCESS, STATUS_MOCK}


@dataclass(frozen=True)
class GenerationResult:
    """generate_response 的统一返回。

    无论成功、失败还是 mock，结构保持一致，便于页面统一渲染。raw_response
    只保存供应商响应体，绝不包含 Authorization 等认证信息。
    """

    provider: str
    model_id: str
    status: str
    response_text: str = ""
    raw_response: Mapping[str, Any] = field(default_factory=dict)
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    http_status: int | None = None
    trace_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {STATUS_SUCCESS, STATUS_MOCK}


@dataclass(frozen=True)
class ConnectivityResult:
    """供应商连通性检查结果。"""

    provider: str
    reachable: bool
    mode: str  # live / mock
    message: str


class ModelProvider(ABC):
    """文本对话模型供应商的统一接口（ModelClient）。

    实现需保证：
      - list_models 默认只返回文本对话（type=text、sub_type=chat）模型；
      - generate_response 返回结构化 GenerationResult，不抛供应商异常给调用方；
      - 任何错误都转为结构化字段，不泄露密钥与认证头。
    """

    #: 供应商注册名，registry 以此检索。
    name: str = "base"

    @abstractmethod
    def list_models(self, model_type: str = "text", sub_type: str = "chat") -> ModelListResult:
        """拉取可用模型列表，默认筛选文本对话模型。"""

    @abstractmethod
    def generate_response(
        self,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> GenerationResult:
        """对单轮 messages 生成回答，返回统一结构。"""

    def check_connectivity(self) -> ConnectivityResult:
        """默认连通性检查：尝试拉取模型列表。子类可覆盖为更轻量的探测。"""
        result = self.list_models()
        reachable = result.ok
        mode = "mock" if result.status == STATUS_MOCK else "live"
        message = result.error_message or ("连接正常。" if reachable else "连接失败。")
        return ConnectivityResult(self.name, reachable, mode, message)


# ModelClient 作为接口别名，便于按调用方习惯命名。
ModelClient = ModelProvider


def normalize_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """校验并规整对话消息：要求非空、每条含 role 与 content。"""
    if not messages:
        raise ValueError("messages 不能为空。")
    normalized: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, Mapping) or "role" not in item or "content" not in item:
            raise ValueError("每条 message 需包含 role 与 content 字段。")
        normalized.append({"role": str(item["role"]), "content": item["content"]})
    return normalized
