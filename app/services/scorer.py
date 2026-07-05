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

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.models.base import ModelProvider, STATUS_FAILED, STATUS_MOCK, STATUS_SUCCESS

# Fixed judge model for scoring (PR-LOGIC1)
DEFAULT_JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Pro"

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

    if not result.ok:
        return ScoreOutcome(
            **base, judge_status=STATUS_FAILED,
            scores={d["field"]: None for d in dimensions}, total_score=None,
            error_code=result.error_code, error_message=result.error_message, **common,
        )

    parsed = parse_judge_output(result.response_text, dimensions)
    if not parsed.ok:
        return ScoreOutcome(
            **base, judge_status=STATUS_FAILED,
            scores={d["field"]: None for d in dimensions}, total_score=None,
            error_code="judge_parse_error", error_message=parsed.error, **common,
        )

    return ScoreOutcome(
        **base, judge_status=STATUS_SUCCESS,
        scores=parsed.scores, total_score=parsed.total,
        rationale=parsed.rationale, review_note=parsed.review_note, **common,
    )


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
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return False
        repo = Repository(path)
        if _score_outcome_exists(repo, score_run_id, outcome.case_id, outcome.eval_model):
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
        return True
    except Exception:
        return False


def _score_outcome_exists(repo, score_run_id: str, case_id: str, eval_model: str) -> bool:
    try:
        rows = repo.list_df("live_run_scores")
        if rows.empty:
            return False
        required = {"score_run_id", "case_id", "eval_model"}
        if not required.issubset(rows.columns):
            return False
        matched = rows[
            (rows["score_run_id"].astype(str) == str(score_run_id))
            & (rows["case_id"].astype(str) == str(case_id))
            & (rows["eval_model"].astype(str) == str(eval_model))
        ]
        return not matched.empty
    except Exception:
        return False


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


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
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
