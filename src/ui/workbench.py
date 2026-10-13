"""Read-only workbench projections. All quality gates remain in services."""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services.comparison import comparison_for_runs
from app.services.conclusion_read_model import ReportScope
from app.services.evidence_index import build_evidence_index
from app.services.snapshot import _safe, restore_context
from src.ui import conclusions_data as cd
from src.ui.history_view import active_snapshot, snapshot_report
from src.ui.labels import DOMAIN_LABELS, display_label


def load_workbench_source(base):
    snapshot = active_snapshot()
    if snapshot:
        selected = st.session_state.get("history_run_select")
        ids = None if not selected or selected == "当前兼容比较组" else [selected]
        return cd.ConclusionSource(True, snapshot_report(snapshot, ids))
    tasks = getattr(base, "tasks", pd.DataFrame())
    records = tuple(tasks.to_dict("records")) if isinstance(tasks, pd.DataFrame) else ()
    ids = tuple(sorted(str(r["case_id"]) for r in records))
    gold = getattr(base, "gold_answer_map", {}) or {}
    return cd.load_conclusion_source(ids, records, tuple(sorted(gold.items())), tuple(ds.get_rubric_dimensions()))


def overview_facts(base, report):
    tasks = getattr(base, "tasks", pd.DataFrame())
    dates = [
        str(r.get("created_at"))
        for r in (report.runtime_tables.get("live_evaluation_runs", []) if report else [])
        if r.get("created_at")
    ]
    # Lexical maximum is not valid when historical timestamps use different offsets.
    latest = max(dates, key=lambda x: pd.to_datetime(x, utc=True, errors="coerce").value) if dates else None
    return dict(
        samples=len(tasks),
        domains=int(tasks["domain"].nunique()) if "domain" in tasks else 0,
        models=report.scope.model_count if report else 0,
        scores=report.scope.formal_score_count if report else 0,
        latest=latest,
    )


def overview_score_observation(report, model_name):
    """Quote saved feedback from the lowest scored readable formal record.

    This is a case observation, not a semantic classification or frequency claim.
    Missing legacy checkpoints must not be interpreted as evidence of no errors.
    """
    scores = report.formal_scores
    if scores.empty or "eval_model" not in scores:
        return None
    candidates = scores[scores["eval_model"].astype(str) == str(model_name)].copy()
    candidates["_score_order"] = pd.to_numeric(candidates.get("total_score"), errors="coerce")
    for field in ("case_id", "run_id"):
        candidates[f"_{field}_order"] = candidates[field].map(cc._text) if field in candidates else ""
    candidates = candidates.sort_values(
        ["_score_order", "_case_id_order", "_run_id_order"], kind="mergesort", na_position="last"
    )
    for row in candidates.to_dict("records"):
        text = cc._text(row.get("review_note"))
        source = "评分说明"
        if not text:
            reasons = cc._parse_rationale(row.get("rationale"))
            text = "；".join(f"{field}：{reason}" for field, reason in reasons.items())
            source = "维度评分理由"
        if text:
            return _safe(dict(case_id=cc._text(row.get("case_id")), run_id=cc._text(row.get("run_id")),
                              source=source, text=text))
    return None


def report_tasks(report, fallback):
    """Prefer the task captured at evaluation time over the current library."""
    ids = set(report.formal_scores.get("run_id", []))
    runs = [r for r in report.runtime_tables.get("live_evaluation_runs", []) if r["run_id"] in ids]
    if runs:
        captured = restore_context(runs, report.formal_scores.get("case_id", []))[0]
        return [dict(t, domain=t.get("domain") or "历史未记录") for t in captured]
    tasks = {str(r["case_id"]): r for r in fallback}
    for items in report.evidence_by_model.values():
        for item in items:
            if item.task:
                tasks[item.case_id] = dict(item.task)
    return list(tasks.values())


def filter_report(report, tasks, *, domain="全部", models=None, case_id="全部"):
    scores = report.formal_scores.copy()
    permitted = {str(t["case_id"]) for t in tasks if domain == "全部" or str(t.get("domain")) == domain}
    if not scores.empty:
        scores = scores[scores["case_id"].isin(permitted)]
        if models is not None:
            scores = scores[scores["eval_model"].isin(models)]
        if case_id != "全部":
            scores = scores[scores["case_id"] == case_id]
    responses = report.formal_responses
    if not responses.empty:
        pairs = set(zip(scores.get("run_id", []), scores.get("case_id", [])))
        responses = responses[
            [
                (r["run_id"], r["case_id"]) in pairs and (models is None or r["model_name"] in models)
                for r in responses.to_dict("records")
            ]
        ]
    baseline = next(
        (
            r
            for r in report.runtime_tables.get("live_evaluation_runs", [])
            if r["run_id"] in set(report.formal_scores.get("run_id", []))
        ),
        None,
    )
    runs = [
        dict(r)
        for r in report.runtime_tables.get("live_evaluation_runs", [])
        if baseline
        and (
            r["run_id"] == baseline["run_id"]
            or (
                cc._cohort_signature(pd.Series(baseline)) is not None
                and cc._cohort_signature(pd.Series(r)) == cc._cohort_signature(pd.Series(baseline))
            )
        )
    ]
    if models is not None:
        for run in runs:
            run["model_ids_json"] = json.dumps(
                [m for m in json.loads(run.get("model_ids_json") or "[]") if m in models]
            )
    from app.services.comparison import common_sample_comparison

    comparison = comparison_for_runs(scores, runs) if runs else common_sample_comparison(scores, models)
    task_frame = pd.DataFrame(tasks)
    summary_scores = scores.drop_duplicates(["case_id", "eval_model"], keep="last") if not scores.empty else scores
    summaries = tuple(cc.build_model_issue_summaries(summary_scores, pd.DataFrame(), task_frame))
    captured_tasks, captured_gold, captured_dimensions = restore_context(runs, scores.get("case_id", []))
    evidence = {
        str(m): tuple(
            build_evidence_index(
                scores, responses, pd.DataFrame(captured_tasks), captured_gold, captured_dimensions, str(m)
            )
        )
        for m in scores.get("eval_model", pd.Series(dtype=str)).unique()
    }
    return replace(
        report,
        formal_scores=scores,
        formal_responses=responses,
        scope=ReportScope(
            int(scores["case_id"].nunique()) if not scores.empty else 0,
            int(scores["eval_model"].nunique()) if not scores.empty else 0,
            len(scores),
        ),
        model_summaries=tuple(sorted(summaries, key=lambda r: r["model_name"])),
        evidence_by_model=evidence,
        comparison=comparison,
    )


def render_report_filters(report, fallback):
    tasks = report_tasks(report, fallback)
    model_options = sorted(
        set(report.formal_scores.get("eval_model", []))
        | {str(r["model_id"]).split(" | ")[0] for r in report.comparison.get("models", [])}
    )
    if not model_options:
        return report
    with st.container(key="workbench_filters", border=True):
        columns = st.columns([1, 1.5, 1.5])
        domain = columns[0].selectbox(
            "专业场景",
            ["全部", *sorted({str(t.get("domain")) for t in tasks if t.get("domain")})],
            format_func=lambda x: display_label(x, DOMAIN_LABELS),
            key="comparison_domain",
        )
        state = st.session_state.get("comparison_models")
        if state is None:
            st.session_state["comparison_models"] = model_options
        else:
            st.session_state["comparison_models"] = [m for m in state if m in model_options]
        models = columns[1].multiselect("模型", model_options, key="comparison_models")
        available = {str(t["case_id"]): t for t in tasks if domain == "全部" or str(t.get("domain")) == domain}
        options = ["全部", *sorted(available)]
        if st.session_state.get("comparison_task") not in options:
            st.session_state["comparison_task"] = "全部"
        case = columns[2].selectbox("专业任务", options, key="comparison_task")
    return filter_report(report, tasks, domain=domain, models=models, case_id=case)


def render_common_dimensions(report, dimensions):
    common = report.comparison.get("case_ids", [])
    if not common:
        return
    if not dimensions:
        st.caption("历史维度定义未保存；不使用当前评分标准补造维度比较。原始维度分仍可逐题查看。")
        return
    rows = []
    metadata = {r["run_id"]: r for r in report.runtime_tables.get("live_evaluation_runs", [])}
    scores = report.formal_scores[report.formal_scores["case_id"].isin(common)].copy()
    labels = []
    for row in scores.to_dict("records"):
        run = metadata.get(row["run_id"])
        labels.append(
            f"{row['eval_model']} | {run.get('provider') or '服务商未知'} | {run.get('service_endpoint') or '端点未记录'}"
            if run
            else row["eval_model"]
        )
    scores["unit"] = labels
    scores = scores.drop_duplicates(["unit", "case_id"], keep="last")
    for model, group in scores.groupby("unit"):
        row = {"模型 / 服务配置": model, "共同样本": len(group)}
        for dimension in dimensions:
            field = dimension.get("field")
            values = pd.to_numeric(group[field], errors="coerce") if field in group else pd.Series(dtype=float)
            # Missing dimensions do not quietly change the denominator.
            row[f"{dimension.get('name', field)} / {dimension.get('full_mark', '—')}"] = (
                round(float(values.mean()), 1) if len(values) == len(common) and values.notna().all() else None
            )
        rows.append(row)
    st.markdown("**共同样本的维度差异**")
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("维度缺失显示空值；所有均分使用相同任务范围。小样本差异仅供观察。")


def historical_dimensions(report):
    ids = set(report.formal_scores.get("run_id", []))
    runs = [r for r in report.runtime_tables.get("live_evaluation_runs", []) if r["run_id"] in ids]
    return restore_context(runs, [])[2]


def has_multiple_endpoints(report):
    seen = {}
    for row in report.comparison.get("models", []):
        label = str(row["model_id"])
        model = label.split(" | ")[0]
        seen.setdefault(model, set()).add(label)
    return any(len(units) > 1 for units in seen.values())
