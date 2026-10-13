"""Existing mutation and diagnostic operations, separated from public reading."""
from __future__ import annotations

import streamlit as st

from app.persistence import (
    PersistenceConfigurationError,
    ResultStoreError,
    ResultStoreUnavailableError,
    get_result_store,
)
from app.services import dataset_service as ds
from src.ui.conclusions import _render_score_data_maintenance_controls, render_score_io_message
from src.ui.history_view import (
    render_attempts_and_costs,
    render_history_controls,
    render_judge_selftest,
    render_snapshot_export,
)
from src.ui.report_components import render_report_masthead
from src.ui.samples import render_samples_page


def render_management_page(data_bundle: dict) -> None:
    section = st.radio("数据维护", ["专业样本", "评测结果与快照"], horizontal=True, key="management_section")
    if section == "专业样本":
        render_samples_page(data_bundle)
        return
    render_report_masthead("结果与快照维护", "导入、导出和只读回放；这些操作独立于公开评测结果。")
    render_score_io_message()
    replay = render_history_controls()
    from src.ui.workbench import load_workbench_source

    source = load_workbench_source(data_bundle.get("base") or data_bundle["data"])
    if replay or source.report:
        render_attempts_and_costs(replay or source.report)
    try:
        store = get_result_store()
    except (PersistenceConfigurationError, ResultStoreUnavailableError, ResultStoreError):
        store = None
    with st.expander("评分导入与导出"):
        _render_score_data_maintenance_controls(store)
    with st.expander("完整评测快照导出"):
        render_snapshot_export(store)
    render_judge_selftest(ds.get_rubric_dimensions())
