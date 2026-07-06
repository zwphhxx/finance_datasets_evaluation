"""真实模型评测的 LLM-as-judge 评分编排（PR-35）。

在 eval_runner 生成被评测模型回答之后，由「裁判模型」对照该题 Gold Answer 与 Rubric
各维度打分，产出**机器建议分**。建议分需经人工复核（review_status: pending → confirmed）
才计入结果，本模块不自动定稿、不下「哪个模型最好」的结论。

边界（重要）：
  - 裁判模型可以看到 Gold Answer（评分必需）；这与「被评测模型绝不可见 Gold」是两条独立链路，
    被评测模型的 prompt 仍由 eval_runner.build_messages 构造，白名单不含 Gold。
  - 无 API Key（mock provider）时不产生任何真实分数：各维度留空、judge_status=mock。
  - 评分写入独立表 live_run_scores，与 seed 的 score_records 分离，不污染既有分析页。
本模块不依赖 Streamlit 运行时，便于单元测试。
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.models.base import ModelProvider, STATUS_FAILED, STATUS_MOCK, STATUS_SUCCESS
from app.services import model_display as md

# Fixed judge model for scoring (PR-LOGIC1)
DEFAULT_JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Pro"
PROJECT_DISPLAY_NAME = "财务/法律/投行场景大模型对比评测"
SCORE_EXPORT_TYPE = "confirmed_score_export"
SCORE_EXPORT_SCHEMA_VERSION = 1
DEMO_CONFIRMED_SCORE_EXPORT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "confirmed_score_exports" / "demo_confirmed_scores.json"
)
DEFAULT_JUDGE_RETRY_DELAYS: tuple[float, float] = (3.0, 8.0)
RETRYABLE_JUDGE_ERRORS = {
    "timeout",
    "rate_limited",
    "service_unavailable",
    "gateway_timeout",
    "connection_error",
}
NON_RETRYABLE_JUDGE_ERRORS = {
    "unauthorized",
    "bad_request",
    "not_found",
    "missing_api_key",
    "judge_parse_error",
    "invalid_response",
}

SCORE_EXPORT_COLUMNS = [
    "score_run_id",
    "run_id",
    "case_id",
    "task_type",
    "eval_model",
    "judge_provider",
    "judge_model",
    "judge_mode",
    "judge_status",
    "accuracy_score",
    "reasoning_score",
    "coverage_score",
    "evidence_score",
    "expression_score",
    "total_score",
    "rationale",
    "review_note",
    "review_status",
    "status",
    "created_at",
    "updated_at",
]
SCORE_IMPORT_REQUIRED_FIELDS = {
    "score_run_id",
    "run_id",
    "case_id",
    "eval_model",
    "judge_model",
    "judge_status",
    "total_score",
    "review_status",
}
SCORE_IMPORT_ALLOWED_REVIEW_STATUS = {"confirmed", "pending", "skipped"}
SENSITIVE_IMPORT_FIELDS = {
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "headers",
    "request_headers",
    "response_headers",
}

_JUDGE_SYSTEM_PROMPT = (
    "你是金融与专业尽调领域的资深评审。你的任务是依据给定的 Gold Answer 与评分量表（Rubric），"
    "对「被评测模型的回答」逐维度打分。"
    "请基于证据与量表客观评分，对照 Gold Answer 的核心结论、必须覆盖点与不可接受错误，"
    "不要拔高也不要苛责，不要编造 Gold Answer 中没有的标准。"
    "每个维度给出 0 到该维度满分之间的整数分，并给出一句简短依据。"
    "你只输出评分，不改写或续写被评测回答，也不替用户下最终结论；分数仅为机器建议，仍需人工复核。"
)

# 要求裁判严格输出的 JSON 结构说明（仅结构，不含任何示例分数，避免诱导造数）。
_JUDGE_OUTPUT_INSTRUCTION = (
    "请只输出一个 JSON 对象，不要包含 Markdown 代码块或额外说明，结构如下："
    '{{"scores": {{{score_keys}}}, "rationale": {{{rationale_keys}}}, "review_note": "整体复核提示"}}。'
    "scores 的每个值为该维度的整数得分（0 到满分之间），rationale 为对应维度的简短打分依据。"
)


@dataclass(frozen=True)
class ScoreOutcome:
    """单个（被评测模型 × 题）的裁判评分结果。"""

    case_id: str
    task_type: str
    eval_model: str
    judge_provider: str
    judge_model: str
    judge_status: str  # success / failed / mock
    scores: Mapping[str, int | None] = field(default_factory=dict)
    total_score: int | None = None
    rationale: Mapping[str, str] = field(default_factory=dict)
    review_note: str = ""
    review_status: str = "pending"  # pending / confirmed
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    trace_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0

    @property
    def ok(self) -> bool:
        return self.judge_status == STATUS_SUCCESS


@dataclass(frozen=True)
class ScoreResult:
    """一次评分运行（可覆盖多模型多题）的汇总。"""

    score_run_id: str
    run_id: str
    judge_provider: str
    judge_model: str
    mode: str  # live / mock
    created_at: str
    outcomes: Sequence[ScoreOutcome] = field(default_factory=tuple)

    @property
    def scored_count(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)


@dataclass(frozen=True)
class _JudgeParse:
    ok: bool
    scores: dict
    total: int | None
    rationale: dict
    review_note: str
    error: str = ""


def generate_score_run_id() -> str:
    """生成本次评分运行的 score_run_id：时间戳 + 短随机后缀。"""
    return f"SCORE-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def build_judge_messages(
    task: Mapping[str, Any],
    answer_text: str,
    gold: Mapping[str, Any],
    dimensions: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """构造发送给裁判模型的消息：任务 + 被评测回答 + Gold 参考 + Rubric 维度。"""
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

    lines.append("【被评测模型的回答】\n" + (answer_text or "（空）"))

    gold_block = _format_gold(gold)
    if gold_block:
        lines.append("【Gold Answer 参考（仅供你评分，请勿照抄）】\n" + gold_block)

    lines.append("【评分量表】\n" + _format_rubric(dimensions))

    score_keys = ", ".join(f'"{d["field"]}": 整数' for d in dimensions)
    rationale_keys = ", ".join(f'"{d["field"]}": "依据"' for d in dimensions)
    lines.append(
        "【输出要求】"
        + _JUDGE_OUTPUT_INSTRUCTION.format(score_keys=score_keys, rationale_keys=rationale_keys)
    )

    return [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(lines)},
    ]


def parse_judge_output(text: str, dimensions: Sequence[Mapping[str, Any]]) -> _JudgeParse:
    """从裁判输出中稳健解析 JSON，逐维度 clamp 到 [0, 满分]，total 由各维度求和。

    任一维度缺失或非数值即视为解析失败（ok=False），不臆造分数。
    """
    payload = _extract_json_object(text)
    if payload is None:
        return _JudgeParse(False, {}, None, {}, "", error="未能从裁判输出中解析出 JSON 评分。")

    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, dict):
        return _JudgeParse(False, {}, None, {}, "", error="裁判输出缺少 scores 字段。")

    scores: dict[str, int] = {}
    for dim in dimensions:
        field_name = dim["field"]
        full_mark = int(dim.get("full_mark") or 0)
        value = raw_scores.get(field_name)
        number = _as_number(value)
        if number is None:
            return _JudgeParse(
                False, {}, None, {}, "", error=f"裁判输出缺少或无法识别维度 {field_name} 的分数。"
            )
        scores[field_name] = max(0, min(full_mark, int(round(number))))

    rationale_raw = payload.get("rationale")
    rationale = {
        str(k): _clean(v)
        for k, v in rationale_raw.items()
        if isinstance(rationale_raw, dict)
    } if isinstance(rationale_raw, dict) else {}

    total = sum(scores.values())
    review_note = _clean(payload.get("review_note"))
    return _JudgeParse(True, scores, total, rationale, review_note)


def score_single(
    provider: ModelProvider,
    judge_model_id: str,
    task: Mapping[str, Any],
    answer_text: str,
    gold: Mapping[str, Any],
    dimensions: Sequence[Mapping[str, Any]],
    *,
    eval_model: str = "",
    temperature: float = 0.0,
    max_tokens: int = 1024,
    retry_delays: Sequence[float] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    **kwargs: Any,
) -> ScoreOutcome:
    """对单条（被评测回答）做一次裁判评分，转为统一 ScoreOutcome（不抛异常给调用方）。"""
    case_id = str(task.get("case_id", ""))
    task_type = str(task.get("task_type", ""))
    base = dict(
        case_id=case_id,
        task_type=task_type,
        eval_model=eval_model,
        judge_provider=getattr(provider, "name", ""),
        judge_model=judge_model_id,
    )

    # mock provider：不发起真实调用、不产生任何真实分数。
    if getattr(provider, "name", "") == "mock":
        return ScoreOutcome(
            **base,
            judge_status=STATUS_MOCK,
            scores={d["field"]: None for d in dimensions},
            total_score=None,
            review_note="【MOCK 模拟评分】未配置 API Key，未产生真实评分，仅用于打通链路。",
        )

    messages = build_judge_messages(task, answer_text, gold, dimensions)
    delays = tuple(DEFAULT_JUDGE_RETRY_DELAYS if retry_delays is None else retry_delays)
    sleeper = sleep_fn or time.sleep
    retry_count = 0

    while True:
        result = provider.generate_response(
            judge_model_id, messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )
        common = dict(
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            trace_id=result.trace_id,
        )

        if result.ok:
            parsed = parse_judge_output(result.response_text, dimensions)
            if parsed.ok:
                return ScoreOutcome(
                    **base, judge_status=STATUS_SUCCESS,
                    scores=parsed.scores, total_score=parsed.total,
                    rationale=parsed.rationale, review_note=parsed.review_note,
                    retry_count=retry_count, **common,
                )
            error_code = "judge_parse_error"
            error_message = parsed.error
        else:
            error_code = result.error_code or "invalid_response"
            error_message = result.error_message or "裁判评分失败。"

        if _should_retry_judge_error(error_code, retry_count, delays):
            delay = float(delays[retry_count])
            retry_count += 1
            sleeper(delay)
            continue

        return ScoreOutcome(
            **base, judge_status=STATUS_FAILED,
            scores={d["field"]: None for d in dimensions}, total_score=None,
            error_code=error_code,
            error_message=_with_retry_count(error_message, retry_count),
            retry_count=retry_count,
            **common,
        )


def _should_retry_judge_error(error_code: str | None, retry_count: int, delays: Sequence[float]) -> bool:
    code = str(error_code or "").strip().lower()
    return code in RETRYABLE_JUDGE_ERRORS and retry_count < len(delays)


def _with_retry_count(message: str | None, retry_count: int) -> str:
    text = _clean(message) or "裁判评分失败。"
    if retry_count <= 0:
        return text
    suffix = f"已重试 {retry_count} 次。"
    if suffix in text:
        return text
    return f"{text} {suffix}"


def score_compare(
    provider: ModelProvider,
    compare_result,
    gold_map: Mapping[str, Mapping[str, Any]],
    tasks_by_case: Mapping[str, Mapping[str, Any]],
    dimensions: Sequence[Mapping[str, Any]],
    *,
    judge_model_id: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    score_run_id: str | None = None,
    **kwargs: Any,
) -> ScoreResult:
    """对一次多模型对比运行的每条成功回答评分；裁判模型固定为 DEFAULT_JUDGE_MODEL。"""
    sid = score_run_id or generate_score_run_id()
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    # 固定裁判模型，用户不可配置
    judge_model = _clean(judge_model_id) or DEFAULT_JUDGE_MODEL
    outcomes: list[ScoreOutcome] = []
    for outcome in compare_result.outcomes:
        if not outcome.success:
            continue
        task = tasks_by_case.get(outcome.case_id) or {
            "case_id": outcome.case_id,
            "task_type": outcome.task_type,
        }
        gold = gold_map.get(outcome.case_id) or {}
        outcomes.append(
            score_single(
                provider, judge_model, task, outcome.answer_text, gold, dimensions,
                eval_model=outcome.model_id, temperature=temperature, max_tokens=max_tokens, **kwargs,
            )
        )

    return ScoreResult(
        score_run_id=sid,
        run_id=getattr(compare_result, "run_id", ""),
        judge_provider=getattr(provider, "name", ""),
        judge_model=judge_model,
        mode=mode,
        created_at=datetime.now().isoformat(timespec="seconds"),
        outcomes=tuple(outcomes),
    )


def persist_score_result(result: ScoreResult, db_path: Path | None = None) -> bool:
    """尽力将评分结果写入 SQLite live_run_scores；数据库不可用时静默跳过，返回是否成功。

    写入独立的 live_run_scores 表，不触碰 seed 的 score_records。已写入的单条评分会按
    (score_run_id, case_id, eval_model) 去重，避免增量评分和最终汇总重复入库。
    """
    if not result.outcomes:
        return False
    persisted = [
        persist_score_outcome(
            result.score_run_id,
            result.run_id,
            result.judge_provider,
            result.judge_model,
            result.mode,
            outcome,
            db_path=db_path,
        )
        for outcome in result.outcomes
    ]
    return all(persisted)


def persist_score_outcome(
    score_run_id: str,
    run_id: str,
    judge_provider: str,
    judge_model: str,
    mode: str,
    outcome: ScoreOutcome,
    *,
    db_path: Path | None = None,
) -> bool:
    """增量写入单条评分草稿；用于边评分边入库。"""
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        ensure_recoverable_queue_tables(path)
        repo = Repository(path)
        existing = _find_score_outcome_row(repo, score_run_id, outcome.case_id, outcome.eval_model)
        if existing is not None:
            if _should_update_existing_score_outcome(existing, outcome):
                row_id = _as_number(existing.get("id"))
                if row_id is None:
                    _sync_score_queue_from_outcome(score_run_id, outcome, path)
                    return True
                repo.update(
                    "live_run_scores",
                    int(row_id),
                    _score_outcome_row(
                        score_run_id,
                        run_id,
                        judge_provider,
                        judge_model,
                        mode,
                        outcome,
                    ),
                )
            _sync_score_queue_from_outcome(score_run_id, outcome, path)
            return True
        repo.bulk_insert(
            "live_run_scores",
            [
                _score_outcome_row(
                    score_run_id,
                    run_id,
                    judge_provider,
                    judge_model,
                    mode,
                    outcome,
                )
            ],
        )
        _sync_score_queue_from_outcome(score_run_id, outcome, path)
        return True
    except Exception:
        return False


def initialize_score_queue(
    score_run_id: str,
    run_id: str,
    queue_items: Sequence[Any],
    judge_provider: str,
    judge_model: str,
    *,
    db_path: Path | None = None,
) -> bool:
    """开始裁判评分前写入完整评分队列，用于中断恢复。"""
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        ensure_recoverable_queue_tables(path)
        repo = Repository(path)
        existing = _safe_list_df(repo, "live_score_queue")
        if not existing.empty and "score_run_id" in existing.columns:
            if not existing[existing["score_run_id"].astype(str) == str(score_run_id)].empty:
                return True
        rows: list[dict[str, Any]] = []
        for item in queue_items or []:
            case_id = _clean(getattr(item, "case_id", None) or _mapping_get(item, "case_id"))
            eval_model = _clean(getattr(item, "model_id", None) or _mapping_get(item, "eval_model") or _mapping_get(item, "model_id"))
            if not case_id or not eval_model:
                continue
            rows.append({
                "score_run_id": str(score_run_id),
                "run_id": str(run_id or ""),
                "case_id": case_id,
                "task_type": _clean(getattr(item, "task_type", None) or _mapping_get(item, "task_type")),
                "eval_model": eval_model,
                "judge_model": str(judge_model or ""),
                "judge_provider": str(judge_provider or ""),
                "status": "queued",
                "attempt_count": 0,
            })
        if not rows:
            return False
        repo.bulk_insert("live_score_queue", rows)
        return True
    except Exception:
        return False


def mark_score_queue_item_running(
    score_run_id: str,
    case_id: str,
    eval_model: str,
    *,
    db_path: Path | None = None,
) -> bool:
    """将一条评分队列项标记为运行中，并增加尝试次数。"""
    return _update_score_queue_item(
        score_run_id,
        case_id,
        eval_model,
        {"status": "running"},
        increment_attempt=True,
        db_path=db_path,
    )


def load_score_queue(score_run_id: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return []
        ensure_recoverable_queue_tables(path)
        rows = Repository(path).list_df("live_score_queue", order_by="id")
        if rows.empty or "score_run_id" not in rows.columns:
            return []
        matched = rows[rows["score_run_id"].astype(str) == str(score_run_id)]
        return matched.to_dict("records")
    except Exception:
        return []


def summarize_score_queue(score_run_id: str, *, db_path: Path | None = None) -> dict[str, int]:
    rows = load_score_queue(score_run_id, db_path=db_path)
    counts = {"total": len(rows), "queued": 0, "running": 0, "success": 0, "failed": 0, "skipped": 0}
    for row in rows:
        status = str(row.get("status") or "queued").strip().lower()
        if status in counts:
            counts[status] += 1
    counts["unfinished"] = counts["queued"] + counts["running"]
    return counts


def queue_items_for_status(
    score_run_id: str,
    statuses: set[str],
    *,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    wanted = {str(status).strip().lower() for status in statuses}
    return [
        row for row in load_score_queue(score_run_id, db_path=db_path)
        if str(row.get("status") or "").strip().lower() in wanted
    ]


def latest_score_queue(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    try:
        from app.services.dataset_service import database_ready, ensure_recoverable_queue_tables, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return []
        ensure_recoverable_queue_tables(path)
        frame = Repository(path).list_df("live_score_queue", order_by="id")
        if frame.empty or "score_run_id" not in frame.columns:
            return []
        latest = str(frame.iloc[-1]["score_run_id"])
        return frame[frame["score_run_id"].astype(str) == latest].to_dict("records")
    except Exception:
        return []


def restore_score_result_from_db(score_run_id: str, *, db_path: Path | None = None) -> ScoreResult | None:
    """从 live_run_scores 重建已完成评分结果；不重新调用裁判模型。"""
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return None
        frame = Repository(path).list_df("live_run_scores", order_by="id")
        if frame.empty or "score_run_id" not in frame.columns:
            return None
        matched = frame[frame["score_run_id"].astype(str) == str(score_run_id)]
        if matched.empty:
            return None
        first = matched.iloc[0]
        outcomes = tuple(_score_outcome_from_row(row) for row in matched.to_dict("records"))
        return ScoreResult(
            score_run_id=str(score_run_id),
            run_id=str(first.get("run_id") or ""),
            judge_provider=str(first.get("judge_provider") or ""),
            judge_model=str(first.get("judge_model") or DEFAULT_JUDGE_MODEL),
            mode=str(first.get("judge_mode") or "live"),
            created_at=str(first.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            outcomes=outcomes,
        )
    except Exception:
        return None


def _score_outcome_exists(repo, score_run_id: str, case_id: str, eval_model: str) -> bool:
    return _find_score_outcome_row(repo, score_run_id, case_id, eval_model) is not None


def _find_score_outcome_row(repo, score_run_id: str, case_id: str, eval_model: str) -> dict[str, Any] | None:
    try:
        rows = repo.list_df("live_run_scores")
        if rows.empty:
            return None
        required = {"score_run_id", "case_id", "eval_model"}
        if not required.issubset(rows.columns):
            return None
        matched = rows[
            (rows["score_run_id"].astype(str) == str(score_run_id))
            & (rows["case_id"].astype(str) == str(case_id))
            & (rows["eval_model"].astype(str) == str(eval_model))
        ]
        if matched.empty:
            return None
        return matched.iloc[0].to_dict()
    except Exception:
        return None


def _should_update_existing_score_outcome(existing: Mapping[str, Any], outcome: ScoreOutcome) -> bool:
    review_status = str(existing.get("review_status") or "pending").strip().lower()
    if review_status in {"confirmed", "skipped"}:
        return False
    existing_status = str(existing.get("judge_status") or "").strip().lower()
    return existing_status != STATUS_SUCCESS


def _score_outcome_row(
    score_run_id: str,
    run_id: str,
    judge_provider: str,
    judge_model: str,
    mode: str,
    outcome: ScoreOutcome,
) -> dict[str, Any]:
    row = {
        "score_run_id": score_run_id,
        "run_id": run_id,
        "case_id": outcome.case_id,
        "task_type": outcome.task_type,
        "eval_model": outcome.eval_model,
        "judge_provider": outcome.judge_provider or judge_provider,
        "judge_model": outcome.judge_model or judge_model,
        "judge_mode": mode,
        "judge_status": outcome.judge_status,
        "total_score": outcome.total_score,
        "rationale": json.dumps(dict(outcome.rationale), ensure_ascii=False) if outcome.rationale else None,
        "review_note": outcome.review_note or None,
        "review_status": outcome.review_status or "pending",
        "latency_ms": outcome.latency_ms,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "total_tokens": outcome.total_tokens,
        "trace_id": outcome.trace_id,
        "error_code": outcome.error_code,
        "error_message": outcome.error_message,
    }
    for field_name, value in outcome.scores.items():
        row[field_name] = value
    return row


def confirm_score_review(
    row_id: int,
    edited_scores: Mapping[str, Any],
    review_note: str = "",
    *,
    db_path: Path | None = None,
) -> bool:
    """人工复核确认：写入修订后的各维度分与总分，并将 review_status 置为 confirmed。"""
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        changes: dict[str, Any] = {"review_status": "confirmed"}
        total = 0
        for field_name, value in edited_scores.items():
            number = _as_number(value)
            score = 0 if number is None else int(round(number))
            changes[field_name] = score
            total += score
        changes["total_score"] = total
        if review_note:
            changes["review_note"] = review_note
        Repository(path).update("live_run_scores", row_id, changes)
        return True
    except Exception:
        return False


def confirm_score_reviews_bulk(
    row_ids: Sequence[int],
    review_note: str = "",
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """批量确认低风险评分草稿；仅处理 live_run_scores 中仍为 pending 的记录。"""
    def _result(confirmed_ids: list[int], failed_ids: list[int], reason: str = "") -> dict[str, Any]:
        confirmed_count = len(confirmed_ids)
        failed_count = len(failed_ids)
        summary = f"已确认 {confirmed_count} 条评分。"
        if failed_count:
            summary += f" {failed_count} 条未确认。"
        if reason:
            summary += f" {reason}"
        return {
            "confirmed": confirmed_count,
            "confirmed_count": confirmed_count,
            "confirmed_ids": confirmed_ids,
            "failed": failed_ids,
            "failed_count": failed_count,
            "failed_ids": failed_ids,
            "reason": reason,
            "summary": summary,
        }

    unique_ids: list[int] = []
    for row_id in row_ids:
        try:
            numeric_id = int(row_id)
        except (TypeError, ValueError):
            continue
        if numeric_id not in unique_ids:
            unique_ids.append(numeric_id)
    if not unique_ids:
        return _result([], [], "没有可确认的评分。")

    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return _result([], unique_ids, "SQLite 数据层不可用。")
        repo = Repository(path)
        rows = repo.list_df("live_run_scores")
        if rows.empty or "id" not in rows.columns:
            return _result([], unique_ids, "未找到评分草稿。")

        id_set = set(unique_ids)
        valid_ids: list[int] = []
        for _, row in rows.iterrows():
            try:
                row_id = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if row_id not in id_set:
                continue
            judge_status = str(row.get("judge_status") or "").strip().lower()
            review_status = str(row.get("review_status") or "pending").strip().lower()
            if judge_status == STATUS_SUCCESS and review_status == "pending":
                valid_ids.append(row_id)

        changes: dict[str, Any] = {"review_status": "confirmed"}
        if review_note:
            changes["review_note"] = review_note
        for row_id in valid_ids:
            repo.update("live_run_scores", row_id, changes)
        failed = [row_id for row_id in unique_ids if row_id not in set(valid_ids)]
        reason = "" if not failed else "仅待确认且裁判成功的评分支持批量确认。"
        return _result(valid_ids, failed, reason)
    except Exception:
        return _result([], unique_ids, "批量确认失败。")


def skip_score_review(
    row_id: int,
    review_note: str = "",
    *,
    db_path: Path | None = None,
) -> bool:
    """标记评分草稿为暂不采用；记录保留，但不会进入正式结论。"""
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        changes: dict[str, Any] = {"review_status": "skipped"}
        if review_note:
            changes["review_note"] = review_note
        Repository(path).update("live_run_scores", row_id, changes)
        return True
    except Exception:
        return False


def is_mock_score(result: ScoreResult) -> bool:
    return result.mode == "mock" or any(o.judge_status == STATUS_MOCK for o in result.outcomes)


def load_score_rows(score_run_id: str, db_path: Path | None = None) -> list[dict]:
    """读取某次评分运行已落库的行（含主键 id），供人工复核改分使用；不可用时返回空列表。"""
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return []
        frame = Repository(path).list_df("live_run_scores")
        if frame.empty or "score_run_id" not in frame.columns:
            return []
        return frame[frame["score_run_id"] == score_run_id].to_dict("records")
    except Exception:
        return []


def load_score_row_for_case(score_run_id: str, case_id: str, eval_model: str, db_path: Path | None = None) -> dict | None:
    """读取某次评分运行中指定 (case_id, eval_model) 的评分行（含主键 id），无则返回 None。"""
    rows = load_score_rows(score_run_id, db_path)
    target_case = str(case_id)
    target_model = str(eval_model)
    for row in rows:
        if (
            str(row.get("case_id")) == target_case
            and str(row.get("eval_model")) == target_model
            and row.get("judge_status") == "success"
        ):
            return row
    return None


def load_exportable_score_rows(
    *,
    include_pending: bool = False,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """读取可导出的真实评分行。

    默认只导出 review_status=confirmed 且 judge_status=success 的真实运行评分；
    include_pending=True 时额外包含 pending 草稿，便于演示环境迁移未处理批次。
    暂不采用记录、seed 模型和 inactive 行始终不导出。
    """
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return []
        frame = Repository(path).list_df("live_run_scores")
        if frame.empty:
            return []

        rows = frame.copy()
        if "judge_status" in rows.columns:
            rows = rows[rows["judge_status"].astype(str).str.strip().str.lower() == STATUS_SUCCESS]
        if "status" in rows.columns:
            rows = rows[rows["status"].astype(str).str.strip().str.lower() != "inactive"]
        if "eval_model" in rows.columns:
            rows = rows[~rows["eval_model"].apply(md.is_seed_model)]
        allowed_statuses = {"confirmed", "pending"} if include_pending else {"confirmed"}
        if "review_status" in rows.columns:
            rows = rows[rows["review_status"].astype(str).str.strip().str.lower().isin(allowed_statuses)]
        else:
            return []
        if "id" in rows.columns:
            rows = rows.sort_values("id")
        return [_score_export_row(row.to_dict()) for _, row in rows.iterrows()]
    except Exception:
        return []


def build_score_export_payload(rows: Sequence[Mapping[str, Any]], *, include_pending: bool = False) -> dict[str, Any]:
    """构造项目内历史评分导出 payload；不包含 API Key 或请求头。"""
    clean_rows = [_score_export_row(dict(row)) for row in rows]
    return {
        "export_type": SCORE_EXPORT_TYPE,
        "schema_version": SCORE_EXPORT_SCHEMA_VERSION,
        "project_name": PROJECT_DISPLAY_NAME,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "scope": "confirmed_and_pending" if include_pending else "confirmed",
        "row_count": len(clean_rows),
        "records": clean_rows,
    }


def export_score_payload(
    *,
    include_pending: bool = False,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """读取并构造历史评分导出 payload。"""
    rows = load_exportable_score_rows(include_pending=include_pending, db_path=db_path)
    return build_score_export_payload(rows, include_pending=include_pending)


def serialize_score_export_payload(payload: Mapping[str, Any]) -> str:
    """序列化导出 payload 为 JSON 文本。"""
    return json.dumps(_jsonable(payload), ensure_ascii=False, indent=2)


def parse_score_import_content(file_name: str, content: bytes | str) -> dict[str, Any]:
    """解析项目导出的历史评分文件，返回 rows/errors。

    JSON 需带 confirmed_score_export 导出标识；CSV 需至少包含必需字段。
    """
    name = str(file_name or "").strip().lower()
    raw = content.decode("utf-8-sig") if isinstance(content, (bytes, bytearray)) else str(content or "")
    if not raw.strip():
        return {"ok": False, "rows": [], "errors": ["文件为空。"]}

    if name.endswith(".json"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "rows": [], "errors": ["JSON 文件无法解析。"]}
        if not isinstance(payload, Mapping) or payload.get("export_type") != SCORE_EXPORT_TYPE:
            return {"ok": False, "rows": [], "errors": ["该 JSON 不是项目导出的历史评分文件。"]}
        if int(payload.get("schema_version") or 0) != SCORE_EXPORT_SCHEMA_VERSION:
            return {"ok": False, "rows": [], "errors": ["评分文件版本不受支持。"]}
        rows = payload.get("records")
        if not isinstance(rows, list):
            return {"ok": False, "rows": [], "errors": ["导出文件缺少 records。"]}
        return validate_score_import_rows(rows)

    if name.endswith(".csv"):
        try:
            rows = list(csv.DictReader(io.StringIO(raw)))
        except csv.Error:
            return {"ok": False, "rows": [], "errors": ["CSV 文件无法解析。"]}
        return validate_score_import_rows(rows)

    return {"ok": False, "rows": [], "errors": ["仅支持导入 JSON 或 CSV 文件。"]}


def validate_score_import_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """校验并标准化历史评分导入行。"""
    errors: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    if not rows:
        return {"ok": False, "rows": [], "errors": ["文件中没有评分记录。"]}

    for index, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, Mapping):
            errors.append(f"第 {index} 行不是有效记录。")
            continue
        row = {str(key).strip(): value for key, value in raw_row.items() if str(key).strip()}
        sensitive = sorted({key.lower() for key in row} & SENSITIVE_IMPORT_FIELDS)
        if sensitive:
            errors.append(f"第 {index} 行包含敏感字段：{', '.join(sensitive)}。")
            continue
        missing = sorted(field for field in SCORE_IMPORT_REQUIRED_FIELDS if not _clean(row.get(field)))
        if missing:
            errors.append(f"第 {index} 行缺少必要字段：{', '.join(missing)}。")
            continue
        if md.is_seed_model(row.get("eval_model")):
            errors.append(f"第 {index} 行为示例模型记录，不能导入真实评分表。")
            continue
        review_status = _clean(row.get("review_status")).lower()
        if review_status not in SCORE_IMPORT_ALLOWED_REVIEW_STATUS:
            errors.append(f"第 {index} 行 review_status 不支持：{review_status or '空'}。")
            continue
        judge_status = _clean(row.get("judge_status")).lower()
        if judge_status != STATUS_SUCCESS:
            errors.append(f"第 {index} 行裁判状态不是 success，不能导入。")
            continue
        normalized_rows.append(_normalize_import_score_row(row))

    return {"ok": bool(normalized_rows) and not errors, "rows": normalized_rows, "errors": errors}


def import_score_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    duplicate_action: str = "skip",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """导入历史评分到 live_run_scores。

    duplicate_action:
      - skip: 按 (score_run_id, case_id, eval_model) 跳过重复记录；
      - update: 更新已有记录；
      - cancel: 不执行导入。
    """
    if duplicate_action == "cancel":
        return _import_result(0, 0, 0, ["已取消导入。"])
    if duplicate_action not in {"skip", "update"}:
        return _import_result(0, 0, 0, ["重复记录处理方式不支持。"])

    validation = validate_score_import_rows(rows)
    valid_rows = validation.get("rows") or []
    errors = list(validation.get("errors") or [])
    if not valid_rows:
        return _import_result(0, 0, 0, errors or ["没有可导入的评分记录。"])

    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return _import_result(0, 0, 0, ["SQLite 数据层不可用。"])
        repo = Repository(path)
        existing = repo.list_df("live_run_scores")
        existing_by_key: dict[tuple[str, str, str], int] = {}
        if not existing.empty:
            for _, row in existing.iterrows():
                key = _score_unique_key(row)
                if all(key):
                    existing_by_key[key] = int(row.get("id"))

        imported = 0
        updated = 0
        skipped = 0
        for row in valid_rows:
            key = _score_unique_key(row)
            existing_id = existing_by_key.get(key)
            payload = {column: row.get(column) for column in SCORE_EXPORT_COLUMNS if column in row}
            payload.setdefault("status", "active")
            if existing_id is None:
                payload.pop("updated_at", None)
                new_id = repo.insert("live_run_scores", payload)
                existing_by_key[key] = new_id
                imported += 1
                continue
            if duplicate_action == "skip":
                skipped += 1
                continue
            changes = {
                key_name: value
                for key_name, value in payload.items()
                if key_name not in {"created_at", "updated_at"}
            }
            repo.update("live_run_scores", existing_id, changes)
            updated += 1
        return _import_result(imported, updated, skipped, errors)
    except Exception:
        return _import_result(0, 0, 0, ["导入失败：请检查 SQLite 数据层是否已初始化。"])


def load_demo_score_export_payload(path: Path | None = None) -> dict[str, Any]:
    """Load the committed demo score export payload, returning an empty valid payload if absent."""
    source = path or DEMO_CONFIRMED_SCORE_EXPORT_PATH
    if not source.exists():
        return build_score_export_payload([])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return build_score_export_payload([])
    if not isinstance(payload, Mapping):
        return build_score_export_payload([])
    return dict(payload)


def import_demo_confirmed_scores(
    *,
    path: Path | None = None,
    duplicate_action: str = "skip",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Restore the committed demo confirmed-score export into live_run_scores."""
    payload = load_demo_score_export_payload(path)
    if payload.get("export_type") != SCORE_EXPORT_TYPE:
        return _import_result(0, 0, 0, ["演示评分文件不是项目导出的评分文件。"])
    records = payload.get("records")
    if not isinstance(records, list):
        return _import_result(0, 0, 0, ["演示评分文件缺少 records。"])
    return import_score_rows(records, duplicate_action=duplicate_action, db_path=db_path)


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _score_export_row(row: Mapping[str, Any]) -> dict[str, Any]:
    exported = {
        column: _jsonable(row.get(column))
        for column in SCORE_EXPORT_COLUMNS
        if column in row
    }
    rationale = exported.get("rationale")
    if isinstance(rationale, str):
        try:
            parsed = json.loads(rationale)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            exported["rationale"] = _jsonable(dict(parsed))
    return exported


def _sync_score_queue_from_outcome(score_run_id: str, outcome: ScoreOutcome, db_path: Path) -> bool:
    return _update_score_queue_item(
        score_run_id,
        outcome.case_id,
        outcome.eval_model,
        {
            "status": "success" if outcome.judge_status == STATUS_SUCCESS else "failed",
            "error_code": outcome.error_code,
            "error_message": outcome.error_message,
        },
        db_path=db_path,
    )


def _update_score_queue_item(
    score_run_id: str,
    case_id: str,
    eval_model: str,
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
        rows = repo.list_df("live_score_queue", order_by="id")
        if rows.empty:
            return False
        matched = rows[
            (rows["score_run_id"].astype(str) == str(score_run_id))
            & (rows["case_id"].astype(str) == str(case_id))
            & (rows["eval_model"].astype(str) == str(eval_model))
        ]
        if matched.empty:
            return False
        row = matched.iloc[0].to_dict()
        row_id = _as_number(row.get("id"))
        if row_id is None:
            return False
        payload = dict(changes)
        if increment_attempt:
            payload["attempt_count"] = int(row.get("attempt_count") or 0) + 1
        repo.update("live_score_queue", int(row_id), payload)
        return True
    except Exception:
        return False


def _safe_list_df(repo, table: str):
    try:
        return repo.list_df(table, order_by="id")
    except Exception:
        import pandas as pd

        return pd.DataFrame()


def _mapping_get(value: Any, key: str) -> Any:
    getter = getattr(value, "get", None)
    return getter(key) if callable(getter) else None


def _score_outcome_from_row(row: Mapping[str, Any]) -> ScoreOutcome:
    rationale = row.get("rationale")
    rationale_map: dict[str, str] = {}
    if isinstance(rationale, str) and rationale.strip():
        try:
            parsed = json.loads(rationale)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            rationale_map = {str(key): str(value) for key, value in parsed.items()}
    scores = {
        field: int(value) if _as_number(value) is not None else None
        for field, value in {
            "accuracy_score": row.get("accuracy_score"),
            "reasoning_score": row.get("reasoning_score"),
            "coverage_score": row.get("coverage_score"),
            "evidence_score": row.get("evidence_score"),
            "expression_score": row.get("expression_score"),
        }.items()
    }
    total = _as_number(row.get("total_score"))
    return ScoreOutcome(
        case_id=str(row.get("case_id") or ""),
        task_type=str(row.get("task_type") or ""),
        eval_model=str(row.get("eval_model") or ""),
        judge_provider=str(row.get("judge_provider") or ""),
        judge_model=str(row.get("judge_model") or ""),
        judge_status=str(row.get("judge_status") or ""),
        scores=scores,
        total_score=int(total) if total is not None else None,
        rationale=rationale_map,
        review_note=str(row.get("review_note") or ""),
        review_status=str(row.get("review_status") or "pending"),
        latency_ms=int(_as_number(row.get("latency_ms"))) if _as_number(row.get("latency_ms")) is not None else None,
        input_tokens=int(_as_number(row.get("input_tokens"))) if _as_number(row.get("input_tokens")) is not None else None,
        output_tokens=int(_as_number(row.get("output_tokens"))) if _as_number(row.get("output_tokens")) is not None else None,
        total_tokens=int(_as_number(row.get("total_tokens"))) if _as_number(row.get("total_tokens")) is not None else None,
        trace_id=row.get("trace_id"),
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
    )


def _normalize_import_score_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    text_fields = {
        "score_run_id",
        "run_id",
        "case_id",
        "task_type",
        "eval_model",
        "judge_provider",
        "judge_model",
        "judge_mode",
        "judge_status",
        "review_note",
        "review_status",
        "trace_id",
        "error_code",
        "error_message",
        "status",
        "created_at",
        "updated_at",
    }
    numeric_fields = {
        "accuracy_score",
        "reasoning_score",
        "coverage_score",
        "evidence_score",
        "expression_score",
        "total_score",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }
    for field_name in text_fields:
        value = _clean(row.get(field_name))
        if value:
            normalized[field_name] = value
    for field_name in numeric_fields:
        number = _as_number(row.get(field_name))
        if number is not None:
            normalized[field_name] = int(round(number))
    rationale = row.get("rationale")
    if isinstance(rationale, Mapping):
        normalized["rationale"] = json.dumps(_jsonable(dict(rationale)), ensure_ascii=False)
    else:
        text = _clean(rationale)
        if text:
            normalized["rationale"] = text
    normalized.setdefault("judge_mode", "live")
    normalized.setdefault("judge_provider", "")
    normalized.setdefault("status", "active")
    return normalized


def _score_unique_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    getter = row.get if hasattr(row, "get") else lambda key, default=None: default
    return (
        _clean(getter("score_run_id")),
        _clean(getter("case_id")),
        _clean(getter("eval_model")),
    )


def _import_result(imported: int, updated: int, skipped: int, errors: Sequence[str] | None = None) -> dict[str, Any]:
    messages: list[str] = []
    if imported:
        messages.append(f"已导入 {imported} 条")
    if updated:
        messages.append(f"已更新 {updated} 条")
    if skipped:
        messages.append(f"跳过 {skipped} 条重复记录")
    if not messages:
        messages.append("未导入评分记录")
    if errors:
        messages.append("；".join(str(error) for error in errors[:3]))
    return {
        "imported_count": int(imported),
        "updated_count": int(updated),
        "skipped_count": int(skipped),
        "failed_count": int(len(errors or [])),
        "errors": list(errors or []),
        "summary": "，".join(messages) + "。",
        "ok": bool(imported or updated) and not errors,
    }


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    text = str(value)
    return None if text.lower() in {"nan", "none", "nat"} else text


_GOLD_TEXT_FIELDS = (
    ("core_conclusion", "核心结论"),
    ("key_evidence", "关键依据"),
    ("analysis", "分析"),
    ("boundary_conditions", "边界条件"),
)
_GOLD_LIST_FIELDS = (
    ("must_have_points", "必须覆盖点"),
    ("unacceptable_errors", "不可接受错误"),
)


def _format_gold(gold: Mapping[str, Any]) -> str:
    if not gold:
        return ""
    parts: list[str] = []
    for key, label in _GOLD_TEXT_FIELDS:
        text = _clean(gold.get(key))
        if text:
            parts.append(f"- {label}：{text}")
    for key, label in _GOLD_LIST_FIELDS:
        items = gold.get(key)
        if isinstance(items, (list, tuple)):
            cleaned = [_clean(item) for item in items if _clean(item)]
            if cleaned:
                parts.append(f"- {label}：" + "；".join(cleaned))
        else:
            text = _clean(items)
            if text:
                parts.append(f"- {label}：{text}")
    return "\n".join(parts)


def _format_rubric(dimensions: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"- {d.get('name', d['field'])}（字段 {d['field']}，满分 {d.get('full_mark')}）"
        for d in dimensions
    )


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    candidate = text.strip()
    # 去掉可能的 ```json ... ``` 代码块包裹。
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text
