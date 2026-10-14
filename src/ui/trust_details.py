"""Plain-text, expandable structured scoring evidence used by both result views."""

from __future__ import annotations

import json
import math

import streamlit as st

from app.services.score_evidence import STATUSES
from app.services.snapshot import _safe


def _score_value(score):
    value = score.get("total_score")
    if score.get("judge_status") == "failed" or value is None:
        return "—"
    try:
        return str(value) if math.isfinite(float(value)) else "—"
    except (ValueError, TypeError):
        return "—"


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
        ("task", "任务"),
        ("question", "任务"),
        ("task_prompt", "任务"),
        ("business_background", "业务背景"),
        ("business_context", "业务背景"),
        ("background", "背景"),
        ("context", "材料"),
        ("material", "材料"),
        ("output_requirements", "输出要求"),
        ("expected_capability", "输出要求"),
        ("output_requirement", "输出要求"),
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


def _rationale(score, dimensions, *, limit=None, readable=False):
    rationale = score.get("rationale")
    if not rationale:
        return
    try:
        parsed = json.loads(rationale) if isinstance(rationale, str) else rationale
    except (ValueError, TypeError):
        parsed = rationale
    labels = {d.get("field"): d.get("name") for d in dimensions}
    if readable:
        # Display aliases only: never infer saved weights or rubric definitions.
        from app.services.conclusions import DIMENSION_LABELS

        labels = {**DIMENSION_LABELS, **labels}
    if isinstance(parsed, dict):
        for field, reason in list(parsed.items())[:limit]:
            text = f"{labels.get(field) or ('评价意见' if readable else field)}：{reason}"
            st.text(text[:180] + ("…" if len(text) > 180 else "") if limit else text)
    else:
        text = str(parsed)
        st.text(text[:180] + ("…" if len(text) > 180 else "") if limit else text)


def render_reference_standard(value, *, historical=True, summary=False):
    """Readable saved fields; absence never falls back to the current library."""
    from src.ui.samples import parse_gold_answer_for_display

    if not value:
        st.caption(
            "历史记录未保存运行时专业标准答案；不使用当前题库补造评分依据。"
            if historical
            else "当前任务未保存专业评价要求。"
        )
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

    def render(items):
        for label, content in items:
            st.markdown(f"**{label}**")
            if not content or content == "待补充":
                st.caption("未记录。")
            elif isinstance(content, list):
                for index, item in enumerate(content, 1):
                    st.text(f"{index}. {item}")
            else:
                st.text(str(content))

    if summary:
        primary = {"参考判断", "必须覆盖的要点", "不可接受错误"}
        render([(label, value) for label, value in sections if label in primary])
        with st.expander("依据与适用边界"):
            render([(label, value) for label, value in sections if label not in primary])
    else:
        render(sections)


def _check_priority(check):
    if check.get("kind") == "forbidden" and check.get("status") == "not_met":
        return 0
    return {"not_met": 1, "partial": 2, "unknown": 3, "met": 4}.get(check.get("status"), 3)


def _summary_checks(checks, *, limit=3):
    ordered = sorted(checks, key=_check_priority)
    return ordered[: max(limit, sum(_check_priority(c) == 0 for c in ordered))]


def _render_dimensions(score, dimensions):
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
            st.caption("历史维度定义未保存；满分未知，仅展示原始字段与分数。")
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("没有可读取的维度分数。")


def evidence_gaps(task, gold, score, answer):
    gaps = []
    fields = list(_task_fields(task))
    if not any(label == "任务" for label, _ in fields):
        gaps.append("当时的任务材料")
    elif not any(label in {"业务背景", "背景", "材料"} for label, _ in fields):
        gaps.append("业务背景")
    if not gold:
        gaps.append("参考标准")
    checks = [c for c in _array(score, "checks_json") if isinstance(c, dict)]
    if not checks or not any(quote_matches(c.get("quote"), answer) for c in checks):
        gaps.append("可核对的回答引文")
    elif any(c.get("quote") and not quote_matches(c.get("quote"), answer) for c in checks):
        gaps.append("部分引文无法核对")
    if not score.get("rationale") and not score.get("review_note"):
        gaps.append("评分理由")
    return gaps


def render_portfolio_evaluation(*, answer, score, dimensions, gold, metadata, historical=True):
    """Answer then professional review; all original evidence remains inspectable."""
    raw_answer, raw_score = str(answer or ""), dict(score or {})
    answer, score = str(_safe(raw_answer)), _safe(raw_score)
    checks = [c for c in _array(raw_score, "checks_json") if isinstance(c, dict)]
    summaries = _summary_checks(checks)
    with st.container(key="portfolio_case_result"):
        left, right = st.columns([3, 2], gap="medium")
        with left, st.container(key="portfolio_case_answer"):
            st.subheader("模型回答")
            if answer:
                st.text(answer)
            else:
                st.caption("尚无可读取的模型回答。")
        with right, st.container(key="portfolio_case_rating"):
            st.subheader("专业评价")
            if score.get("judge_status") == "failed":
                from src.ui.evaluation_feedback import failure_label

                st.warning(failure_label(score) + "：模型回答已保存，本次没有有效评分。")
            if score:
                st.metric("AI评分", _score_value(score))
                marks = [d.get("full_mark") for d in dimensions]
                st.caption(
                    f"满分 {sum(marks):g} · AI自动评分，需人工核对。"
                    if marks and all(isinstance(v, (int, float)) for v in marks)
                    else "历史满分未记录 · AI自动评分，需人工核对。"
                )
            else:
                st.caption("任务设计示例，尚无评分记录。")
            for check in summaries:
                _render_check(check, raw_answer, summary=True)
            if any(
                c.get("quote") and not quote_matches(c.get("quote"), raw_answer) for c in checks if c not in summaries
            ):
                st.warning("部分引用不在模型回答原文中，不能作为可靠证据；详见完整评价依据。")
            if not summaries:
                if score.get("review_note"):
                    st.text(str(score["review_note"]))
                elif score.get("rationale"):
                    _rationale(score, dimensions, limit=2, readable=True)
    with st.expander("查看完整评价依据"):
        if score:
            st.markdown("**各维度评分**")
            _render_dimensions(score, dimensions)
            st.markdown("**全部检查要点**")
            if not checks:
                st.caption("历史记录未保存检查要点与回答引文。")
            for check in checks:
                _render_check(check, raw_answer)
            if _array(raw_score, "numeric_checks_json"):
                st.markdown("**程序数值核查**")
                st.dataframe(_safe(_array(raw_score, "numeric_checks_json")), hide_index=True, width="stretch")
                st.caption("仅核对预设公式，不改变评分；未找到明确数值不等于错误。")
            st.markdown("**评分理由**")
            _rationale(score, dimensions)
            if score.get("review_note"):
                st.text(str(score["review_note"]))
            if not score.get("rationale") and not score.get("review_note"):
                st.caption("历史记录未保存评分理由。")
        st.markdown("**参考答案与评价标准**" if historical else "**当前任务参考答案与评价标准**")
        render_reference_standard(gold, historical=historical)
    with st.expander("原始技术记录"):
        st.json(_safe(dict(metadata, score=raw_score, reference_standard=gold, dimensions=dimensions)), expanded=False)


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
    # A recorded unacceptable error must never disappear behind the summary cap.
    summary_checks = _summary_checks(checks)
    with st.container(key=f"score_detail_{key}"):
        right, left = st.columns([2, 3], gap="large")
        with right:
            with st.container(key=f"score_review_{key}"):
                st.markdown("**评价结果**")
                st.metric("AI评分", _score_value(score))
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
        _render_dimensions(score, dimensions)
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
