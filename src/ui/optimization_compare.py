"""Optimization validation page: baseline vs data-patch effect comparison."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.charts import themed_bar_chart
from src.metrics import (
    get_optimization_change_summary,
    get_optimization_comparison_metrics,
)
from src.ui.page_config import get_page_config
from src.ui.components import (
    render_context_grid,
    render_empty_state,
    render_info_panel,
    render_page_shell,
    render_section_title,
)


# Key metrics tracked across optimization rounds. ``kind`` decides the
# direction of "improvement": scores should rise, error rates should fall.
KEY_METRICS = [
    {"key": "avg_score", "label": "平均总分", "kind": "score"},
    {"key": "red_line_error_rate", "label": "红线错误率", "kind": "rate"},
    {"key": "hallucination_rate", "label": "幻觉率", "kind": "rate"},
    {"key": "evidence_score", "label": "依据可靠性", "kind": "score"},
]


def _format_value(value: float, kind: str) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:.1%}" if kind == "rate" else f"{value:.1f}"


def _format_delta(delta: float, kind: str) -> str:
    if pd.isna(delta):
        return "—"
    return f"{delta:+.1%}" if kind == "rate" else f"{delta:+.1f}"


def build_key_change_cards(comparison_df) -> list[dict]:
    """Compare the baseline round against the latest round per key metric."""
    metrics = get_optimization_comparison_metrics(comparison_df)
    if len(metrics) < 2:
        return []

    baseline = metrics.iloc[0]
    latest = metrics.iloc[-1]

    cards = []
    for spec in KEY_METRICS:
        base_value = float(baseline[spec["key"]]) if not pd.isna(baseline[spec["key"]]) else float("nan")
        latest_value = float(latest[spec["key"]]) if not pd.isna(latest[spec["key"]]) else float("nan")
        delta = latest_value - base_value
        if pd.isna(delta) or delta == 0:
            improved = None
        elif spec["kind"] == "score":
            improved = delta > 0
        else:
            improved = delta < 0

        cards.append(
            {
                "label": spec["label"],
                "kind": spec["kind"],
                "baseline_text": _format_value(base_value, spec["kind"]),
                "latest_text": _format_value(latest_value, spec["kind"]),
                "delta_text": _format_delta(delta, spec["kind"]),
                "improved": improved,
            }
        )
    return cards


def build_validation_conclusion(comparison_df) -> dict | None:
    """Summarize whether the data patch is effective and what remains open."""
    metrics = get_optimization_comparison_metrics(comparison_df)
    if len(metrics) < 2:
        return None

    baseline = metrics.iloc[0]
    latest = metrics.iloc[-1]

    avg_delta = float(latest["avg_score"] - baseline["avg_score"])
    red_line_delta = float(latest["red_line_error_rate"] - baseline["red_line_error_rate"])
    effective = avg_delta > 0 and red_line_delta < 0

    # The unresolved point is the error rate that remains highest after the patch.
    residual_label, residual_value = "暂无", 0.0
    for spec in KEY_METRICS:
        if spec["kind"] != "rate":
            continue
        value = float(latest[spec["key"]])
        if value > residual_value:
            residual_label, residual_value = spec["label"], value

    return {
        "baseline_version": str(baseline["version"]),
        "latest_version": str(latest["version"]),
        "effective": effective,
        "avg_delta": avg_delta,
        "red_line_delta": red_line_delta,
        "residual_label": residual_label,
        "residual_value": residual_value,
    }


def collect_optimization_compare_tables(data_bundle: dict) -> dict:
    data = data_bundle["data"]
    comparison_df = getattr(data, "optimization_comparison", pd.DataFrame())
    return {
        "metrics": get_optimization_comparison_metrics(comparison_df),
        "summary": get_optimization_change_summary(comparison_df),
    }


def render_optimization_compare_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    comparison_df = getattr(data, "optimization_comparison", pd.DataFrame())
    render_page_shell(get_page_config("optimization_compare"))

    if comparison_df.empty:
        render_empty_state("暂无可展示数据")
        _render_boundary_note()
        return

    _render_key_changes(comparison_df)

    tab_trend, tab_changes = st.tabs(["指标趋势", "变更说明"])

    with tab_trend:
        _render_metric_trend(comparison_df)

    with tab_changes:
        _render_change_table(comparison_df)

    _render_boundary_note()


def _render_key_changes(comparison_df) -> None:
    conclusion = build_validation_conclusion(comparison_df)
    cards = build_key_change_cards(comparison_df)
    if conclusion is None or not cards:
        render_empty_state("当前对比记录不足，无法展示优化前后变化。")
        return

    render_section_title("关键指标变化", "对比基线与数据补强后的核心指标，先判断改进是否有效。")

    verdict = "改进有效" if conclusion["effective"] else "改进有限"
    render_info_panel(
        f"总体判断：{verdict}",
        f"从「{conclusion['baseline_version']}」到「{conclusion['latest_version']}」，"
        f"平均总分变化 {conclusion['avg_delta']:+.1f} 分，"
        f"红线错误率变化 {conclusion['red_line_delta']:+.1%}。"
        f"其中{conclusion['residual_label']}仍为 {conclusion['residual_value']:.1%}，"
        "是后续仍需补强的方向。",
    )

    items = []
    for card in cards:
        if card["improved"] is True:
            mark = "↓ 改善" if card["kind"] == "rate" else "↑ 改善"
        elif card["improved"] is False:
            mark = "↑ 退步" if card["kind"] == "rate" else "↓ 退步"
        else:
            mark = "持平"
        items.append(
            (
                card["label"],
                f"{card['baseline_text']} → {card['latest_text']}（{card['delta_text']}，{mark}）",
            )
        )
    render_context_grid(items)


def _render_metric_trend(comparison_df) -> None:
    metrics = get_optimization_comparison_metrics(comparison_df)
    if metrics.empty:
        render_empty_state("暂无可展示数据")
        return

    render_section_title("得分指标趋势", "平均总分与依据可靠性逐轮变化，确认改进是否持续。")
    score_long = metrics.melt(
        id_vars="version",
        value_vars=["avg_score", "evidence_score", "reasoning_score"],
        var_name="metric",
        value_name="value",
    )
    score_long["指标"] = score_long["metric"].map(
        {"avg_score": "平均总分", "evidence_score": "依据可靠性", "reasoning_score": "推理与场景适配"}
    )
    themed_bar_chart(score_long, "version", "value", "优化版本", "得分", "指标", "指标")

    render_section_title("错误率趋势", "红线错误率与幻觉率应逐轮下降，未归零的维度仍需补强。")
    rate_long = metrics.melt(
        id_vars="version",
        value_vars=["red_line_error_rate", "hallucination_rate"],
        var_name="metric",
        value_name="value",
    )
    rate_long["指标"] = rate_long["metric"].map(
        {"red_line_error_rate": "红线错误率", "hallucination_rate": "幻觉率"}
    )
    themed_bar_chart(rate_long, "version", "value", "优化版本", "错误率", "指标", "指标")

    summary = get_optimization_change_summary(comparison_df)
    if summary:
        st.caption(summary[0])


def _render_change_table(comparison_df) -> None:
    render_section_title("各轮变更说明", "记录每一轮优化做了什么改动，便于追溯指标变化来源。")
    metrics = get_optimization_comparison_metrics(comparison_df)
    if metrics.empty:
        render_empty_state("暂无可展示数据")
        return

    table = metrics.rename(
        columns={
            "version": "优化版本",
            "change_type": "优化类型",
            "change_description": "改动说明",
            "avg_score": "平均总分",
            "red_line_error_rate": "红线错误率",
            "note": "说明",
        }
    )
    st.dataframe(
        table[["优化版本", "优化类型", "改动说明", "平均总分", "红线错误率", "说明"]],
        width="stretch",
        hide_index=True,
    )


def _render_boundary_note() -> None:
    render_section_title("适用边界")
    render_info_panel(
        "当前结果边界",
        "当前结果基于 MVP 样例数据和当前评测集观察，用于展示评测闭环与数据建设方法。"
        "样本量有限，不代表真实生产环境或大规模实验结论。",
    )
