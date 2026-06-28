from __future__ import annotations

import streamlit as st

from src.charts import themed_bar_chart
from src.metrics import (
    SCORE_DIMENSIONS,
    SCORE_DIMENSION_FULL_MARKS,
    get_dimension_gap_ranking,
    get_model_capability_summaries,
    get_model_dimension_scores,
    get_model_domain_scores,
    get_model_error_type_counts,
    get_model_total_scores,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import DOMAIN_LABELS, display_label
from src.ui.components import (
    render_context_grid,
    render_empty_state,
    render_info_panel,
    render_page_shell,
    render_section_title,
)


_DIMENSION_FULL_BY_LABEL = {
    label: SCORE_DIMENSION_FULL_MARKS[column] for column, label in SCORE_DIMENSIONS
}


def build_diagnosis(scores_df, error_df) -> dict | None:
    """Derive the diagnosis conclusion from current scores and error labels."""
    totals = get_model_total_scores(scores_df)
    if totals.empty:
        return None

    ranking = totals.sort_values("total_score", ascending=False)
    top_model = str(ranking.iloc[0]["model_name"])
    top_score = float(ranking.iloc[0]["total_score"])
    bottom_model = str(ranking.iloc[-1]["model_name"])
    bottom_score = float(ranking.iloc[-1]["total_score"])

    gap_ranking = get_dimension_gap_ranking(scores_df)
    weakest_dimension = str(gap_ranking.iloc[0]["dimension"]) if not gap_ranking.empty else "暂无"
    weakest_attainment = float(gap_ranking.iloc[0]["attainment"]) if not gap_ranking.empty else 0.0

    divergent_dimension, divergent_spread, priority_dimension = _dimension_spreads(scores_df)

    error_counts = get_model_error_type_counts(error_df)
    if not error_counts.empty:
        top_error = error_counts.groupby("error_type")["count"].sum().sort_values(ascending=False)
        top_error_type = str(top_error.index[0])
        top_error_count = int(top_error.iloc[0])
    else:
        top_error_type, top_error_count = "", 0

    return {
        "ranking": [(str(r["model_name"]), float(r["total_score"])) for _, r in ranking.iterrows()],
        "top_model": top_model,
        "top_score": top_score,
        "bottom_model": bottom_model,
        "bottom_score": bottom_score,
        "spread": top_score - bottom_score,
        "weakest_dimension": weakest_dimension,
        "weakest_attainment": weakest_attainment,
        "divergent_dimension": divergent_dimension,
        "divergent_spread": divergent_spread,
        "priority_dimension": priority_dimension,
        "top_error_type": top_error_type,
        "top_error_count": top_error_count,
    }


def _dimension_spreads(scores_df):
    """Return (most divergent dimension, its spread, priority dimension).

    Divergence is the gap between the best and worst model on a dimension's
    attainment; the priority dimension is the one where even the best model
    attains least, signalling a systemic gap.
    """
    dimension_scores = get_model_dimension_scores(scores_df)
    if dimension_scores.empty:
        return "暂无", 0.0, "暂无"

    most_divergent, max_spread = "暂无", -1.0
    priority, min_best = "暂无", 2.0
    for dimension, group in dimension_scores.groupby("dimension"):
        full = _DIMENSION_FULL_BY_LABEL.get(str(dimension))
        if not full:
            continue
        attainments = group["score"] / full
        spread = float(attainments.max() - attainments.min())
        if spread > max_spread:
            most_divergent, max_spread = str(dimension), spread
        best = float(attainments.max())
        if best < min_best:
            priority, min_best = str(dimension), best
    return most_divergent, max_spread, priority


def render_model_diagnosis_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    render_page_shell(get_page_config("model_diagnosis"))

    if data.model_outputs.empty:
        render_empty_state("暂无可展示数据")
        return

    diagnosis = build_diagnosis(data.scores, data.errors)
    if diagnosis is None:
        render_empty_state("当前暂无可展示的评分数据。")
        return

    _render_conclusion(diagnosis)

    tab_total, tab_dimensions, tab_errors, tab_domains, tab_summary = st.tabs(
        ["综合得分", "分维度得分", "错误类型", "领域表现", "逐模型摘要"]
    )

    with tab_total:
        render_section_title("各模型综合得分")
        totals = get_model_total_scores(data.scores)
        themed_bar_chart(totals, "model_name", "total_score", "模型", "平均总分")
        st.caption(
            f"结论：{diagnosis['top_model']} 平均总分最高（{diagnosis['top_score']:.1f}），"
            f"{diagnosis['bottom_model']} 最低（{diagnosis['bottom_score']:.1f}）。"
        )

    with tab_dimensions:
        render_section_title("各模型分维度得分")
        dimensions = get_model_dimension_scores(data.scores)
        themed_bar_chart(dimensions, "dimension", "score", "评分维度", "平均得分", "model_name", "模型")
        st.caption(
            f"结论：{diagnosis['weakest_dimension']} 为各模型共同薄弱维度，"
            f"平均达成率约 {diagnosis['weakest_attainment']:.0%}。"
        )

    with tab_errors:
        render_section_title("各模型错误类型分布")
        error_counts = get_model_error_type_counts(data.errors)
        if error_counts.empty:
            render_empty_state("当前暂无可展示的错误标签数据。")
        else:
            themed_bar_chart(error_counts, "error_type", "count", "错误类型", "出现次数", "model_name", "模型")
            if diagnosis["top_error_type"]:
                st.caption(
                    f"结论：高频错误为「{diagnosis['top_error_type']}」，"
                    f"共 {diagnosis['top_error_count']} 次。"
                )

    with tab_domains:
        render_section_title("各模型领域表现")
        domain_scores = get_model_domain_scores(data.scores, data.tasks)
        _render_domain_chart(domain_scores)

    with tab_summary:
        render_section_title("逐模型能力摘要")
        _render_capability_summaries(data.scores, data.errors, data.tasks)


def _render_conclusion(diagnosis: dict) -> None:
    render_section_title("诊断结论", "先看结论，再看分维度证据。")
    render_info_panel(
        "总体判断",
        f"{diagnosis['top_model']} 综合表现领先，{diagnosis['bottom_model']} 相对落后，"
        f"平均总分差距约 {diagnosis['spread']:.1f} 分。各模型共同薄弱维度为"
        f"{diagnosis['weakest_dimension']}，建议优先补强。",
    )
    render_context_grid(
        [
            (
                "模型间差异",
                f"{diagnosis['divergent_dimension']} 维度分化最明显，"
                f"最高与最低模型达成率相差约 {diagnosis['divergent_spread']:.0%}。",
            ),
            (
                "共同短板",
                f"{diagnosis['weakest_dimension']}，各模型平均达成率约 "
                f"{diagnosis['weakest_attainment']:.0%}。",
            ),
            (
                "优先补强维度",
                f"{diagnosis['priority_dimension']}，即使表现最好的模型在该维度仍未达标。",
            ),
        ]
    )


def _render_domain_chart(domain_scores) -> None:
    if domain_scores.empty:
        render_empty_state("当前暂无可展示的领域得分数据。")
        return

    chart_data = domain_scores.copy()
    chart_data["领域"] = chart_data["domain"].map(lambda value: display_label(value, DOMAIN_LABELS))
    themed_bar_chart(chart_data, "领域", "total_score", "领域", "平均总分", "model_name", "模型")

    domain_avg = chart_data.groupby("领域")["total_score"].mean().sort_values()
    if not domain_avg.empty:
        st.caption(
            f"结论：{domain_avg.index[0]} 相关任务平均得分最低（{domain_avg.iloc[0]:.1f}），"
            "建议优先补强该领域样本。"
        )


def _render_capability_summaries(scores_df, error_df, tasks_df) -> None:
    summaries = get_model_capability_summaries(scores_df, error_df, tasks_df)
    if not summaries:
        render_empty_state("暂无可展示数据")
        return

    for item in summaries:
        with st.expander(item["model_name"], expanded=True):
            st.write(item["summary"])


def collect_model_diagnosis_tables(data_bundle: dict) -> dict:
    data = data_bundle["data"]
    return {
        "total_scores": get_model_total_scores(data.scores),
        "dimension_scores": get_model_dimension_scores(data.scores),
        "error_counts": get_model_error_type_counts(data.errors),
        "domain_scores": get_model_domain_scores(data.scores, data.tasks),
        "summaries": get_model_capability_summaries(data.scores, data.errors, data.tasks),
    }
