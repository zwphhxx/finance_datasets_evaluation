"""Plain-text, expandable structured scoring evidence used by both result views."""

from __future__ import annotations

import json

import streamlit as st

from app.services.score_evidence import STATUSES
from app.services.snapshot import _safe


def _array(row, key):
    try:
        parsed = json.loads(row.get(key) or "[]")
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def render_score_evidence(score, answer):
    raw_answer = str(answer or "")
    raw_checks = _array(score, "checks_json")
    score, answer = _safe(dict(score)), _safe(answer)
    with st.expander("评分依据详情：要点、引文与数值核查"):
        checks = _array(score, "checks_json")
        if not checks:
            st.caption("历史记录未保存结构化证据；评分理由未经引文验证，不能包装为可靠证据。")
        else:
            st.caption("程序仅验证引文存在于回答原文；是否支持专业判断仍依赖裁判。缺失证据不能证明错误不存在。")
        for index, check in enumerate(checks):
            if not isinstance(check, dict):
                st.warning("评价要点结构异常。")
                continue
            st.text(
                f"{check.get('point_id')}｜{STATUSES.get(check.get('status'), '异常状态')}｜{check.get('requirement', '')}"
            )
            quote = check.get("quote") or ""
            original_quote = (
                raw_checks[index].get("quote")
                if index < len(raw_checks) and isinstance(raw_checks[index], dict)
                else None
            )
            verified = quote_matches(original_quote, raw_answer)
            if quote:
                st.code(str(quote), language=None, wrap_lines=True)
            st.caption("引文匹配：已验证" if verified else "引文匹配：无可验证引文")
            if quote and not verified:
                st.warning("引用不在模型回答原文中，不能作为可靠证据。")
            st.text(
                f"错误类型：{check.get('error_type', '—')}；对应维度：{check.get('dimension', '—')}；依据：{check.get('reason', '—')}"
            )
        numeric = _array(score, "numeric_checks_json")
        if numeric:
            st.markdown("**程序数值核查**")
            st.dataframe(numeric, hide_index=True, use_container_width=True)
            st.caption("仅覆盖预设且材料哈希一致的公式。unknown表示未找到明确单一数值，不等于错误；不自动改变权重。")
    with st.expander("原始裁判响应（含失败尝试）"):
        responses = _array(score, "raw_responses_json")
        if not responses:
            st.caption("旧记录未保存原始响应，不补造历史证据。")
        for index, response in enumerate(responses, 1):
            st.caption(f"尝试 {index}")
            st.code(str(response), language=None, wrap_lines=True)


def render_score_detail(*, task, answer, score, dimensions, key):
    """One native two-column evidence view, stacked by responsive CSS."""
    raw_answer = str(answer or "")
    verified_checks = [
        quote_matches(c.get("quote"), raw_answer) if isinstance(c, dict) else False
        for c in _array(score or {}, "checks_json")
    ]
    raw_score = dict(score or {})
    task, score, answer = _safe(dict(task or {})), _safe(raw_score), str(_safe(raw_answer))
    with st.container(key=f"score_detail_{key}"):
        left, right = st.columns([1.1, 1], gap="large")
        with left:
            with st.container(border=True, key=f"score_task_{key}"):
                st.markdown("**专业任务与背景**")
                shown = set()
                for field, label in [
                    ("task", "任务"),
                    ("question", "任务"),
                    ("task_prompt", "任务"),
                    ("business_background", "业务背景"),
                    ("business_context", "业务背景"),
                    ("background", "背景"),
                    ("context", "材料"),
                    ("output_requirements", "输出要求"),
                    ("expected_capability", "输出要求"),
                    ("material", "材料"),
                ]:
                    value = task.get(field)
                    if value and str(value) not in shown:
                        st.caption(label)
                        st.text(str(value))
                        shown.add(str(value))
                if not shown:
                    st.caption("历史记录未保存任务正文；不使用当前题库补造运行时材料。")
            with st.container(border=True, key=f"score_answer_{key}"):
                st.markdown("**被评测模型回答**")
                if answer:
                    # Plain native text wraps long responses and never interprets model HTML.
                    st.text(answer)
                else:
                    st.caption("没有成功回答可供核对。")
        with right:
            with st.container(border=True, key=f"score_review_{key}"):
                st.markdown("**评分与依据**")
                total = score.get("total_score")
                st.metric("综合评分", "—" if total is None else str(total))
                if not score:
                    st.caption("尚无评分记录。")
                rows = [
                    {
                        "维度": d.get("name", d.get("field")),
                        "分数": score.get(d.get("field")),
                        "满分": d.get("full_mark") if d.get("full_mark") is not None else "未记录",
                    }
                    for d in dimensions
                ]
                if not dimensions:
                    rows = [
                        {"维度字段": field, "分数": value, "满分": "未记录"}
                        for field, value in score.items()
                        if field.endswith("_score") and field != "total_score"
                    ]
                    if rows:
                        st.caption("历史维度定义未保存；仅展示原记录的维度字段与分数，满分未知。")
                if rows:
                    st.dataframe(rows, hide_index=True, use_container_width=True)
                checks = []
                for index, check in enumerate(_array(score, "checks_json")):
                    if isinstance(check, dict):
                        check = dict(check)
                        check["_quote_verified"] = verified_checks[index]
                        checks.append(check)
                if not checks:
                    st.caption("历史记录未保存结构化要点评价与回答引文。")
                groups = [
                    ("已满足的评价点 / 已避开的错误", {"met"}),
                    ("未满足的评价点 / 已识别错误", {"not_met"}),
                    ("部分满足 / 尚无法判断", {"partial", "unknown"}),
                ]
                for label, statuses in groups:
                    points = [c for c in checks if c.get("status") in statuses]
                    if not points:
                        continue
                    with st.expander(f"{label} · {len(points)} 项", expanded="not_met" in statuses):
                        for check in points:
                            st.text(f"{check.get('point_id', '')} · {check.get('requirement', '')}")
                            if check.get("kind") == "forbidden":
                                st.caption("不可接受错误检查；满足表示避免该错误。")
                            for field, title in [
                                ("error_type", "错误类型"),
                                ("dimension", "对应维度"),
                                ("reason", "评分理由及影响"),
                            ]:
                                if check.get(field):
                                    st.text(f"{title}：{check[field]}")
                            quote = check.get("quote")
                            if quote:
                                st.code(str(quote), language=None, wrap_lines=True)
                                if check["_quote_verified"]:
                                    st.caption("引文匹配：已验证；专业判断仍需核对。")
                                else:
                                    st.warning("引用不在模型回答原文中，不能作为可靠证据。")
                            else:
                                st.caption("此项未保存对应的回答原文证据。")
                rationale = score.get("rationale")
                if rationale:
                    st.markdown("**各维度评分理由**")
                    try:
                        parsed = json.loads(rationale) if isinstance(rationale, str) else rationale
                    except (ValueError, TypeError):
                        parsed = rationale
                    labels = {d.get("field"): d.get("name") for d in dimensions}
                    if isinstance(parsed, dict):
                        for field, reason in parsed.items():
                            st.text(f"{labels.get(field) or field}：{reason}")
                    else:
                        st.text(str(parsed))
                if score.get("review_note"):
                    st.text(f"审阅备注：{score['review_note']}")
    with st.expander("详细技术信息与原始评分响应"):
        render_score_evidence(raw_score, raw_answer)
        st.json(score, expanded=False)


def quote_matches(quote, answer):
    # Redacted snapshots cannot establish which original identifier was quoted.
    return isinstance(quote, str) and bool(quote.strip()) and "[已脱敏]" not in quote and quote in answer
