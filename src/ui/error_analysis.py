"""Error attribution and data improvement workflow page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.metrics import (
    ERROR_TYPE_TO_DIMENSION,
    get_error_attribution_actions,
    get_priority_error_samples,
)
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_compact_hero,
    render_empty_state,
    render_numbered_section,
    render_section_title,
)


ACTION_PATH_COLUMNS = ["错误表现", "可能原因", "数据补强动作", "验证指标"]

# Compact error-label table, Chinese headers ordered for business reading.
ERROR_TABLE_COLUMNS = ["错误类型", "影响范围", "对应数据补强动作", "验证方式"]

# Main error-label → data-action table: one row per error label, priority-first.
ERROR_IMPROVEMENT_COLUMNS = [
    "错误标签",
    "出现次数",
    "影响维度",
    "典型表现",
    "可能数据原因",
    "补强动作",
    "验证指标",
]

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


def _typical_manifestations(error_df) -> dict[str, str]:
    """A representative error description per error type, read from the data."""
    if error_df is None or error_df.empty or "error_type" not in error_df:
        return {}
    if "error_description" not in error_df.columns:
        return {}
    result = {}
    for error_type, group in error_df.groupby("error_type"):
        descriptions = [
            text
            for text in (str(value).strip() for value in group["error_description"].tolist())
            if text and text.lower() not in {"nan", "none", "null"}
        ]
        if descriptions:
            result[str(error_type)] = descriptions[0]
    return result


def build_error_improvement_table(actions_df, error_df) -> pd.DataFrame:
    """Error label → data-action table, sorted by priority then frequency.

    Impact dimension, typical manifestation, root cause, action and validation
    are all derived from the loaded error labels and optimization plan.
    """
    if actions_df is None or actions_df.empty:
        return pd.DataFrame(columns=ERROR_IMPROVEMENT_COLUMNS)

    typical = _typical_manifestations(error_df)
    ranked = actions_df.copy()
    ranked["_priority_rank"] = ranked.get("priority", "").map(PRIORITY_RANK).fillna(9)
    ranked["_count"] = pd.to_numeric(ranked.get("count", 0), errors="coerce").fillna(0)
    ranked = ranked.sort_values(["_priority_rank", "_count"], ascending=[True, False])

    rows = []
    for _, row in ranked.iterrows():
        error_type = _text(row.get("error_type"), "未分类错误")
        rows.append(
            {
                "错误标签": error_type,
                "出现次数": int(row["_count"]),
                "影响维度": ERROR_TYPE_TO_DIMENSION.get(error_type, "综合表现"),
                "典型表现": typical.get(error_type, "暂无样本记录"),
                "可能数据原因": _text(row.get("root_cause"), "暂无记录"),
                "补强动作": _text(row.get("data_action"), "暂无对应动作"),
                "验证指标": _text(row.get("validation_metric"), "暂无验证方式"),
            }
        )
    return pd.DataFrame(rows, columns=ERROR_IMPROVEMENT_COLUMNS)


def render_error_analysis(data_bundle):
    config = get_page_config("error_analysis")
    render_compact_hero(
        eyebrow="财务/法律/投行场景大模型对比评测",
        title=config.title,
        question=config.question,
    )

    data = data_bundle["data"]
    error_df = data.errors
    optimization_df = data.optimizations

    actions = get_error_attribution_actions(error_df, optimization_df)
    if actions.empty:
        render_empty_state("暂无错误标签数据，无法展示错误归因。")
        return

    _render_boundary_line(error_df)
    _render_improvement_table(actions, error_df)
    _show_error_action_path(error_df, optimization_df)
    _show_priority_samples(error_df, optimization_df)


def _render_boundary_line(error_df) -> None:
    label_count = len(error_df)
    type_count = error_df["error_type"].nunique() if "error_type" in error_df else 0
    st.caption(
        f"当前共 {label_count} 条错误标签、{type_count} 类错误类型；样本量有限，"
        "补强动作仅用于当前评测集的数据建设参考。"
    )


def _render_improvement_table(actions, error_df) -> None:
    render_section_title(
        "错误标签 → 数据补强动作",
        "按影响优先级与出现次数排序，低优先级不使用强烈颜色。",
    )
    table = build_error_improvement_table(actions, error_df)
    if table.empty:
        render_empty_state("暂无错误标签数据。")
        return
    st.caption("当前样本观察：优先呈现高优先级与高频错误标签对应的数据补强动作。")
    st.dataframe(table, width="stretch", hide_index=True)


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
