"""评测结论页数据加载缓存层。

app.services.conclusions 保持纯函数与只读数据库访问；这里用 st.cache_data 包住
昂贵的远端 Postgres 读取，并暴露 clear_conclusions_caches() 供写入点
（评测运行、评分、评分导入）做定向失效。
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.persistence.result_store import ResultStoreError
from app.services import conclusions as cc
from app.services.conclusion_read_model import ConclusionReport, build_conclusion_report


_DATABASE_UNAVAILABLE_MESSAGE = "评测结果数据库暂不可用。当前无法读取已持久化的回答与评分。"


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


@st.cache_data(show_spinner=False)
def load_conclusion_source(
    allowed_case_ids: tuple[str, ...],
    _tasks_records: Sequence[Mapping[str, Any]],
    _gold_records: Mapping[str, object],
    _dimensions: Sequence[Mapping[str, Any]],
) -> ConclusionSource:
    """Read one current cohort and project it into a formal conclusion report."""
    try:
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
        report = build_conclusion_report(
            scores_df=cohort,
            responses_df=responses,
            tasks_df=pd.DataFrame(_tasks_records),
            gold_map=_gold_records,
            dimensions=_dimensions,
        )
        return ConclusionSource(available=True, report=report)
    except (ResultStoreError, SQLAlchemyError):
        return ConclusionSource(
            available=False,
            report=None,
            message=_DATABASE_UNAVAILABLE_MESSAGE,
        )


def clear_conclusions_caches() -> None:
    load_current_cohort_scores.clear()
    load_live_responses.clear()
    load_conclusion_source.clear()
