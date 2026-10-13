"""评测结论页数据加载缓存层。

app.services.conclusions 保持纯函数与只读数据库访问；这里用 st.cache_data 包住
昂贵的远端 Postgres 读取，并暴露 clear_conclusions_caches() 供写入点
（评测运行、评分、评分导入）做定向失效。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.result_store import ResultStoreError
from app.services import conclusions as cc
from app.services.comparison import comparison_for_runs
from app.services.conclusion_read_model import ConclusionReport, build_conclusion_report
from app.services.snapshot import restore_context

_DATABASE_UNAVAILABLE_MESSAGE = "评测结果数据库暂不可用。当前无法读取已持久化的回答与评分。"
CONCLUSION_REPORT_CACHE_TTL_SECONDS = 15


@dataclass(frozen=True)
class ConclusionSource:
    available: bool
    report: ConclusionReport | None
    message: str = ""


@st.cache_data(show_spinner=False)
def load_current_cohort_scores(allowed_case_ids: tuple[str, ...] = ()) -> pd.DataFrame:
    return cc.load_current_cohort_scores(
        allowed_case_ids=allowed_case_ids or None,
    )


@st.cache_data(show_spinner=False)
def load_live_responses(allowed_case_ids: tuple[str, ...] = ()) -> pd.DataFrame:
    return cc.load_live_responses(
        allowed_case_ids=allowed_case_ids or None,
    )


def load_conclusion_source(
    allowed_case_ids: tuple[str, ...],
    _tasks_records: Sequence[Mapping[str, Any]],
    _gold_records: Sequence[tuple[str, Mapping[str, object]]] | Mapping[str, object],
    _dimensions: Sequence[Mapping[str, Any]],
) -> ConclusionSource:
    """Return a report or a non-cached unavailable state for expected DB errors."""
    try:
        report = _load_available_conclusion_report(
            allowed_case_ids,
            _tasks_records,
            _gold_records,
            _dimensions,
        )
        return ConclusionSource(available=True, report=report)
    except (ResultStoreError, SQLAlchemyError):
        return ConclusionSource(
            available=False,
            report=None,
            message=_DATABASE_UNAVAILABLE_MESSAGE,
        )


@st.cache_data(ttl=CONCLUSION_REPORT_CACHE_TTL_SECONDS, show_spinner=False)
def _load_available_conclusion_report(
    allowed_case_ids: tuple[str, ...],
    _tasks_records: Sequence[Mapping[str, Any]],
    _gold_records: Sequence[tuple[str, Mapping[str, object]]] | Mapping[str, object],
    _dimensions: Sequence[Mapping[str, Any]],
) -> ConclusionReport:
    """Read and cache only a successfully built conclusion report."""
    runs = cc.load_evaluation_runs(suppress_errors=False)
    scores = cc.load_live_scores(suppress_errors=False)
    responses = cc.load_live_responses(
        allowed_case_ids=allowed_case_ids or None,
        suppress_errors=False,
    )
    cohort = cc.select_current_cohort_scores(
        runs,
        scores,
        allowed_case_ids=allowed_case_ids or None,
    )
    baseline = next((r for r in runs.to_dict("records") if str(r.get("run_id")) in set(cohort.get("run_id", []))), None)
    compatible = [r for r in runs.to_dict("records") if baseline and cc._cohort_signature(pd.Series(r)) == cc._cohort_signature(pd.Series(baseline))]
    historical_tasks, historical_gold, historical_dimensions = restore_context(compatible, cohort.get("case_id", []))
    report = build_conclusion_report(
        scores_df=cohort,
        responses_df=responses,
        tasks_df=pd.DataFrame(historical_tasks if not runs.empty else _tasks_records),
        gold_map=historical_gold if not runs.empty else dict(_gold_records),
        dimensions=historical_dimensions if not runs.empty else _dimensions,
    )
    if runs.empty:
        return report
    # Keep every runtime record visible, including failures excluded from quality means.
    tables = {"live_evaluation_runs": runs.to_dict("records"), "live_run_scores": scores.to_dict("records")}
    for name in ("live_run_responses", "live_run_queue", "live_score_queue", "request_attempts"):
        tables[name] = cc._load_live_table(name, None, suppress_errors=False).to_dict("records")
    comparison = comparison_for_runs(report.formal_scores, compatible) if compatible else report.comparison
    real_run_ids = {r["run_id"] for r in tables["live_evaluation_runs"] if str(r.get("provider") or "").lower() not in {"mock", "demo", "selftest", "synthetic", "synthetic_judge_selftest"}}
    tables = {name: [r for r in rows if r.get("run_id") in real_run_ids] for name,rows in tables.items()}
    return replace(report, comparison=comparison, runtime_tables=tables)



def _clear_conclusion_source_cache() -> None:
    _load_available_conclusion_report.clear()


load_conclusion_source.clear = _clear_conclusion_source_cache


def clear_conclusions_caches() -> None:
    load_current_cohort_scores.clear()
    load_live_responses.clear()
    load_conclusion_source.clear()
