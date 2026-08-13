"""HTML primitives for the evidence-first editorial report surface."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from html import escape

from app.services.evidence_index import EvidenceItem
from src.ui.components import render_html


def report_masthead_html(title: str, description: str, eyebrow: str = "") -> str:
    """Return an escaped report masthead without any page-specific decisions."""
    eyebrow_html = (
        f'<p class="report-eyebrow">{_escaped(eyebrow)}</p>' if str(eyebrow).strip() else ""
    )
    return (
        '<header class="report-masthead">'
        f"{eyebrow_html}"
        f'<h1 class="report-masthead-title">{_escaped(title)}</h1>'
        f'<p class="report-masthead-description">{_escaped(description)}</p>'
        "</header>"
    )


def scope_ledger_html(items: Iterable[tuple[object, object]]) -> str:
    """Return a small escaped scope ledger for report metadata."""
    rows = "".join(
        '<div class="report-ledger-item">'
        f"<dt>{_escaped(label)}</dt><dd>{_escaped(value)}</dd>"
        "</div>"
        for label, value in items
    )
    return f'<dl class="report-ledger">{rows}</dl>'


def report_section_html(index: str, label: str, title: str, body_html: str) -> str:
    """Return one report section; only ``body_html`` is an already-trusted slot."""
    return (
        '<section class="report-section">'
        '<header class="report-section-heading">'
        f'<div class="report-section-index">{_escaped(index)}</div>'
        "<div>"
        f'<p class="report-section-label">{_escaped(label)}</p>'
        f'<h2 class="report-section-title">{_escaped(title)}</h2>'
        "</div>"
        "</header>"
        f'<div class="report-section-body">{body_html}</div>'
        "</section>"
    )


def report_index_row_html(cells: Iterable[object], *, active: bool = False) -> str:
    """Return a single semantic review row used on desktop and mobile alike."""
    classes = "report-index-row report-index-row--active" if active else "report-index-row"
    cell_html = "".join(
        f'<div class="report-index-cell">{_escaped(cell)}</div>' for cell in cells
    )
    return f'<div class="{classes}">{cell_html}</div>'


def evidence_index_html(items: Iterable[EvidenceItem]) -> str:
    """Render the linear evidence ledger with every item field escaped."""
    rows = "".join(_evidence_item_html(item) for item in items)
    return (
        '<section class="evidence-index" aria-label="代表样本证据索引">'
        f'<ol class="evidence-index-list">{rows}</ol>'
        "</section>"
    )


def render_report_masthead(title: str, description: str, eyebrow: str = "") -> None:
    render_html(report_masthead_html(title, description, eyebrow))


def render_scope_ledger(items: Iterable[tuple[object, object]]) -> None:
    render_html(scope_ledger_html(items))


def _evidence_item_html(item: EvidenceItem) -> str:
    dimensions = "".join(
        f"<li>{_escaped(field)}：{_escaped(score)}</li>"
        for field, score in item.dimension_scores.items()
    )
    details = (
        _detail_html("总分", item.total_score)
        + _detail_html("最弱维度", item.weakest_dimension)
        + _detail_html("维度得分", dimensions, trusted=True)
        + _detail_html("评分理由", item.rationale)
        + _detail_html("审阅备注", item.review_note)
        + _detail_html("模型回答", item.answer_text)
        + _detail_html("专业标准答案", item.gold_answer)
    )
    return (
        '<li class="evidence-index-item">'
        '<span class="evidence-index-rail" aria-hidden="true"></span>'
        '<div class="evidence-index-content">'
        '<div class="evidence-index-head">'
        f'<span class="evidence-index-case">{_escaped(item.case_id)}</span>'
        f'<span class="evidence-index-model">{_escaped(item.model_name)}</span>'
        f'<span class="evidence-index-reason">{_escaped(item.selection_reason)}</span>'
        "</div>"
        f'<h3 class="evidence-index-title">{_escaped(item.title)}</h3>'
        f'<dl class="evidence-index-details">{details}</dl>'
        "</div>"
        "</li>"
    )


def _detail_html(label: object, value: object, *, trusted: bool = False) -> str:
    display = str(value) if trusted else _escaped(value)
    return f"<div><dt>{_escaped(label)}</dt><dd>{display}</dd></div>"


def _escaped(value: object) -> str:
    return escape(_display(value), quote=True)


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, Mapping):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)
