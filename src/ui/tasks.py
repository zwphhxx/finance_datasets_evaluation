from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.metrics import get_task_by_case_id, merge_case_outputs_with_scores
from src.gold_quality import evaluate_gold_quality, field_text, field_value
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_action_cards,
    render_answer_boundary_panel,
    render_card,
    render_compact_hero,
    render_context_grid,
    render_empty_state,
    render_evidence_panel,
    render_html,
    render_info_panel,
    render_numbered_section,
    render_section_title,
    render_status_badge,
    render_status_summary,
    render_tag_cloud,
    render_story_section,
)


# Display-name mappings: translate stored English field values to business
# Chinese labels. Unmapped values fall back to the raw value so new data is
# never dropped or hidden. These are presentation labels, not invented data.
DOMAIN_LABELS = {
    "Capital Markets": "资本市场",
    "Financial": "财务尽调",
    "Legal": "法律审核",
}
TASK_TYPE_LABELS = {
    "Regulatory Analysis": "监管合规分析",
    "Revenue Verification": "收入核查",
    "Inventory Assessment": "存货评估",
    "Legal Compliance": "法律合规审查",
    "Gross Margin Analysis": "毛利率分析",
    "Receivables Risk": "应收回款风险",
    "Cash Flow Analysis": "现金流分析",
    "Related Party Funds": "关联方资金核查",
    "Contract Review": "重大合同审阅",
    "Related Party Compliance": "关联交易合规",
    "Control Change Review": "控制权变更审查",
    "Performance Commitment": "业绩承诺与补偿",
    "IPO Inquiry Review": "IPO 问询回复评估",
    "M&A Analysis": "并购交易分析",
}
DIFFICULTY_LABELS = {"Hard": "高难度", "Medium": "中等难度", "Easy": "低难度"}
DIFFICULTY_BADGE = {"Hard": "high", "Medium": "medium", "Easy": "low"}
RISK_LABELS = {"高": "高风险", "中": "中风险", "低": "低风险"}
RISK_BADGE = {"高": "high", "中": "medium", "低": "low"}

SUMMARY_LIMIT = 140

# Compact auxiliary table, ordered for business reading with Chinese headers.
TABLE_COLUMNS = [
    ("case_id", "案例编号", None),
    ("domain", "领域", DOMAIN_LABELS),
    ("task_type", "任务类型", TASK_TYPE_LABELS),
    ("difficulty", "难度", DIFFICULTY_LABELS),
    ("risk_level", "风险等级", RISK_LABELS),
    ("expected_capability", "考察能力", None),
    ("question", "任务摘要", None),
]


def _clean_text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def display_label(value, mapping: dict[str, str]) -> str:
    text = _clean_text(value)
    if text == "未标注":
        return text
    return mapping.get(text, text)


def summarize_text(value, limit: int = SUMMARY_LIMIT) -> str:
    text = _clean_text(value, fallback="")
    if not text:
        return "暂无摘要"
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_task_records(tasks_df: pd.DataFrame) -> list[dict[str, str]]:
    """Pure transform from raw task rows to business display fields."""
    records: list[dict[str, str]] = []
    for row in tasks_df.to_dict(orient="records"):
        difficulty_raw = _clean_text(row.get("difficulty"))
        risk_raw = _clean_text(row.get("risk_level"))
        records.append(
            {
                "case_id": _clean_text(row.get("case_id")),
                "domain_label": display_label(row.get("domain"), DOMAIN_LABELS),
                "task_type_label": display_label(row.get("task_type"), TASK_TYPE_LABELS),
                "difficulty_label": DIFFICULTY_LABELS.get(difficulty_raw, difficulty_raw),
                "difficulty_badge": DIFFICULTY_BADGE.get(difficulty_raw, "neutral"),
                "risk_label": RISK_LABELS.get(risk_raw, risk_raw),
                "risk_badge": RISK_BADGE.get(risk_raw, "neutral"),
                "capability": _clean_text(row.get("expected_capability"), fallback="暂无记录"),
                "summary": summarize_text(row.get("question")),
                "question_full": _clean_text(row.get("question"), fallback="暂无任务全文"),
                "context_full": _clean_text(row.get("context"), fallback=""),
            }
        )
    return records


def build_task_table(tasks_df: pd.DataFrame) -> pd.DataFrame:
    """Compact, business-ordered table with Chinese headers and labels."""
    table: dict[str, list[str]] = {}
    for source_column, display_name, mapping in TABLE_COLUMNS:
        if source_column not in tasks_df.columns:
            continue
        if mapping is not None:
            table[display_name] = [display_label(value, mapping) for value in tasks_df[source_column]]
        elif display_name == "任务摘要":
            table[display_name] = [summarize_text(value, limit=60) for value in tasks_df[source_column]]
        else:
            table[display_name] = [_clean_text(value) for value in tasks_df[source_column]]
    return pd.DataFrame(table)


def _truncate(value, limit: int = 40) -> str:
    text = _clean_text(value, fallback="暂无记录")
    if text == "暂无记录":
        return text
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def build_case_overview_rows(data) -> list[dict]:
    """One compact row per task, with Gold Answer / model-answer / error-label
    status derived from the linked data files. No values are hardcoded.
    Includes judgment criteria completeness (draft vs active)."""
    tasks_df = data.tasks
    if tasks_df.empty or "case_id" not in tasks_df.columns:
        return []

    answer_counts: dict[str, int] = {}
    if "case_id" in getattr(data.model_outputs, "columns", []):
        answer_counts = data.model_outputs["case_id"].dropna().astype(str).value_counts().to_dict()
    error_counts: dict[str, int] = {}
    if "case_id" in getattr(data.errors, "columns", []):
        error_counts = data.errors["case_id"].dropna().astype(str).value_counts().to_dict()

    rows: list[dict] = []
    for row in tasks_df.to_dict(orient="records"):
        case_id = _clean_text(row.get("case_id"))
        difficulty_raw = _clean_text(row.get("difficulty"))
        gold = data.gold_answer_map.get(case_id) or {}
        has_gold = field_value(gold, "core_conclusion") is not None
        # Judgment criteria completeness
        has_criteria = bool(
            has_gold
            and field_value(gold, "must_have_points")
            and field_value(gold, "unacceptable_errors")
        )
        rows.append(
            {
                "case_id": case_id,
                "domain_label": display_label(row.get("domain"), DOMAIN_LABELS),
                "task_type_label": display_label(row.get("task_type"), TASK_TYPE_LABELS),
                "difficulty_label": DIFFICULTY_LABELS.get(difficulty_raw, difficulty_raw),
                "difficulty_badge": DIFFICULTY_BADGE.get(difficulty_raw, "neutral"),
                "capability": _truncate(row.get("expected_capability")),
                "has_gold": has_gold,
                "has_criteria": has_criteria,
                "model_answer_count": int(answer_counts.get(case_id, 0)),
                "error_label_count": int(error_counts.get(case_id, 0)),
            }
        )
    return rows


# Difficulty display order from hardest to easiest, for the filter dropdown.
_DIFFICULTY_ORDER = ["高难度", "中等难度", "低难度"]


def filter_case_rows(rows, domain="全部", task_type="全部", difficulty="全部", gold="全部", answer="全部") -> list[dict]:
    """Apply the lightweight top filters to the pre-built case rows."""
    filtered = []
    for row in rows:
        if domain != "全部" and row["domain_label"] != domain:
            continue
        if task_type != "全部" and row["task_type_label"] != task_type:
            continue
        if difficulty != "全部" and row["difficulty_label"] != difficulty:
            continue
        if gold == "有" and not row["has_gold"]:
            continue
        if gold == "无" and row["has_gold"]:
            continue
        if answer == "有" and row["model_answer_count"] == 0:
            continue
        if answer == "无" and row["model_answer_count"] > 0:
            continue
        filtered.append(row)
    return filtered


def _build_sample_coverage_summary(rows) -> list[tuple[str, str]]:
    """Sample coverage summary derived from the case rows."""
    total = len(rows)
    with_gold = sum(1 for r in rows if r["has_gold"])
    with_criteria = sum(1 for r in rows if r["has_criteria"])
    with_answer = sum(1 for r in rows if r["model_answer_count"] > 0)
    with_error = sum(1 for r in rows if r["error_label_count"] > 0)
    return [
        ("任务总数", f"{total} 道"),
        ("Gold Answer 覆盖", f"{with_gold}/{total}"),
        ("评判标准完整", f"{with_criteria}/{total}"),
        ("已有模型回答", f"{with_answer} 道"),
        ("已触发错误标签", f"{with_error} 道"),
    ]


def render_tasks_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    config = get_page_config("tasks")

    # Portfolio compact hero
    domain_count = 0
    if not data.tasks.empty and "domain" in data.tasks.columns:
        domain_count = data.tasks["domain"].dropna().nunique()
    hero_stats = [
        (str(len(data.tasks)), "尽调任务样本"),
        (str(int(domain_count)), "专业领域"),
    ]
    render_compact_hero(
        eyebrow="财务/法律/投行场景大模型对比评测",
        title=config.title,
        question=config.question,
        stats=hero_stats,
    )

    if data.tasks.empty:
        render_empty_state("暂无可展示数据")
        return

    rows = build_case_overview_rows(data)

    # Portfolio sub-page: intro + inline tags
    domains = sorted({row["domain_label"] for row in rows})
    render_tag_cloud(domains)

    # 01 Sample coverage summary
    render_numbered_section("01", "样本覆盖摘要", "当前数据集的 Gold Answer、模型回答与错误标签覆盖情况。")
    render_context_grid(_build_sample_coverage_summary(rows))

    # 02 Filters
    render_numbered_section("02", "筛选条件", "按领域、任务类型、难度、Gold Answer 与模型回答状态过滤。")
    filtered = _render_filters(rows)

    # 03 Task table as evidence panel
    render_numbered_section("03", "任务清单", "一行一题，长文本见下方任务详情。")
    if not filtered:
        render_empty_state("没有符合当前筛选条件的任务。")
    else:
        _render_overview_table(filtered)

    # 04 Selected task detail
    render_numbered_section("04", "选中任务详情", "查看任务背景、要求、Gold Answer 与模型覆盖。")
    _render_selected_task_detail(data, filtered)


def _render_filters(rows) -> list[dict]:
    domains = ["全部"] + sorted({row["domain_label"] for row in rows})
    task_types = ["全部"] + sorted({row["task_type_label"] for row in rows})
    present_difficulties = {row["difficulty_label"] for row in rows}
    difficulties = ["全部"] + [d for d in _DIFFICULTY_ORDER if d in present_difficulties]
    difficulties += sorted(present_difficulties - set(_DIFFICULTY_ORDER))

    columns = st.columns(5)
    domain = columns[0].selectbox("领域", domains)
    task_type = columns[1].selectbox("任务类型", task_types)
    difficulty = columns[2].selectbox("难度", difficulties)
    gold = columns[3].selectbox("Gold Answer", ["全部", "有", "无"])
    answer = columns[4].selectbox("模型回答", ["全部", "有", "无"])

    return filter_case_rows(rows, domain, task_type, difficulty, gold, answer)


def _render_overview_table(rows) -> None:
    header_cells = "".join(
        f"<th>{escape(name)}</th>"
        for name in [
            "任务编号",
            "领域",
            "任务类型",
            "难度",
            "考察能力",
            "Gold Answer",
            "评判标准",
            "模型回答数",
            "错误标签数",
        ]
    )
    body = ""
    for row in rows:
        diff_badge = f'<span class="status-badge status-{row["difficulty_badge"]}">{escape(row["difficulty_label"])}</span>'
        if row["has_gold"]:
            gold_badge = '<span class="status-badge status-success">具备</span>'
        else:
            gold_badge = '<span class="status-badge status-neutral">缺失</span>'
        if row["has_criteria"]:
            criteria_badge = '<span class="status-badge status-success">完整</span>'
        else:
            criteria_badge = '<span class="status-badge status-warning">草稿</span>'
        body += (
            f'<tr><td class="check-key">{escape(row["case_id"])}</td>'
            f"<td>{escape(row['domain_label'])}</td>"
            f"<td>{escape(row['task_type_label'])}</td>"
            f"<td>{diff_badge}</td>"
            f'<td class="check-note">{escape(row["capability"])}</td>'
            f"<td>{gold_badge}</td>"
            f"<td>{criteria_badge}</td>"
            f'<td class="check-count">{row["model_answer_count"]}</td>'
            f'<td class="check-count">{row["error_label_count"]}</td></tr>'
        )
    table_html = f'<table class="check-table"><thead><tr>{header_cells}</tr></thead><tbody>{body}</tbody></table>'
    render_evidence_panel("任务列表", table_html)


def _render_selected_task_detail(data, rows) -> None:
    if not rows:
        render_empty_state("请调整筛选条件后再查看任务详情。")
        return

    domain_by_case = {row["case_id"]: row["domain_label"] for row in rows}
    case_ids = [row["case_id"] for row in rows]
    selected = st.selectbox(
        "选择任务",
        case_ids,
        format_func=lambda case_id: f"{case_id} · {domain_by_case.get(case_id, '未标注领域')}",
    )

    task_rows = get_task_by_case_id(data.tasks, selected)
    if task_rows.empty:
        render_empty_state("未找到该任务的记录。")
        return
    task = task_rows.iloc[0]

    scenario = _clean_text(task.get("scenario"), fallback=_clean_text(task.get("question"), fallback="暂无任务场景"))
    context = _clean_text(task.get("context"), fallback="暂无背景材料")
    capability = _clean_text(task.get("expected_capability"), fallback="暂无任务要求")
    fields = [("任务场景", scenario), ("任务背景", context), ("任务要求", capability)]
    render_card(
        "".join(
            f'<div class="fact-field"><div class="fact-label">{escape(label)}</div>'
            f'<div class="fact-value">{escape(value)}</div></div>'
            for label, value in fields
        ),
        class_name="fact-card",
    )

    _render_gold_summary(data.gold_answer_map.get(selected))
    _render_covered_models(data, selected)


def _render_gold_summary(gold) -> None:
    if not isinstance(gold, dict) or field_value(gold, "core_conclusion") is None:
        render_empty_state("该任务暂无 Gold Answer 记录。")
        return

    quality = evaluate_gold_quality(gold)
    status_class = "success" if quality["is_usable"] else "warning"
    render_status_badge(f"Gold Answer {quality['status']}", status_class)
    render_info_panel("Gold Answer 摘要", field_text(gold, "core_conclusion", "暂无标准结论"))

    render_answer_boundary_panel(
        "评测边界",
        [
            ("边界条件", field_text(gold, "boundary_conditions", "暂无记录")),
            ("不可接受错误", field_text(gold, "unacceptable_errors", "暂无记录")),
        ],
    )


def _render_covered_models(data, case_id: str) -> None:
    merged = merge_case_outputs_with_scores(data.model_outputs, data.scores, case_id)
    if merged.empty or "model_name" not in merged.columns:
        render_empty_state("该任务暂无模型回答记录。")
        return

    items = []
    for model_name in sorted(merged["model_name"].dropna().astype(str).unique()):
        model_rows = merged[merged["model_name"].astype(str) == model_name]
        total = model_rows.iloc[0].get("total_score")
        if total is None or (isinstance(total, float) and pd.isna(total)):
            score_text = "未评分"
        else:
            score_text = f"总分 {float(total):.0f}"
        items.append((model_name, score_text))

    render_section_title("已覆盖模型回答", f"当前任务共 {len(items)} 个模型回答。")
    render_context_grid(items)
