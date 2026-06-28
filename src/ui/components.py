from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st


STYLE_CSS = """
<style>
:root {
    --fde-bg: #f5f7fa;
    --fde-surface: #ffffff;
    --fde-surface-muted: #eef2f7;
    --fde-line: #d8dee8;
    --fde-text: #172033;
    --fde-muted: #607089;
    --fde-blue: #12345a;
    --fde-blue-soft: #e7eef8;
    --fde-red: #b42318;
    --fde-red-soft: #fdebea;
    --fde-orange: #b76e00;
    --fde-orange-soft: #fff4dd;
    --fde-green: #247a4b;
    --fde-green-soft: #e8f5ee;
    --fde-gray-soft: #f2f4f7;
}
.stApp {
    background: var(--fde-bg);
    color: var(--fde-text);
}
.block-container {
    padding-top: 2rem;
}
[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid var(--fde-line);
}
[data-testid="stSidebar"] .stButton > button {
    width: 100%;
    justify-content: flex-start;
    border: 1px solid transparent;
    background: transparent;
    color: var(--fde-text);
    border-radius: 10px;
    padding: 0.62rem 0.75rem;
    font-weight: 600;
}
[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] .stButton > button:focus {
    border-color: var(--fde-line);
    background: var(--fde-blue-soft);
    color: var(--fde-blue);
}
.page-header {
    border: 1px solid var(--fde-line);
    background: linear-gradient(135deg, #ffffff 0%, #f1f5fa 100%);
    border-radius: 16px;
    padding: 1.2rem 1.3rem;
    margin-bottom: 1.1rem;
}
.page-header h1 {
    color: var(--fde-blue);
    font-size: 1.85rem;
    line-height: 1.2;
    margin: 0 0 0.45rem 0;
}
.page-header p {
    color: var(--fde-muted);
    margin: 0.2rem 0;
}
.metric-card,
.info-panel,
.warning-panel,
.empty-state,
.model-answer-card {
    border: 1px solid var(--fde-line);
    border-radius: 14px;
    background: var(--fde-surface);
    padding: 1rem;
    margin: 0.45rem 0;
}
.metric-card .metric-label,
.section-caption,
.panel-content,
.empty-state {
    color: var(--fde-muted);
}
.metric-card .metric-value {
    color: var(--fde-blue);
    font-size: 1.65rem;
    font-weight: 750;
    line-height: 1.25;
}
.info-panel {
    background: #ffffff;
}
.context-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.75rem;
    margin: 0.65rem 0 1rem 0;
}
.context-item {
    border: 1px solid var(--fde-line);
    background: #ffffff;
    border-radius: 12px;
    padding: 0.85rem 0.95rem;
}
.context-label {
    color: var(--fde-blue);
    font-size: 0.86rem;
    font-weight: 750;
    margin-bottom: 0.35rem;
}
.context-copy {
    color: var(--fde-muted);
    font-size: 0.94rem;
    line-height: 1.55;
}
.warning-panel {
    border-color: #f2c98b;
    background: var(--fde-orange-soft);
}
.empty-state {
    background: var(--fde-gray-soft);
    text-align: center;
}
.section-title {
    margin-top: 1.2rem;
    margin-bottom: 0.45rem;
}
.section-title h3 {
    color: var(--fde-blue);
    margin-bottom: 0.15rem;
}
.score-badge,
.status-badge {
    display: inline-block;
    border-radius: 999px;
    padding: 0.18rem 0.58rem;
    font-size: 0.84rem;
    font-weight: 700;
    border: 1px solid transparent;
}
.score-high,
.status-success,
.status-low {
    background: var(--fde-green-soft);
    color: var(--fde-green);
    border-color: #b8dec8;
}
.score-mid,
.status-warning,
.status-medium {
    background: var(--fde-orange-soft);
    color: var(--fde-orange);
    border-color: #f0d19c;
}
.score-low,
.status-danger,
.status-high {
    background: var(--fde-red-soft);
    color: var(--fde-red);
    border-color: #f3b8b2;
}
.status-neutral {
    background: var(--fde-gray-soft);
    color: var(--fde-muted);
    border-color: var(--fde-line);
}
.model-answer-card h4 {
    margin: 0 0 0.35rem 0;
    color: var(--fde-blue);
}
.model-answer-meta {
    color: var(--fde-muted);
    font-size: 0.9rem;
    margin-bottom: 0.6rem;
}
.loop-rail {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 0.65rem;
    border: 1px solid var(--fde-line);
    border-radius: 16px;
    background: #ffffff;
    padding: 0.85rem;
    margin: 0.5rem 0 1rem 0;
}
.loop-step {
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-blue-soft);
    border-radius: 10px;
    padding: 0.7rem 0.75rem;
    min-height: 4.3rem;
}
.loop-step-index {
    color: var(--fde-muted);
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.04em;
}
.loop-step-label {
    color: var(--fde-blue);
    font-weight: 750;
    margin-top: 0.25rem;
}
</style>
"""


def apply_global_styles() -> None:
    st.markdown(STYLE_CSS, unsafe_allow_html=True)


def render_page_header(title, subtitle, boundary_note=None) -> None:
    boundary_html = ""
    if boundary_note:
        boundary_html = f"<p><strong>当前数据边界：</strong>{escape(str(boundary_note))}</p>"
    st.markdown(
        f"""
        <div class="page-header">
            <h1>{escape(str(title))}</h1>
            <p>{escape(str(subtitle))}</p>
            {boundary_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label, value, help_text=None) -> None:
    help_html = f'<div class="metric-help">{escape(str(help_text))}</div>' if help_text else ""
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{escape(str(label))}</div>
            <div class="metric-value">{escape(str(value))}</div>
            {help_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_info_panel(title, content) -> None:
    st.markdown(
        f"""
        <div class="info-panel">
            <strong>{escape(str(title))}</strong>
            <div class="panel-content">{escape(str(content))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_context_summary(context) -> None:
    items = [
        ("本页回答什么问题", context.get("question", "")),
        ("当前数据边界", context.get("boundary", "")),
        ("页面核心看点", context.get("highlights", "")),
    ]
    item_html = []
    for label, copy in items:
        item_html.append(
            f"""
            <div class="context-item">
                <div class="context-label">{escape(str(label))}</div>
                <div class="context-copy">{escape(str(copy))}</div>
            </div>
            """
        )
    st.markdown(
        f'<div class="context-grid">{"".join(item_html)}</div>',
        unsafe_allow_html=True,
    )


def render_warning_panel(content) -> None:
    st.markdown(
        f'<div class="warning-panel">{escape(str(content))}</div>',
        unsafe_allow_html=True,
    )


def render_empty_state(message) -> None:
    st.markdown(
        f'<div class="empty-state">{escape(str(message))}</div>',
        unsafe_allow_html=True,
    )


def render_score_badge(score) -> None:
    score_text, level = _score_text_and_level(score)
    st.markdown(
        f'<span class="score-badge score-{level}">{escape(score_text)}</span>',
        unsafe_allow_html=True,
    )


def render_status_badge(text, level) -> None:
    normalized_level = _normalize_level(level)
    st.markdown(
        f'<span class="status-badge status-{normalized_level}">{escape(str(text))}</span>',
        unsafe_allow_html=True,
    )


def render_section_title(title, caption=None) -> None:
    caption_html = f'<div class="section-caption">{escape(str(caption))}</div>' if caption else ""
    st.markdown(
        f"""
        <div class="section-title">
            <h3>{escape(str(title))}</h3>
            {caption_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_loop_rail(steps) -> None:
    step_html = []
    for index, step in enumerate(steps, start=1):
        step_html.append(
            f"""
            <div class="loop-step">
                <div class="loop-step-index">环节 {index:02d}</div>
                <div class="loop-step-label">{escape(str(step))}</div>
            </div>
            """
        )
    st.markdown(
        f'<div class="loop-rail">{"".join(step_html)}</div>',
        unsafe_allow_html=True,
    )


def render_model_answer_card(
    model_name,
    answer,
    output_id=None,
    score=None,
    review_note=None,
) -> None:
    meta_parts = []
    if output_id is not None and _has_value(output_id):
        meta_parts.append(f"output_id {output_id}")
    if score is not None and _has_value(score):
        meta_parts.append(f"总分 {float(score):.0f}")
    meta = " · ".join(meta_parts) if meta_parts else "当前样本观察"
    note_html = ""
    if review_note is not None and _has_value(review_note):
        note_html = f'<p><strong>评审说明：</strong>{escape(str(review_note))}</p>'

    st.markdown(
        f"""
        <div class="model-answer-card">
            <h4>{escape(str(model_name))}</h4>
            <div class="model-answer-meta">{escape(meta)}</div>
            <p>{escape(str(answer if _has_value(answer) else "暂无可展示数据"))}</p>
            {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _score_text_and_level(score) -> tuple[str, str]:
    if not _has_value(score):
        return "暂无评分", "neutral"
    value = float(score)
    if value >= 80:
        return f"{value:.0f}", "high"
    if value >= 60:
        return f"{value:.0f}", "mid"
    return f"{value:.0f}", "low"


def _normalize_level(level) -> str:
    level_text = str(level).strip().lower()
    mapping = {
        "高": "high",
        "中": "medium",
        "低": "low",
        "通过": "success",
        "成功": "success",
        "warning": "warning",
        "danger": "danger",
        "error": "danger",
        "high": "high",
        "medium": "medium",
        "low": "low",
        "success": "success",
        "neutral": "neutral",
    }
    return mapping.get(level_text, "neutral")


def _has_value(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except TypeError:
        return True
