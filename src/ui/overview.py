from __future__ import annotations

import streamlit as st

from src.ui.page_config import get_page_config
from src.ui.components import (
    render_empty_state,
    render_context_grid,
    render_loop_rail,
    render_metric_card,
    render_page_shell,
    render_section_title,
    render_status_badge,
)


# Score columns that make up the Rubric, excluding the aggregate total_score.
_RUBRIC_TOTAL_COLUMN = "total_score"


def _distinct_count(df, column: str) -> int:
    if column in getattr(df, "columns", []):
        return int(df[column].dropna().nunique())
    return 0


def _rubric_dimension_count(scores_df) -> int:
    columns = getattr(scores_df, "columns", [])
    return sum(
        1
        for column in columns
        if column.endswith("_score") and column != _RUBRIC_TOTAL_COLUMN
    )


def get_overview_insight_cards(data) -> list[dict[str, str | int]]:
    """Three conclusion-first insight cards. Every number is read from data."""
    task_count = len(data.tasks)
    domain_count = _distinct_count(data.tasks, "domain")
    model_count = _distinct_count(data.model_outputs, "model_name")
    dimension_count = _rubric_dimension_count(data.scores)
    error_type_count = _distinct_count(data.errors, "error_type")
    optimization_count = len(data.optimizations)

    return [
        {
            "label": "样本资产",
            "value": task_count,
            "note": f"覆盖 {domain_count} 个专业领域的脱敏尽调任务。",
        },
        {
            "label": "评测机制",
            "value": model_count,
            "note": f"多模型回答对照 Gold Answer，按 {dimension_count} 维 Rubric 评分。",
        },
        {
            "label": "数据优化价值",
            "value": optimization_count,
            "note": f"由 {error_type_count} 类错误标签驱动的数据补强与验证。",
        },
    ]


def get_overview_asset_cards(data) -> list[dict[str, str | int]]:
    task_count = len(data.tasks)
    output_count = len(data.model_outputs)
    gold_count = len(data.gold_answer_map)
    error_count = len(data.errors)
    preference_count = len(data.preference_pairs)
    optimization_count = len(data.optimizations)

    return [
        {"label": "任务样本", "value": task_count, "note": "脱敏专业评测任务。"},
        {"label": "模型回答", "value": output_count, "note": "用于评分和错误分析的回答记录。"},
        {"label": "Gold Answer 覆盖", "value": f"{gold_count}/{task_count}", "note": "用于定义优秀回答边界。"},
        {"label": "错误标签", "value": error_count, "note": "用于定位扣分原因。"},
        {"label": "Preference Pair", "value": preference_count, "note": "用于记录回答偏好和改进方向。"},
        {"label": "优化动作", "value": optimization_count, "note": "用于承接数据补强任务。"},
    ]


def get_overview_summary_items(data) -> list[tuple[str, str]]:
    """Compact data-asset summary. Counts are derived from the loaded data."""
    task_count = len(data.tasks)
    domain_count = _distinct_count(data.tasks, "domain")
    task_type_count = _distinct_count(data.tasks, "task_type")
    model_count = _distinct_count(data.model_outputs, "model_name")
    output_count = len(data.model_outputs)
    gold_count = len(data.gold_answer_map)
    error_type_count = _distinct_count(data.errors, "error_type")
    error_rows = len(data.errors)
    optimization_count = len(data.optimizations)

    return [
        ("任务样本", f"{task_count} 道 · {domain_count} 个领域"),
        ("任务类型", f"{task_type_count} 类专业任务"),
        ("模型回答", f"{model_count} 个模型 · {output_count} 条回答"),
        ("Gold Answer", f"{gold_count}/{task_count} 覆盖"),
        ("错误标签", f"{error_type_count} 类 · {error_rows} 条标注"),
        ("数据补强", f"{optimization_count} 项优化动作"),
    ]


def get_evaluation_loop_steps() -> list[str]:
    return [
        "专业任务",
        "Gold Answer",
        "模型回答",
        "Rubric 评分",
        "错误归因",
        "数据补强",
        "优化验证",
    ]


def render_data_quality_status(validation_result) -> None:
    render_section_title("数据质量状态")
    if validation_result.is_valid:
        render_status_badge("通过", "success")
    else:
        render_status_badge("需处理", "danger")

    for message in validation_result.errors:
        st.error(message)
    for message in validation_result.warnings:
        st.warning(message)


def render_overview_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    validation_result = data_bundle["validation_result"]
    render_page_shell(get_page_config("overview"))

    render_section_title("核心洞察", "关键数字均由当前样本动态计算。")
    insight_cards = get_overview_insight_cards(data)
    insight_columns = st.columns(len(insight_cards))
    for column, card in zip(insight_columns, insight_cards):
        with column:
            render_metric_card(card["label"], card["value"], card["note"])

    render_section_title("可运行闭环", "从评测样本到优化验证的主线。")
    render_loop_rail(get_evaluation_loop_steps())

    render_section_title("数据资产摘要", "只展示关键摘要，详情见对应页面。")
    summary_items = get_overview_summary_items(data)
    if not summary_items:
        render_empty_state("暂无可展示数据")
        return
    render_context_grid(summary_items)

    render_data_quality_status(validation_result)
