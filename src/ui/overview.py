from __future__ import annotations

import streamlit as st

from src.ui.common import PAGE_CONTEXTS
from src.ui.components import (
    render_empty_state,
    render_info_panel,
    render_loop_rail,
    render_metric_card,
    render_page_header,
    render_section_title,
    render_status_badge,
)


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


def render_overview_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    validation_result = data_bundle["validation_result"]
    context = PAGE_CONTEXTS["评测项目总览"]

    render_page_header("评测项目总览", context["question"], context["boundary"])
    render_info_panel("页面核心看点", context["highlights"])

    render_section_title("项目定位")
    st.write(
        "FinDueEval 用结构化 MVP 样本展示金融专业场景模型评测与数据优化闭环，"
        "重点说明模型哪里不稳定、为什么出错、后续补什么数据。"
    )

    render_section_title("三个核心问题")
    question_cols = st.columns(3)
    question_cols[0].write("**模型哪里不稳定**\n\n通过分维度评分、错误类型和领域表现定位能力短板。")
    question_cols[1].write("**为什么出错**\n\n通过 Gold Answer、扣分说明和错误标签还原问题来源。")
    question_cols[2].write("**补什么数据**\n\n将错误归因转化为数据补强动作和后续验证指标。")

    render_section_title("闭环流程", "从评测样本到优化验证的主线。")
    render_loop_rail(get_evaluation_loop_steps())

    render_section_title("核心数据资产")
    cards = get_overview_asset_cards(data)
    if not cards:
        render_empty_state("暂无可展示数据")
        return
    for row_start in range(0, len(cards), 3):
        cols = st.columns(3)
        for col, card in zip(cols, cards[row_start : row_start + 3]):
            with col:
                render_metric_card(card["label"], card["value"], card["note"])

    render_data_quality_status(validation_result)
