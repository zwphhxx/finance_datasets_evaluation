"""评测运行与会话状态管理（从 eval_console 拆出）。

本模块只负责读写 streamlit.session_state 中与真实评测相关的键，不处理任何 UI 渲染或
数据解析。保留原有键名（live_eval_last_run / live_eval_last_score）以兼容既有会话。
"""

from __future__ import annotations

from typing import Any

import streamlit as st

_RUN_KEY = "live_eval_last_run"
_SCORE_KEY = "live_eval_last_score"


def get_last_run() -> Any | None:
    """返回最近一次评测运行结果（CompareRunResult / RunResult），无则 None。"""
    return st.session_state.get(_RUN_KEY)


def set_last_run(result: Any) -> None:
    """保存最近一次评测运行结果，并清空旧评分（避免对应错乱）。"""
    st.session_state[_RUN_KEY] = result
    st.session_state.pop(_SCORE_KEY, None)


def get_last_score() -> Any | None:
    """返回最近一次裁判评分结果（ScoreResult），无则 None。"""
    return st.session_state.get(_SCORE_KEY)


def set_last_score(score_result: Any) -> None:
    """保存最近一次裁判评分结果。"""
    st.session_state[_SCORE_KEY] = score_result


def has_run() -> bool:
    """当前会话是否已有运行结果。"""
    return get_last_run() is not None


def clear() -> None:
    """清空运行与评分会话状态。"""
    st.session_state.pop(_RUN_KEY, None)
    st.session_state.pop(_SCORE_KEY, None)
