from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.metrics import (
    get_case_ids,
    get_errors_for_output,
    get_preference_pair_details_for_case,
    get_task_by_case_id,
    merge_case_outputs_with_scores,
)
from src.ui.common import has_value
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
    render_context_grid,
    render_empty_state,
    render_html,
    render_info_panel,
    render_model_answer_card,
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


# --- rendering ---------------------------------------------------------------

def render_case_detail_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    render_page_shell(get_page_config("case_detail"))

    case_ids = get_case_ids(data.tasks)
    if not case_ids:
        render_empty_state("暂无可展示数据")
        return

    domain_by_case = _domain_by_case(data.tasks)
    selected_case = st.selectbox(
        "选择样板题",
        case_ids,
        format_func=lambda case_id: f"{case_id} · {domain_by_case.get(case_id, '未标注领域')}",
    )

    task_rows = get_task_by_case_id(data.tasks, selected_case)
    if task_rows.empty:
        render_empty_state("未找到该案例的任务信息。")
        return
    task_info = task_rows.iloc[0]

    merged = merge_case_outputs_with_scores(data.model_outputs, data.scores, selected_case)

    left, right = st.columns([1, 1], gap="large")
    with left:
        _render_task_panel(task_info)
        _render_gold_answer(data.gold_answer_map.get(selected_case))
    with right:
        selected_output = _render_model_panel(merged, selected_case)

    st.divider()
    _render_rubric_breakdown(selected_output)
    _render_error_attribution(data.errors, data.optimizations, selected_output)
    _render_data_fix_actions(data.errors, data.optimizations, selected_output)
    _render_preference_section(data.preference_pairs, data.model_outputs, selected_case)


def _render_task_panel(task_info: pd.Series) -> None:
    render_section_title("任务题与评测标准")

    domain = display_label(task_info.get("domain"), DOMAIN_LABELS)
    task_type = display_label(task_info.get("task_type"), TASK_TYPE_LABELS)
    difficulty = DIFFICULTY_LABELS.get(_text(task_info.get("difficulty")), _text(task_info.get("difficulty")))
    risk = RISK_LABELS.get(_text(task_info.get("risk_level")), _text(task_info.get("risk_level")))
    render_html(
        f"""
        <div class="task-card-tags">
            <span class="tag tag-domain">{escape(domain)}</span>
            <span class="tag tag-type">{escape(task_type)}</span>
            <span class="status-badge status-medium">{escape(difficulty)}</span>
            <span class="status-badge status-high">{escape(risk)}</span>
        </div>
        """
    )

    scenario = _text(task_info.get("scenario"), _text(task_info.get("question"), "暂无任务场景"))
    capability = _text(task_info.get("expected_capability"), "暂无任务要求")
    context = _text(task_info.get("context"), "")
    fields = [("任务场景", scenario), ("任务要求", capability)]
    if context:
        fields.append(("背景材料", context))
    render_card(
        "".join(
            f'<div class="fact-field"><div class="fact-label">{escape(label)}</div>'
            f'<div class="fact-value">{escape(value)}</div></div>'
            for label, value in fields
        ),
        class_name="fact-card",
    )


def _render_gold_answer(gold_answer: dict | None) -> None:
    if not gold_answer:
        render_empty_state("该样板题暂无 Gold Answer 记录。")
        return

    render_info_panel("Gold Answer 摘要", _text(gold_answer.get("conclusion"), "暂无标准结论"))

    render_answer_boundary_panel(
        "Gold Answer 边界",
        [
            ("判断依据", gold_answer.get("basis")),
            ("分析逻辑", gold_answer.get("analysis")),
            ("需核查资料", gold_answer.get("materials_to_check")),
            ("风险边界", gold_answer.get("risk_boundary")),
        ],
    )

    must_points = _as_list(gold_answer.get("must_have_points"))
    if must_points:
        render_section_title("必须覆盖要点")
        render_html(
            '<div class="boundary-list">'
            + "".join(f'<div class="point-item">{escape(str(point))}</div>' for point in must_points)
            + "</div>"
        )

    red_lines = _as_list(gold_answer.get("red_line_errors"))
    if red_lines:
        render_section_title("不可接受错误（红线）")
        render_html(
            '<div class="boundary-list">'
            + "".join(f'<div class="redline-item">{escape(str(item))}</div>' for item in red_lines)
            + "</div>"
        )


def _render_model_panel(merged: pd.DataFrame, selected_case: str) -> pd.Series | None:
    render_section_title("模型表现")
    models = get_case_models(merged)
    if not models:
        render_empty_state("该样板题暂无模型回答记录。")
        return None

    selected_model = st.selectbox("选择模型", models, key="case_detail_model")
    output_row = get_output_row(merged, selected_model)
    if output_row is None:
        render_empty_state("该模型在当前样板题暂无回答记录。")
        return None

    output_id = _display(output_row.get("output_id"), "暂无")
    full_answer = _text(output_row.get("answer_text"), "暂无回答内容。")
    render_model_answer_card(
        selected_model,
        summarize_text(full_answer, ANSWER_SUMMARY_LIMIT),
        score=output_row.get("total_score") if has_value(output_row.get("total_score")) else None,
        meta=f"output_id {output_id}",
    )
    if len(full_answer) > ANSWER_SUMMARY_LIMIT:
        with st.expander("查看完整模型回答"):
            st.write(full_answer)

    rubric_rows = build_rubric_rows(output_row)
    if rubric_rows:
        render_context_grid(
            [(row["dimension"], f"{row['score']:.0f} / {row['full']}") for row in rubric_rows]
        )

    review_note = _text(output_row.get("review_note"), "")
    if review_note:
        render_info_panel("关键扣分原因", review_note)
    return output_row


def _render_rubric_breakdown(output_row: pd.Series | None) -> None:
    render_section_title("Rubric 评分明细", "维度、得分、扣分点与评测依据。")
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    rubric_rows = build_rubric_rows(output_row)
    if not rubric_rows:
        render_empty_state("当前模型回答尚未配置分项评分。")
        return

    body = "".join(
        f"<tr>"
        f'<td><span class="rubric-dim">{escape(row["dimension"])}</span></td>'
        f'<td><span class="rubric-score">{row["score"]:.0f} / {row["full"]}</span></td>'
        f'<td><span class="rubric-gap">扣 {row["gap"]:.0f}</span></td>'
        f'<td><span class="status-badge status-{row["level_class"]}">{escape(row["level_text"])}</span></td>'
        f'<td><span class="rubric-evidence">{escape(row["basis"])}</span></td>'
        f"</tr>"
        for row in rubric_rows
    )
    render_html(
        '<table class="rubric-table"><thead><tr>'
        "<th>评分维度</th><th>得分</th><th>扣分点</th><th>达标情况</th><th>评测依据</th>"
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def _render_error_attribution(errors_df, optimization_df, output_row: pd.Series | None) -> None:
    render_section_title("错误归因", "针对当前模型回答的错误标签与可能数据原因。")
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    records = build_error_attribution(errors_df, optimization_df, output_row.get("output_id"))
    if not records:
        render_html(
            '<div class="evidence-card evidence-card-clean">'
            '<div class="evidence-head"><span class="evidence-title">当前模型回答未触发错误标签</span>'
            '<span class="status-badge status-success">无红线错误</span></div>'
            "</div>"
        )
        return

    for record in records:
        severity_class = SEVERITY_BADGE.get(record["severity"], "neutral")
        render_html(
            f"""
            <div class="evidence-card evidence-card-flagged">
                <div class="evidence-head">
                    <span class="evidence-title">{escape(record["error_type"])}</span>
                    <span class="status-badge status-{severity_class}">严重程度 {escape(record["severity"])}</span>
                </div>
                <div class="evidence-field">
                    <div class="evidence-label">错误说明</div>
                    <div class="evidence-value">{escape(record["description"])}</div>
                </div>
                <div class="evidence-field">
                    <div class="evidence-label">可能的数据原因</div>
                    <div class="evidence-value">{escape(record["likely_cause"])}</div>
                </div>
            </div>
            """
        )


def _render_data_fix_actions(errors_df, optimization_df, output_row: pd.Series | None) -> None:
    render_section_title("数据补强建议", "对应错误标签的可执行数据动作。")
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    records = build_data_fix_actions(errors_df, optimization_df, output_row.get("output_id"))
    if not records:
        render_empty_state("当前模型回答无错误标签，暂无数据补强动作。")
        return

    for record in records:
        priority_class = PRIORITY_BADGE.get(record["priority"], "neutral")
        problem_html = (
            f'<div class="evidence-field"><div class="evidence-label">典型问题</div>'
            f'<div class="evidence-value">{escape(record["typical_problem"])}</div></div>'
            if record["typical_problem"]
            else ""
        )
        render_html(
            f"""
            <div class="evidence-card">
                <div class="evidence-head">
                    <span class="status-badge status-neutral">{escape(record["error_type"])}</span>
                    <span class="status-badge status-{priority_class}">优先级 {escape(record["priority"])}</span>
                </div>
                <div class="evidence-field">
                    <div class="evidence-label">数据补强动作</div>
                    <div class="evidence-value">{escape(record["action"])}</div>
                </div>
                <div class="evidence-field">
                    <div class="evidence-label">样本格式</div>
                    <div class="evidence-value">{escape(record["sample_format"])}</div>
                </div>
                {problem_html}
            </div>
            """
        )


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


def _as_list(value) -> list:
    if isinstance(value, list):
        return [item for item in value if has_value(item)]
    if has_value(value):
        return [value]
    return []


def _text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def _display(value, fallback: str) -> str:
    return str(value) if has_value(value) else fallback
