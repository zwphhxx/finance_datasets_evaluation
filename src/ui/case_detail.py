from __future__ import annotations

import re
from html import escape

import pandas as pd
import streamlit as st

from src.metrics import (
    ERROR_TYPE_TO_DIMENSION,
    get_case_ids,
    get_errors_for_output,
    get_preference_pair_details_for_case,
    get_task_by_case_id,
    merge_case_outputs_with_scores,
)
from src.ui.common import has_value
from src.gold_quality import evaluate_gold_quality, field_list, field_text
from src.ui.page_config import get_page_config
from src.ui.tasks import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    RISK_LABELS,
    TASK_TYPE_LABELS,
    display_label,
    summarize_text,
)
from src.ui.components import (
    render_answer_boundary_panel,
    render_card,
    render_empty_state,
    render_html,
    render_info_panel,
    render_preference_comparison,
    render_page_shell,
    render_section_title,
)


# Rubric definition: dimension column, Chinese label, full marks, and the
# evaluation basis the dimension checks. Full marks sum to 100 and match the
# stored total_score; this is rubric methodology, not per-case data.
RUBRIC = [
    ("accuracy_score", "专业准确性", 30, "结论与关键计算是否准确，并对照判断依据。"),
    ("reasoning_score", "推理与场景适配", 20, "分析逻辑是否完整，是否贴合任务场景。"),
    ("coverage_score", "风险覆盖", 20, "是否覆盖必须关注的风险点与核查事项。"),
    ("evidence_score", "依据可靠性", 15, "是否提供法规、数据等可靠依据支撑结论。"),
    ("expression_score", "专业表达", 15, "表达是否清晰、审慎，符合专业报告风格。"),
]

SEVERITY_BADGE = {"高": "danger", "中": "warning", "低": "neutral"}
PRIORITY_BADGE = {"高": "danger", "中": "warning", "低": "neutral"}

ANSWER_SUMMARY_LIMIT = 220


# --- data derivation (pure, dynamic on case + model) --------------------------

def get_case_models(merged_outputs: pd.DataFrame) -> list[str]:
    if merged_outputs.empty or "model_name" not in merged_outputs:
        return []
    return sorted(merged_outputs["model_name"].dropna().astype(str).unique().tolist())


def get_output_row(merged_outputs: pd.DataFrame, model_name: str) -> pd.Series | None:
    if merged_outputs.empty or "model_name" not in merged_outputs:
        return None
    rows = merged_outputs[merged_outputs["model_name"].astype(str) == str(model_name)]
    if rows.empty:
        return None
    return rows.iloc[0]


def build_rubric_rows(score_row: pd.Series) -> list[dict]:
    rows = []
    for column, label, full, basis in RUBRIC:
        if not has_value(score_row.get(column)):
            continue
        score = float(score_row.get(column))
        ratio = score / full if full else 0.0
        if ratio >= 0.85:
            level_text, level_class = "达标", "success"
        elif ratio >= 0.6:
            level_text, level_class = "部分达标", "warning"
        else:
            level_text, level_class = "需改进", "danger"
        rows.append(
            {
                "dimension": label,
                "score": score,
                "full": full,
                "gap": full - score,
                "level_text": level_text,
                "level_class": level_class,
                "basis": basis,
            }
        )
    return rows


def _optimization_lookup(optimization_df: pd.DataFrame) -> dict[str, dict]:
    if optimization_df.empty or "frequent_error" not in optimization_df:
        return {}
    return {
        str(row["frequent_error"]): row.to_dict()
        for _, row in optimization_df.iterrows()
    }


def build_error_attribution(errors_df: pd.DataFrame, optimization_df: pd.DataFrame, output_id) -> list[dict]:
    """Errors tied to one model output, joined to a likely data cause."""
    errors = get_errors_for_output(errors_df, output_id)
    if errors.empty:
        return []
    lookup = _optimization_lookup(optimization_df)
    records = []
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        plan = lookup.get(error_type, {})
        likely_cause = _text(plan.get("likely_cause"), _text(error.get("correction"), "暂无记录"))
        records.append(
            {
                "error_type": error_type,
                "severity": _text(error.get("severity"), "未标注"),
                "description": _text(error.get("error_description"), "暂无说明"),
                "likely_cause": likely_cause,
            }
        )
    return records


def build_data_fix_actions(errors_df: pd.DataFrame, optimization_df: pd.DataFrame, output_id) -> list[dict]:
    """Executable data actions, one per distinct error label of this output."""
    errors = get_errors_for_output(errors_df, output_id)
    if errors.empty:
        return []
    lookup = _optimization_lookup(optimization_df)
    records = []
    seen = set()
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        if error_type in seen:
            continue
        seen.add(error_type)
        plan = lookup.get(error_type, {})
        action = _text(plan.get("optimization_action"), _text(error.get("optimization_action"), "暂无对应动作"))
        records.append(
            {
                "error_type": error_type,
                "action": action,
                "sample_format": _text(plan.get("data_sample_format"), "暂无样本格式"),
                "priority": _text(plan.get("priority"), "未标注"),
                "typical_problem": _text(plan.get("typical_problem"), ""),
            }
        )
    return records


def build_point_coverage(points, answer_text) -> tuple[list[str], list[str]]:
    """Approximate which must-have points the answer covers, by keyword match.

    Coverage is a presentation heuristic over the answer text, not stored data;
    it works for any case/model and is labelled as approximate in the UI.
    """
    answer = _normalize_text(answer_text)
    covered: list[str] = []
    missed: list[str] = []
    for point in points:
        text = str(point).strip()
        if not text:
            continue
        keywords = [token for token in re.split(r"[，。、；：（）()/\s,.;:]+", text) if len(token) >= 3]
        if keywords:
            hit = any(_normalize_text(token) in answer for token in keywords)
        else:
            hit = _normalize_text(text) in answer
        (covered if hit else missed).append(text)
    return covered, missed


def _normalize_text(value) -> str:
    return re.sub(r"\s+", "", str(value))


def _has_red_line(errors_df, output_id) -> bool:
    """A red-line error is triggered when this output carries a high-severity label."""
    errors = get_errors_for_output(errors_df, output_id)
    if errors.empty or "severity" not in errors.columns:
        return False
    return any(_text(value) == "高" for value in errors["severity"].tolist())


def _errors_by_dimension(errors_df, output_id):
    """Bucket this output's error labels under the Rubric dimension each affects."""
    errors = get_errors_for_output(errors_df, output_id)
    by_dimension: dict[str, list[tuple[str, str]]] = {}
    unmapped: list[tuple[str, str]] = []
    if errors.empty:
        return by_dimension, unmapped
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        severity = _text(error.get("severity"), "")
        dimension = ERROR_TYPE_TO_DIMENSION.get(error_type)
        if dimension:
            by_dimension.setdefault(dimension, []).append((error_type, severity))
        else:
            unmapped.append((error_type, severity))
    return by_dimension, unmapped


def _score_badge_level(score) -> str:
    if not has_value(score):
        return "neutral"
    value = float(score)
    if value >= 80:
        return "success"
    if value >= 60:
        return "warning"
    return "danger"


# --- rendering ---------------------------------------------------------------

def render_case_detail_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    render_page_shell(get_page_config("case_detail"))

    case_ids = get_case_ids(data.tasks)
    if not case_ids:
        render_empty_state("暂无可展示数据")
        return

    domain_by_case = _domain_by_case(data.tasks)
    select_left, select_right = st.columns(2)
    selected_case = select_left.selectbox(
        "选择任务",
        case_ids,
        format_func=lambda case_id: f"{case_id} · {domain_by_case.get(case_id, '未标注领域')}",
    )

    task_rows = get_task_by_case_id(data.tasks, selected_case)
    if task_rows.empty:
        render_empty_state("未找到该任务的记录。")
        return
    task_info = task_rows.iloc[0]

    merged = merge_case_outputs_with_scores(data.model_outputs, data.scores, selected_case)
    models = get_case_models(merged)
    if models:
        selected_model = select_right.selectbox("选择模型", models, key="case_detail_model")
        output_row = get_output_row(merged, selected_model)
    else:
        select_right.selectbox("选择模型", ["暂无模型回答"], disabled=True)
        output_row = None

    gold = data.gold_answer_map.get(selected_case)

    # Screen 1 — task brief vs model performance
    left, right = st.columns(2, gap="large")
    with left:
        _render_task_brief(task_info)
    with right:
        _render_model_performance(output_row, data.errors)

    st.divider()

    # Screen 2 — evaluation standard vs model answer
    left, right = st.columns(2, gap="large")
    with left:
        _render_gold_standard(gold)
    with right:
        _render_model_answer(output_row, gold, data.errors)

    st.divider()

    # Screen 3 — single scoring matrix
    _render_scoring_matrix(output_row, data.errors)

    _render_preference_section(data.preference_pairs, data.model_outputs, selected_case)


def _render_task_brief(task_info: pd.Series) -> None:
    render_section_title("任务题")
    background = _text(task_info.get("context"), "暂无背景材料")
    requirement = _text(task_info.get("question"), _text(task_info.get("scenario"), "暂无任务要求"))
    capability = _text(task_info.get("expected_capability"), "暂无考察能力说明")
    domain = display_label(task_info.get("domain"), DOMAIN_LABELS)
    task_type = display_label(task_info.get("task_type"), TASK_TYPE_LABELS)
    difficulty = DIFFICULTY_LABELS.get(_text(task_info.get("difficulty")), _text(task_info.get("difficulty")))
    risk = RISK_LABELS.get(_text(task_info.get("risk_level")), _text(task_info.get("risk_level")))
    boundary = f"{domain} · {task_type} · 难度 {difficulty} · 风险 {risk}"

    fields = [
        ("任务背景", summarize_text(background, 160)),
        ("任务要求", summarize_text(requirement, 160)),
        ("考察能力", capability),
        ("数据边界", boundary),
    ]
    render_card(
        "".join(
            f'<div class="fact-field"><div class="fact-label">{escape(label)}</div>'
            f'<div class="fact-value">{escape(value)}</div></div>'
            for label, value in fields
        ),
        class_name="fact-card",
    )
    if len(background) > 160 or len(requirement) > 160:
        with st.expander("查看任务全文"):
            st.markdown("**任务要求**")
            st.write(requirement)
            if background and background != "暂无背景材料":
                st.markdown("**任务背景**")
                st.write(background)


def _render_model_performance(output_row: pd.Series | None, errors_df) -> None:
    render_section_title("模型表现")
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录。")
        return

    rubric_rows = build_rubric_rows(output_row)
    total = output_row.get("total_score")
    total_text = f"{float(total):.0f}" if has_value(total) else "未评分"
    score_badge = f'<span class="status-badge status-{_score_badge_level(total)}">{escape(total_text)}</span>'

    if rubric_rows:
        weakest = min(rubric_rows, key=lambda row: (row["score"] / row["full"] if row["full"] else 0.0))
        weak_text = f'{weakest["dimension"]}（{weakest["score"]:.0f}/{weakest["full"]}）'
    else:
        weak_text = "暂无分项评分"

    review = _text(output_row.get("review_note"), "暂无扣分说明")
    triggered = _has_red_line(errors_df, output_row.get("output_id"))
    red_badge = (
        '<span class="status-badge status-danger">触发</span>'
        if triggered
        else '<span class="status-badge status-success">未触发</span>'
    )

    render_html(
        '<div class="fact-card">'
        f'<div class="fact-field"><div class="fact-label">总分</div><div class="fact-value">{score_badge}</div></div>'
        f'<div class="fact-field"><div class="fact-label">维度短板</div><div class="fact-value">{escape(weak_text)}</div></div>'
        f'<div class="fact-field"><div class="fact-label">主要扣分原因</div><div class="fact-value">{escape(summarize_text(review, 160))}</div></div>'
        f'<div class="fact-field"><div class="fact-label">是否触发红线错误</div><div class="fact-value">{red_badge}</div></div>'
        "</div>"
    )
    if len(review) > 160:
        with st.expander("查看完整扣分说明"):
            st.write(review)


def _render_gold_standard(gold: dict | None) -> None:
    render_section_title("Gold Answer / 评测标准")
    if not isinstance(gold, dict):
        render_empty_state("该任务暂无 Gold Answer 记录。")
        return

    quality = evaluate_gold_quality(gold)
    status_class = "success" if quality["is_usable"] else "warning"
    render_html(
        f'<span class="status-badge status-{status_class}">当前 Gold Answer {escape(quality["status"])}</span>'
    )

    render_answer_boundary_panel(
        "评测标准",
        [
            ("标准结论", field_text(gold, "core_conclusion", "需进一步补充")),
            ("判断依据", field_text(gold, "key_evidence", "待补充依据")),
            ("边界条件", field_text(gold, "boundary_conditions", "待补充边界")),
        ],
    )

    must_points = field_list(gold, "must_have_points")
    if must_points:
        render_html(
            '<div class="fact-label">必须覆盖点</div><div class="boundary-list">'
            + "".join(f'<div class="point-item">{escape(str(point))}</div>' for point in must_points)
            + "</div>"
        )

    red_lines = field_list(gold, "unacceptable_errors")
    if red_lines:
        render_html(
            '<div class="fact-label">不可接受错误（红线）</div><div class="boundary-list">'
            + "".join(f'<div class="redline-item">{escape(str(item))}</div>' for item in red_lines)
            + "</div>"
        )

    review = quality["manual_review"]
    if review:
        st.caption(f"人工复核提示：{review}")


def _render_model_answer(output_row: pd.Series | None, gold, errors_df) -> None:
    render_section_title("模型回答")
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录。")
        return

    answer = _text(output_row.get("answer_text"), "暂无回答内容。")
    render_card(
        '<div class="fact-field"><div class="fact-label">回答摘要</div>'
        f'<div class="fact-value">{escape(summarize_text(answer, ANSWER_SUMMARY_LIMIT))}</div></div>',
        class_name="fact-card",
    )
    if len(answer) > ANSWER_SUMMARY_LIMIT:
        with st.expander("查看完整模型回答"):
            st.write(answer)

    must_points = field_list(gold, "must_have_points") if isinstance(gold, dict) else []
    if must_points:
        covered, missed = build_point_coverage(must_points, answer)
        st.caption("要点覆盖基于关键词近似匹配，仅供对照参考。")
        if covered:
            render_html(
                '<div class="fact-label">已覆盖要点</div><div class="boundary-list">'
                + "".join(f'<div class="point-item">{escape(point)}</div>' for point in covered)
                + "</div>"
            )
        if missed:
            render_html(
                '<div class="fact-label">遗漏要点</div><div class="boundary-list">'
                + "".join(f'<div class="redline-item">{escape(point)}</div>' for point in missed)
                + "</div>"
            )

    errors = get_errors_for_output(errors_df, output_row.get("output_id"))
    if not errors.empty:
        badges = "".join(
            f'<span class="status-badge status-{SEVERITY_BADGE.get(_text(error.get("severity")), "neutral")}">'
            f'{escape(_text(error.get("error_type"), "未分类错误"))}</span>'
            for _, error in errors.iterrows()
        )
        render_html(f'<div class="fact-label">错误标签</div><div class="task-card-badges">{badges}</div>')
    else:
        render_html('<div class="fact-label">错误标签</div><div class="fact-value">未触发错误标签。</div>')


def _render_scoring_matrix(output_row: pd.Series | None, errors_df) -> None:
    render_section_title("评分矩阵", "维度、权重、Gold 要求、模型得分、扣分与对应错误标签。")
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    rubric_rows = build_rubric_rows(output_row)
    if not rubric_rows:
        render_empty_state("当前模型回答尚未配置分项评分。")
        return

    by_dimension, unmapped = _errors_by_dimension(errors_df, output_row.get("output_id"))
    header = (
        "<th>评分维度</th><th>权重</th><th>Gold 要求</th>"
        "<th>模型得分</th><th>扣分原因</th><th>对应错误标签</th>"
    )
    body = ""
    for row in rubric_rows:
        reason = "未扣分" if row["gap"] <= 0 else f'扣 {row["gap"]:.0f} 分（{row["level_text"]}）'
        dimension_errors = by_dimension.get(row["dimension"], [])
        if dimension_errors:
            labels = "".join(
                f'<span class="status-badge status-{SEVERITY_BADGE.get(severity, "neutral")}">{escape(error_type)}</span>'
                for error_type, severity in dimension_errors
            )
        else:
            labels = '<span class="rubric-gap">—</span>'
        body += (
            f'<tr><td><span class="rubric-dim">{escape(row["dimension"])}</span></td>'
            f'<td><span class="rubric-gap">{row["full"]}</span></td>'
            f'<td><span class="rubric-evidence">{escape(row["basis"])}</span></td>'
            f'<td><span class="rubric-score">{row["score"]:.0f} / {row["full"]}</span></td>'
            f'<td><span class="rubric-gap">{escape(reason)}</span></td>'
            f"<td>{labels}</td></tr>"
        )
    render_html(
        '<table class="rubric-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    if unmapped:
        extra = "、".join(f"{error_type}（{severity}）" for error_type, severity in unmapped)
        st.caption(f"其他错误标签：{extra}")


def _render_preference_section(preference_pairs_df, model_outputs_df, selected_case: str) -> None:
    pairs = get_preference_pair_details_for_case(preference_pairs_df, model_outputs_df, selected_case)
    if pairs.empty:
        return

    render_section_title("偏好样本对照", "同题不同回答的偏好判断，用于沉淀改进方向。")
    for _, pair in pairs.iterrows():
        preferred_meta = (
            f"output_id {_display(pair.get('preferred_output_id'), '暂无')} · "
            f"{_display(pair.get('preferred_model_name'), '未标注模型')}"
        )
        rejected_meta = (
            f"output_id {_display(pair.get('rejected_output_id'), '暂无')} · "
            f"{_display(pair.get('rejected_model_name'), '未标注模型')}"
        )
        with st.expander(
            f"{_display(pair.get('pair_id'), '偏好样本')} · {_display(pair.get('preference_dimension'), '未标注维度')}",
            expanded=False,
        ):
            if has_value(pair.get("preference_reason")):
                render_info_panel("偏好理由", _text(pair.get("preference_reason")))
            render_preference_comparison(
                "偏好回答",
                pair.get("preferred_answer_text"),
                "对照回答",
                pair.get("rejected_answer_text"),
                preferred_meta=preferred_meta,
                rejected_meta=rejected_meta,
            )


# --- small helpers -----------------------------------------------------------

def _domain_by_case(tasks_df: pd.DataFrame) -> dict[str, str]:
    if tasks_df.empty or "case_id" not in tasks_df:
        return {}
    return {
        str(row.get("case_id")): display_label(row.get("domain"), DOMAIN_LABELS)
        for _, row in tasks_df.iterrows()
    }


def _text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def _display(value, fallback: str) -> str:
    return str(value) if has_value(value) else fallback
