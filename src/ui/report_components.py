"""HTML primitives for the evidence-first editorial report surface."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from html import escape

from app.services.evidence_index import EvidenceItem
from app.services.model_display import display_model_detail, display_model_name
from src.metrics import SCORE_DIMENSION_FULL_MARKS, SCORE_DIMENSIONS
from src.ui.components import render_html

_DIMENSION_LABELS = dict(SCORE_DIMENSIONS)


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


def report_section_html(
    index: str,
    label: str,
    title: str,
    body_html: str,
    *,
    anchor_id: str = "",
) -> str:
    """Return one report section; only ``body_html`` is an already-trusted slot."""
    anchor = f' id="{_escaped(anchor_id)}"' if str(anchor_id).strip() else ""
    return (
        f'<section class="report-section"{anchor}>'
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


def report_contents_html(items: Iterable[tuple[object, object, object]]) -> str:
    """Return an escaped in-page contents list for report appendices."""
    links = "".join(
        '<li class="report-contents-item">'
        f'<a href="#{_escaped(anchor_id)}">'
        f'<span>{_escaped(index)}</span>{_escaped(title)}'
        "</a></li>"
        for anchor_id, index, title in items
    )
    return (
        '<nav class="report-contents" aria-label="本页目录">'
        '<p class="report-contents-label">本页目录</p>'
        f'<ol class="report-contents-list">{links}</ol>'
        "</nav>"
    )


def report_index_row_html(
    cells: Iterable[object],
    *,
    labels: Iterable[object] | None = None,
    accessible_label: object | None = None,
    active: bool = False,
    header: bool = False,
) -> str:
    """Return a single semantic review row used on desktop and mobile alike."""
    classes = ["report-index-row"]
    if active:
        classes.append("report-index-row--active")
    if header:
        classes.append("report-index-row--header")
    class_name = " ".join(classes)
    values = tuple(cells)
    cell_labels = tuple(labels or ())
    cell_html = "".join(
        '<div class="report-index-cell"'
        + (
            f' data-label="{_escaped(cell_labels[index])}"'
            if index < len(cell_labels) and str(cell_labels[index]).strip()
            else ""
        )
        + f">{_escaped(cell)}</div>"
        for index, cell in enumerate(values)
    )
    if header:
        return f'<div class="{class_name}" aria-hidden="true">{cell_html}</div>'
    current = ' aria-current="true"' if active else ""
    row_label = (
        _review_row_accessible_label(values, cell_labels)
        if accessible_label is None
        else str(accessible_label)
    )
    return (
        f'<div class="{class_name}" role="group" '
        f'aria-label="{_escaped(row_label)}"{current}>{cell_html}</div>'
    )


def evidence_index_html(
    items: Iterable[EvidenceItem],
    *,
    include_full_details: bool = True,
) -> str:
    """Render the linear evidence ledger with every item field escaped."""
    rows = "".join(
        _evidence_item_html(item, include_full_details=include_full_details) for item in items
    )
    return (
        '<section class="evidence-index" aria-label="代表样本证据索引">'
        f'<ol class="evidence-index-list">{rows}</ol>'
        "</section>"
    )


def render_report_masthead(title: str, description: str, eyebrow: str = "") -> None:
    render_html(report_masthead_html(title, description, eyebrow))


def render_scope_ledger(items: Iterable[tuple[object, object]]) -> None:
    render_html(scope_ledger_html(items))


def render_report_contents(items: Iterable[tuple[object, object, object]]) -> None:
    render_html(report_contents_html(items))


def _evidence_item_html(
    item: EvidenceItem,
    *,
    include_full_details: bool = True,
) -> str:
    model_name = display_model_name(item.model_name, source="live")
    model_id = display_model_detail(item.model_name)
    model_id_html = (
        f'<span class="evidence-index-model-id">{_escaped(model_id)}</span>'
        if model_id != model_name
        else ""
    )
    details = (
        _detail_html(
            "总分",
            f"{_score_text(item.total_score)} / 100",
            wrapper_class="evidence-index-total",
            value_class="evidence-index-total-value",
        )
        + _detail_html(
            "模型整体最弱维度",
            _dimension_label(item.weakest_dimension),
            wrapper_class="evidence-index-weakest",
            value_class="evidence-index-weakest-value",
        )
        + _dimension_detail_html(item.dimension_scores)
    )
    if include_full_details:
        details += (
            _detail_html("评分理由", item.rationale)
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
        f'<span class="evidence-index-model">{_escaped(model_name)}</span>'
        f"{model_id_html}"
        f'<span class="evidence-index-reason">{_escaped(_selection_reason_text(item.selection_reason))}</span>'
        "</div>"
        f'<h3 class="evidence-index-title">{_escaped(item.title)}</h3>'
        f'<dl class="evidence-index-details">{details}</dl>'
        "</div>"
        "</li>"
    )


def _detail_html(
    label: object,
    value: object,
    *,
    wrapper_class: str = "",
    value_class: str = "",
) -> str:
    wrapper_attr = f' class="{wrapper_class}"' if wrapper_class else ""
    value_attr = f' class="{value_class}"' if value_class else ""
    return (
        f"<div{wrapper_attr}><dt>{_escaped(label)}</dt>"
        f"<dd{value_attr}>{_escaped(value)}</dd></div>"
    )


def _dimension_detail_html(scores: Mapping[object, object]) -> str:
    return (
        f'<div class="evidence-index-dimension-detail"><dt>{_escaped("维度得分")}</dt><dd>'
        f"{_escaped_dimension_list_html(scores)}"
        "</dd></div>"
    )


def _escaped_dimension_list_html(scores: Mapping[object, object]) -> str:
    rows = "".join(
        f"<li>{_escaped(_dimension_score_text(field, score))}</li>"
        for field, score in scores.items()
    )
    return f'<ul class="evidence-index-dimensions">{rows}</ul>'


def _dimension_score_text(field: object, score: object) -> str:
    field_name = str(field)
    label = _dimension_label(field_name)
    full_mark = SCORE_DIMENSION_FULL_MARKS.get(field_name)
    score_text = _score_text(score)
    return f"{label} {score_text} / {full_mark}" if full_mark is not None else f"{label} {score_text}"


def _dimension_label(field: object) -> str:
    field_name = str(field)
    return _DIMENSION_LABELS.get(field_name, field_name)


def _selection_reason_text(reason: object) -> str:
    text = str(reason)
    prefix = "最弱维度："
    if not text.startswith(prefix):
        return text
    field_name = text[len(prefix) :].strip()
    return prefix + _dimension_label(field_name)


def _score_text(value: object) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _display(value)
    return f"{number:g}"


def _escaped(value: object) -> str:
    return escape(_display(value), quote=True)


def _review_row_accessible_label(
    values: Sequence[object],
    labels: Sequence[object],
) -> str:
    default_labels = ("模型", "样本数／平均分", "当前判断")
    parts = []
    for index, value in enumerate(values[:3]):
        label = labels[index] if index < len(labels) and str(labels[index]).strip() else default_labels[index]
        parts.append(f"{label}：{_display(value)}")
    return "；".join(parts)


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
