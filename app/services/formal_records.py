"""Single policy for records that may be presented as formal evaluation evidence."""

from __future__ import annotations

import json
import math
from typing import Any, Collection

import pandas as pd

from app.services.model_display import is_seed_model
from src.metrics import SCORE_DIMENSION_FULL_MARKS

_NON_FORMAL_MODES = {"mock", "demo", "selftest", "synthetic", "synthetic_judge_selftest"}


def is_non_formal_runtime_record(row: dict[str, Any]) -> bool:
    """Shared snapshot policy, including queues that have provider but no mode."""
    return any(
        _text(row.get(field)).lower() in _NON_FORMAL_MODES
        for field in ("run_mode", "judge_mode", "provider", "judge_provider")
    )


def filter_formal_responses(
    responses: pd.DataFrame,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.DataFrame:
    """Return only successful, non-demo answers within the optional sample scope."""
    if not isinstance(responses, pd.DataFrame):
        return pd.DataFrame()
    return responses.loc[formal_response_mask(responses, allowed_case_ids)].copy()


def formal_response_mask(
    responses: pd.DataFrame,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.Series:
    """Return formal-answer eligibility for every input row."""
    if not isinstance(responses, pd.DataFrame):
        return pd.Series(dtype=bool)
    active = _text_series(responses, "status", "active").str.lower() != "inactive"
    successful = _text_series(responses, "run_status", "").str.lower() == "success"
    live_mode = ~_text_series(responses, "run_mode", "live").str.lower().isin(_NON_FORMAL_MODES)
    live_provider = ~_text_series(responses, "provider", "").str.lower().isin(_NON_FORMAL_MODES)
    real_model = ~_model_series(responses, ("model_name", "eval_model")).map(is_seed_model)
    real_model &= ~_model_series(responses, ("model_name", "eval_model")).str.lower().isin(_NON_FORMAL_MODES)
    has_run = _text_series(responses, "run_id", "") != ""
    has_answer = _text_series(responses, "answer_text", "") != ""
    return active & successful & live_mode & live_provider & real_model & has_run & has_answer & _scope_mask(
        responses, allowed_case_ids
    )


def filter_formal_scores(
    scores: pd.DataFrame,
    responses: pd.DataFrame | None = None,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.DataFrame:
    """Return only formal AI scores, optionally requiring a matching formal answer."""
    if not isinstance(scores, pd.DataFrame):
        return pd.DataFrame()
    return scores.loc[formal_score_mask(scores, responses, allowed_case_ids)].copy()


def formal_score_mask(
    scores: pd.DataFrame,
    responses: pd.DataFrame | None = None,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.Series:
    """Return formal-score eligibility for every input row."""
    if not isinstance(scores, pd.DataFrame):
        return pd.Series(dtype=bool)
    active = _text_series(scores, "status", "active").str.lower() != "inactive"
    successful = _text_series(scores, "judge_status", "").str.lower() == "success"
    live_mode = ~_text_series(scores, "judge_mode", "live").str.lower().isin(_NON_FORMAL_MODES)
    live_provider = ~_text_series(scores, "judge_provider", "").str.lower().isin(_NON_FORMAL_MODES)
    included = _text_series(scores, "review_status", "ai_final").str.lower() != "skipped"
    real_model = ~_model_series(scores, ("eval_model", "model_name")).map(is_seed_model)
    real_model &= ~_model_series(scores, ("eval_model", "model_name")).str.lower().isin(_NON_FORMAL_MODES)
    has_run = _text_series(scores, "run_id", "") != ""
    mask = active & successful & live_mode & live_provider & included & real_model & has_run & _scope_mask(
        scores, allowed_case_ids
    )
    mask &= pd.Series([score_row_valid(r) for r in scores.to_dict("records")], index=scores.index, dtype=bool)
    if responses is not None:
        mask &= _verified_quote_mask(scores, responses)
        mask &= _matching_formal_response_mask(scores, responses, allowed_case_ids)
    return mask


def score_row_valid(row: dict) -> bool:
    evidence_status = _text(row.get("evidence_status"))
    if evidence_status not in {"", "legacy_unverified", "verified_quotes", "no_checkpoints"}:
        return False
    if evidence_status in {"verified_quotes", "no_checkpoints"}:
        values = [row.get(k) for k in SCORE_DIMENSION_FULL_MARKS]
        try:
            if any(v is None or isinstance(v, bool) or pd.isna(v) for v in values) or sum(float(v) for v in values) != float(row.get("total_score")):
                return False
        except (ValueError, TypeError):
            return False
    for key, full_mark in {**SCORE_DIMENSION_FULL_MARKS, "total_score": 100}.items():
        value = row.get(key)
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            continue  # Legacy incomplete rows stay unverified, never filled in.
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if isinstance(value, bool) or not math.isfinite(number) or not number.is_integer() or not 0 <= number <= full_mark:
            return False
    return True


def _verified_quote_mask(scores, responses):
    answers = {(str(r.get("run_id")), str(r.get("case_id")), str(r.get("model_name"))):
               str(r.get("answer_text") or "") for r in responses.to_dict("records")}
    def eligible(row):
        if _text(row.get("evidence_status")) != "verified_quotes":
            return True
        try:
            checks = json.loads(row.get("checks_json") or "null")
            answer = answers.get((str(row.get("run_id")), str(row.get("case_id")), str(row.get("eval_model"))), "")
            return isinstance(checks, list) and bool(checks) and all(
                isinstance(c, dict) and isinstance(c.get("quote"), str) and
                (not c["quote"] or c["quote"] in answer) and
                (c.get("status") not in {"met", "partial"} or bool(c["quote"].strip()))
                for c in checks)
        except (ValueError, TypeError):
            return False
    return pd.Series([eligible(r) for r in scores.to_dict("records")], index=scores.index, dtype=bool)


def filter_formal_score_rows(
    scores: pd.DataFrame,
    responses: pd.DataFrame,
    allowed_case_ids: Collection[str] | None = None,
) -> list[dict]:
    """Return export-ready original score rows backed by a formal answer."""
    return filter_formal_scores(scores, responses, allowed_case_ids).to_dict("records")


def formal_recovery_run_eligible(
    metadata: Any = None,
    queue_rows: Collection[Any] | None = None,
    result: Any = None,
) -> bool:
    """Whether a batch may be offered for recovery or continuation."""
    records = [metadata, result, *(queue_rows or [])]
    providers = [_record_value(record, "provider") for record in records]
    modes = [
        _record_value(record, field_name)
        for record in records
        for field_name in ("run_mode", "mode")
    ]
    return not any(
        value.lower() in _NON_FORMAL_MODES
        for value in (*providers, *modes)
        if value
    )


def _matching_formal_response_mask(
    scores: pd.DataFrame,
    responses: pd.DataFrame,
    allowed_case_ids: Collection[str] | None,
) -> pd.Series:
    if not isinstance(responses, pd.DataFrame):
        return pd.Series(False, index=scores.index, dtype=bool)
    formal_responses = filter_formal_responses(responses, allowed_case_ids)
    if formal_responses.empty:
        return pd.Series(False, index=scores.index, dtype=bool)
    response_keys = {
        (_text(row.get("run_id")), _text(row.get("case_id")), _model_value(row, ("model_name", "eval_model")))
        for row in formal_responses.to_dict("records")
    }
    return pd.Series(
        [
            (_text(row.get("run_id")), _text(row.get("case_id")), _model_value(row, ("eval_model", "model_name")))
            in response_keys
            for row in scores.to_dict("records")
        ],
        index=scores.index,
        dtype=bool,
    )


def _scope_mask(frame: pd.DataFrame, allowed_case_ids: Collection[str] | None) -> pd.Series:
    if allowed_case_ids is None:
        return pd.Series(True, index=frame.index, dtype=bool)
    allowed = {_text(case_id) for case_id in allowed_case_ids if _text(case_id)}
    return _text_series(frame, "case_id", "").isin(allowed)


def _model_series(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    for column in columns:
        if column in frame.columns:
            return _text_series(frame, column, "")
    return pd.Series("", index=frame.index, dtype="object")


def _model_value(row: dict[str, Any], columns: tuple[str, ...]) -> str:
    for column in columns:
        if column in row:
            return _text(row.get(column))
    return ""


def _record_value(record: Any, field_name: str) -> str:
    if isinstance(record, dict):
        return _text(record.get(field_name))
    return _text(getattr(record, field_name, None))


def _text_series(frame: pd.DataFrame, column: str, default: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="object")
    return frame[column].map(lambda value: _text(value, default))


def _text(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    text = str(value).strip()
    return default if text.lower() in {"nan", "none", "null"} else text
