"""评测结论页数据加载缓存层。

app.services.conclusions 保持纯函数与只读数据库访问；这里用 st.cache_data 包住
昂贵的远端 Postgres 读取，并暴露 clear_conclusions_caches() 供写入点
（评测运行、评分、评分导入）做定向失效。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services import conclusions as cc


@st.cache_data(show_spinner=False)
def load_current_cohort_scores() -> pd.DataFrame:
    return cc.load_current_cohort_scores()


@st.cache_data(show_spinner=False)
def load_live_responses() -> pd.DataFrame:
    return cc.load_live_responses()


def clear_conclusions_caches() -> None:
    load_current_cohort_scores.clear()
    load_live_responses.clear()
