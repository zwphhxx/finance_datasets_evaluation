"""A single public reading path; all evaluation and access rules stay in services."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.services.model_display import display_model_name
from app.services.snapshot import _safe
from src.ui import workbench
from src.ui.components import render_html
from src.ui.conclusions import _formal_response_for_score
from src.ui.labels import DOMAIN_LABELS, display_label
from src.ui.review import ROUTE_FIELDS, _record_identity, _review_records, historical_task, open_case_review
from src.ui.scroll import request_scroll
from src.ui.trust_details import _task_fields, evidence_gaps, render_portfolio_evaluation

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
    for field in ROUTE_FIELDS:
        st.query_params.pop(field, None)
    if st.query_params.pop("origin", None) == "evaluation_preview":
        st.query_params.update(page="evaluation_preview", stage="results")
        st.session_state.current_page = "evaluation_preview"
        request_scroll("top")
        return
    st.query_params["page"] = "conclusions"
    st.session_state.current_page = "conclusions"
    request_scroll("#fde-featured-case")


def render_portfolio_home(data_bundle):
    base = data_bundle.get("base") or data_bundle["data"]
    tasks = _tasks(base)
    task_map = {str(t["case_id"]): t for t in tasks}
    case_id = "FD-001" if "FD-001" in task_map else next(iter(sorted(task_map)), "")
    source = workbench.load_workbench_source(base)
    report = source.report if source.available else None
    if not case_id and report is not None:
        case_id = next(iter(sorted(set(report.formal_scores.get("case_id", [])))), "")
    design = task_map.get(case_id, {})
    score = featured_record(report, case_id)
    with st.container(key="portfolio_home"):
        st.title("让AI回答，经得起专业检验。")
        st.markdown("将财务、法律及投行业务中的专业判断，转化为可检查的模型评价任务。")
        domains = list(dict.fromkeys(display_label(str(t["domain"]), DOMAIN_LABELS).removesuffix("场景")
                                    for t in tasks if t.get("domain")))
        st.caption(f"{len(tasks)}个专业任务 · {'/'.join(domains) or '领域未记录'} · AI自动评分原型")
        from src.ui.public_preview import navigate_preview
        with st.container(horizontal=True):
            st.button("体验评测流程", key="portfolio_evaluation_preview", on_click=navigate_preview, args=("evaluation_preview",))
            st.button("查看样本库", key="portfolio_sample_preview", on_click=navigate_preview, args=("sample_preview",), type="tertiary")
        render_html('<div id="fde-featured-case"></div>')
        with st.container(key="portfolio_featured"):
            st.subheader("收入增长，但回款是否正常？" if case_id == "FD-001" else
                         str(_safe(design.get("title") or design.get("scenario") or (f"专业案例 · {case_id}" if case_id else "专业任务"))))
            if design:
                st.caption(f"当前任务设计 · {case_id}")
                fields = list(_task_fields(design))
                background = next((v for label, v in fields if label in {"业务背景", "背景", "材料"}), "")
                question = next((v for label, v in fields if label == "任务"), "")
                if background:
                    st.text(_excerpt(background, 145))
                if question:
                    st.markdown("**评测目标**")
                    requirement = next((v for label, v in fields if label == "输出要求"), question)
                    st.text(_excerpt(requirement.split("。")[0] + "。", 120))
            if score is not None:
                rows, responses = _review_records(report)
                answer = _formal_response_for_score(responses, score).get("answer_text") or ""
                task, gold, _ = historical_task(report, case_id, str(score["run_id"]))
                model = display_model_name(str(score["eval_model"]), source="live")
                st.markdown(f"**历史回答节选 · {str(_safe(model))}**")
                gaps = evidence_gaps(task, gold, score, answer)
                if gaps:
                    st.caption("该记录尚不具备完整评价证据：缺少" + "、".join(gaps) + "。上方当前任务设计不代表当时输入。")
                st.text(_excerpt(answer, 120))
                if score.get("review_note"):
                    st.caption("原始评价摘录")
                    st.text(_excerpt(score["review_note"], 160))
                st.button("查看完整案例", key="portfolio_open_case", type="primary", on_click=open_case_review,
                          args=(case_id, str(score["eval_model"]), str(score["run_id"]), _record_identity(score)[2]))
            elif case_id:
                st.caption("任务设计示例，尚无完整实测记录。")
                if not source.available:
                    st.caption("历史结果暂不可读取，可先查看任务与评价标准。")
                st.button("查看完整案例", key="portfolio_open_case", type="primary", on_click=open_case_review,
                          args=(case_id, "", ""))
            else:
                st.caption("暂无可读取的专业任务，请稍后查看。")
        render_html('<div id="fde-method"></div>')
        st.markdown("**评测方法**")
        st.markdown("项目通过专业任务、参考答案及评价标准，对模型回答进行自动评分和分析。结果仅反映当前样本与测试条件，不构成模型整体能力排名。")
        st.link_button("查看方法与技术说明", REPOSITORY_URL + "#评测边界", type="tertiary")


def render_portfolio_case(data_bundle):
    base = data_bundle.get("base") or data_bundle["data"]
    with st.container(key="portfolio_case"):
        st.button("← 返回评测体验" if st.query_params.get("origin") == "evaluation_preview" else "← 返回作品首页",
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
                st.caption("该记录尚不具备完整评价证据：缺少" + "、".join(gaps) + "。")
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
