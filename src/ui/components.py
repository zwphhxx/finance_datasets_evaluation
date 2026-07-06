from __future__ import annotations

from html import escape
import re
from textwrap import dedent

import streamlit as st


PROJECT_DISPLAY_NAME = "财务/法律/投行场景大模型对比评测"


STYLE_CSS = """
<style>
:root {
    --fde-bg: #f6f7f9;
    --fde-surface: #ffffff;
    --fde-surface-subtle: #fafbfc;
    --fde-line: #e1e5ec;
    --fde-line-strong: #cfd6e1;
    --fde-ink: #263241;
    --fde-text: #1f2733;
    --fde-muted: #6a7686;
    --fde-accent: #33465f;
    --fde-accent-soft: #eef2f6;
    --fde-success-bg: #edf3ef;
    --fde-success-text: #2f5d3f;
    --fde-warning-bg: #f5f0e7;
    --fde-warning-text: #6f5430;
    --fde-danger-bg: #f5ecec;
    --fde-danger-text: #7a3f3f;
    --fde-radius: 10px;
    --fde-max-width: 1120px;
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
    max-width: var(--fde-max-width);
    margin: 0 auto;
    padding-top: 0;
    padding-bottom: 3rem;
}
[data-testid="stSidebar"] {
    display: none;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
    min-height: 56px;
    align-items: center;
    padding: 0.58rem 1.5rem 0.62rem 1.5rem;
    margin: 0.2rem 0 1.45rem 0;
    border-bottom: 1px solid var(--fde-line);
    background: transparent;
}
.top-nav-brand {
    color: var(--fde-ink);
    font-size: 1.02rem;
    font-weight: 720;
    line-height: 1.35;
    letter-spacing: 0;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton {
    display: flex;
    justify-content: center;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button {
    min-height: 1.9rem;
    padding: 0.18rem 0.38rem;
    border: 0;
    border: 0 !important;
    border-radius: 3px;
    background: transparent !important;
    box-shadow: none !important;
    color: var(--fde-muted);
    font-size: 0.94rem;
    font-weight: 590;
    white-space: nowrap;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button[kind="secondary"] {
    color: var(--fde-ink);
    font-weight: 720;
}
[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button:hover {
    color: var(--fde-ink);
    background: transparent !important;
}
@media (max-width: 860px) {
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        flex-wrap: wrap;
        min-height: auto;
        padding: 0.55rem 1rem 0.65rem 1rem;
    }
    .top-nav-brand {
        font-size: 0.92rem;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton {
        justify-content: flex-start;
    }
}
.page-title-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    margin: 0.35rem 0 1rem 0;
}
.page-title-main {
    min-width: 0;
}
.page-title-heading {
    color: var(--fde-ink);
    font-size: 1.45rem;
    font-weight: 760;
    line-height: 1.24;
    margin: 0;
    letter-spacing: 0;
}
.page-title-copy {
    color: var(--fde-muted);
    font-size: 0.95rem;
    line-height: 1.55;
    margin-top: 0.32rem;
}
.page-title-actions {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    flex-shrink: 0;
}
.compact-hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 1.3rem;
    align-items: end;
    margin: 0.35rem 0 1.2rem 0;
    padding-bottom: 0.9rem;
    border-bottom: 1px solid var(--fde-line);
}
.compact-hero-eyebrow {
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 700;
    margin-bottom: 0.22rem;
}
.compact-hero-title {
    color: var(--fde-ink);
    font-size: 1.62rem;
    font-weight: 780;
    line-height: 1.22;
    margin: 0;
}
.compact-hero-copy {
    color: var(--fde-muted);
    font-size: 0.96rem;
    line-height: 1.58;
    margin: 0.38rem 0 0 0;
}
.compact-hero-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 0.7rem;
    justify-content: flex-end;
}
.compact-hero-stat {
    min-width: 5.2rem;
    border-left: 1px solid var(--fde-line);
    padding-left: 0.75rem;
}
.compact-hero-stat strong {
    display: block;
    color: var(--fde-ink);
    font-size: 1.25rem;
    line-height: 1.1;
}
.compact-hero-stat span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.78rem;
    margin-top: 0.2rem;
}
.numbered-section {
    display: grid;
    grid-template-columns: 2.4rem minmax(0, 1fr);
    gap: 0.8rem;
    align-items: start;
    margin: 1.55rem 0 0.72rem 0;
}
.numbered-section-index {
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 760;
    letter-spacing: 0.03em;
    padding-top: 0.12rem;
}
.numbered-section-title {
    color: var(--fde-ink);
    font-size: 1.08rem;
    font-weight: 760;
    line-height: 1.35;
}
.numbered-section-caption {
    color: var(--fde-muted);
    font-size: 0.9rem;
    line-height: 1.55;
    margin-top: 0.16rem;
}
.inline-status {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.55rem 0.8rem;
    margin: 0.45rem 0 0.75rem 0;
}
.inline-status-item {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.28rem 0 0.42rem 0;
}
.inline-status-item span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.75rem;
    font-weight: 650;
    margin-bottom: 0.16rem;
}
.inline-status-item strong {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 650;
    line-height: 1.45;
}
.empty-state {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    background: var(--fde-surface-subtle);
    color: var(--fde-muted);
    padding: 1rem 1.1rem;
    line-height: 1.6;
    margin: 0.5rem 0 1rem 0;
}
.detail-panel,
.sample-detail-panel {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    background: var(--fde-surface);
    overflow: hidden;
    margin: 0.55rem 0 1rem 0;
}
.detail-panel-header,
.sample-detail-panel-header {
    padding: 0.82rem 1rem;
    border-bottom: 1px solid var(--fde-line);
}
.detail-panel-title,
.sample-detail-panel-title {
    color: var(--fde-ink);
    font-size: 1rem;
    font-weight: 720;
    line-height: 1.45;
}
.detail-panel-meta,
.sample-detail-panel-meta {
    color: var(--fde-muted);
    font-size: 0.86rem;
    line-height: 1.45;
    margin-top: 0.18rem;
}
.detail-panel-body,
.sample-detail-panel-body {
    padding: 0.95rem 1rem 1.1rem 1rem;
}
.sample-detail-toolbar-title {
    padding: 0.42rem 0;
}
.sample-detail-toolbar-title div {
    color: var(--fde-ink);
    font-size: 1.02rem;
    font-weight: 720;
    line-height: 1.42;
    overflow-wrap: anywhere;
}
.sample-detail-toolbar-title span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.86rem;
    margin-top: 0.22rem;
}
[data-testid="stHorizontalBlock"]:has(.sample-detail-toolbar-title) {
    align-items: start;
    gap: 0.55rem;
    margin-bottom: 0.45rem;
}
[data-testid="stHorizontalBlock"]:has(.sample-detail-toolbar-title) .stButton > button {
    margin-top: 0.1rem;
}
.sample-detail-section {
    margin-top: 1.05rem;
}
.sample-detail-section:first-child {
    margin-top: 0;
}
.sample-detail-section-title {
    color: var(--fde-muted);
    font-size: 0.84rem;
    font-weight: 760;
    margin-bottom: 0.48rem;
}
.sample-detail-kv-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
    gap: 0.45rem 0.9rem;
}
.sample-detail-kv {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.28rem 0 0.42rem 0;
}
.sample-detail-kv span,
.sample-detail-label {
    display: block;
    color: var(--fde-muted);
    font-size: 0.76rem;
    font-weight: 700;
    margin: 0.25rem 0 0.18rem 0;
}
.sample-detail-kv strong,
.sample-detail-text,
.sample-detail-list {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 400;
    line-height: 1.62;
}
.sample-detail-text {
    margin: 0 0 0.55rem 0;
}
.sample-detail-list {
    margin: 0 0 0.65rem 1.1rem;
    padding: 0;
}
.sample-detail-list li {
    margin: 0.16rem 0;
}
.sample-detail-table,
.check-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    line-height: 1.5;
}
.sample-detail-table th,
.sample-detail-table td,
.check-table td {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.5rem 0.45rem;
    vertical-align: top;
}
.sample-detail-table th {
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 720;
    text-align: left;
    background: var(--fde-surface-subtle);
}
.answer-viewer-summary {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    background: var(--fde-surface);
    padding: 0.8rem 0.95rem;
    margin: 0.55rem 0 0.8rem 0;
}
.answer-viewer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.5rem 0.8rem;
}
.answer-viewer-item {
    border-bottom: 1px solid var(--fde-line);
    padding-bottom: 0.34rem;
}
.answer-viewer-item span {
    display: block;
    color: var(--fde-muted);
    font-size: 0.74rem;
    font-weight: 650;
}
.answer-viewer-item strong {
    color: var(--fde-ink);
    font-size: 0.92rem;
    font-weight: 650;
    line-height: 1.45;
}
.answer-viewer-muted {
    color: var(--fde-muted);
    font-size: 0.78rem;
    margin-top: 0.5rem;
    overflow-wrap: anywhere;
}
.markdown-detail-body {
    color: var(--fde-ink);
    font-size: 0.94rem;
    font-weight: 400;
    line-height: 1.62;
}
.markdown-detail-body p {
    margin: 0 0 0.68rem 0;
    font-weight: 400;
}
.markdown-detail-heading {
    color: var(--fde-muted);
    font-size: 0.86rem;
    font-weight: 760;
    line-height: 1.45;
    margin: 0.95rem 0 0.42rem 0;
}
.markdown-detail-heading:first-child {
    margin-top: 0;
}
.markdown-detail-list {
    margin: 0.26rem 0 0.74rem 1.1rem;
    padding: 0;
}
.markdown-detail-list li {
    margin: 0.18rem 0;
    line-height: 1.6;
}
.markdown-detail-code {
    background: var(--fde-surface-subtle);
    border: 1px solid var(--fde-line);
    border-radius: 8px;
    color: var(--fde-text);
    font-size: 0.84rem;
    line-height: 1.55;
    margin: 0.55rem 0 0.8rem 0;
    overflow: auto;
    padding: 0.68rem 0.78rem;
}
.markdown-detail-inline-code {
    background: var(--fde-surface-subtle);
    border: 1px solid var(--fde-line);
    border-radius: 4px;
    padding: 0.04rem 0.24rem;
}
.markdown-detail-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
    line-height: 1.5;
    margin: 0.5rem 0 0.85rem 0;
}
.markdown-detail-table th,
.markdown-detail-table td {
    border-bottom: 1px solid var(--fde-line);
    padding: 0.45rem 0.45rem;
    text-align: left;
    vertical-align: top;
}
.markdown-detail-table th {
    background: var(--fde-surface-subtle);
    color: var(--fde-muted);
    font-size: 0.78rem;
    font-weight: 720;
}
.clean-list {
    margin: 0.25rem 0 0.85rem 1.1rem;
    padding: 0;
    color: var(--fde-ink);
    line-height: 1.65;
}
.clean-list li {
    margin: 0.18rem 0;
}
.inline-pill {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--fde-line);
    border-radius: 999px;
    background: var(--fde-surface-subtle);
    color: var(--fde-muted);
    padding: 0.12rem 0.5rem;
    font-size: 0.78rem;
    font-weight: 650;
}
.inline-pill-success {
    background: var(--fde-success-bg);
    color: var(--fde-success-text);
}
.inline-pill-warning {
    background: var(--fde-warning-bg);
    color: var(--fde-warning-text);
}
.inline-pill-danger {
    background: var(--fde-danger-bg);
    color: var(--fde-danger-text);
}
.stButton > button {
    border-radius: 6px !important;
    box-shadow: none !important;
    font-weight: 650 !important;
}
.stButton > button[kind="primary"] {
    background: var(--fde-accent) !important;
    border: 1px solid var(--fde-accent) !important;
    color: #ffffff !important;
}
.stButton > button[kind="secondary"] {
    background: var(--fde-surface) !important;
    border: 1px solid var(--fde-line-strong) !important;
    color: var(--fde-ink) !important;
}
.stButton > button[kind="tertiary"] {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: var(--fde-muted) !important;
}
.stButton > button:hover {
    border-color: var(--fde-line-strong) !important;
    color: var(--fde-ink) !important;
}
[data-testid="stDataFrame"] {
    border: 1px solid var(--fde-line);
    border-radius: var(--fde-radius);
    overflow: hidden;
    background: var(--fde-surface);
}
[data-testid="stDataFrame"] [role="columnheader"] {
    background: var(--fde-surface-subtle) !important;
    color: var(--fde-muted) !important;
    font-weight: 700 !important;
}
[data-testid="stDataFrame"] [role="gridcell"] {
    color: var(--fde-ink) !important;
}
div[data-testid="stAlert"] {
    border-radius: var(--fde-radius);
    border: 1px solid var(--fde-line);
    box-shadow: none;
}
div[data-testid="stDialog"] {
    color: var(--fde-text);
}
@media (max-width: 760px) {
    .page-title-row,
    .compact-hero {
        grid-template-columns: 1fr;
        display: block;
    }
    .page-title-actions,
    .compact-hero-stats {
        justify-content: flex-start;
        margin-top: 0.75rem;
    }
    .numbered-section {
        grid-template-columns: 1fr;
        gap: 0.18rem;
    }
}
</style>
"""


def _clean_html(html: str) -> str:
    text = dedent(str(html or "")).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "".join(lines)


def render_html(html: str, container=None) -> None:
    target = container or st
    target.markdown(_clean_html(html), unsafe_allow_html=True)


def apply_global_styles() -> None:
    render_html(STYLE_CSS)


def render_page_heading(title: str, description: str | None = None) -> None:
    desc_html = (
        f'<div class="page-title-copy">{escape(str(description))}</div>'
        if description
        else ""
    )
    render_html(
        f"""
        <div class="page-title-row">
            <div class="page-title-main">
                <h1 class="page-title-heading">{escape(str(title))}</h1>
                {desc_html}
            </div>
        </div>
        """
    )


def render_compact_hero(
    eyebrow: str,
    title: str,
    question: str | None = None,
    stats: list[tuple[str, str]] | None = None,
) -> None:
    stat_html = "".join(
        f'<div class="compact-hero-stat"><strong>{escape(str(value))}</strong><span>{escape(str(label))}</span></div>'
        for value, label in (stats or [])
    )
    eyebrow_html = f'<div class="compact-hero-eyebrow">{escape(str(eyebrow))}</div>' if eyebrow else ""
    question_html = f'<p class="compact-hero-copy">{escape(str(question))}</p>' if question else ""
    aside_html = f'<div class="compact-hero-stats">{stat_html}</div>' if stat_html else ""
    render_html(
        f"""
        <div class="compact-hero">
            <div>
                {eyebrow_html}
                <h1 class="compact-hero-title">{escape(str(title))}</h1>
                {question_html}
            </div>
            {aside_html}
        </div>
        """
    )


def render_numbered_section(index: str, title: str, caption: str | None = None) -> None:
    caption_html = (
        f'<div class="numbered-section-caption">{escape(str(caption))}</div>'
        if caption
        else ""
    )
    render_html(
        f"""
        <div class="numbered-section">
            <div class="numbered-section-index">{escape(str(index))}</div>
            <div>
                <div class="numbered-section-title">{escape(str(title))}</div>
                {caption_html}
            </div>
        </div>
        """
    )


def render_empty_state(message: str) -> None:
    render_html(f'<div class="empty-state">{escape(str(message))}</div>')


def render_inline_status(items: list[tuple[str, str]]) -> None:
    parts = "".join(
        f'<div class="inline-status-item"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in items
    )
    render_html(f'<div class="inline-status">{parts}</div>')


def render_kv_grid(items: list[tuple[str, object]]) -> None:
    parts = "".join(
        f'<div class="sample-detail-kv"><span>{escape(str(label))}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in items
    )
    render_html(f'<div class="sample-detail-kv-grid">{parts}</div>')


def render_detail_panel(body_html: str, title: str | None = None, meta: str | None = None) -> None:
    header_html = ""
    if title or meta:
        title_html = f'<div class="detail-panel-title">{escape(str(title))}</div>' if title else ""
        meta_html = f'<div class="detail-panel-meta">{escape(str(meta))}</div>' if meta else ""
        header_html = f'<div class="detail-panel-header">{title_html}{meta_html}</div>'
    render_html(
        f"""
        <div class="detail-panel sample-detail-panel">
            {header_html}
            <div class="detail-panel-body sample-detail-panel-body">{body_html}</div>
        </div>
        """
    )


def markdown_detail_html(markdown_text: str) -> str:
    """Render model-authored Markdown into a constrained detail-pane HTML subset."""
    lines = str(markdown_text or "").splitlines()
    parts: list[str] = []
    list_type: str | None = None
    code_lines: list[str] = []
    in_code = False
    index = 0

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            parts.append(f"</{list_type}>")
            list_type = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_code:
                parts.append(
                    '<pre class="markdown-detail-code"><code>'
                    + escape("\n".join(code_lines))
                    + "</code></pre>"
                )
                code_lines = []
                in_code = False
            else:
                close_list()
                in_code = True
                code_lines = []
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            close_list()
            index += 1
            continue

        if _is_markdown_table_start(lines, index):
            close_list()
            table_rows, next_index = _collect_markdown_table(lines, index)
            parts.append(_markdown_table_html(table_rows))
            index = next_index
            continue

        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            close_list()
            parts.append(f'<div class="markdown-detail-heading">{_inline_markdown_html(heading.group(1))}</div>')
            index += 1
            continue

        unordered = re.match(r"^\s*[-*]\s+(.+)$", line)
        if unordered:
            if list_type != "ul":
                close_list()
                list_type = "ul"
                parts.append('<ul class="markdown-detail-list">')
            parts.append(f"<li>{_inline_markdown_html(unordered.group(1))}</li>")
            index += 1
            continue

        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if ordered:
            if list_type != "ol":
                close_list()
                list_type = "ol"
                parts.append('<ol class="markdown-detail-list">')
            parts.append(f"<li>{_inline_markdown_html(ordered.group(1))}</li>")
            index += 1
            continue

        close_list()
        parts.append(f"<p>{_inline_markdown_html(stripped)}</p>")
        index += 1

    close_list()
    if in_code:
        parts.append(
            '<pre class="markdown-detail-code"><code>'
            + escape("\n".join(code_lines))
            + "</code></pre>"
        )
    return "\n".join(parts) or "<p>—</p>"


def render_markdown_detail_panel(
    title: str,
    markdown_text: str,
    meta: str | None = None,
) -> None:
    body_html = f'<div class="markdown-detail-body">{markdown_detail_html(markdown_text)}</div>'
    render_detail_panel(body_html, title=title, meta=meta)


def _inline_markdown_html(text: str) -> str:
    html = escape(str(text or "").strip())
    html = re.sub(r"`([^`]+)`", r'<code class="markdown-detail-inline-code">\1</code>', html)
    html = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html)
    return html


def _is_markdown_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = lines[index].strip()
    divider = lines[index + 1].strip()
    if "|" not in header or "|" not in divider:
        return False
    cells = [cell.strip() for cell in divider.strip("|").split("|")]
    return bool(cells) and all(re.match(r"^:?-{3,}:?$", cell or "") for cell in cells)


def _collect_markdown_table(lines: list[str], index: int) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    cursor = index
    while cursor < len(lines):
        line = lines[cursor].strip()
        if "|" not in line:
            break
        if cursor == index + 1:
            cursor += 1
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
        cursor += 1
    return rows, cursor


def _markdown_table_html(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = rows[0]
    body_rows = rows[1:]
    header_html = "".join(f"<th>{_inline_markdown_html(cell)}</th>" for cell in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_inline_markdown_html(cell)}</td>" for cell in row) + "</tr>"
        for row in body_rows
    )
    return (
        '<table class="markdown-detail-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
    )


def render_clean_list(items: list[str]) -> None:
    rows = "".join(f"<li>{escape(str(item))}</li>" for item in items)
    render_html(f'<ul class="clean-list">{rows}</ul>')


def render_status_pill(text: str, level: str = "neutral") -> None:
    normalized = str(level or "neutral").strip().lower()
    if normalized not in {"success", "warning", "danger", "neutral"}:
        normalized = "neutral"
    render_html(f'<span class="inline-pill inline-pill-{normalized}">{escape(str(text))}</span>')
