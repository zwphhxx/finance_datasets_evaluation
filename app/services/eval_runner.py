"""真实模型评测运行编排（PR-34）。

把「选任务 → 构造 prompt → 调用 provider → 汇总结果」的逻辑从页面中抽离，页面只负责
交互与展示。本模块不依赖 Streamlit 运行时，便于单元测试。

Prompt 边界（重要）：
  - 绝不把 Gold Answer / 必须覆盖点 / 不可接受错误等评测答案发送给被评测模型；
  - 被评测模型只看到任务场景、题干、必要背景与输出格式要求；
  - 不让模型自评、不引导其输出虚假确定结论；
  - 对金融 / 法律 / 投资判断类任务，提示模型说明依据与核查边界。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.models.base import ModelProvider, STATUS_MOCK

# 被评测模型可见的任务字段（白名单）。Gold Answer 相关字段一律不在其中。
_VISIBLE_TASK_FIELDS = ("scenario", "question", "context")

_SYSTEM_PROMPT = (
    "你是金融与专业尽调领域的分析助手。请仅依据题目提供的信息作答，"
    "不要编造材料中没有的事实或给出无依据的确定性结论。"
    "对涉及金融、法律或投资判断的问题，请说明你的判断依据，并明确指出仍需进一步核实的边界与前提。"
    "请按以下结构作答：1) 结论；2) 主要依据；3) 风险与核查边界。"
    "不要对自己的回答进行打分或自评。"
)

_OUTPUT_HINT = "请用中文作答，结构清晰、专业克制；信息不足时应说明需要补充核实的内容，而非臆测。"


@dataclass(frozen=True)
class RunOutcome:
    """单题运行结果（统一结构，便于表格展示与后续 Gold Answer 对比复用）。"""

    case_id: str
    task_type: str
    provider: str
    model_id: str
    run_status: str  # success / failed / mock
    success: bool
    answer_text: str = ""
    answer_length: int = 0
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    http_status: int | None = None
    trace_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RunResult:
    """一次运行（可含单题或多题）的汇总。"""

    run_id: str
    provider: str
    model_id: str
    mode: str  # live / mock
    created_at: str
    outcomes: Sequence[RunOutcome] = field(default_factory=tuple)

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.success)


@dataclass(frozen=True)
class CompareRunResult:
    """一次多模型对比运行的汇总：一个 run_id 下，N 个模型各自跑同一组任务。

    outcomes 是 (模型 × 任务) 的扁平列表，每个 RunOutcome 自带 model_id 以区分模型，
    便于在结果表中按模型分组并排展示。
    """

    run_id: str
    provider: str
    model_ids: Sequence[str]
    mode: str  # live / mock
    created_at: str
    outcomes: Sequence[RunOutcome] = field(default_factory=tuple)

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.success)


def generate_run_id() -> str:
    """生成本次运行的 run_id：时间戳 + 短随机后缀，便于人读且基本唯一。"""
    return f"RUN-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def build_messages(task: Mapping[str, Any]) -> list[dict[str, str]]:
    """构造发送给被评测模型的对话消息，只暴露任务白名单字段，绝不含 Gold Answer。"""
    lines: list[str] = []
    scenario = _clean(task.get("scenario"))
    if scenario:
        lines.append(f"【业务场景】{scenario}")
    question = _clean(task.get("question"))
    if question:
        lines.append(f"【任务问题】{question}")
    context = _clean(task.get("context"))
    if context:
        lines.append(f"【背景信息】{context}")
    lines.append(f"【输出要求】{_OUTPUT_HINT}")
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def run_single(
    provider: ModelProvider,
    model_id: str,
    task: Mapping[str, Any],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    **kwargs: Any,
) -> RunOutcome:
    """对单题运行一次模型调用，转为统一 RunOutcome（不抛异常给调用方）。"""
    messages = build_messages(task)
    result = provider.generate_response(
        model_id, messages, temperature=temperature, max_tokens=max_tokens, **kwargs
    )
    answer = result.response_text or ""
    return RunOutcome(
        case_id=str(task.get("case_id", "")),
        task_type=str(task.get("task_type", "")),
        provider=result.provider,
        model_id=model_id,
        run_status=result.status,
        success=result.ok,
        answer_text=answer,
        answer_length=len(answer),
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        http_status=result.http_status,
        trace_id=result.trace_id,
        error_code=result.error_code,
        error_message=result.error_message,
    )


def run_evaluation(
    provider: ModelProvider,
    model_id: str,
    tasks: Sequence[Mapping[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    run_id: str | None = None,
    **kwargs: Any,
) -> RunResult:
    """对一道或多道任务顺序运行，返回带 run_id 的汇总结果。

    单题即传入长度为 1 的 tasks；批量传入多条。任一题失败只影响该题的 RunOutcome，
    不中断整体运行。
    """
    rid = run_id or generate_run_id()
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    outcomes = tuple(
        run_single(provider, model_id, task, temperature=temperature, max_tokens=max_tokens, **kwargs)
        for task in tasks
    )
    return RunResult(
        run_id=rid,
        provider=getattr(provider, "name", ""),
        model_id=model_id,
        mode=mode,
        created_at=datetime.now().isoformat(timespec="seconds"),
        outcomes=outcomes,
    )


def run_models(
    provider: ModelProvider,
    model_ids: Sequence[str],
    tasks: Sequence[Mapping[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    run_id: str | None = None,
    **kwargs: Any,
) -> CompareRunResult:
    """对多个模型各自跑同一组任务，汇总成一个 CompareRunResult（共享 run_id）。

    去重并保序处理 model_ids；对每个模型的每道任务调用 run_single，任一调用失败只影响
    该 (模型, 任务) 的 RunOutcome，不中断整体。模型列表为空时 outcomes 为空。
    """
    unique_models = _dedupe_preserve_order(model_ids)
    rid = run_id or generate_run_id()
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    outcomes = tuple(
        run_single(provider, model_id, task, temperature=temperature, max_tokens=max_tokens, **kwargs)
        for model_id in unique_models
        for task in tasks
    )
    return CompareRunResult(
        run_id=rid,
        provider=getattr(provider, "name", ""),
        model_ids=tuple(unique_models),
        mode=mode,
        created_at=datetime.now().isoformat(timespec="seconds"),
        outcomes=outcomes,
    )


def persist_run_result(result, db_path: Path | None = None) -> bool:
    """尽力将运行结果写入 SQLite live_run_responses；数据库不可用时静默跳过。

    接受 RunResult（单模型）或 CompareRunResult（多模型）：两者都带 run_id / mode /
    outcomes，每行的 model_name 取自 outcome.model_id，故多模型会在同一 run_id 下分行写入。
    写入独立的 live_run_responses 表，不污染承载评分的 model_responses（seed）。
    返回是否成功落库。任何异常都不向上抛出，保证页面不因落库失败而崩溃。
    """
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        rows = [
            {
                "run_id": result.run_id,
                "case_id": o.case_id,
                "task_type": o.task_type,
                "provider": o.provider,
                "model_name": o.model_id,
                "run_mode": result.mode,
                "run_status": o.run_status,
                "answer_text": o.answer_text,
                "answer_length": o.answer_length,
                "latency_ms": o.latency_ms,
                "input_tokens": o.input_tokens,
                "output_tokens": o.output_tokens,
                "total_tokens": o.total_tokens,
                "http_status": o.http_status,
                "trace_id": o.trace_id,
                "error_code": o.error_code,
                "error_message": o.error_message,
            }
            for o in result.outcomes
        ]
        if not rows:
            return False
        Repository(path).bulk_insert("live_run_responses", rows)
        return True
    except Exception:
        return False


def persist_compare_result(result: CompareRunResult, db_path: Path | None = None) -> bool:
    """多模型对比结果落库（与 persist_run_result 同实现，命名上更直观）。"""
    return persist_run_result(result, db_path=db_path)


def is_mock_result(result) -> bool:
    return result.mode == "mock" or any(o.run_status == STATUS_MOCK for o in result.outcomes)


def _dedupe_preserve_order(items: Sequence[str]) -> list[str]:
    """去除空白项并按首次出现顺序去重，避免对同一模型重复评测。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = _clean(item)
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text
