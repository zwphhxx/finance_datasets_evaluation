from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.components import render_score_badge


PAGE_CONTEXTS = {
    "评测项目总览": {
        "question": "这个评测集评什么，以及如何形成模型评测与数据优化闭环。",
        "boundary": "当前结论仅基于 MVP 样本、脱敏任务和模拟模型回答。",
        "highlights": "项目定位、三个核心问题、闭环流程和核心数据资产。",
    },
    "专业任务集": {
        "question": "当前任务样本覆盖哪些专业场景，是否足以支撑后续评测观察。",
        "boundary": "当前任务是脱敏专业任务样本，不是概念题，也不是完整行业题库。",
        "highlights": "任务分布、Gold Answer 覆盖、模型回答覆盖和简洁任务表。",
    },
    "样板题深度评测": {
        "question": "一道专业题如何定义优秀回答，模型回答具体差在哪里。",
        "boundary": "单题结论只服务于样板题拆解，不代表模型整体能力。",
        "highlights": "Gold Answer、多模型回答、Rubric 评分、错误标签、偏好样本和数据补强建议。",
    },
    "模型能力诊断": {
        "question": "当前样本下模型在哪些能力维度更不稳定。",
        "boundary": "本页不作为模型整体能力结论，也不提供采购建议或性价比判断。",
        "highlights": "综合得分、分维度得分、错误类型分布、领域场景表现和能力诊断摘要。",
    },
    "错误归因与数据补强": {
        "question": "错误表现对应什么可能原因，以及后续应该补什么数据。",
        "boundary": "错误归因来自当前错误标签和优化计划，未匹配记录会保留为空数据提示。",
        "highlights": "错误分布、可能原因、数据补强动作、样本格式和验证指标。",
    },
    "优化验证": {
        "question": "Prompt、RAG 或数据补强前后，关键指标是否出现可观察变化。",
        "boundary": "当前结果仅用于 MVP 样本观察，不代表真实大规模实验结论。",
        "highlights": "版本变更、平均分、依据可靠性、推理得分、幻觉率和红线错误率。",
    },
}


def render_page_context(page_name: str) -> None:
    context = PAGE_CONTEXTS.get(page_name)
    if not context:
        return

    with st.container():
        st.markdown("**本页回答什么问题**")
        st.write(context["question"])
        st.markdown("**当前数据边界**")
        st.write(context["boundary"])
        st.markdown("**页面核心看点**")
        st.write(context["highlights"])


def has_value(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except TypeError:
        return True


def write_text_field(label: str, value) -> None:
    st.write(f"**{label}：** {value if has_value(value) else '暂无'}")


def write_list_field(label: str, value) -> None:
    st.write(f"**{label}：**")
    if isinstance(value, list) and value:
        for item in value:
            st.write(f"- {item}")
    elif has_value(value):
        st.write(value)
    else:
        st.write("暂无")


def show_model_score(row: pd.Series) -> None:
    total_score = row.get("total_score")
    if not has_value(total_score):
        st.write("**评分：** 当前模型回答尚未评分。")
        return

    render_score_badge(total_score)
    accuracy = row.get("accuracy_score", "暂无")
    reasoning = row.get("reasoning_score", "暂无")
    coverage = row.get("coverage_score", "暂无")
    evidence = row.get("evidence_score", "暂无")
    expression = row.get("expression_score", "暂无")
    st.write(
        f"**得分：** 总分 {float(total_score):.0f}"
        f"（专业准确性 {accuracy}，推理与场景适配 {reasoning}，风险覆盖 {coverage}，"
        f"依据可靠性 {evidence}，专业表达 {expression}）"
    )
