"""Error attribution and data improvement workflow page."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.metrics import (
    get_error_attribution_actions,
    get_priority_error_samples,
)
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_empty_state,
    render_html,
    render_page_shell,
    render_section_title,
)


ACTION_PATH_COLUMNS = ["错误表现", "可能原因", "数据补强动作", "验证指标"]

# Compact error-label table, Chinese headers ordered for business reading.
ERROR_TABLE_COLUMNS = ["错误类型", "影响范围", "对应数据补强动作", "验证方式"]

PRIORITY_RANK = {"高": 0, "中": 1, "低": 2}
PRIORITY_BADGE = {"高": "danger", "中": "warning", "低": "neutral"}


def build_error_action_path(actions_df):
    if actions_df is None or actions_df.empty:
        return pd.DataFrame(columns=ACTION_PATH_COLUMNS)

    path_df = pd.DataFrame(
        {
            "错误表现": actions_df.get("error_type", ""),
            "可能原因": actions_df.get("root_cause", ""),
            "数据补强动作": actions_df.get("data_action", ""),
            "验证指标": actions_df.get("validation_metric", ""),
        }
    )
    for column in ACTION_PATH_COLUMNS:
        path_df[column] = path_df[column].fillna("")
        path_df[column] = path_df[column].where(
            path_df[column].astype(str).str.strip() != "",
            "暂无对应记录",
        )
    return path_df[ACTION_PATH_COLUMNS]


def build_top_data_actions(actions_df, limit: int = 3) -> list[dict]:
    """Priority-sorted data actions derived from the error attribution table."""
    if actions_df is None or actions_df.empty:
        return []

    ranked = actions_df.copy()
    ranked["_priority_rank"] = ranked.get("priority", "").map(PRIORITY_RANK).fillna(9)
    ranked["_count"] = pd.to_numeric(ranked.get("count", 0), errors="coerce").fillna(0)
    ranked = ranked.sort_values(["_priority_rank", "_count"], ascending=[True, False])

    records = []
    for _, row in ranked.head(limit).iterrows():
        records.append(
            {
                "error_type": _text(row.get("error_type"), "未分类错误"),
                "priority": _text(row.get("priority"), "未标注"),
                "count": int(row["_count"]),
                "severity": _text(row.get("severity"), "未标注"),
                "models": _text(row.get("models"), "未标注"),
                "data_action": _text(row.get("data_action"), "暂无对应动作"),
                "sample_format": _text(row.get("sample_format"), "暂无样本格式"),
                "validation_metric": _text(row.get("validation_metric"), "暂无验证方式"),
            }
        )
    return records


def build_error_label_table(actions_df) -> pd.DataFrame:
    """Compact error-label view: type, impact, data action, validation."""
    if actions_df is None or actions_df.empty:
        return pd.DataFrame(columns=ERROR_TABLE_COLUMNS)

    rows = []
    for _, row in actions_df.iterrows():
        count = _text(row.get("count"), "0")
        severity = _text(row.get("severity"), "未标注")
        models = _text(row.get("models"), "未标注")
        rows.append(
            {
                "错误类型": _text(row.get("error_type"), "未分类错误"),
                "影响范围": f"{count} 次 · 严重程度 {severity} · {models}",
                "对应数据补强动作": _text(row.get("data_action"), "暂无对应动作"),
                "验证方式": _text(row.get("validation_metric"), "暂无验证方式"),
            }
        )
    return pd.DataFrame(rows, columns=ERROR_TABLE_COLUMNS)


def render_error_analysis(data_bundle):
    render_page_shell(get_page_config("error_analysis"))

    data = data_bundle["data"]
    error_df = data.errors
    optimization_df = data.optimizations

    actions = get_error_attribution_actions(error_df, optimization_df)
    if actions.empty:
        render_empty_state("暂无错误标签数据，无法展示错误归因。")
        return

    _render_top_actions(actions)
    _show_error_action_path(error_df, optimization_df)
    _render_error_label_table(actions)
    _show_priority_samples(error_df, optimization_df)


def _render_top_actions(actions) -> None:
    render_section_title("Top 数据补强动作", "按优先级与出现频次，从错误标签收敛出的重点数据建设动作。")
    records = build_top_data_actions(actions)
    if not records:
        render_empty_state("该模块用于展示数据闭环，当前暂无对应记录。")
        return

    st.caption("当前样本观察：以下动作直接对应高频或高严重程度的错误标签。")
    for record in records:
        priority_class = PRIORITY_BADGE.get(record["priority"], "neutral")
        render_html(
            f"""
            <div class="evidence-card evidence-card-flagged">
                <div class="evidence-head">
                    <span class="status-badge status-neutral">{escape(record["error_type"])}</span>
                    <span class="status-badge status-{priority_class}">优先级 {escape(record["priority"])}</span>
                    <span class="evidence-title">影响 {record["count"]} 次 · 严重程度 {escape(record["severity"])}</span>
                </div>
                <div class="evidence-field">
                    <div class="evidence-label">数据补强动作</div>
                    <div class="evidence-value">{escape(record["data_action"])}</div>
                </div>
                <div class="evidence-field">
                    <div class="evidence-label">样本格式</div>
                    <div class="evidence-value">{escape(record["sample_format"])}</div>
                </div>
                <div class="evidence-field">
                    <div class="evidence-label">验证方式</div>
                    <div class="evidence-value">{escape(record["validation_metric"])}</div>
                </div>
            </div>
            """
        )


def _show_error_action_path(error_df, optimization_df):
    render_section_title(
        "错误表现 → 可能原因 → 数据补强动作",
        "将错误标签收敛成可执行的数据建设路径，并保留验证指标用于复测。",
    )
    actions = get_error_attribution_actions(error_df, optimization_df)
    path_df = build_error_action_path(actions)
    if path_df.empty:
        render_empty_state("该模块用于展示数据闭环，当前暂无对应记录。")
        return
    st.dataframe(path_df, width="stretch", hide_index=True)


def _render_error_label_table(actions) -> None:
    render_section_title("错误标签明细", "错误类型、影响范围、对应数据补强动作与验证方式。")
    table = build_error_label_table(actions)
    if table.empty:
        render_empty_state("暂无错误标签数据。")
        return
    st.dataframe(table, width="stretch", hide_index=True)


def _show_priority_samples(error_df, optimization_df):
    render_section_title("重点错误样本", "优先展示高严重程度样本，定位需要补强的数据类型。")

    samples = get_priority_error_samples(error_df, optimization_df)
    if samples.empty:
        render_empty_state("暂无可展示数据")
        return

    sample_view = samples.copy()
    sample_view["data_action"] = sample_view["data_action"].fillna("")
    sample_view["data_action"] = sample_view["data_action"].where(
        sample_view["data_action"].astype(str).str.strip() != "",
        "暂无匹配数据补强动作。",
    )
    rename = {
        "case_id": "案例编号",
        "model_name": "模型",
        "error_type": "错误类型",
        "severity": "严重程度",
        "error_description": "错误说明",
        "data_action": "数据补强动作",
        "validation_metric": "验证方式",
    }
    available = [column for column in rename if column in sample_view.columns]
    display = sample_view[available].rename(columns=rename)
    st.dataframe(display, width="stretch", hide_index=True)


def render_error_analysis_page(data_bundle):
    render_error_analysis(data_bundle)


def _text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text
