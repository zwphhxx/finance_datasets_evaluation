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


def render_score_evidence(score, answer, *, inline=False):
    raw_answer = str(answer or "")
    raw_checks = _array(score, "checks_json")
    score, answer = _safe(dict(score)), _safe(answer)
    with st.container() if inline else st.expander("评分依据详情：要点、引文与数值核查"):
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
    with st.container() if inline else st.expander("原始裁判响应（含失败尝试）"):
        st.markdown("**原始裁判响应（含失败尝试）**")
        responses = _array(score, "raw_responses_json")
        if not responses:
            st.caption("旧记录未保存原始响应，不补造历史证据。")
        for index, response in enumerate(responses, 1):
            st.caption(f"尝试 {index}")
            st.code(str(response), language=None, wrap_lines=True)


def _task_fields(task):
    shown = set()
    for field, label in [
        ("task", "任务"), ("question", "任务"), ("task_prompt", "任务"),
        ("business_background", "业务背景"), ("business_context", "业务背景"),
        ("background", "背景"), ("context", "材料"), ("material", "材料"),
        ("output_requirements", "输出要求"), ("expected_capability", "输出要求"),
    ]:
        value = task.get(field)
        if value and str(value) not in shown:
            shown.add(str(value))
            yield label, str(value)


def _render_check(check, raw_answer, *, summary=False):
    original_quote = check.get("quote")
    check = _safe(dict(check))
    status = STATUSES.get(check.get("status"), "状态未记录")
    text = f"{check.get('requirement') or check.get('point_id') or '评价点'} · {status}"
    if check.get("kind") == "forbidden" and check.get("status") == "not_met":
        st.warning(text)
    else:
        st.text(text)
    if check.get("kind") == "forbidden" and check.get("status") == "met":
        st.caption("此项表示已避免该错误。")
    if check.get("reason"):
        reason = str(check["reason"])
        st.text((reason[:180] + "…") if summary and len(reason) > 180 else reason)
    quote = check.get("quote")
    if quote:
        st.code(str(_safe(quote)), language=None, wrap_lines=True)
        if quote_matches(original_quote, raw_answer):
            st.caption("引文匹配：已验证；专业判断仍需核对。")
        else:
            st.warning("引用不在模型回答原文中，不能作为可靠证据。")
    else:
        st.caption("此项未保存回答原文证据。")
    if not summary:
        for field, title in [("point_id", "评价点编号"), ("error_type", "错误类型"), ("dimension", "对应维度")]:
            if check.get(field):
                st.caption(f"{title}：{check[field]}")


def _rationale(score, dimensions, *, limit=None):
    rationale = score.get("rationale")
    if not rationale:
        return
    try:
        parsed = json.loads(rationale) if isinstance(rationale, str) else rationale
    except (ValueError, TypeError):
        parsed = rationale
    labels = {d.get("field"): d.get("name") for d in dimensions}
    if isinstance(parsed, dict):
        for field, reason in list(parsed.items())[:limit]:
            text = f"{labels.get(field) or field}：{reason}"
            st.text(text[:180] + ("…" if len(text) > 180 else "") if limit else text)
    else:
        st.text(str(parsed))


def render_reference_standard(value, *, historical=True):
    """Readable saved fields; absence never falls back to the current library."""
    from src.ui.samples import parse_gold_answer_for_display

    if not value:
        st.caption("历史记录未保存运行时专业标准答案；不使用当前题库补造评分依据。" if historical else "当前任务未保存专业评价要求。")
        return
    parsed = parse_gold_answer_for_display(_safe(value))
    if not parsed["parsed"]:
        st.text(parsed["fallback_text"])
        return
    fields, lists = parsed["fields"], parsed["lists"]
    sections = [
        ("参考判断", fields["标准结论"]),
        ("关键依据", fields["关键依据"]),
        ("必须覆盖的要点", lists["必须覆盖点"]),
        ("不可接受错误", lists["不可接受错误"]),
        ("适用边界", fields["边界与需核查事项"]),
        ("评审提示", fields["评审提示"]),
        ("评分关注点", fields["本题评分关注点"]),
    ]
    for label, content in sections:
        st.markdown(f"**{label}**")
        if not content or content == "待补充":
            st.caption("未记录。")
        elif isinstance(content, list):
            for index, item in enumerate(content, 1):
                st.text(f"{index}. {item}")
        else:
            st.text(str(content))


def render_score_detail(*, task, answer, score, dimensions, key):
    """Case overview and a 60/40 reading view; summary first in the DOM for mobile."""
    raw_answer, raw_score = str(answer or ""), dict(score or {})
    task, score, answer = _safe(dict(task or {})), _safe(raw_score), str(_safe(raw_answer))
    with st.container(key=f"score_task_{key}"):
        title = task.get("title") or task.get("scenario") or "案例概览"
        st.subheader(str(title))
        if task.get("domain"):
            from src.ui.labels import DOMAIN_LABELS, display_label
            st.caption(display_label(str(task["domain"]), DOMAIN_LABELS))
        fields = list(_task_fields(task))
        if fields:
            summary = fields[0][1]
            st.text(summary[:160] + ("…" if len(summary) > 160 else ""))
            with st.expander("完整任务与背景"):
                for label, value in fields:
                    st.caption(label)
                    st.text(value)
        else:
            st.caption("历史记录未保存任务正文；不使用当前题库补造运行时材料。")
    checks = [c for c in _array(raw_score, "checks_json") if isinstance(c, dict)]
    # Preserve the original sequence in the full inspector. Only the summary is
    # ordered by recorded status/kind, never inferred from answer prose.
    def priority(check):
        if check.get("kind") == "forbidden" and check.get("status") == "not_met":
            return 0
        return {"not_met": 1, "partial": 2, "unknown": 3, "met": 4}.get(check.get("status"), 3)
    ordered = sorted(checks, key=priority)
    critical_count = sum(priority(c) == 0 for c in ordered)
    # A recorded unacceptable error must never disappear behind the summary cap.
    summary_checks = ordered[:max(3, critical_count)]
    with st.container(key=f"score_detail_{key}"):
        right, left = st.columns([2, 3], gap="large")
        with right:
            with st.container(key=f"score_review_{key}"):
                st.markdown("**评价结果**")
                total = score.get("total_score")
                st.metric("AI评分", "—" if total is None else str(total))
                known_marks = [d.get("full_mark") for d in dimensions]
                if known_marks and all(isinstance(v, (int, float)) for v in known_marks):
                    st.caption(f"满分 {sum(known_marks):g} · 自动评分，需人工核对。")
                elif score:
                    st.caption("历史满分未记录 · 自动评分，需人工核对。")
                else:
                    st.caption("尚无评分记录。")
                if summary_checks:
                    for check in summary_checks:
                        _render_check(check, raw_answer, summary=True)
                else:
                    note = score.get("review_note")
                    if note:
                        st.text(str(note)[:220] + ("…" if len(str(note)) > 220 else ""))
                    else:
                        _rationale(score, dimensions, limit=2)
                    st.caption("历史记录未保存结构化要点评价与回答引文。")
        with left:
            with st.container(key=f"score_answer_{key}"):
                st.markdown("**模型回答**")
                if answer:
                    if len(answer) > 3000:
                        st.text(answer[:1600] + "…")
                        st.caption("回答较长，以上为开头节选。完整原文保留如下。")
                        with st.expander("完整模型回答"):
                            st.text(answer)
                    else:
                        st.text(answer)
                else:
                    st.caption("没有成功回答可供核对。")
    with st.expander("完整评分维度"):
        rows = [{"维度": d.get("name", d.get("field")), "分数": score.get(d.get("field")),
                 "满分": d.get("full_mark") if d.get("full_mark") is not None else "未记录"} for d in dimensions]
        if not dimensions:
            rows = [{"维度字段": field, "分数": value, "满分": "未记录"}
                    for field, value in score.items() if field.endswith("_score") and field != "total_score"]
            if rows:
                st.caption("历史维度定义未保存；满分未知，仅展示原始字段与分数。")
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
        else:
            st.caption("没有可读取的维度分数。")
    with st.expander(f"全部检查要点 · {len(checks)} 项"):
        if not checks:
            st.caption("历史记录未保存结构化要点评价与回答引文。")
        for check in checks:
            _render_check(check, raw_answer)
    with st.expander("完整评分理由"):
        _rationale(score, dimensions)
        if score.get("review_note"):
            st.text(str(score["review_note"]))
        if not score.get("rationale") and not score.get("review_note"):
            st.caption("历史记录未保存评分理由。")
    with st.expander("原始技术记录"):
        render_score_evidence(raw_score, raw_answer, inline=True)
        st.json(score, expanded=False)


def quote_matches(quote, answer):
    # Redacted snapshots cannot establish which original identifier was quoted.
    return isinstance(quote, str) and bool(quote.strip()) and "[已脱敏]" not in quote and quote in answer
