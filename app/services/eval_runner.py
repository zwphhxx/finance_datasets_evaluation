"""真实模型评测运行编排（PR-34）。

把「选任务 → 构造 prompt → 调用 provider → 汇总结果」的逻辑从页面中抽离，页面只负责
交互与展示。本模块不依赖 Streamlit 运行时，便于单元测试。

Prompt 边界（重要）：
  - 绝不把 Gold Answer / 必须覆盖点 / 不可接受错误等评测答案发送给被评测模型；
  - 被评测模型只看到任务场景、题干、必要背景与样本输出要求；
  - 不让模型自评、不引导其输出绝对化结论；
  - 对财务 / 法律 / 投行判断类任务，提示模型先基于已给数据形成初步判断，再说明依据与核查边界。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.models.base import ERROR_EMPTY_RESPONSE, ModelProvider, STATUS_FAILED, STATUS_MOCK

# 被评测模型可见的任务字段（白名单）。Gold Answer 相关字段一律不在其中。
_VISIBLE_TASK_FIELDS = ("scenario", "question", "context", "output_requirement")

_SYSTEM_PROMPT = (
    "你是财务、法律与投行尽调场景下的专业分析助手。请仅依据题目提供的信息作答，"
    "不得编造题目未提供的事实。如果题目已经提供模拟数据、财务数据、合同条款、"
    "交易安排或其他已知背景，你必须先基于已提供数据形成初步判断，"
    "不得以“资料不足”“缺乏数据”“无法直接判定”“仍需进一步核查”作为主要结论。"
    "你的回答应体现：在当前已给数据范围内可以作出的判断、支撑该判断的关键数据和逻辑、"
    "仍需进一步核查或核实的边界。请按以下结构作答：1）初步结论；2）关键数据依据；"
    "3）风险事项；4）后续核查边界。"
    "不要对自己的回答进行打分或自评。"
)

_OUTPUT_HINT = (
    "请用中文作答，结构清晰、专业克制。第一段必须基于题目已提供数据形成初步判断；"
    "随后列示关键数据依据、风险事项和后续核查边界。除非题目完全没有提供可判断的数据，"
    "否则不得只回答“资料不足”或“无法直接判定”，也不得以“缺乏数据”作为主要结论。"
)


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

    def summary_counts(self) -> dict[str, int]:
        """返回五档计数：成功、空回答、超时、鉴权/权限、其他失败。"""
        counts = {"success": 0, "empty_response": 0, "timeout": 0, "auth": 0, "other": 0}
        for o in self.outcomes:
            if o.success:
                counts["success"] += 1
                continue
            code = o.error_code or ""
            if code == ERROR_EMPTY_RESPONSE:
                counts["empty_response"] += 1
            elif code == "timeout":
                counts["timeout"] += 1
            elif code in {"unauthorized", "forbidden", "missing_api_key"}:
                counts["auth"] += 1
            else:
                counts["other"] += 1
        return counts


@dataclass(frozen=True)
class OutcomeSummary:
    """一次运行的运行侧汇总，便于页面直接展示。"""

    total: int
    success: int
    empty_response: int
    timeout: int
    auth: int
    other: int


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
    output_requirement = _clean(task.get("output_requirement") or task.get("expected_capability"))
    lines.append(f"【输出要求】{output_requirement or _OUTPUT_HINT}")
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

    # 兜底：即便某个 provider 把「HTTP 成功但空回答」标成功，运行侧也不当成功。
    # mock 始终有占位内容，不受影响。
    run_status = result.status
    success = result.ok
    error_code = result.error_code
    error_message = result.error_message
    if success and result.status != STATUS_MOCK and not answer.strip():
        run_status = STATUS_FAILED
        success = False
        error_code = error_code or ERROR_EMPTY_RESPONSE
        error_message = error_message or "模型返回成功但回答为空。"

    return RunOutcome(
        case_id=str(task.get("case_id", "")),
        task_type=str(task.get("task_type", "")),
        provider=result.provider,
        model_id=model_id,
        run_status=run_status,
        success=success,
        answer_text=answer,
        answer_length=len(answer),
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        http_status=result.http_status,
        trace_id=result.trace_id,
        error_code=error_code,
        error_message=error_message,
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
    progress_callback: Callable[[int, int, str, str], None] | None = None,
    **kwargs: Any,
) -> CompareRunResult:
    """对多个模型各自跑同一组任务，汇总成一个 CompareRunResult（共享 run_id）。

    去重并保序处理 model_ids；对每个模型的每道任务调用 run_single，任一调用失败只影响
    该 (模型, 任务) 的 RunOutcome，不中断整体。模型列表为空时 outcomes 为空。

    progress_callback（可选）在每道生成开始前回调 (已完成数, 总数, 当前模型, 当前任务)，
    供页面做逐条进度反馈；不传则行为不变。回调异常被吞掉，不影响运行。
    """
    unique_models = _dedupe_preserve_order(model_ids)
    rid = run_id or generate_run_id()
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    pairs = [(model_id, task) for model_id in unique_models for task in tasks]
    total = len(pairs)
    outcomes: list[RunOutcome] = []
    for index, (model_id, task) in enumerate(pairs):
        if progress_callback is not None:
            _safe_progress(progress_callback, index, total, model_id, str(task.get("case_id", "")))
        outcomes.append(
            run_single(provider, model_id, task, temperature=temperature, max_tokens=max_tokens, **kwargs)
        )
    if progress_callback is not None and total:
        _safe_progress(progress_callback, total, total, "", "")
    return CompareRunResult(
        run_id=rid,
        provider=getattr(provider, "name", ""),
        model_ids=tuple(unique_models),
        mode=mode,
        created_at=datetime.now().isoformat(timespec="seconds"),
        outcomes=tuple(outcomes),
    )


def summarize_outcomes(outcomes: Sequence[RunOutcome]) -> OutcomeSummary:
    """把 outcomes 聚合为五档计数（成功 / 空回答 / 超时 / 鉴权 / 其他）。"""
    counts = {"success": 0, "empty_response": 0, "timeout": 0, "auth": 0, "other": 0}
    for o in outcomes:
        if o.success:
            counts["success"] += 1
            continue
        code = o.error_code or ""
        if code == ERROR_EMPTY_RESPONSE:
            counts["empty_response"] += 1
        elif code == "timeout":
            counts["timeout"] += 1
        elif code in {"unauthorized", "forbidden", "missing_api_key"}:
            counts["auth"] += 1
        else:
            counts["other"] += 1
    return OutcomeSummary(
        total=len(outcomes),
        success=counts["success"],
        empty_response=counts["empty_response"],
        timeout=counts["timeout"],
        auth=counts["auth"],
        other=counts["other"],
    )


def default_task_selection(tasks: Sequence[Any]) -> list[Any]:
    """默认只选 1 道活跃任务，避免「模型数 × 任务数」一次跑满导致长时间无反馈。

    优先选第一条 status=active 的任务；没有任何 status 字段或无活跃任务时，回退到首条，
    保证页面始终有一个可运行的默认项。
    """
    items = list(tasks or [])
    if not items:
        return []
    for item in items:
        if _task_status(item) == "active":
            return [item]
    return items[:1]


def _task_status(task: Any) -> str:
    getter = getattr(task, "get", None)
    raw = getter("status") if callable(getter) else getattr(task, "status", None)
    return _clean(raw).lower()


def _safe_progress(callback, done: int, total: int, model_id: str, case_id: str) -> None:
    try:
        callback(done, total, model_id, case_id)
    except Exception:
        pass


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


def initialize_run_queue(
    run_id: str,
    provider: str,
    queue_items: Sequence[Mapping[str, Any]],
    *,
    db_path: Path | None = None,
) -> bool:
    """开始调用模型前写入完整队列，用于页面中断后的恢复。"""
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        ensure_recoverable_queue_tables(path)
        repo = Repository(path)
        existing = _safe_list_df(repo, "live_run_queue")
        if not existing.empty and "run_id" in existing.columns:
            if not existing[existing["run_id"].astype(str) == str(run_id)].empty:
                return True
        rows: list[dict[str, Any]] = []
        for item in queue_items or []:
            task = item.get("task") or {}
            case_id = _clean(item.get("case_id")) or _clean(task.get("case_id"))
            model_id = _clean(item.get("model_id"))
            if not case_id or not model_id:
                continue
            rows.append({
                "run_id": str(run_id),
                "case_id": case_id,
                "task_type": _clean(task.get("task_type")),
                "model_id": model_id,
                "provider": str(provider or ""),
                "status": "queued",
                "attempt_count": 0,
            })
        if not rows:
            return False
        repo.bulk_insert("live_run_queue", rows)
        return True
    except Exception:
        return False


def mark_run_queue_item_running(
    run_id: str,
    case_id: str,
    model_id: str,
    *,
    db_path: Path | None = None,
) -> bool:
    """将一条模型回答队列项标记为运行中，并增加尝试次数。"""
    return _update_run_queue_item(
        run_id,
        case_id,
        model_id,
        {"status": "running"},
        increment_attempt=True,
        db_path=db_path,
    )


def persist_run_outcome(
    run_id: str,
    mode: str,
    outcome: RunOutcome,
    *,
    db_path: Path | None = None,
) -> bool:
    """逐条写入模型回答，并同步 live_run_queue 状态。"""
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        repo = Repository(path)
        existing = _find_run_response_row(repo, run_id, outcome.case_id, outcome.model_id)
        row = _run_outcome_row(run_id, mode, outcome)
        if existing is None:
            repo.insert("live_run_responses", row)
        else:
            row_id = _as_int(existing.get("id"))
            if row_id is not None and _should_update_existing_run_outcome(existing, outcome):
                repo.update("live_run_responses", row_id, row)
        _update_run_queue_item(
            run_id,
            outcome.case_id,
            outcome.model_id,
            {
                "status": "success" if outcome.success else "failed",
                "error_code": outcome.error_code,
                "error_message": outcome.error_message,
            },
            db_path=path,
        )
        return True
    except Exception:
        return False


def load_run_queue(run_id: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    """读取指定 run_id 的可恢复模型回答队列。"""
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return []
        ensure_recoverable_queue_tables(path)
        rows = Repository(path).list_df("live_run_queue", order_by="id")
        if rows.empty or "run_id" not in rows.columns:
            return []
        matched = rows[rows["run_id"].astype(str) == str(run_id)]
        return matched.to_dict("records")
    except Exception:
        return []


def summarize_run_queue(run_id: str, *, db_path: Path | None = None) -> dict[str, int]:
    rows = load_run_queue(run_id, db_path=db_path)
    counts = {"total": len(rows), "queued": 0, "running": 0, "success": 0, "failed": 0, "skipped": 0}
    for row in rows:
        status = str(row.get("status") or "queued").strip().lower()
        if status in counts:
            counts[status] += 1
    counts["unfinished"] = counts["queued"] + counts["running"]
    return counts


def queue_items_for_status(
    run_id: str,
    statuses: set[str],
    *,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    wanted = {str(status).strip().lower() for status in statuses}
    return [
        row for row in load_run_queue(run_id, db_path=db_path)
        if str(row.get("status") or "").strip().lower() in wanted
    ]


def latest_run_queue(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    """返回最近一次模型回答队列，供页面 session 丢失时恢复提示。"""
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return []
        ensure_recoverable_queue_tables(path)
        frame = Repository(path).list_df("live_run_queue", order_by="id")
        if frame.empty or "run_id" not in frame.columns:
            return []
        latest = str(frame.iloc[-1]["run_id"])
        return frame[frame["run_id"].astype(str) == latest].to_dict("records")
    except Exception:
        return []


def restore_compare_result_from_db(run_id: str, *, db_path: Path | None = None) -> CompareRunResult | None:
    """从已落库模型回答重建结果对象；不重新调用模型。"""
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return None
        repo = Repository(path)
        responses = repo.list_df("live_run_responses", order_by="id")
        if responses.empty or "run_id" not in responses.columns:
            return None
        matched = responses[responses["run_id"].astype(str) == str(run_id)]
        if matched.empty:
            return None
        outcomes = tuple(_run_outcome_from_row(row) for row in matched.to_dict("records"))
        queue = load_run_queue(run_id, db_path=path)
        model_ids = _dedupe_preserve_order(
            [str(row.get("model_id") or "") for row in queue]
            or [outcome.model_id for outcome in outcomes]
        )
        provider = str(matched.iloc[0].get("provider") or "")
        mode = str(matched.iloc[0].get("run_mode") or "live")
        created_at = str(matched.iloc[0].get("created_at") or datetime.now().isoformat(timespec="seconds"))
        return CompareRunResult(
            run_id=str(run_id),
            provider=provider,
            model_ids=tuple(model_ids),
            mode=mode,
            created_at=created_at,
            outcomes=outcomes,
        )
    except Exception:
        return None


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


def _safe_list_df(repo, table: str):
    try:
        return repo.list_df(table, order_by="id")
    except Exception:
        import pandas as pd

        return pd.DataFrame()


def _run_outcome_row(run_id: str, mode: str, outcome: RunOutcome) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "case_id": outcome.case_id,
        "task_type": outcome.task_type,
        "provider": outcome.provider,
        "model_name": outcome.model_id,
        "run_mode": mode,
        "run_status": outcome.run_status,
        "answer_text": outcome.answer_text,
        "answer_length": outcome.answer_length,
        "latency_ms": outcome.latency_ms,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "total_tokens": outcome.total_tokens,
        "http_status": outcome.http_status,
        "trace_id": outcome.trace_id,
        "error_code": outcome.error_code,
        "error_message": outcome.error_message,
    }


def _find_run_response_row(repo, run_id: str, case_id: str, model_id: str) -> dict[str, Any] | None:
    rows = _safe_list_df(repo, "live_run_responses")
    if rows.empty:
        return None
    required = {"run_id", "case_id", "model_name"}
    if not required.issubset(rows.columns):
        return None
    matched = rows[
        (rows["run_id"].astype(str) == str(run_id))
        & (rows["case_id"].astype(str) == str(case_id))
        & (rows["model_name"].astype(str) == str(model_id))
    ]
    if matched.empty:
        return None
    return matched.iloc[0].to_dict()


def _should_update_existing_run_outcome(existing: Mapping[str, Any], outcome: RunOutcome) -> bool:
    existing_status = str(existing.get("run_status") or "").strip().lower()
    return existing_status != "success" or outcome.success


def _update_run_queue_item(
    run_id: str,
    case_id: str,
    model_id: str,
    changes: dict[str, Any],
    *,
    increment_attempt: bool = False,
    db_path: Path | None = None,
) -> bool:
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        ensure_recoverable_queue_tables(path)
        repo = Repository(path)
        rows = repo.list_df("live_run_queue", order_by="id")
        if rows.empty:
            return False
        matched = rows[
            (rows["run_id"].astype(str) == str(run_id))
            & (rows["case_id"].astype(str) == str(case_id))
            & (rows["model_id"].astype(str) == str(model_id))
        ]
        if matched.empty:
            return False
        row = matched.iloc[0].to_dict()
        row_id = _as_int(row.get("id"))
        if row_id is None:
            return False
        payload = dict(changes)
        if increment_attempt:
            payload["attempt_count"] = int(row.get("attempt_count") or 0) + 1
        repo.update("live_run_queue", row_id, payload)
        return True
    except Exception:
        return False


def _run_outcome_from_row(row: Mapping[str, Any]) -> RunOutcome:
    status = str(row.get("run_status") or "").strip().lower()
    return RunOutcome(
        case_id=str(row.get("case_id") or ""),
        task_type=str(row.get("task_type") or ""),
        provider=str(row.get("provider") or ""),
        model_id=str(row.get("model_name") or ""),
        run_status=str(row.get("run_status") or ""),
        success=status in {"success", STATUS_MOCK},
        answer_text=str(row.get("answer_text") or ""),
        answer_length=int(row.get("answer_length") or 0),
        latency_ms=_as_int(row.get("latency_ms")),
        input_tokens=_as_int(row.get("input_tokens")),
        output_tokens=_as_int(row.get("output_tokens")),
        total_tokens=_as_int(row.get("total_tokens")),
        http_status=_as_int(row.get("http_status")),
        trace_id=row.get("trace_id"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
    )


def _as_int(value: Any) -> int | None:
    try:
        if value is None or str(value) == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text
