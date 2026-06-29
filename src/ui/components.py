from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st


STYLE_CSS = """
<style>
:root {
    --fde-bg: #f6f7f9;
    --fde-surface: #ffffff;
    --fde-surface-muted: #eef1f5;
    --fde-line: #e1e5ec;
    --fde-text: #1f2733;
    --fde-muted: #6a7686;
    --fde-blue: #2b4a6f;
    --fde-blue-soft: #eaf0f7;
    --fde-blue-border: #d3deec;
    /* Low-saturation status palette: error = rose, warning = beige, improve = sage. */
    --fde-red: #8a3a3a;
    --fde-red-soft: #f6e9ea;
    --fde-red-border: #e3cdcd;
    --fde-orange: #7c5a30;
    --fde-orange-soft: #f2ecdf;
    --fde-orange-border: #e0d4ba;
    --fde-green: #2f5d3f;
    --fde-green-soft: #e9f0ea;
    --fde-green-border: #cdddd0;
    --fde-gray-soft: #f1f3f6;
    --fde-shadow: 0 1px 2px rgba(31, 39, 51, 0.05);
}
.stApp {
    background: var(--fde-bg);
    color: var(--fde-text);
}
#MainMenu,
footer,
header,
[data-testid="stDeployButton"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stToolbar"] {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
}
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}
[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid var(--fde-line);
}
.nav-brand {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 0.9rem 1rem;
    margin: 0.25rem 0 1rem 0;
}
.nav-brand-title {
    color: var(--fde-blue);
    font-size: 1.05rem;
    font-weight: 800;
    letter-spacing: 0.02em;
}
.nav-brand-subtitle {
    color: var(--fde-muted);
    font-size: 0.82rem;
    line-height: 1.45;
    margin-top: 0.28rem;
}
[data-testid="stSidebar"] .stButton > button {
    width: 100%;
    justify-content: flex-start;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    background: transparent;
    color: var(--fde-text);
    border-radius: 9px;
    padding: 0.62rem 0.8rem;
    font-weight: 650;
    box-shadow: none;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: var(--fde-blue-soft);
    border-color: var(--fde-blue-border);
    border-left: 3px solid var(--fde-blue);
    color: var(--fde-blue);
    font-weight: 750;
}
[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] .stButton > button:focus {
    background: var(--fde-surface-muted);
    color: var(--fde-blue);
    border-color: transparent;
    border-left-color: var(--fde-line);
}
.page-header {
    border: 1px solid var(--fde-line);
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-surface);
    border-radius: 12px;
    padding: 0.95rem 1.15rem;
    margin-bottom: 0.7rem;
    box-shadow: var(--fde-shadow);
}
.page-eyebrow {
    color: var(--fde-muted);
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.3rem;
}
.page-header h1 {
    color: var(--fde-blue);
    font-size: 1.55rem;
    line-height: 1.2;
    margin: 0 0 0.35rem 0;
}
.page-header p {
    color: var(--fde-muted);
    margin: 0.15rem 0;
    font-size: 0.95rem;
}
.boundary-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    align-items: center;
    margin: 0 0 1rem 0;
}
.boundary-chip {
    display: inline-block;
    background: var(--fde-surface-muted);
    color: var(--fde-muted);
    border: 1px solid var(--fde-line);
    border-radius: 999px;
    padding: 0.16rem 0.66rem;
    font-size: 0.78rem;
    font-weight: 600;
}
.metric-card,
.fde-card,
.info-panel,
.warning-panel,
.empty-state,
.model-answer-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1rem;
    margin: 0.45rem 0;
    box-shadow: var(--fde-shadow);
}
.metric-card .metric-label,
.metric-help,
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
    background: var(--fde-surface);
    border-left: 3px solid var(--fde-blue);
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
    border-color: var(--fde-orange-border);
    background: var(--fde-orange-soft);
    color: var(--fde-orange);
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
    border-color: var(--fde-green-border);
}
.score-mid,
.status-warning,
.status-medium {
    background: var(--fde-orange-soft);
    color: var(--fde-orange);
    border-color: var(--fde-orange-border);
}
.score-low,
.status-danger,
.status-high {
    background: var(--fde-red-soft);
    color: var(--fde-red);
    border-color: var(--fde-red-border);
}
.status-neutral {
    background: var(--fde-gray-soft);
    color: var(--fde-muted);
    border-color: var(--fde-line);
}
.score-neutral {
    background: var(--fde-gray-soft);
    color: var(--fde-muted);
    border-color: var(--fde-line);
}
.model-answer-card h4 {
    margin: 0 0 0.35rem 0;
    color: var(--fde-blue);
}
.model-answer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    color: var(--fde-blue);
    margin-bottom: 0.35rem;
}
.model-answer-meta {
    color: var(--fde-muted);
    font-size: 0.9rem;
    margin-bottom: 0.6rem;
}
.model-answer-text,
.comparison-answer,
.model-answer-note p {
    color: var(--fde-text);
    line-height: 1.65;
}
.model-answer-note {
    border-top: 1px solid var(--fde-line);
    margin-top: 0.85rem;
    padding-top: 0.75rem;
}
.answer-boundary-panel {
    border: 1px solid var(--fde-blue-border);
    border-left: 3px solid var(--fde-blue);
    background: var(--fde-blue-soft);
    border-radius: 12px;
    padding: 1rem;
    margin: 0.65rem 0 1rem 0;
}
.answer-boundary-panel h4,
.comparison-card h4 {
    color: var(--fde-blue);
    margin: 0 0 0.5rem 0;
}
.boundary-row {
    border-top: 1px solid var(--fde-line);
    padding: 0.55rem 0;
}
.boundary-row:first-of-type {
    border-top: none;
}
.boundary-label,
.comparison-meta {
    color: var(--fde-muted);
    font-size: 0.84rem;
    font-weight: 700;
}
.boundary-value,
.comparison-body {
    color: var(--fde-text);
    line-height: 1.6;
    margin-top: 0.18rem;
}
.comparison-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 0.85rem;
    margin-top: 0.7rem;
}
.comparison-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: #ffffff;
    padding: 1rem;
}
.comparison-card-preferred {
    border-left: 3px solid var(--fde-green);
}
.comparison-card-rejected {
    border-left: 3px solid var(--fde-orange);
}
.comparison-label {
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 750;
    letter-spacing: 0.04em;
    margin-bottom: 0.3rem;
}
.loop-rail {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(128px, 1fr);
    overflow-x: auto;
    gap: 0.65rem;
    border: 1px solid var(--fde-line);
    border-radius: 12px;
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
.task-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1.05rem 1.15rem;
    margin: 0.55rem 0;
    box-shadow: var(--fde-shadow);
}
.task-card-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
}
.task-card-id {
    color: var(--fde-blue);
    font-weight: 800;
    font-size: 1.02rem;
    letter-spacing: 0.02em;
}
.task-card-badges {
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
}
.task-card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0.55rem 0 0.2rem 0;
}
.tag {
    display: inline-block;
    border-radius: 999px;
    padding: 0.16rem 0.62rem;
    font-size: 0.8rem;
    font-weight: 700;
    border: 1px solid transparent;
}
.tag-domain {
    background: var(--fde-blue-soft);
    color: var(--fde-blue);
    border-color: var(--fde-blue-border);
}
.tag-type {
    background: var(--fde-gray-soft);
    color: var(--fde-muted);
    border-color: var(--fde-line);
}
.task-card-field {
    margin-top: 0.6rem;
}
.task-card-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.15rem;
}
.task-card-value {
    color: var(--fde-text);
    line-height: 1.6;
}
[data-testid="stSelectbox"] label {
    color: var(--fde-muted);
    font-weight: 700;
    font-size: 0.82rem;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    border-radius: 12px;
    border-color: var(--fde-line);
    background: #ffffff;
}
.fact-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 1rem 1.1rem;
    margin: 0.45rem 0;
    box-shadow: var(--fde-shadow);
}
.fact-field {
    margin-top: 0.65rem;
}
.fact-field:first-child {
    margin-top: 0;
}
.fact-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.15rem;
}
.fact-value {
    color: var(--fde-text);
    line-height: 1.62;
}
.boundary-list {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    margin: 0.3rem 0 0.2rem 0;
}
.redline-item {
    border: 1px solid var(--fde-red-border);
    border-left: 3px solid var(--fde-red);
    background: var(--fde-red-soft);
    color: var(--fde-red);
    border-radius: 10px;
    padding: 0.5rem 0.72rem;
    font-size: 0.92rem;
    line-height: 1.5;
}
.point-item {
    border: 1px solid var(--fde-green-border);
    border-left: 3px solid var(--fde-green);
    background: var(--fde-green-soft);
    color: var(--fde-green);
    border-radius: 10px;
    padding: 0.5rem 0.72rem;
    font-size: 0.92rem;
    line-height: 1.5;
}
.rubric-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.4rem 0 0.6rem 0;
    font-size: 0.92rem;
}
.rubric-table thead th {
    text-align: left;
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 750;
    padding: 0.5rem 0.6rem;
    border-bottom: 1px solid var(--fde-line);
}
.rubric-table td {
    padding: 0.6rem;
    border-bottom: 1px solid var(--fde-line);
    color: var(--fde-text);
    vertical-align: top;
}
.rubric-dim {
    font-weight: 750;
    color: var(--fde-blue);
    white-space: nowrap;
}
.rubric-score {
    font-weight: 800;
    color: var(--fde-blue);
    white-space: nowrap;
}
.rubric-gap {
    color: var(--fde-muted);
    white-space: nowrap;
}
.rubric-evidence {
    color: var(--fde-muted);
    line-height: 1.55;
}
.evidence-card {
    border: 1px solid var(--fde-line);
    border-radius: 12px;
    background: var(--fde-surface);
    padding: 0.9rem 1.05rem;
    margin: 0.45rem 0;
    box-shadow: var(--fde-shadow);
}
.evidence-card-clean {
    border-left: 3px solid var(--fde-green);
}
.evidence-card-flagged {
    border-left: 3px solid var(--fde-red);
}
.evidence-head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.35rem;
}
.evidence-title {
    color: var(--fde-blue);
    font-weight: 750;
}
.evidence-field {
    margin-top: 0.55rem;
}
.evidence-label {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.12rem;
}
.evidence-value {
    color: var(--fde-text);
    line-height: 1.6;
}
.matrix-table,
.check-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.4rem 0 0.4rem 0;
    font-size: 0.9rem;
}
.matrix-table th,
.matrix-table td {
    border: 1px solid var(--fde-line);
    padding: 0.5rem 0.6rem;
    text-align: center;
}
.matrix-table thead th {
    background: var(--fde-surface-muted);
    color: var(--fde-muted);
    font-weight: 750;
}
.matrix-table tbody th {
    background: var(--fde-blue-soft);
    color: var(--fde-blue);
    font-weight: 750;
    text-align: left;
    white-space: nowrap;
}
.matrix-table td {
    color: var(--fde-text);
}
.matrix-zero {
    color: var(--fde-muted);
}
.matrix-total {
    background: var(--fde-gray-soft);
    font-weight: 750;
    color: var(--fde-blue);
}
.check-table td,
.check-table th {
    padding: 0.6rem;
    border-bottom: 1px solid var(--fde-line);
    text-align: left;
    vertical-align: top;
}
.check-table thead th {
    color: var(--fde-muted);
    font-size: 0.8rem;
    font-weight: 750;
}
.check-table .check-key {
    color: var(--fde-blue);
    font-weight: 750;
    white-space: nowrap;
}
.check-table .check-count {
    font-weight: 800;
    color: var(--fde-blue);
    white-space: nowrap;
}
.check-table .check-note {
    color: var(--fde-muted);
    line-height: 1.55;
}
</style>
"""


def render_html(html: str, container=None) -> None:
    """Render trusted internal HTML as a single Markdown HTML block.

    Streamlit renders Markdown, which treats a blank line as the end of an
    HTML block and any line indented four or more spaces as a code block.
    Multi-line f-string templates leak both: nested fragments keep their
    source indentation and join with blank lines, so Streamlit shows the raw
    tags as code. Stripping every line and dropping blanks collapses the
    template into one uninterrupted HTML block that always renders as markup.
    """
    target = container or st
    lines = [line.strip() for line in str(html).splitlines()]
    normalized = "\n".join(line for line in lines if line)
    target.markdown(normalized, unsafe_allow_html=True)


def apply_global_styles() -> None:
    render_html(STYLE_CSS)


def render_page_header(title: str, subtitle: str, boundary_note: str | None = None) -> None:
    """Render a consistent page header.

    boundary_note is kept for backward compatibility. The page-level data
    boundary is shown by render_context_summary to avoid duplicate top notes.
    """
    import streamlit as st

    safe_title = escape(str(title or ""))
    safe_subtitle = escape(str(subtitle or ""))
    render_html(
        f"""
        <div class="page-header">
            <div class="page-eyebrow">FinDueEval</div>
            <h1>{safe_title}</h1>
            <p>{safe_subtitle}</p>
        </div>
        """
    )


# Global, qualitative boundary disclaimer shown as a one-line chip strip under
# every page header. These are project-wide caveats about the demo's data nature
# (not business metrics, sample counts, model names or scores), so they stay a
# fixed constant rather than being read per-page.
GLOBAL_BOUNDARY_CHIPS = ["MVP 样本", "脱敏任务", "裁判建议分待复核", "仅用于样本内观察"]


def render_boundary_bar(chips=None) -> None:
    """Render the one-line boundary strip that replaces the old 3-card top."""
    items = chips if chips is not None else GLOBAL_BOUNDARY_CHIPS
    chip_html = "".join(f'<span class="boundary-chip">{escape(str(chip))}</span>' for chip in items)
    render_html(f'<div class="boundary-bar">{chip_html}</div>')


def render_page_shell(page_config) -> None:
    """Render the unified page title and a lightweight boundary bar."""
    render_page_header(page_config.title, page_config.subtitle)
    render_boundary_bar()


def render_card(content: str, class_name: str = "fde-card") -> None:
    render_html(f'<div class="{escape(str(class_name))}">{content}</div>')


def render_metric_card(label, value, help_text=None) -> None:
    help_html = f'<div class="metric-help">{escape(str(help_text))}</div>' if help_text else ""
    render_card(
        f"""
        <div class="metric-label">{escape(str(label))}</div>
        <div class="metric-value">{escape(str(value))}</div>
        {help_html}
        """,
        class_name="metric-card",
    )


def render_info_panel(title, content) -> None:
    render_html(
        f"""
        <div class="info-panel">
            <strong>{escape(str(title))}</strong>
            <div class="panel-content">{escape(str(content))}</div>
        </div>
        """
    )


def render_context_grid(items) -> None:
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
    render_html(
        f'<div class="context-grid">{"".join(item_html)}</div>',
    )


def render_context_summary(context) -> None:
    render_context_grid(
        [
            ("本页回答什么问题", context.get("question", "")),
            ("当前数据边界", context.get("boundary", "")),
            ("页面核心看点", context.get("highlights", "")),
        ]
    )


def render_warning_panel(content) -> None:
    render_html(
        f'<div class="warning-panel">{escape(str(content))}</div>',
    )


def render_empty_state(message) -> None:
    render_html(
        f'<div class="empty-state">{escape(str(message))}</div>',
    )


def render_empty_state_with_actions(message: str, actions: list[tuple[str, str]]) -> None:
    """Render an empty state with call-to-action buttons.

    actions: list of (label, page_key) tuples. Each button navigates to the
    corresponding page when clicked.
    """
    import streamlit as st

    render_html(f'<div class="empty-state">{escape(message)}</div>')
    cols = st.columns(len(actions))
    for col, (label, page_key) in zip(cols, actions):
        with col:
            if st.button(label, key=f"empty_cta_{page_key}", use_container_width=True):
                st.session_state.current_page = page_key
                st.rerun()


def render_badge(text, level: str = "neutral", kind: str = "status") -> None:
    class_prefix = "score" if kind == "score" else "status"
    if class_prefix == "score":
        normalized_level = str(level).strip().lower()
        if normalized_level not in {"high", "mid", "low", "neutral"}:
            normalized_level = "neutral"
    else:
        normalized_level = _normalize_level(level)
    render_html(f'<span class="{class_prefix}-badge {class_prefix}-{normalized_level}">{escape(str(text))}</span>')


def render_status_badge(text, level) -> None:
    render_badge(text, str(level), kind="status")


def render_score_badge(score) -> None:
    score_text, level = _score_text_and_level(score)
    render_badge(score_text, level, kind="score")


def render_review_caveat(eval_status) -> None:
    """真实模式下，在展示评分的页面顶部提示：分数为裁判建议分，需人工复核。

    eval_status 为 app.py 注入 data_bundle 的字典；非真实运行时静默跳过。
    """
    if not isinstance(eval_status, dict) or not eval_status.get("live"):
        return
    scored = int(eval_status.get("scored", 0) or 0)
    confirmed = int(eval_status.get("confirmed", 0) or 0)
    render_html(
        '<div class="warning-panel">当前评分为裁判模型建议分（如未复核，请在总览页确认归档）。'
        f"已复核 {confirmed}/{scored}。</div>"
    )


def render_section_title(title, caption=None) -> None:
    caption_html = f'<div class="section-caption">{escape(str(caption))}</div>' if caption else ""
    render_html(
        f"""
        <div class="section-title">
            <h3>{escape(str(title))}</h3>
            {caption_html}
        </div>
        """
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
    render_html(
        f'<div class="loop-rail">{"".join(step_html)}</div>',
    )


def render_model_answer_card(
    model_name: str,
    answer: object,
    score: object | None = None,
    review_note: object | None = None,
    meta: object | None = None,
) -> None:
    """Render a model answer card while preserving paragraph structure."""
    import streamlit as st

    def display_value(value: object, fallback: str = "暂无可展示数据") -> str:
        if value is None:
            return fallback
        text_value = str(value).strip()
        if not text_value or text_value.lower() in {"nan", "none", "null"}:
            return fallback
        return text_value

    safe_model = escape(display_value(model_name, "未标注模型"))
    safe_answer = escape(display_value(answer, "暂无回答内容。"))
    safe_answer = safe_answer.replace(chr(10), "<br>")
    score_text = display_value(score, "")
    meta_text = display_value(meta, "")
    review_text = display_value(review_note, "")
    safe_review = escape(review_text).replace(chr(10), "<br>") if review_text else ""

    score_html = f'<span class="score-badge">{escape(score_text)}</span>' if score_text else ""
    meta_html = f'<div class="model-answer-meta">{escape(meta_text)}</div>' if meta_text else ""
    review_html = (
        f'<div class="model-answer-note"><strong>扣分说明</strong><p>{safe_review}</p></div>'
        if safe_review
        else ""
    )

    render_html(
        f"""
        <div class="model-answer-card">
            <div class="model-answer-header">
                <strong>{safe_model}</strong>
                {score_html}
            </div>
            {meta_html}
            <div class="model-answer-text" style="white-space: pre-wrap; line-height: 1.65;">{safe_answer}</div>
            {review_html}
        </div>
        """
    )


def render_answer_boundary_panel(title, fields) -> None:
    rows = []
    for label, value in fields:
        rows.append(
            f"""
            <div class="boundary-row">
                <div class="boundary-label">{escape(str(label))}</div>
                <div class="boundary-value">{escape(str(value if _has_value(value) else "暂无记录"))}</div>
            </div>
            """
        )
    render_html(
        f"""
        <div class="answer-boundary-panel">
            <h4>{escape(str(title))}</h4>
            {"".join(rows)}
        </div>
        """
    )


def render_preference_comparison(
    preferred_title: str,
    preferred_answer: object,
    rejected_title: str,
    rejected_answer: object,
    preferred_meta: object | None = None,
    rejected_meta: object | None = None,
) -> None:
    """Render preferred and rejected answers with missing-value guardrails."""
    import streamlit as st

    def display_value(value: object, fallback: str = "未标注") -> str:
        if value is None:
            return fallback
        text_value = str(value).strip()
        if not text_value or text_value.lower() in {"nan", "none", "null"}:
            return fallback
        return text_value

    preferred_answer_html = escape(display_value(preferred_answer, "暂无回答内容。")).replace(chr(10), "<br>")
    rejected_answer_html = escape(display_value(rejected_answer, "暂无回答内容。")).replace(chr(10), "<br>")
    preferred_meta_text = display_value(preferred_meta, "")
    rejected_meta_text = display_value(rejected_meta, "")
    preferred_meta_html = f'<div class="comparison-meta">{escape(preferred_meta_text)}</div>' if preferred_meta_text else ""
    rejected_meta_html = f'<div class="comparison-meta">{escape(rejected_meta_text)}</div>' if rejected_meta_text else ""

    render_html(
        f"""
        <div class="comparison-grid">
            <div class="comparison-card comparison-card-preferred">
                <div class="comparison-label">偏好回答</div>
                <h4>{escape(display_value(preferred_title, "偏好回答"))}</h4>
                {preferred_meta_html}
                <div class="comparison-answer" style="white-space: pre-wrap; line-height: 1.65;">{preferred_answer_html}</div>
            </div>
            <div class="comparison-card comparison-card-rejected">
                <div class="comparison-label">对比回答</div>
                <h4>{escape(display_value(rejected_title, "对比回答"))}</h4>
                {rejected_meta_html}
                <div class="comparison-answer" style="white-space: pre-wrap; line-height: 1.65;">{rejected_answer_html}</div>
            </div>
        </div>
        """
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
