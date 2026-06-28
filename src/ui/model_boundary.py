from __future__ import annotations

from html import escape

import streamlit as st

from src.data_service import load_dataset_manifest
from src.model_boundary import (
    BOUNDARY_AWARENESS_LABEL,
    build_boundary_matrix,
    build_data_actions,
    build_data_boundary,
    build_frequent_risks,
    summarize_usage_tiers,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import DOMAIN_LABELS, TASK_TYPE_LABELS, display_label
from src.ui.components import (
    render_card,
    render_context_grid,
    render_empty_state,
    render_html,
    render_info_panel,
    render_page_shell,
    render_section_title,
)


# 使用边界三类对应的低饱和状态色：可直接使用=浅绿，需人工复核=米色，不可直接使用=浅玫瑰。
_TIER_BADGE_LEVEL = {
    "direct": "success",
    "review": "warning",
    "not_direct": "danger",
}


def render_model_boundary_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    render_page_shell(get_page_config("model_boundary"))

    if data.tasks.empty or data.scores.empty:
        render_empty_state("暂无可展示数据")
        return

    manifest = load_dataset_manifest()
    _render_data_boundary(build_data_boundary(data, manifest))
    _render_usage_tiers(summarize_usage_tiers(data))
    _render_frequent_risks(build_frequent_risks(data))
    _render_data_actions(build_data_actions(data))
    _render_dimension_matrix(build_boundary_matrix(data))

    st.caption(
        "本页结论由当前评分、错误标签与 Gold Answer 边界动态归纳，仅用于样本内观察，"
        "不构成模型采购或业务决策建议。"
    )


def _render_data_boundary(boundary: dict) -> None:
    render_section_title("数据边界", "先看清结论建立在什么样本与版本上。")
    render_context_grid(
        [
            (
                "当前样本量",
                f"{boundary['task_count']} 道任务 · {boundary['model_count']} 个模型 · "
                f"{boundary['output_count']} 条模型回答",
            ),
            ("数据集版本", boundary["version"]),
            (
                "模型回答来源",
                "模拟生成（未接入真实模型 API）" if boundary["simulated_answers"] else "真实模型回答",
            ),
            ("结论适用范围", boundary["scope_note"]),
        ]
    )


def _tier_task_type_text(task_types: list[str]) -> str:
    if not task_types:
        return "暂无任务"
    labels = [display_label(task_type, TASK_TYPE_LABELS) for task_type in task_types]
    return "、".join(labels)


def _tier_score_text(summary: dict) -> str:
    low, high = summary.get("score_low"), summary.get("score_high")
    if low is None or high is None:
        return "暂无评分"
    if abs(high - low) < 0.05:
        return f"平均分约 {low:.1f}"
    return f"平均分区间 {low:.1f}–{high:.1f}"


def _render_usage_tiers(summaries: list[dict]) -> None:
    render_section_title(
        "模型可用边界",
        "按风险等级、能力下限与是否触发红线错误，将任务归入三类使用边界。",
    )
    for summary in summaries:
        level = _TIER_BADGE_LEVEL.get(summary["key"], "neutral")
        count = summary["count"]
        if count == 0:
            detail = "当前样本中暂无归入此类的任务。"
        else:
            redline = summary.get("redline_hits", 0)
            redline_text = (
                f"，其中 {redline} 道已观察到高严重度红线类错误" if redline > 0 else ""
            )
            detail = (
                f"{_tier_score_text(summary)}{redline_text}。"
                f"任务类型：{_tier_task_type_text(summary['task_types'])}。"
            )
        render_card(
            f"""
            <div class="model-answer-header">
                <strong>{escape(summary['title'])}</strong>
                <span class="status-badge status-{level}">{count} 道任务</span>
            </div>
            <div class="panel-content">{escape(summary['definition'])}</div>
            <div class="task-card-field">
                <div class="task-card-value">{escape(detail)}</div>
            </div>
            """,
            class_name="fde-card",
        )


def _render_frequent_risks(risks: list[dict]) -> None:
    render_section_title("高频风险", "按错误标签出现次数排序，对应受影响的评分维度。")
    if not risks:
        render_empty_state("当前暂无错误标签，无法归纳高频风险。")
        return

    header = (
        "<th>风险类型</th><th>出现次数</th><th>主要影响维度</th>"
        "<th>涉及模型数</th><th>涉及案例数</th>"
    )
    body = ""
    for risk in risks:
        body += (
            f'<tr><td class="check-key">{escape(risk["error_type"])}</td>'
            f'<td class="check-count">{risk["count"]}</td>'
            f'<td>{escape(risk["dimension"])}</td>'
            f'<td class="check-count">{risk["model_count"]}</td>'
            f'<td class="check-count">{risk["case_count"]}</td></tr>'
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )
    st.caption("出现次数与涉及模型/案例数均按当前错误标签统计，反映样本内的集中风险点。")


def _render_data_actions(actions: list[dict]) -> None:
    render_section_title("数据补强方向", "由高频错误关联到既有优化计划中的数据补强动作与验证指标。")
    if not actions:
        render_empty_state("当前暂无可关联的数据补强动作。")
        return

    header = "<th>对应风险</th><th>出现次数</th><th>数据补强动作</th><th>验证指标</th>"
    body = ""
    for action in actions:
        body += (
            f'<tr><td class="check-key">{escape(action["error_type"])}</td>'
            f'<td class="check-count">{action["count"]}</td>'
            f'<td>{escape(action["data_action"])}</td>'
            f'<td class="check-note">{escape(action["validation_metric"])}</td></tr>'
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )


def _render_dimension_matrix(matrix: dict) -> None:
    render_section_title(
        "模型维度矩阵",
        "行为模型，列为事实依据、推理完整性、风险识别、专业表达与边界意识。",
    )
    if not matrix["rows"]:
        render_empty_state("当前暂无分维度评分数据。")
        return

    header = "<th>模型</th>" + "".join(
        f"<th>{escape(dimension)}</th>" for dimension in matrix["dimensions"]
    )
    body = ""
    for row in matrix["rows"]:
        cells = ""
        for cell in row["cells"]:
            cells += (
                f'<td><span class="status-badge status-{cell["level"]}">'
                f'{escape(str(cell["text"]))}</span></td>'
            )
        body += f'<tr><th>{escape(row["model"])}</th>{cells}</tr>'
    render_html(
        f'<table class="matrix-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )
    render_info_panel(
        "边界意识如何得出",
        "前四列为 Rubric 维度达成率（达成率 ≥85% 浅绿、60–85% 米色、<60% 浅玫瑰）；"
        f"{BOUNDARY_AWARENESS_LABEL}由红线类错误（风险遗漏、依据错误）出现频率推导，"
        "频率越低越稳健，均按当前样本计算。",
    )
