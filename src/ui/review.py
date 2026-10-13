"""One read-only destination for task, answer and saved scoring evidence."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services.model_display import display_model_name
from app.services.snapshot import _safe, restore_context
from src.ui.conclusions import _formal_response_for_score, _render_formal_record_dialog
from src.ui.report_components import render_report_masthead
from src.ui.scroll import request_scroll
from src.ui.trust_details import render_score_detail


def open_case_review(case_id: str, model: str, run_id: str) -> None:
    st.query_params.update(page="review", case=case_id, model=model, run=run_id)
    st.session_state.current_page = "review"
    st.session_state.pop("review_case", None)
    st.session_state.pop("review_record", None)
    request_scroll("top")
    st.rerun()


def _record_identity(row):
    return str(row.get("run_id") or ""), str(row.get("eval_model") or "")


def render_review_page(data_bundle: dict) -> None:
    from src.ui.workbench import load_workbench_source

    base = data_bundle.get("base") or data_bundle["data"]
    render_report_masthead("案例审阅", "选择专业任务和模型记录，核对回答、评分理由与已保存证据。")
    source = load_workbench_source(base)
    report = source.report
    tasks = getattr(base, "tasks", pd.DataFrame())
    current_tasks = {str(t["case_id"]): t for t in tasks.to_dict("records")} if isinstance(tasks, pd.DataFrame) else {}
    rows = report.formal_scores.to_dict("records") if report is not None else []
    cases = sorted(set(current_tasks) | {str(r["case_id"]) for r in rows})
    if not source.available:
        st.warning(source.message)
    if not cases:
        st.info("当前没有可审阅的案例。可在管理中只读加载历史快照或维护专业样本。")
        return
    requested = st.query_params.get("case")
    if st.session_state.get("review_case") not in cases:
        st.session_state["review_case"] = requested if requested in cases else cases[0]
    with st.container(key="review_filters"):
        case_id = st.selectbox("专业任务", cases, key="review_case")
        selected_rows = [r for r in rows if str(r.get("case_id")) == case_id]
        if not selected_rows:
            st.query_params.update(case=case_id)
            st.query_params.pop("model", None)
            st.query_params.pop("run", None)
            st.info("此任务暂无可读取的正式评分。以下为当前题库任务，不代表历史运行时材料。")
            task = current_tasks.get(case_id, {})
            render_score_detail(task=task, answer="", score={}, dimensions=[], key="review_unscored")
            with st.expander("当前专业评价要求"):
                gold = getattr(base, "gold_answer_map", {}).get(case_id)
                if gold:
                    st.json(_safe(gold), expanded=True)
                else:
                    st.caption("当前任务未保存专业评价要求。")
            return
        identities = list(dict.fromkeys(_record_identity(r) for r in selected_rows))
        requested_record = st.query_params.get("run", ""), st.query_params.get("model", "")
        if st.session_state.get("review_record") not in identities:
            st.session_state["review_record"] = requested_record if requested_record in identities else identities[0]
        selected = st.selectbox("模型 / 运行批次", identities,
                                format_func=lambda r: f"{display_model_name(r[1], source='live')} · {r[0]}",
                                key="review_record")
    score = next(r for r in selected_rows if _record_identity(r) == selected)
    st.query_params.update(case=case_id, model=selected[1], run=selected[0])
    runs = [r for r in report.runtime_tables.get("live_evaluation_runs", []) if str(r.get("run_id")) == selected[0]]
    captured, gold, dimensions = restore_context(runs, [case_id])
    task = next((t for t in captured if str(t.get("case_id")) == case_id), {})
    response = _formal_response_for_score(report.formal_responses, score)
    st.caption(f"{case_id} · {selected[1]} · {selected[0]} ｜ 自动评分，专业判断仍需人工核对。")
    render_score_detail(task=task, answer=response.get("answer_text") or "", score=score,
                        dimensions=dimensions, key="review")
    with st.expander("运行时专业评价标准"):
        if gold.get(case_id):
            st.json(_safe(gold[case_id]), expanded=True)
        else:
            st.caption("历史记录未保存运行时专业标准答案；不使用当前题库补造评分依据。")
    if st.button("打开完整记录", key="review_full_record", type="tertiary"):
        _render_formal_record_dialog(report, score)
