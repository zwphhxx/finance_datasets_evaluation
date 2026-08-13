"""Pure read projection for the formal evaluation-conclusion report."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

import pandas as pd

from app.services import conclusions
from app.services import evidence_index
from app.services import formal_records
from app.services.evidence_index import EvidenceItem


@dataclass(frozen=True)
class ReportScope:
    sample_count: int
    model_count: int
    formal_score_count: int
    data_basis: str = "仅纳入正式评分"


@dataclass(frozen=True)
class ConclusionReport:
    scope: ReportScope
    formal_scores: pd.DataFrame
    formal_responses: pd.DataFrame
    model_summaries: tuple[dict, ...]
    evidence_by_model: Mapping[str, tuple[EvidenceItem, ...]]


def build_conclusion_report(
    *,
    scores_df: object,
    responses_df: object,
    tasks_df: object,
    gold_map: object,
    dimensions: object,
) -> ConclusionReport:
    """Build all conclusion inputs from one formal, current-sample cohort."""
    allowed_case_ids = _case_ids(tasks_df)
    formal_responses = formal_records.filter_formal_responses(responses_df, allowed_case_ids)
    formal_scores = formal_records.filter_formal_scores(scores_df, formal_responses, allowed_case_ids)
    tasks = tasks_df if isinstance(tasks_df, pd.DataFrame) else pd.DataFrame()
    summaries = tuple(conclusions.build_model_issue_summaries(formal_scores, pd.DataFrame(), tasks))
    evidence = {
        str(summary.get("model_name")): tuple(evidence_index.build_evidence_index(
            formal_scores,
            formal_responses,
            tasks,
            gold_map if isinstance(gold_map, Mapping) else {},
            dimensions,
            str(summary.get("model_name")),
        ))
        for summary in summaries
        if str(summary.get("model_name") or "")
    }
    return ConclusionReport(
        scope=ReportScope(
            sample_count=_distinct_count(formal_scores, "case_id"),
            model_count=_distinct_count(formal_scores, "eval_model"),
            formal_score_count=len(formal_scores),
        ),
        formal_scores=formal_scores,
        formal_responses=formal_responses,
        model_summaries=summaries,
        evidence_by_model=evidence,
    )


def _case_ids(tasks_df: object) -> tuple[str, ...]:
    if not isinstance(tasks_df, pd.DataFrame) or "case_id" not in tasks_df.columns:
        return ()
    return tuple(
        case_id
        for case_id in (_text(value) for value in tasks_df["case_id"].tolist())
        if case_id
    )


def _distinct_count(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return len({_text(value) for value in frame[column].tolist() if _text(value)})


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
