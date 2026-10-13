"""A single public reading path; all evaluation and access rules stay in services."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services.conclusions import _parse_rationale
from app.services.model_display import display_model_name
from app.services.snapshot import _safe
from src.ui import workbench
from src.ui.components import render_html
from src.ui.conclusions import _formal_response_for_score
from src.ui.labels import DOMAIN_LABELS, display_label
from src.ui.review import (
    ROUTE_FIELDS,
    _record_identity,
    _record_labels,
    _review_records,
    historical_task,
    open_case_review,
)
from src.ui.scroll import request_scroll
from src.ui.trust_details import (
    _array,
    _rationale,
    _render_check,
    _summary_checks,
    _task_fields,
    evidence_gaps,
    render_portfolio_evaluation,
)

REPOSITORY_URL = "https://github.com/zwphhxx/finance_datasets_evaluation"


def _tasks(base):
    frame = getattr(base, "tasks", None)
    return frame.to_dict("records") if isinstance(frame, pd.DataFrame) else []


def _excerpt(value, limit):
    text = str(_safe(value or ""))
    if len(text) <= limit:
        return text
    end = max(text.rfind("。", 0, limit) + 1, text.rfind("\n", 0, limit))
    return text[:end if end >= limit // 2 else limit].rstrip() + "…"


def featured_record(report, case_id):
    """Prefer saved evidence, then date/identity; never select by score/rank."""
    if report is None or not report.scope.formal_score_count:
        return None
    rows, responses = _review_records(report)
    rows = [r for r in rows if str(r.get("case_id")) == case_id]
    metadata = {str(r["run_id"]): r for r in report.runtime_tables.get("live_evaluation_runs", [])}

    def order(row):
        run, model, score = _record_identity(row)
        task, gold, _ = historical_task(report, case_id, run)
        answer = _formal_response_for_score(responses, row).get("answer_text") or ""
        date = pd.to_datetime(metadata.get(run, {}).get("created_at"), utc=True, errors="coerce")
        timestamp = date.value if pd.notna(date) else 0
        return (bool(evidence_gaps(task, gold, row, answer)), -timestamp, run, model, score)

    return min(rows, key=order) if rows else None


def _return_home():
    origin = st.query_params.pop("origin", None)
    if origin == "evaluation_preview":
        st.session_state["public_preview_record"] = tuple(st.query_params.get(f, "") for f in ("run", "model", "score", "case"))
        if st.query_params.get("run"):
            st.query_params["history"] = st.query_params["run"]
    if origin != "portfolio_home":
        for field in ROUTE_FIELDS:
            st.query_params.pop(field, None)
    if origin == "evaluation_preview":
        st.query_params.update(page="evaluation_preview", stage="results")
        st.session_state.current_page = "evaluation_preview"
        request_scroll("top")
        return
    st.query_params["page"] = "conclusions"
    st.session_state.current_page = "conclusions"
    request_scroll("#fde-featured-case")


def _reset_home_selection():
    for field in (*ROUTE_FIELDS, "origin"):
        st.query_params.pop(field, None)
    for key in ("portfolio_home_case", "portfolio_home_record"):
        st.session_state.pop(key, None)


def _home_case_changed():
    if st.session_state.portfolio_home_case:
        st.query_params["case"] = st.session_state.portfolio_home_case
    else:
        st.query_params.pop("case", None)
    for field in ("run", "model", "score"):
        st.query_params.pop(field, None)
    st.session_state.pop("portfolio_home_record", None)


def _home_record_changed():
    if st.session_state.portfolio_home_record is None:
        for field in ("run", "model", "score"):
            st.query_params.pop(field, None)
        return
    run, model, score = st.session_state.portfolio_home_record
    st.query_params.update(case=st.session_state.portfolio_home_case, run=run, model=model, score=score)


def _open_home_case(fallback):
    case, run, model, score = fallback
    if st.session_state.get("portfolio_home_record"):
        case = st.session_state.portfolio_home_case
        run, model, score = st.session_state.portfolio_home_record
    elif "portfolio_home_record" in st.session_state or st.session_state.get("portfolio_home_case", case) != case:
        st.warning("案例正在切换，请稍后再打开。")
        return
    open_case_review(case, model, run, score)
    st.query_params["origin"] = "portfolio_home"


def _render_home_selection(report, rows, task_map):
    """Only select formal saved records; query links override existing widgets."""
    cases = sorted({str(r["case_id"]) for r in rows})
    requested = st.query_params.get("case")
    exact = any(st.query_params.get(f) for f in ("run", "model", "score"))
    candidates = [r for r in rows if str(r["case_id"]) == requested and
                  _record_identity(r) == tuple(st.query_params.get(f, "") for f in ("run", "model", "score"))]
    if (requested and requested not in cases) or (exact and len(candidates) != 1):
        st.error("无法定位该案例评分记录，请重新选择案例。")
        st.button("重新选择案例", key="portfolio_reset_selection", on_click=_reset_home_selection)
        return None, None
    if not cases:
        return None, None
    labels = {}
    for case in cases:
        representative = featured_record(report, case)
        task, _, _ = historical_task(report, case, str(representative["run_id"]))
        title = task.get("title") or task.get("scenario") or task_map.get(case, {}).get("title") or task_map.get(case, {}).get("scenario")
        labels[case] = str(_safe(f"{title} · {case}" if title else f"历史案例 · {case}"))
    default_case = requested or st.session_state.get("portfolio_home_case")
    if default_case not in cases:
        default_case = "FD-001" if "FD-001" in cases else cases[0]
    if requested or "portfolio_home_case" not in st.session_state or st.session_state.portfolio_home_case not in (*cases, None):
        st.session_state.portfolio_home_case = default_case
    with st.expander("切换案例"), st.container(key="portfolio_home_selectors"):
        left, right = st.columns([1, 1], gap="small")
        with left:
            case = st.selectbox("专业案例", cases, index=None, format_func=labels.get,
                                key="portfolio_home_case", on_change=_home_case_changed)
        if case is None:
            with right:
                st.selectbox("模型与测试日期", [], index=None, disabled=True)
            st.caption("请选择专业案例。")
            return None, None
        case_rows = sorted((r for r in rows if str(r["case_id"]) == case), key=_record_identity)
        identities = {_record_identity(r): r for r in case_rows}
        metadata = {str(r["run_id"]): r for r in report.runtime_tables.get("live_evaluation_runs", [])}
        record_labels = _record_labels(case_rows, metadata)
        selected = _record_identity(candidates[0]) if exact else st.session_state.get("portfolio_home_record")
        if selected not in identities and ("portfolio_home_record" not in st.session_state or selected is not None):
            selected = _record_identity(featured_record(report, case))
        st.session_state.portfolio_home_record = selected
        with right:
            identity = st.selectbox("模型与测试日期", list(identities), index=None, format_func=record_labels.get,
                                    key="portfolio_home_record", on_change=_home_record_changed)
    if identity is None:
        st.caption("请选择模型与测试日期。")
        return None, None
    st.query_params.update(case=case, run=identity[0], model=identity[1], score=identity[2])
    return case, identities[identity]


def render_portfolio_home(data_bundle):
    base = data_bundle.get("base") or data_bundle["data"]
    tasks = _tasks(base)
    task_map = {str(t["case_id"]): t for t in tasks}
    case_id = "FD-001" if "FD-001" in task_map else next(iter(sorted(task_map)), "")
    source = workbench.load_workbench_source(base)
    report = source.report if source.available else None
    rows, responses = _review_records(report)
    if report is None or not report.scope.formal_score_count:
        rows = []
    score = None
    with st.container(key="portfolio_home"):
        st.title("专业场景大模型评测")
        st.markdown("将财务、法律及投行业务中的专业判断，转化为可检查的模型评价任务。")
        domains = list(dict.fromkeys(display_label(str(t["domain"]), DOMAIN_LABELS).removesuffix("场景")
                                    for t in tasks if t.get("domain")))
        st.caption(f"{len(tasks)}个专业任务 · {'/'.join(domains) or '领域未记录'} · AI自动评分原型")
        render_html('<div id="fde-featured-case"></div>')
        with st.container(key="portfolio_featured"):
            if rows or any(st.query_params.get(f) for f in ROUTE_FIELDS):
                case_id, score = _render_home_selection(report, rows, task_map)
            if case_id is not None:
                _render_home_excerpt(report, source, task_map, case_id, score, responses)
        render_html('<div id="fde-method"></div>')
        st.markdown("**评测方法与局限**")
        st.markdown("项目以专业任务、参考答案及评价标准检查模型回答。AI自动评分需人工核对；结果仅反映当前样本与测试条件，不构成模型整体能力排名。")
        st.link_button("查看方法与技术说明", REPOSITORY_URL + "#评测边界", type="tertiary")


def _render_home_rating(raw_score, dimensions, answer):
    """Summarize saved deductions; legacy text is feedback, not a deduction map."""
    score = _safe(dict(raw_score))
    total = pd.to_numeric(score.get("total_score"), errors="coerce")
    st.markdown(f"**AI评分：{total:g}**" if pd.notna(total) else "**AI评分：未记录**")
    marks = {d.get("field"): pd.to_numeric(d.get("full_mark"), errors="coerce") for d in dimensions}
    values = {k: pd.to_numeric(v, errors="coerce") for k, v in score.items()
              if k.endswith("_score") and k != "total_score"}
    complete = (bool(marks) and bool(values) and set(values) == set(marks)
                and all(pd.notna(v) for v in [*marks.values(), *values.values(), total])
                and abs(sum(values.values()) - total) < 1e-6 and total <= sum(marks.values()))
    st.caption(f"满分 {sum(marks.values()):g}。" if complete else "历史满分未记录。")
    saved_checks = [c for c in _array(raw_score, "checks_json") if isinstance(c, dict)]
    checks = [c for c in saved_checks if c.get("status") in {"not_met", "partial"}]
    if checks:
        st.markdown("**关键扣分理由**")
        for check in _summary_checks(checks):
            _render_check(check, answer, summary=True)
        return
    reasons = _parse_rationale(score.get("rationale"))
    deductions = {field: reasons[field] for field, mark in marks.items()
                  if field in reasons and pd.notna(mark) and pd.notna(values.get(field))
                  and values[field] < mark}
    if deductions:
        st.markdown("**关键扣分理由**")
        _rationale(dict(score, rationale=deductions), dimensions, limit=3, readable=True)
        return
    st.caption("原始评分反馈：未保存逐项扣分对应关系，不推算扣分。" if not complete and not saved_checks
               else "原始评分反馈；未列出问题不代表证据完整。")
    if score.get("review_note"):
        st.text(_excerpt(score["review_note"], 200))
    if score.get("rationale"):
        _rationale(score, dimensions, limit=2 if score.get("review_note") else 3, readable=True)
    if not score.get("review_note") and not score.get("rationale"):
        st.caption("历史记录未保存评分理由，不能据此判断没有问题。")


def _render_home_excerpt(report, source, task_map, case_id, score, responses):
    design = task_map.get(case_id, {})
    task, dimensions, answer = {}, [], ""
    if score is not None:
        answer = _formal_response_for_score(responses, score).get("answer_text") or ""
        task, gold, dimensions = historical_task(report, case_id, str(score["run_id"]))
    historical_fields = list(_task_fields(task))
    material = task if historical_fields else design
    st.subheader(str(_safe(task.get("title") or material.get("title") or material.get("scenario") or
                          (f"专业案例 · {case_id}" if case_id else "专业任务"))))
    if score is not None:
        gaps = evidence_gaps(task, gold, score, answer)
        if gaps:
            st.caption("该记录尚不具备完整评价证据：缺少" + "、".join(gaps) + "。" +
                       ("当前任务设计仅用于理解业务场景，不代表当时输入。" if design and not historical_fields else "不补造历史材料。"))
    if material:
        st.caption(f"{'当次任务材料' if historical_fields else '当前任务设计'} · {case_id}")
        fields = list(_task_fields(material))
        background = next((v for label, v in fields if label in {"业务背景", "背景", "材料"}), "")
        question = next((v for label, v in fields if label == "任务"), "")
        if background:
            st.text(_excerpt(background, 145))
        if question:
            st.markdown("**评测目标**")
            st.text(_excerpt(question, 180))
    if score is not None:
        model = display_model_name(str(score["eval_model"]), source="live")
        st.markdown("**历史回答节选**")
        case_rows, _ = _review_records(report)
        metadata = {str(r['run_id']): r for r in report.runtime_tables.get('live_evaluation_runs', [])}
        labels = _record_labels([r for r in case_rows if str(r['case_id']) == case_id], metadata)
        st.caption(labels.get(_record_identity(score), str(_safe(model))))
        if answer:
            st.text(_excerpt(answer, 360))
        else:
            st.caption("历史回答未保存，无法展示回答节选。")
        st.markdown("**专业评价**")
        _render_home_rating(score, dimensions, answer)
        st.button("查看完整案例 →", key="portfolio_open_case", type="primary", on_click=_open_home_case,
                  args=((case_id, *_record_identity(score)),))
    elif case_id:
        st.caption("任务设计示例，尚无完整实测记录。")
        if not source.available:
            st.caption("历史结果暂不可读取，可先查看任务与评价标准。")
        st.button("查看专业任务 →", key="portfolio_open_case", type="primary", on_click=open_case_review,
                  args=(case_id, "", ""))
    else:
        st.caption("暂无可读取的专业任务，请稍后查看。")


def render_portfolio_case(data_bundle):
    base = data_bundle.get("base") or data_bundle["data"]
    with st.container(key="portfolio_case"):
        st.button("← 返回评测流程" if st.query_params.get("origin") == "evaluation_preview" else "← 返回评测结果",
                  key="portfolio_return_home", type="tertiary", on_click=_return_home)
        source = workbench.load_workbench_source(base)
        report = source.report if source.available else None
        rows, responses = _review_records(report)
        task_map = {str(t["case_id"]): t for t in _tasks(base)}
        route = tuple(st.query_params.get(field, "") for field in ROUTE_FIELDS)
        case_id, run_id, model, score_id = route
        if not any(route):
            case_id = "FD-001" if "FD-001" in task_map else next(iter(sorted(task_map)), "")
            row = featured_record(report, case_id)
            if row is not None:
                run_id, model, score_id = _record_identity(row)
        candidates = [r for r in rows if str(r.get("case_id")) == case_id and
                      (not run_id or str(r.get("run_id")) == run_id) and
                      (not model or str(r.get("eval_model")) == model) and
                      (not score_id or _record_identity(r)[2] == score_id)]
        if len(candidates) == 1:
            score = candidates[0]
            run_id, model, score_id = _record_identity(score)
            st.query_params.update(page="review", case=case_id, run=run_id, model=model, score=score_id)
            task, gold, dimensions = historical_task(report, case_id, run_id)
            response = _formal_response_for_score(responses, score)
            answer = response.get("answer_text") or ""
            metadata = next((r for r in report.runtime_tables.get("live_evaluation_runs", []) if str(r["run_id"]) == run_id), {})
            st.title(str(_safe(task.get("title") or task.get("scenario") or f"历史案例 · {case_id}")))
            st.caption(str(_safe(display_model_name(model, source="live"))) + " · " + str(metadata.get("created_at") or "日期未记录")[:10])
            gaps = evidence_gaps(task, gold, score, answer)
            if gaps:
                st.caption("该记录尚不具备完整评价证据：缺少" + "、".join(gaps) + "。不使用当前题库补造历史材料。")
            if list(_task_fields(task)):
                _render_task(task, historical=True)
            related = {}
            for table in ("live_run_queue", "live_score_queue", "request_attempts"):
                related[table] = [r for r in report.runtime_tables.get(table, [])
                                  if str(r.get("run_id")) == run_id and str(r.get("case_id")) == case_id
                                  and str(r.get("eval_model") or r.get("model_name") or r.get("model_id")) == model
                                  and (not r.get("score_run_id") or str(r["score_run_id"]) == score_id)]
            render_portfolio_evaluation(answer=answer, score=score, dimensions=dimensions, gold=gold,
                                        metadata=dict(run=metadata, task=task, response=response, related=related))
        elif not candidates and case_id in task_map and not any((run_id, model, score_id)):
            task = task_map[case_id]
            st.title(str(_safe(task.get("title") or task.get("scenario") or case_id)))
            st.caption("当前任务设计，尚无完整实测记录。")
            if not source.available:
                st.caption("历史结果暂不可读取，此处仅展示当前任务设计。")
            _render_task(task, historical=False)
            render_portfolio_evaluation(answer="", score={}, dimensions=[],
                                        gold=getattr(base, "gold_answer_map", {}).get(case_id),
                                        metadata=dict(task=task), historical=False)
        else:
            st.error("无法定位该案例记录：链接不完整、记录不存在或存在多个匹配。请返回首页选择案例。")


def _render_task(task, *, historical):
    if task.get("domain"):
        st.caption(display_label(str(task["domain"]), DOMAIN_LABELS))
    fields = list(_task_fields(_safe(task)))
    if not fields:
        if historical:
            st.text("历史任务材料未保存，不使用当前题库替代。")
        return
    length = sum(len(v) for _, v in fields)
    if length <= 1400:
        for label, value in fields:
            st.markdown(f"**{label}**")
            st.text(value)
    else:
        st.text(_excerpt(fields[0][1], 220))
        with st.expander("查看完整任务材料"):
            for label, value in fields:
                st.markdown(f"**{label}**")
                st.text(value)
