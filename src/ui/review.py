"""One read-only destination for the exact historical task, answer and score."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from app.services.formal_records import filter_formal_responses, filter_formal_scores
from app.services.model_display import display_model_name
from app.services.snapshot import _safe, restore_context
from src.ui.conclusions import _formal_response_for_score, _render_formal_record_dialog
from src.ui.report_components import render_report_masthead
from src.ui.scroll import request_scroll
from src.ui.trust_details import render_reference_standard, render_score_detail

ROUTE_FIELDS = ("case", "run", "model", "score")


def open_case_review(case_id: str, model: str, run_id: str, score_run_id: str = "") -> None:
    st.query_params.update(page="review", case=case_id, model=model, run=run_id)
    if score_run_id:
        st.query_params["score"] = score_run_id
    else:
        st.query_params.pop("score", None)
    st.session_state.current_page = "review"
    st.session_state.pop("review_route", None)
    request_scroll("top")


def _record_identity(row):
    return (str(row.get("run_id") or ""), str(row.get("eval_model") or ""),
            str(row.get("score_run_id") or row.get("id") or ""))


def historical_task(report, case_id, run_id):
    runs = [r for r in report.runtime_tables.get("live_evaluation_runs", []) if str(r.get("run_id")) == run_id]
    tasks, gold, dimensions = restore_context(runs, [case_id])
    return next((t for t in tasks if str(t.get("case_id")) == case_id), {}), gold.get(case_id), dimensions


def case_label(task, case_id):
    title = task.get("title") or task.get("scenario")
    return str(_safe(f"{title} · {case_id}" if title else case_id))


def _review_records(report):
    # Review links may point outside the current comparison cohort. Preserve every
    # original formal scoring attempt; never collapse by model/case here.
    if report is None:
        return [], pd.DataFrame()
    tables = report.runtime_tables
    if "live_run_scores" in tables and "live_run_responses" in tables:
        answers = filter_formal_responses(pd.DataFrame(tables["live_run_responses"]))
        scores = filter_formal_scores(pd.DataFrame(tables["live_run_scores"]), answers)
        return scores.to_dict("records"), answers
    return report.formal_scores.to_dict("records"), report.formal_responses


def _change_case():
    st.query_params["case"] = st.session_state["review_case"]
    for field in ("run", "model", "score"):
        st.query_params.pop(field, None)
    st.session_state.pop("review_record", None)
    request_scroll("top")


def _change_record():
    run, model, score = st.session_state["review_record"]
    st.query_params.update(run=run, model=model)
    if score:
        st.query_params["score"] = score
    else:
        st.query_params.pop("score", None)
    request_scroll("top")


def _unresolved():
    st.error("无法定位该案例评分记录：链接不完整、记录不存在或存在多个匹配。请重新选择案例。")
    if st.button("重新选择案例", key="review_reset_route"):
        for field in ROUTE_FIELDS:
            st.query_params.pop(field, None)
        for key in ("review_case", "review_record", "review_route"):
            st.session_state.pop(key, None)
        st.rerun()


def _record_labels(rows, metadata):
    labels = {}
    duplicates = Counter(str(r.get("eval_model")) for r in rows)
    for row in rows:
        identity = _record_identity(row)
        run = metadata.get(identity[0], {})
        date = str(run.get("created_at") or "测试日期未记录")[:10]
        label = f"{display_model_name(identity[1], source='live')} · {date}"
        if duplicates[identity[1]] > 1:
            label += f" · {run.get('provider') or '服务商未记录'} · {run.get('service_endpoint') or '端点未记录'}"
        labels[identity] = str(_safe(label))
    collisions = Counter(labels.values())
    for identity, label in list(labels.items()):
        if collisions[label] > 1:
            labels[identity] += f" · {identity[1]} · {identity[0]} · {identity[2] or '评分标识未记录'}"
    return labels


def render_review_page(data_bundle: dict) -> None:
    from src.ui.workbench import load_workbench_source

    base = data_bundle.get("base") or data_bundle["data"]
    render_report_masthead("案例审阅", "选择案例和模型记录，核对回答与评分依据。")
    source = load_workbench_source(base)
    if not source.available:
        st.warning(source.message)
        return
    report = source.report
    rows, responses = _review_records(report)
    tasks = getattr(base, "tasks", pd.DataFrame())
    current_tasks = {str(t["case_id"]): t for t in tasks.to_dict("records")} if isinstance(tasks, pd.DataFrame) else {}
    scored = sorted({str(r["case_id"]) for r in rows})
    cases = scored + sorted(set(current_tasks) - set(scored))
    route = tuple(st.query_params.get(field, "") for field in ROUTE_FIELDS)
    requested_case, requested_run, requested_model, requested_score = route
    if requested_case and requested_case not in cases:
        _unresolved()
        return
    if (requested_run or requested_model or requested_score) and not requested_case:
        _unresolved()
        return
    if not cases:
        st.info("暂无可查看的专业任务。")
        return
    if route != st.session_state.get("review_route"):
        st.session_state["review_case"] = requested_case or cases[0]
        st.session_state.pop("review_record", None)
    st.session_state["review_route"] = route
    if st.session_state.get("review_case") not in cases:
        st.session_state["review_case"] = cases[0]
    titles = dict(current_tasks)
    for row in rows:
        task, _, _ = historical_task(report, str(row["case_id"]), str(row["run_id"]))
        titles[str(row["case_id"])] = task
    with st.container(key="review_filters"):
        case_column, record_column = st.columns([1, 1.3], gap="medium")
        case_id = case_column.selectbox("专业案例", cases, key="review_case",
                                        format_func=lambda c: case_label(titles.get(c, {}), c), on_change=_change_case)
        selected_rows = [r for r in rows if str(r.get("case_id")) == case_id]
        if not selected_rows:
            if requested_run or requested_model or requested_score:
                _unresolved()
                return
            st.query_params["case"] = case_id
            st.caption("当前题库任务，尚无历史评分。")
            render_score_detail(task=current_tasks.get(case_id, {}), answer="", score={}, dimensions=[], key="review_unscored")
            with st.expander("当前专业评价要求"):
                render_reference_standard(getattr(base, "gold_answer_map", {}).get(case_id), historical=False)
            with st.expander("当前任务技术详情"):
                st.json(_safe(dict(task=current_tasks.get(case_id, {}),
                                   reference_standard=getattr(base, "gold_answer_map", {}).get(case_id))), expanded=False)
            return
        candidates = [r for r in selected_rows if
                      (not requested_run or str(r.get("run_id")) == requested_run) and
                      (not requested_model or str(r.get("eval_model")) == requested_model) and
                      (not requested_score or _record_identity(r)[2] == requested_score)]
        if (requested_run or requested_model or requested_score) and len(candidates) != 1:
            _unresolved()
            return
        identities = [_record_identity(r) for r in selected_rows]
        if len(set(identities)) != len(identities):
            _unresolved()
            return
        if st.session_state.get("review_record") not in identities:
            st.session_state["review_record"] = _record_identity(candidates[0]) if candidates else identities[0]
        metadata = {str(r["run_id"]): r for r in report.runtime_tables.get("live_evaluation_runs", [])}
        labels = _record_labels(selected_rows, metadata)
        selected = record_column.selectbox("模型记录", identities, format_func=labels.get,
                                            key="review_record", on_change=_change_record)
    score = next(r for r in selected_rows if _record_identity(r) == selected)
    st.query_params.update(case=case_id, run=selected[0], model=selected[1])
    if selected[2]:
        st.query_params["score"] = selected[2]
    else:
        st.query_params.pop("score", None)
    st.session_state["review_route"] = tuple(st.query_params.get(f, "") for f in ROUTE_FIELDS)
    task, gold, dimensions = historical_task(report, case_id, selected[0])
    response = _formal_response_for_score(responses, score)
    render_score_detail(task=task, answer=response.get("answer_text") or "", score=score, dimensions=dimensions, key="review")
    with st.expander("专业参考标准 · 运行时记录"):
        render_reference_standard(gold)
    with st.expander("运行与评分记录信息"):
        st.json(_safe(dict(run=metadata.get(selected[0], {}), case_id=case_id,
                           model=selected[1], score_run_id=selected[2], reference_standard=gold)), expanded=False)
    if st.button("打开完整记录", key="review_full_record", type="tertiary"):
        from dataclasses import replace
        _render_formal_record_dialog(replace(report, formal_responses=responses), score)
