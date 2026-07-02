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
    render_compact_hero,
    render_context_grid,
    render_empty_state,
    render_info_panel,
    render_numbered_section,
    render_section_title,
)


# Key metrics tracked across optimization rounds. ``kind`` decides the
# direction of "improvement": scores should rise, error rates should fall.
KEY_METRICS = [
    {"key": "avg_score", "label": "平均总分", "kind": "score"},
    {"key": "evidence_score", "label": "依据可靠性", "kind": "score"},
    {"key": "hallucination_rate", "label": "幻觉率", "kind": "rate"},
    {"key": "red_line_error_rate", "label": "红线错误率", "kind": "rate"},
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


def build_open_issues(comparison_df, scores_df, errors_df) -> list[str]:
    """Issues the current evaluation set has not yet resolved, from live data."""
    issues = []

    metrics = get_optimization_comparison_metrics(comparison_df)
    if not metrics.empty:
        latest = metrics.iloc[-1]
        red_line = latest.get("red_line_error_rate")
        if pd.notna(red_line) and red_line > 0:
            issues.append(f"红线错误率仍为 {red_line:.1%}，尚未归零。")
        hallucination = latest.get("hallucination_rate")
        if pd.notna(hallucination) and hallucination > 0:
            issues.append(f"幻觉率仍为 {hallucination:.1%}，需继续补强依据类样本。")

    version_count = len(metrics)
    model_count = scores_df["model_name"].nunique() if "model_name" in getattr(scores_df, "columns", []) else 0
    score_count = len(scores_df)
    issues.append(
        f"评测样本量较小（{score_count} 条评分 · {model_count} 个模型 · {version_count} 轮对比），"
        "结论仅供样本内观察。"
    )
    issues.append("模型回答为模拟生成，尚未接入真实模型 API。")

    if errors_df is not None and not errors_df.empty and "error_type" in errors_df:
        counts = errors_df["error_type"].value_counts()
        scarce = [str(error_type) for error_type, count in counts.items() if count <= 1]
        if scarce:
            issues.append(f"部分错误标签样本不足（各仅 1 次）：{'、'.join(scarce)}。")
    return issues


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

    config = get_page_config("optimization_compare")
    render_compact_hero(
        eyebrow="FinDueEval",
        title=config.title,
        question=config.question,
    )

    if comparison_df.empty:
        render_empty_state("暂无可展示数据")
        return

    _render_key_changes(comparison_df)
    _render_comparison(comparison_df)
    _render_open_issues(comparison_df, data)


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


def _render_comparison(comparison_df) -> None:
    render_section_title("Baseline 与数据补强对比", "逐轮记录改动与关键指标，确认补强是否带来可观察改善。")
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
            "evidence_score": "依据可靠性",
            "hallucination_rate": "幻觉率",
            "red_line_error_rate": "红线错误率",
        }
    )
    st.dataframe(
        table[["优化版本", "优化类型", "改动说明", "平均总分", "依据可靠性", "幻觉率", "红线错误率"]],
        width="stretch",
        hide_index=True,
    )
    _render_metric_trend(comparison_df)


def _render_metric_trend(comparison_df) -> None:
    metrics = get_optimization_comparison_metrics(comparison_df)
    if metrics.empty:
        return

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


def _render_open_issues(comparison_df, data) -> None:
    render_section_title("仍未解决的问题", "当前评测集尚未覆盖或尚未改善的部分。")
    issues = build_open_issues(comparison_df, data.scores, data.errors)
    if not issues:
        render_empty_state("暂无记录")
        return
    for text in issues:
        st.markdown(f"- {text}")
