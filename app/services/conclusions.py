"""评测结论汇总服务（PR-B）。

把真实运行结果归一为「正式结论 / 草稿 / 已确认评分」三层，供「评测结论」页取数：

  - 草稿评测（draft）：live_run_scores 中 review_status == pending 的现场评分，未进入正式结论；
  - 已确认评分（confirmed）：live_run_scores 中 review_status == confirmed 的评分，可计入正式结论。

正式结论 = 已确认 live 结论，**绝不包含 pending 草稿或 seed 示例评价**。

本模块为纯函数 + 只读数据库访问，不依赖 Streamlit 渲染上下文，便于单元测试；任何数据库
异常都吞掉并回退为空，保证 SQLite 不可用时仍可只用 seed 数据展示。绝不回写 data/ 下 seed 文件。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from app.services import model_display as md
from src.metrics import SCORE_DIMENSION_FULL_MARKS, SCORE_DIMENSIONS, get_dimension_gap_ranking

# Rubric 维度字段与中文标签，统一取自 metrics（不在此另立第二份口径）。
DIMENSION_FIELDS: list[str] = [field for field, _ in SCORE_DIMENSIONS]
DIMENSION_LABELS: dict[str, str] = dict(SCORE_DIMENSIONS)

# 归一后的正式打分表列（仅 confirmed live 投影到这里）。
_FORMAL_COLUMNS = ["model_name", "case_id", *DIMENSION_FIELDS, "total_score", "review_note", "source"]

# 模型展示名映射：键为原始 model_name，值为对外展示名。默认空；seed 示例模型的
# 业务化展示由 app.services.model_display 统一处理，不改写底层数据。
MODEL_DISPLAY_NAMES: dict[str, str] = {}

BOUNDARY_REFERENCE = "可作为初稿参考"
BOUNDARY_REVIEW = "必须人工复核"
BOUNDARY_NOT_EVIDENCE = "不可作为依据"

BOUNDARY_REFERENCE_FLOOR = 85.0
BOUNDARY_PASS_FLOOR = 60.0
MIN_BOUNDARY_SAMPLE_COUNT = 2
WEAK_DIMENSION_ATTAINMENT = 0.60
SEVERE_DIMENSION_ATTAINMENT = 0.35
HIGH_RISK_REVIEW_FLOOR = 70.0

_BOUNDARY_LEVELS = {
    BOUNDARY_REFERENCE: "success",
    BOUNDARY_REVIEW: "warning",
    BOUNDARY_NOT_EVIDENCE: "danger",
}
_BOUNDARY_RANK = {
    BOUNDARY_REFERENCE: 0,
    BOUNDARY_REVIEW: 1,
    BOUNDARY_NOT_EVIDENCE: 2,
}
_RANK_BOUNDARY = {rank: boundary for boundary, rank in _BOUNDARY_RANK.items()}
_NOT_EVIDENCE_NOTE_KEYWORDS = ("不可采信", "不可作为依据", "不能采信", "不应采信", "重大遗漏", "重大错误")
_CAUTION_NOTE_KEYWORDS = ("谨慎", "需复核", "需进一步", "证据不足", "不足", "风险")


def display_model_name(
    name: Any,
    mapping: Mapping[str, str] | None = None,
    *,
    source: str | None = None,
) -> str:
    """返回模型展示名；seed 示例与 live 真实模型使用统一显示口径。"""
    table = MODEL_DISPLAY_NAMES if mapping is None else mapping
    return md.display_model_name(name, source=source, mapping=table)


def display_model_source(source: str | None) -> str:
    """返回模型结果来源展示名。"""
    return md.source_label(source)


# --------------------------------------------------------------------------- #
# 只读数据库访问（SQLite 不可用时一律回退空表）
# --------------------------------------------------------------------------- #
def load_live_scores(db_path=None) -> pd.DataFrame:
    """读取全部 live_run_scores 行；数据库不可用或异常时返回空 DataFrame。"""
    return _load_live_table("live_run_scores", db_path)


def load_live_responses(db_path=None) -> pd.DataFrame:
    """读取全部 live_run_responses 行（含模型回答），用于草稿区拼接回答。"""
    return _load_live_table("live_run_responses", db_path)


def _load_live_table(table: str, db_path) -> pd.DataFrame:
    try:
        from app.services.dataset_service import database_ready, get_db_path
        from app.db.repository import Repository

        path = db_path or get_db_path()
        if not database_ready(path):
            return pd.DataFrame()
        frame = Repository(path).list_df(table, order_by="id")
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def split_live_scores(live_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """把 live 评分拆为 (已确认 confirmed, 草稿 pending)，均限定 judge_status=success、未停用。

    只有评分成功且人工确认（review_status=confirmed）的行进入 confirmed；其余成功行为草稿。
    失败 / mock / 暂不采用评分既不进正式结论也不进草稿。
    """
    empty = pd.DataFrame()
    if not isinstance(live_df, pd.DataFrame) or live_df.empty:
        return empty, empty

    df = live_df
    if "judge_status" in df.columns:
        df = df[df["judge_status"].astype(str) == "success"]
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.strip().str.lower() != "inactive"]
    if df.empty:
        return empty, empty

    if "review_status" in df.columns:
        status = df["review_status"].astype(str).str.strip().str.lower()
    else:
        status = pd.Series(["pending"] * len(df), index=df.index)
    confirmed = df[status == "confirmed"].reset_index(drop=True)
    pending = df[status == "pending"].reset_index(drop=True)
    return confirmed, pending


def _normalize_live_scores(live_df: pd.DataFrame) -> pd.DataFrame:
    """把 live_run_scores 行投影为正式打分表列（eval_model → model_name）。"""
    if not isinstance(live_df, pd.DataFrame) or live_df.empty:
        return pd.DataFrame(columns=_FORMAL_COLUMNS)
    out = pd.DataFrame()
    out["model_name"] = live_df.get("eval_model")
    out["case_id"] = live_df.get("case_id")
    for field in DIMENSION_FIELDS:
        out[field] = pd.to_numeric(live_df[field], errors="coerce") if field in live_df.columns else None
    out["total_score"] = (
        pd.to_numeric(live_df["total_score"], errors="coerce") if "total_score" in live_df.columns else None
    )
    out["review_note"] = live_df.get("review_note")
    out["source"] = "confirmed_live"
    return out


def combine_formal_scores(seed_scores: pd.DataFrame, confirmed_live: pd.DataFrame) -> pd.DataFrame:
    """把已确认 live 结论投影为统一打分表（带 source 列）。

    seed_scores 参数保留用于兼容旧调用，但不再纳入正式结论。
    """
    frames: list[pd.DataFrame] = []
    normalized = _normalize_live_scores(confirmed_live)
    if not normalized.empty:
        frames.append(normalized)
    if not frames:
        return pd.DataFrame(columns=_FORMAL_COLUMNS)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if "total_score" in combined.columns:
        combined = combined[combined["total_score"].notna()].reset_index(drop=True)
    return combined


def build_formal_conclusions(
    seed_scores: pd.DataFrame,
    confirmed_live: pd.DataFrame,
    *,
    mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """按模型聚合正式结论：平均总分、各 Rubric 维度均分、人工点评摘要与来源构成。

    不包含 pending 草稿。无可用数据时返回空列表。
    """
    combined = combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty or "model_name" not in combined.columns:
        return []

    results: list[dict[str, Any]] = []
    for model_name, group in combined.groupby("model_name"):
        dimensions: dict[str, float | None] = {}
        for field in DIMENSION_FIELDS:
            if field in group.columns and group[field].notna().any():
                dimensions[field] = float(group[field].mean())
            else:
                dimensions[field] = None
        notes = _collect_notes(group.get("review_note"))
        source_counts = group["source"].value_counts().to_dict() if "source" in group.columns else {}
        results.append(
            {
                "model_name": str(model_name),
                "display_name": display_model_name(
                    model_name, mapping, source=_source_for_group(group)
                ),
                "sample_count": int(len(group)),
                "avg_total": float(group["total_score"].mean()),
                "dimensions": dimensions,
                "review_notes": notes,
                "source": _source_for_group(group),
                "source_label": display_model_source(_source_for_group(group)),
                "seed_count": int(source_counts.get("seed", 0)),
                "confirmed_count": int(source_counts.get("confirmed_live", 0)),
            }
        )
    # 按平均总分降序仅为展示稳定性，页面文案明确说明这不是排行榜。
    results.sort(key=lambda item: (-item["avg_total"], item["display_name"]))
    return results


def build_model_boundaries(
    seed_scores: pd.DataFrame,
    confirmed_live: pd.DataFrame,
    errors_df: pd.DataFrame | None = None,
    tasks_df: pd.DataFrame | None = None,
    *,
    mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Classify model usage boundaries from formal conclusions and risk signals.

    The input scope is the same as formal conclusions: confirmed live scores only.
    Pending scores and seed examples are excluded.
    """
    combined = combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty or "model_name" not in combined.columns or "total_score" not in combined.columns:
        return []

    risk_lookup = _case_risk_lookup(tasks_df)
    rows: list[dict[str, Any]] = []
    for model_name, group in combined.groupby("model_name", dropna=False):
        model = str(model_name)
        scores = group.copy()
        scores["total_score"] = pd.to_numeric(scores["total_score"], errors="coerce")
        scores = scores[scores["total_score"].notna()]
        if scores.empty:
            continue

        avg_total = float(scores["total_score"].mean())
        sample_count = int(len(scores))
        source_counts = scores["source"].value_counts().to_dict() if "source" in scores.columns else {}
        model_errors = _errors_for_model_group(errors_df, scores, model)
        high_errors = _high_severity_errors(model_errors)
        high_risk_cases = _high_risk_cases(scores, risk_lookup)
        high_risk_issue_count = _high_risk_issue_count(scores, high_errors, high_risk_cases)
        weaknesses = _model_dimension_weaknesses(scores)
        notes = _collect_notes(scores.get("review_note"))

        rank, reasons = _base_boundary_from_average(avg_total)
        sample_insufficient = sample_count < MIN_BOUNDARY_SAMPLE_COUNT
        if sample_insufficient:
            rank = max(rank, _BOUNDARY_RANK[BOUNDARY_REVIEW])
            reasons.append(f"样本数量不足（{sample_count}/{MIN_BOUNDARY_SAMPLE_COUNT}），结论仅作观察")

        if not high_errors.empty:
            rank = max(rank, _BOUNDARY_RANK[BOUNDARY_REVIEW])
            reasons.append(f"存在高严重度错误 {len(high_errors)} 条")
            if high_risk_issue_count > 0:
                rank = _BOUNDARY_RANK[BOUNDARY_NOT_EVIDENCE]
                reasons.append("高风险任务中出现高严重度错误")

        high_risk_low_scores = _high_risk_low_scores(scores, high_risk_cases, BOUNDARY_PASS_FLOOR)
        if high_risk_low_scores:
            rank = _BOUNDARY_RANK[BOUNDARY_NOT_EVIDENCE]
            reasons.append("高风险任务中出现明显低分")
        elif _high_risk_low_scores(scores, high_risk_cases, HIGH_RISK_REVIEW_FLOOR):
            rank = max(rank, _BOUNDARY_RANK[BOUNDARY_REVIEW])
            reasons.append("高风险任务表现不足，需人工复核")

        if weaknesses:
            severe = [item for item in weaknesses if item["attainment"] < SEVERE_DIMENSION_ATTAINMENT]
            rank = max(rank, _BOUNDARY_RANK[BOUNDARY_REVIEW])
            main = "、".join(item["dimension"] for item in weaknesses[:2])
            reasons.append(f"关键维度短板：{main}")
            if severe:
                rank = _BOUNDARY_RANK[BOUNDARY_NOT_EVIDENCE]
                reasons.append("关键维度严重低分")

        note_rank = _note_risk_rank(notes)
        if note_rank:
            rank = max(rank, note_rank)
            reasons.append("人工复核说明提示需谨慎" if note_rank == 1 else "人工复核说明提示不可采信")

        boundary = _RANK_BOUNDARY[rank]
        rows.append(
            {
                "model_name": model,
                "display_name": display_model_name(model, mapping, source=_source_for_group(scores)),
                "boundary": boundary,
                "boundary_level": _BOUNDARY_LEVELS[boundary],
                "avg_total": avg_total,
                "sample_count": sample_count,
                "source": _source_for_group(scores),
                "source_label": display_model_source(_source_for_group(scores)),
                "seed_count": int(source_counts.get("seed", 0)),
                "confirmed_count": int(source_counts.get("confirmed_live", 0)),
                "major_weaknesses": weaknesses[:3],
                "has_high_severity_error": bool(not high_errors.empty),
                "high_severity_count": int(len(high_errors)),
                "high_risk_case_count": int(len(high_risk_cases)),
                "high_risk_issue_count": int(high_risk_issue_count),
                "sample_insufficient": bool(sample_insufficient),
                "review_notes": notes,
                "reasons": _dedupe(reasons),
                "basis_summary": "；".join(_dedupe(reasons)[:3]),
            }
        )

    rows.sort(key=lambda item: (_BOUNDARY_RANK.get(item["boundary"], 9), -item["avg_total"], item["display_name"]))
    return rows


def summarize_formal(seed_scores: pd.DataFrame, confirmed_live: pd.DataFrame) -> dict[str, Any]:
    """正式结论首屏统计：纳入条数、模型数、平均总分与来源构成。"""
    combined = combine_formal_scores(seed_scores, confirmed_live)
    if combined.empty:
        return {"total_rows": 0, "model_count": 0, "avg_total": None, "seed_rows": 0, "confirmed_rows": 0}
    source = combined["source"] if "source" in combined.columns else pd.Series([], dtype=str)
    return {
        "total_rows": int(len(combined)),
        "model_count": int(combined["model_name"].nunique()) if "model_name" in combined.columns else 0,
        "avg_total": float(combined["total_score"].mean()),
        "seed_rows": int((source == "seed").sum()),
        "confirmed_rows": int((source == "confirmed_live").sum()),
    }


def build_draft_rows(
    pending_live: pd.DataFrame,
    responses_df: pd.DataFrame | None = None,
    *,
    mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """把 pending live 评分整理为草稿行：模型、建议分、各维度、复核说明、错误信息与模型回答。

    回答文本从 live_run_responses 按 (run_id, case_id, model_name) 拼接，缺失则留空。
    """
    if not isinstance(pending_live, pd.DataFrame) or pending_live.empty:
        return []

    answers = _index_answers(responses_df)
    rows: list[dict[str, Any]] = []
    for _, row in pending_live.iterrows():
        eval_model = row.get("eval_model")
        key = (str(row.get("run_id")), str(row.get("case_id")), str(eval_model))
        rows.append(
            {
                "row_id": _as_int(row.get("id")),
                "model_name": _text(eval_model),
                "display_name": display_model_name(eval_model, mapping, source="live"),
                "source": "pending_live",
                "source_label": display_model_source("pending_live"),
                "case_id": _text(row.get("case_id")),
                "total_score": _num(row.get("total_score")),
                "dimensions": {field: _num(row.get(field)) for field in DIMENSION_FIELDS},
                "review_note": _text(row.get("review_note")),
                "review_status": _text(row.get("review_status")) or "pending",
                "error_code": _text(row.get("error_code")),
                "error_message": _text(row.get("error_message")),
                "answer_text": _text(answers.get(key)),
            }
        )
    return rows


def summarize_frequent_issues(
    formal_scores: pd.DataFrame,
    errors_df: pd.DataFrame | None = None,
    notes: Sequence[str] | None = None,
    *,
    top_n: int = 4,
) -> list[str]:
    """基于低分维度、错误标签与人工复核说明，归纳当前样本内的高频问题。

    全部由数据动态推导，不臆造模型缺陷；无数据时返回空列表。
    """
    issues: list[str] = []

    if isinstance(formal_scores, pd.DataFrame) and not formal_scores.empty:
        ranking = get_dimension_gap_ranking(formal_scores)
        for _, row in ranking.head(2).iterrows():
            issues.append(f"{row['dimension']}相对薄弱（达成率约 {float(row['attainment']):.0%}）")

    if isinstance(errors_df, pd.DataFrame) and not errors_df.empty and "error_type" in errors_df.columns:
        counts = errors_df["error_type"].dropna().astype(str).value_counts()
        for error_type, count in counts.head(2).items():
            issues.append(f"高频错误标签：{error_type}（{int(count)} 次）")

    if notes:
        cleaned = _collect_notes(notes)
        if cleaned:
            issues.append("人工复核反复提到：" + "；".join(cleaned[:2]))

    return issues[:top_n]


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _base_boundary_from_average(avg_total: float) -> tuple[int, list[str]]:
    if avg_total >= BOUNDARY_REFERENCE_FLOOR:
        return _BOUNDARY_RANK[BOUNDARY_REFERENCE], [f"平均分较高（{avg_total:.1f}）"]
    if avg_total >= BOUNDARY_PASS_FLOOR:
        return _BOUNDARY_RANK[BOUNDARY_REVIEW], [f"平均分处于中间区间（{avg_total:.1f}）"]
    return _BOUNDARY_RANK[BOUNDARY_NOT_EVIDENCE], [f"平均分明显偏低（{avg_total:.1f}）"]


def _source_for_group(group: pd.DataFrame) -> str:
    if not isinstance(group, pd.DataFrame) or group.empty or "source" not in group.columns:
        return ""
    values = [str(value) for value in group["source"].dropna().astype(str).unique().tolist()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if "confirmed_live" in values:
        return "confirmed_live"
    if "seed" in values:
        return "seed"
    return values[0]


def _case_risk_lookup(tasks_df: pd.DataFrame | None) -> dict[str, str]:
    if not isinstance(tasks_df, pd.DataFrame) or tasks_df.empty:
        return {}
    if "case_id" not in tasks_df.columns or "risk_level" not in tasks_df.columns:
        return {}
    lookup: dict[str, str] = {}
    for _, row in tasks_df.iterrows():
        case_id = _text(row.get("case_id"))
        if case_id:
            lookup[case_id] = _text(row.get("risk_level"))
    return lookup


def _errors_for_model_group(errors_df: pd.DataFrame | None, group: pd.DataFrame, model_name: str) -> pd.DataFrame:
    if not isinstance(errors_df, pd.DataFrame) or errors_df.empty:
        return pd.DataFrame()
    errors = errors_df.copy()
    mask = pd.Series([True] * len(errors), index=errors.index)
    if "model_name" in errors.columns:
        mask &= errors["model_name"].astype(str) == str(model_name)
    if "case_id" in errors.columns and "case_id" in group.columns:
        cases = set(group["case_id"].dropna().astype(str))
        if cases:
            mask &= errors["case_id"].astype(str).isin(cases)
    if "output_id" in errors.columns and "output_id" in group.columns:
        output_ids = set(group["output_id"].dropna().astype(str))
        if output_ids:
            mask &= errors["output_id"].astype(str).isin(output_ids)
    return errors[mask].reset_index(drop=True)


def _high_severity_errors(errors: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(errors, pd.DataFrame) or errors.empty or "severity" not in errors.columns:
        return pd.DataFrame()
    severity = errors["severity"].map(_severity_rank)
    return errors[severity >= 3].reset_index(drop=True)


def _severity_rank(value: Any) -> int:
    text = _text(value).lower()
    mapping = {"高": 3, "high": 3, "严重": 3, "中": 2, "medium": 2, "低": 1, "low": 1}
    return mapping.get(text, 0)


def _high_risk_cases(group: pd.DataFrame, risk_lookup: Mapping[str, str]) -> set[str]:
    if not risk_lookup or "case_id" not in group.columns:
        return set()
    case_ids = set(group["case_id"].dropna().astype(str))
    return {case_id for case_id in case_ids if _is_high_risk(risk_lookup.get(case_id))}


def _is_high_risk(value: Any) -> bool:
    text = _text(value).lower()
    return text in {"高", "高风险", "high"} or "high" in text


def _high_risk_issue_count(group: pd.DataFrame, high_errors: pd.DataFrame, high_risk_cases: set[str]) -> int:
    if not high_risk_cases:
        return 0
    count = 0
    if not high_errors.empty and "case_id" in high_errors.columns:
        count += int(high_errors["case_id"].astype(str).isin(high_risk_cases).sum())
    count += len(_high_risk_low_scores(group, high_risk_cases, BOUNDARY_PASS_FLOOR))
    return count


def _high_risk_low_scores(group: pd.DataFrame, high_risk_cases: set[str], floor: float) -> list[str]:
    if not high_risk_cases or "case_id" not in group.columns or "total_score" not in group.columns:
        return []
    rows = group[group["case_id"].astype(str).isin(high_risk_cases)]
    if rows.empty:
        return []
    scores = pd.to_numeric(rows["total_score"], errors="coerce")
    return rows[scores < floor]["case_id"].dropna().astype(str).tolist()


def _model_dimension_weaknesses(group: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, label in SCORE_DIMENSIONS:
        full_mark = SCORE_DIMENSION_FULL_MARKS.get(field)
        if not full_mark or field not in group.columns:
            continue
        scores = pd.to_numeric(group[field], errors="coerce").dropna()
        if scores.empty:
            continue
        avg_score = float(scores.mean())
        attainment = avg_score / float(full_mark)
        if attainment < WEAK_DIMENSION_ATTAINMENT:
            rows.append(
                {
                    "field": field,
                    "dimension": label,
                    "avg_score": avg_score,
                    "full_mark": float(full_mark),
                    "attainment": attainment,
                    "gap": float(full_mark) - avg_score,
                }
            )
    rows.sort(key=lambda item: (item["attainment"], -item["gap"], item["dimension"]))
    return rows


def _note_risk_rank(notes: Sequence[str]) -> int:
    text = " ".join(notes)
    if not text:
        return 0
    if any(keyword in text for keyword in _NOT_EVIDENCE_NOTE_KEYWORDS):
        return _BOUNDARY_RANK[BOUNDARY_NOT_EVIDENCE]
    if any(keyword in text for keyword in _CAUTION_NOTE_KEYWORDS):
        return _BOUNDARY_RANK[BOUNDARY_REVIEW]
    return 0


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def _index_answers(responses_df: pd.DataFrame | None) -> dict[tuple[str, str, str], str]:
    answers: dict[tuple[str, str, str], str] = {}
    if not isinstance(responses_df, pd.DataFrame) or responses_df.empty:
        return answers
    for _, row in responses_df.iterrows():
        key = (str(row.get("run_id")), str(row.get("case_id")), str(row.get("model_name")))
        answers[key] = _text(row.get("answer_text"))
    return answers


def _collect_notes(values) -> list[str]:
    """去重保序地收集非空复核说明。"""
    if values is None:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    iterable = values.tolist() if isinstance(values, pd.Series) else list(values)
    for value in iterable:
        text = _text(value)
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def _as_int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(number)
