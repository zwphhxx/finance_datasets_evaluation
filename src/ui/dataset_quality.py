"""Dataset quality and extensibility view.

This page reframes the project from "five sample questions" to the data-asset
engineering behind it: quality gates, task coverage, answer boundaries,
scoring consistency, attributable errors and extensible data improvement.
Every statistic is derived from the loaded data files and the dataset
manifest / label taxonomy — nothing is hardcoded.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.data_service import load_dataset_manifest, load_label_taxonomy
from src.gold_quality import QUALITY_FIELDS, evaluate_gold_quality
from src.ui.page_config import get_page_config
from src.ui.tasks import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    TASK_TYPE_LABELS,
    display_label,
)
from src.ui.components import (
    render_compact_hero,
    render_context_grid,
    render_empty_state,
    render_evidence_panel,
    render_html,
    render_metric_card,
    render_numbered_section,
    render_section_title,
)


CURRENT_MATRIX_NOTE = (
    "覆盖矩阵基于当前脱敏样本，用于展示任务覆盖结构，不代表完整生产数据集。"
    "样本较少时空白单元仅表示该组合暂未收录，可作为后续扩展的补样方向。"
)

GOLD_FIELD_CHECKS = [(label, canonical) for canonical, label in QUALITY_FIELDS]


# --------------------------------------------------------------------------- #
# Pure builders (no Streamlit calls) — kept testable.
# --------------------------------------------------------------------------- #
def _distinct(df: pd.DataFrame, column: str) -> int:
    if column in getattr(df, "columns", []):
        return int(df[column].dropna().nunique())
    return 0


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return str(value).strip() not in {"", "nan", "none", "null"}


def get_dataset_overview_cards(data, manifest: dict) -> list[dict]:
    """Six headline numbers, every value read from data or the manifest."""
    version = str(manifest.get("version") or "未声明")
    domain_count = _distinct(data.tasks, "domain")
    task_type_count = _distinct(data.tasks, "task_type")

    return [
        {"label": "数据集版本", "value": version, "note": "manifest 声明的数据集版本。"},
        {"label": "任务样本", "value": len(data.tasks), "note": f"覆盖 {domain_count} 个专业领域。"},
        {"label": "覆盖领域", "value": domain_count, "note": "用于衡量任务覆盖广度。"},
        {"label": "任务类型", "value": task_type_count, "note": "区分不同专业任务形态。"},
        {"label": "模型回答", "value": len(data.model_outputs), "note": "用于评分与错误归因的回答记录。"},
        {"label": "错误标签", "value": len(data.errors), "note": "可归因的扣分点标注。"},
    ]


def _translate_axis(value, mapping: dict) -> str:
    text = str(value)
    if text == "合计":
        return text
    return display_label(value, mapping)


def build_coverage_matrix(
    tasks_df: pd.DataFrame,
    row_field: str,
    col_field: str,
    row_labels: dict,
    col_labels: dict,
) -> pd.DataFrame:
    """Crosstab of two task dimensions with Chinese axis labels and totals."""
    if row_field not in tasks_df.columns or col_field not in tasks_df.columns:
        return pd.DataFrame()
    if tasks_df.empty:
        return pd.DataFrame()

    matrix = pd.crosstab(
        tasks_df[row_field],
        tasks_df[col_field],
        margins=True,
        margins_name="合计",
    )
    matrix.index = [_translate_axis(value, row_labels) for value in matrix.index]
    matrix.columns = [_translate_axis(value, col_labels) for value in matrix.columns]
    return matrix


def build_gold_answer_checks(gold_answer_map: dict, tasks_df: pd.DataFrame) -> list[dict]:
    """Per-task Gold Answer completeness, derived via the central evaluator."""
    if "case_id" not in tasks_df.columns:
        return []

    rows = []
    for case_id in tasks_df["case_id"].dropna().astype(str):
        quality = evaluate_gold_quality(gold_answer_map.get(case_id, {}))
        rows.append(
            {
                "case_id": case_id,
                "checks": quality["field_status"],
                "complete": quality["is_usable"],
                "status": quality["status"],
                "missing": quality["missing"],
            }
        )
    return rows


def summarize_gold_answer_quality(checks: list[dict]) -> dict:
    """Aggregate how many tasks satisfy each Gold Answer element and overall status."""
    total = len(checks)
    summary = {label: 0 for label, _ in GOLD_FIELD_CHECKS}
    for row in checks:
        for label, ok in row["checks"].items():
            if ok:
                summary[label] += 1
    complete = sum(1 for r in checks if r["complete"])
    return {
        "total": total,
        "by_element": summary,
        "complete": complete,
        "partial": total - complete,
    }


def build_rubric_checks(manifest: dict, scores_df: pd.DataFrame, taxonomy: dict) -> list[dict]:
    """Four Rubric quality gates, each derived from manifest + scores + taxonomy."""
    rubric = manifest.get("rubric", {})
    dimensions = rubric.get("dimensions", [])
    dimension_fields = [dim.get("field") for dim in dimensions]
    total = rubric.get("total")

    checks: list[dict] = []

    missing_fields = [f for f in dimension_fields if f not in getattr(scores_df, "columns", [])]
    if dimensions and not missing_fields:
        checks.append(
            {
                "item": "评分维度完整",
                "status": "pass",
                "detail": f"声明 {len(dimensions)} 个维度，scores.csv 字段齐备。",
            }
        )
    else:
        checks.append(
            {
                "item": "评分维度完整",
                "status": "fail",
                "detail": "维度声明或评分字段缺失：" + "、".join(missing_fields or ["未声明维度"]) + "。",
            }
        )

    weight_sum = sum(int(dim.get("weight", 0)) for dim in dimensions)
    if total is not None and weight_sum == int(total):
        checks.append(
            {"item": "权重合计合理", "status": "pass", "detail": f"各维度权重合计 {weight_sum} 分，与满分一致。"}
        )
    else:
        checks.append(
            {
                "item": "权重合计合理",
                "status": "fail",
                "detail": f"权重合计 {weight_sum} 与声明满分 {total} 不一致。",
            }
        )

    note_coverage = _review_note_coverage(scores_df)
    if note_coverage == 1.0:
        checks.append(
            {"item": "扣分标准可执行", "status": "pass", "detail": "每条评分均附扣分说明，可逐条复核。"}
        )
    elif note_coverage > 0:
        checks.append(
            {
                "item": "扣分标准可执行",
                "status": "warn",
                "detail": f"约 {note_coverage:.0%} 评分记录附扣分说明，其余待补。",
            }
        )
    else:
        checks.append({"item": "扣分标准可执行", "status": "fail", "detail": "评分记录缺少扣分说明字段。"})

    label_count = len(taxonomy.get("labels", []))
    if label_count:
        checks.append(
            {
                "item": "可映射到错误标签",
                "status": "pass",
                "detail": f"错误标签体系已定义 {label_count} 类，扣分可归因到具体标签。",
            }
        )
    else:
        checks.append(
            {"item": "可映射到错误标签", "status": "fail", "detail": "尚未定义错误标签体系，扣分无法归因。"}
        )

    return checks


def _review_note_coverage(scores_df: pd.DataFrame) -> float:
    if "review_note" not in getattr(scores_df, "columns", []) or scores_df.empty:
        return 0.0
    filled = scores_df["review_note"].apply(_has_value).sum()
    return float(filled) / float(len(scores_df))


def build_error_label_coverage(taxonomy: dict, errors_df: pd.DataFrame) -> list[dict]:
    """Taxonomy labels with their observed frequency and improvement direction."""
    labels = taxonomy.get("labels", [])
    if not labels:
        return []

    counts = {}
    if "error_type" in getattr(errors_df, "columns", []):
        counts = errors_df["error_type"].dropna().astype(str).value_counts().to_dict()

    rows = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        name = str(label.get("name", "")).strip()
        rows.append(
            {
                "name": name,
                "definition": str(label.get("definition", "")).strip(),
                "count": int(counts.get(name, 0)),
                "data_direction": str(label.get("data_direction", "")).strip(),
            }
        )
    rows.sort(key=lambda item: item["count"], reverse=True)
    return rows


def get_extension_steps(manifest: dict) -> list[tuple[str, str]]:
    """Concrete接入 steps, phrased against the real data fields."""
    task_fields = "case_id、domain、task_type、difficulty、question、context、expected_capability、risk_level"
    gold_config = manifest.get("gold_answer", {})
    gold_required = "、".join(gold_config.get("required_fields", []) or ["conclusion", "basis"])
    gold_boundary = " / ".join(gold_config.get("boundary_any_of", []) or ["risk_boundary", "red_line_errors"])

    return [
        (
            "新增任务样本",
            f"在 tasks.csv 补齐 {task_fields}，并在 gold_answers.json 配齐 {gold_required} "
            f"与 {gold_boundary}（答案边界至少其一）及评分要点 must_have_points。",
        ),
        (
            "新增模型回答",
            "在 model_outputs.csv 追加 output_id、case_id、model_name、answer_text；"
            "模型须先登记到 manifest 的模型范围，再在 scores.csv 按 Rubric 维度补齐评分。",
        ),
        (
            "新增错误标签",
            "先在 label_taxonomy.yml 登记标签的名称、定义、典型表现与数据补强方向，"
            "再在 error_labels.csv 引用该标签，确保错误可归因。",
        ),
        (
            "新增优化验证",
            "在 optimization_comparison.csv 记录版本、变更类型、变更说明与关键指标，"
            "随后运行 scripts/validate_dataset.py 复核数据一致性。",
        ),
    ]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
_STATUS_LABEL = {"pass": ("具备", "success"), "warn": ("部分", "warning"), "fail": ("缺失", "danger")}


def render_dataset_quality_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    manifest = load_dataset_manifest()
    taxonomy = load_label_taxonomy()

    config = get_page_config("dataset_quality")
    render_compact_hero(
        eyebrow="财务/法律/投行场景大模型对比评测",
        title=config.title,
        question=config.question,
    )

    # 01 数据集概览
    render_numbered_section("01", "数据集概览", "关键数字均由当前数据文件动态计算。")
    _render_overview(data, manifest)

    # 02 任务覆盖矩阵
    render_numbered_section("02", "任务覆盖矩阵", "从领域、任务类型与难度三个角度观察样本覆盖结构。")
    _render_coverage(data)

    # 03 Gold Answer 质量检查
    render_numbered_section("03", "Gold Answer 质量检查", "确认每道题的参考答案具备评分所需的核心要素。")
    _render_gold_answer_quality(data)

    # 04 Rubric 质量检查
    render_numbered_section("04", "Rubric 质量检查", "确认评分维度、权重与扣分标准可执行且可归因。")
    _render_rubric_quality(manifest, data, taxonomy)

    # 05 错误标签覆盖
    render_numbered_section("05", "错误标签覆盖", "展示错误标签体系、出现次数与高频错误的数据补强方向。")
    _render_error_label_coverage(taxonomy, data)

    # 06 扩展接入说明
    render_numbered_section("06", "扩展接入说明", "从五道示例扩展到更大数据集时，各类资产的补齐方式。")
    render_context_grid(get_extension_steps(manifest))


def _render_overview(data, manifest: dict) -> None:
    cards = get_dataset_overview_cards(data, manifest)
    columns = st.columns(3)
    for index, card in enumerate(cards):
        with columns[index % 3]:
            render_metric_card(card["label"], card["value"], card["note"])


def _render_coverage(data) -> None:
    matrices = [
        ("领域 × 任务类型", "domain", "task_type", DOMAIN_LABELS, TASK_TYPE_LABELS),
        ("领域 × 难度", "domain", "difficulty", DOMAIN_LABELS, DIFFICULTY_LABELS),
        ("任务类型 × 难度", "task_type", "difficulty", TASK_TYPE_LABELS, DIFFICULTY_LABELS),
    ]
    rendered_any = False
    for title, row_field, col_field, row_labels, col_labels in matrices:
        matrix = build_coverage_matrix(data.tasks, row_field, col_field, row_labels, col_labels)
        if matrix.empty:
            continue
        table_html = _render_matrix_html(matrix, title)
        render_evidence_panel(title, table_html)
        rendered_any = True

    if rendered_any:
        st.caption(CURRENT_MATRIX_NOTE)
    else:
        render_empty_state("暂无任务样本，无法生成覆盖矩阵。")


def _render_matrix_html(matrix: pd.DataFrame, title: str) -> str:
    columns = list(matrix.columns)
    header_cells = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body_rows = ""
    for index, row in matrix.iterrows():
        is_total_row = str(index) == "合计"
        cells = ""
        for column in columns:
            value = row[column]
            is_total = is_total_row or str(column) == "合计"
            classes = []
            if is_total:
                classes.append("matrix-total")
            elif isinstance(value, (int, float)) and value == 0:
                classes.append("matrix-zero")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            cells += f"<td{class_attr}>{escape(str(value))}</td>"
        body_rows += f"<tr><th>{escape(str(index))}</th>{cells}</tr>"
    return (
        '<table class="matrix-table"><thead><tr><th></th>'
        f"{header_cells}</tr></thead><tbody>{body_rows}</tbody></table>"
    )


def _status_cell(status: str) -> str:
    text, level = _STATUS_LABEL.get(status, ("未知", "neutral"))
    return f'<span class="status-badge status-{level}">{escape(text)}</span>'


def _render_gold_answer_quality(data) -> None:
    checks = build_gold_answer_checks(data.gold_answer_map, data.tasks)
    if not checks:
        render_empty_state("暂无任务样本，无法检查 Gold Answer。")
        return

    summary = summarize_gold_answer_quality(checks)
    st.caption(
        f'共 {summary["total"]} 道题，其中 {summary["complete"]} 道满足评测使用条件，'
        f'{summary["partial"]} 道部分满足。'
    )

    element_labels = [label for label, _ in GOLD_FIELD_CHECKS]
    header = "".join(f"<th>{escape(label)}</th>" for label in element_labels)
    body = ""
    for row in checks:
        cells = "".join(_wrap_td(_status_cell("pass" if row["checks"][label] else "fail")) for label in element_labels)
        status_class = "success" if row["complete"] else "warning"
        status_badge = f'<span class="status-badge status-{status_class}">{escape(row["status"])}</span>'
        body += f'<tr><td class="check-key">{escape(row["case_id"])}</td>{cells}<td>{status_badge}</td></tr>'
    table_html = (
        f'<table class="check-table"><thead><tr><th>案例编号</th>{header}<th>质量状态</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )
    render_evidence_panel("Gold Answer 质量检查", table_html)


def _wrap_td(inner: str) -> str:
    return f"<td>{inner}</td>"


def _render_rubric_quality(manifest: dict, data, taxonomy: dict) -> None:
    checks = build_rubric_checks(manifest, data.scores, taxonomy)
    if not checks:
        render_empty_state("暂无 Rubric 配置，无法检查评分一致性。")
        return

    body = ""
    for check in checks:
        body += (
            f'<tr><td class="check-key">{escape(check["item"])}</td>'
            f"{_wrap_td(_status_cell(check['status']))}"
            f'<td class="check-note">{escape(check["detail"])}</td></tr>'
        )
    table_html = (
        '<table class="check-table"><thead><tr><th>检查项</th><th>状态</th><th>说明</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )
    render_evidence_panel("Rubric 质量检查", table_html)


def _render_error_label_coverage(taxonomy: dict, data) -> None:
    rows = build_error_label_coverage(taxonomy, data.errors)
    if not rows:
        render_empty_state("尚未定义错误标签体系。")
        return

    max_count = max((row["count"] for row in rows), default=0)
    body = ""
    for row in rows:
        is_high = row["count"] > 0 and row["count"] == max_count
        flag = '<span class="status-badge status-warning">高频</span>' if is_high else ""
        count_cell = f'{row["count"]} 次 {flag}'.strip()
        body += (
            f'<tr><td class="check-key">{escape(row["name"])}</td>'
            f'<td class="check-note">{escape(row["definition"])}</td>'
            f'<td class="check-count">{count_cell}</td>'
            f'<td class="check-note">{escape(row["data_direction"])}</td></tr>'
        )
    table_html = (
        '<table class="check-table"><thead><tr><th>错误类型</th><th>定义</th><th>出现次数</th>'
        f"<th>数据补强方向</th></tr></thead><tbody>{body}</tbody></table>"
    )
    render_evidence_panel("错误标签覆盖", table_html)
