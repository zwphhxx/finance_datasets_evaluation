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

# HTTP 成功但供应商返回的回答为空时使用的错误码（区别于鉴权/超时等失败，
# 便于运行汇总单独统计「空回答」条数）。
ERROR_EMPTY_RESPONSE = "empty_response"
ERROR_INCOMPLETE_RESPONSE = "incomplete_response"


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
    finish_reason: str | None = None
    incomplete_reason: str | None = None

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


def _coerce_content(content: Any) -> str:
    """将单个 content 值归一化为纯文本。

    兼容三种 OpenAI 兼容形态：纯字符串；分块列表（[{type,text}|{text}|str, …]，
    多模态 / parts 风格）；其他类型一律转字符串。不假设具体供应商字段名。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping):
                # 常见键：text / content；优先 text。
                value = part.get("text")
                if value is None:
                    value = part.get("content")
                if isinstance(value, (list, tuple)):
                    value = _coerce_content(value)
                if value:
                    parts.append(str(value))
        return "".join(parts)
    return str(content)


def extract_answer_text(body: Mapping[str, Any]) -> str:
    """从 OpenAI 兼容的对话/补全响应体中稳健提取回答文本。

    依次尝试（任一非空即返回，trim 后判断）：
      1) choices[0].message.content（字符串或分块列表）；
      2) choices[0].message.reasoning_content（推理型模型在 content 为空时的回退）；
      3) choices[0].text（旧式 completion 形态）。
    不假设具体供应商私有字段；无法提取时返回空串，由调用方判定为空回答。
    """
    if not isinstance(body, Mapping):
        return ""
    choices = body.get("choices") or []
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, Mapping):
        return ""

    message = first.get("message")
    if isinstance(message, Mapping):
        content = _coerce_content(message.get("content"))
        if content.strip():
            return content
        reasoning = _coerce_content(message.get("reasoning_content"))
        if reasoning.strip():
            return reasoning

    legacy = first.get("text")
    if isinstance(legacy, str) and legacy.strip():
        return legacy

    return ""


def extract_finish_reason(body: Mapping[str, Any]) -> str | None:
    """Extract choices[0].finish_reason from an OpenAI-compatible response."""
    first = _first_choice(body)
    if not first:
        return None
    value = first.get("finish_reason")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def detect_incomplete_answer(answer_text: str, messages: Sequence[Mapping[str, Any]] | None = None) -> str | None:
    """Conservative heuristic for answers that visibly stop mid-thought.

    This is intentionally narrower than a quality check: it catches provider
    truncation symptoms such as ending at "具体测算" or "如下：" while leaving
    short but complete answers alone.
    """
    text = str(answer_text or "").strip()
    if not text:
        return None

    compact = text.rstrip()
    if len(compact) < 300 and _ends_with_dangling_phrase(compact):
        return "回答停在明显未完成的语句。"

    if "具体测算" in compact:
        tail = compact.rsplit("具体测算", 1)[-1]
        if not any(char.isdigit() for char in tail) and _looks_unfinished_tail(tail):
            return "回答提到具体测算但未列出测算结果。"

    if messages and _requires_four_part_structure(messages):
        present = sum(
            1
            for marker in ("1）", "2）", "3）", "4）")
            if marker in compact
        )
        if 0 < present <= 2 and len(compact) < 500 and not _ends_with_terminal_punctuation(compact):
            return "回答未完成要求的结构化部分。"

    return None


def _first_choice(body: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if not isinstance(body, Mapping):
        return None
    choices = body.get("choices") or []
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        return None
    first = choices[0]
    return first if isinstance(first, Mapping) else None


def _ends_with_dangling_phrase(text: str) -> bool:
    dangling = (
        "具体测算",
        "如下",
        "如下：",
        "包括",
        "分别为",
        "主要为",
        "例如",
        "其中",
        "：",
        ":",
        "，",
        ",",
        "、",
    )
    stripped = text.rstrip()
    return any(stripped.endswith(token) for token in dangling)


def _looks_unfinished_tail(tail: str) -> bool:
    stripped = str(tail or "").strip()
    return not stripped or _ends_with_dangling_phrase(stripped) or not _ends_with_terminal_punctuation(stripped)


def _ends_with_terminal_punctuation(text: str) -> bool:
    return str(text or "").rstrip().endswith(("。", "；", "？", "！", ".", ";", "?", "!", "）", ")", "】", "]", "”", "’", "」", "』"))


def _requires_four_part_structure(messages: Sequence[Mapping[str, Any]]) -> bool:
    blob = "\n".join(str(message.get("content", "")) for message in messages or [])
    return all(marker in blob for marker in ("1）", "2）", "3）", "4）"))
