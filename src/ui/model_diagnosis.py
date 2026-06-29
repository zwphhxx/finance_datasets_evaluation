from __future__ import annotations

from html import escape

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
    render_empty_state,
    render_empty_state_with_actions,
    render_html,
    render_page_shell,
    render_review_caveat,
    render_section_title,
)


_DIMENSION_FULL_BY_LABEL = {
    label: SCORE_DIMENSION_FULL_MARKS[column] for column, label in SCORE_DIMENSIONS
}
_DIMENSION_ORDER = [label for _, label in SCORE_DIMENSIONS]


def _attainment_level(attainment: float) -> str:
    if attainment >= 0.85:
        return "success"
    if attainment >= 0.6:
        return "warning"
    return "danger"


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


def _top_error_for_model(error_counts, model_name: str) -> str:
    if error_counts.empty:
        return "无高频错误"
    model_errors = error_counts[error_counts["model_name"].astype(str) == model_name]
    if model_errors.empty:
        return "无高频错误"
    top = model_errors.sort_values("count", ascending=False).iloc[0]
    return f"{top['error_type']}（{int(top['count'])} 次）"


def _model_dimension_extremes(dimension_scores, model_name: str) -> tuple[str, str]:
    if dimension_scores.empty:
        return "暂无", "暂无"
    subset = dimension_scores[dimension_scores["model_name"].astype(str) == model_name]
    attainments = []
    for _, row in subset.iterrows():
        full = _DIMENSION_FULL_BY_LABEL.get(str(row["dimension"]))
        if not full:
            continue
        attainments.append((str(row["dimension"]), float(row["score"]) / full))
    if not attainments:
        return "暂无", "暂无"
    attainments.sort(key=lambda item: item[1])
    weakest, strongest = attainments[0], attainments[-1]
    return f"{strongest[0]}（{strongest[1]:.0%}）", f"{weakest[0]}（{weakest[1]:.0%}）"


def _model_boundary(domain_scores, model_name: str) -> str:
    if domain_scores.empty:
        return "样本有限，仅供当前评测集观察"
    subset = domain_scores[domain_scores["model_name"].astype(str) == model_name]
    if subset.empty:
        return "样本有限，仅供当前评测集观察"
    by_domain = subset.groupby("domain")["total_score"].mean().sort_values()
    worst = display_label(by_domain.index[0], DOMAIN_LABELS)
    best = display_label(by_domain.index[-1], DOMAIN_LABELS)
    if len(by_domain) == 1 or best == worst:
        return f"{best} 任务，仅当前样本观察"
    return f"{best} 相对稳定；{worst} 需人工复核"


def build_model_comparison_rows(scores_df, error_df, tasks_df) -> list[dict]:
    """One comparison row per model, sorted by average score (high to low).

    Average, strongest/weakest dimension, frequent error and applicable
    boundary are all computed from the loaded scores, error labels and tasks.
    """
    totals = get_model_total_scores(scores_df)
    if totals.empty:
        return []

    dimension_scores = get_model_dimension_scores(scores_df)
    error_counts = get_model_error_type_counts(error_df)
    domain_scores = get_model_domain_scores(scores_df, tasks_df)

    rows = []
    for _, total in totals.sort_values("total_score", ascending=False).iterrows():
        model = str(total["model_name"])
        strongest, weakest = _model_dimension_extremes(dimension_scores, model)
        rows.append(
            {
                "model": model,
                "avg_score": float(total["total_score"]),
                "strongest_dim": strongest,
                "weakest_dim": weakest,
                "top_error": _top_error_for_model(error_counts, model),
                "boundary": _model_boundary(domain_scores, model),
            }
        )
    return rows


def build_dimension_matrix(scores_df) -> dict:
    """Models (rows) × Rubric dimensions (columns) with attainment levels."""
    dimension_scores = get_model_dimension_scores(scores_df)
    if dimension_scores.empty:
        return {"dimensions": [], "rows": []}

    present = set(dimension_scores["dimension"].astype(str))
    dimensions = [label for label in _DIMENSION_ORDER if label in present]

    rows = []
    for model, group in dimension_scores.groupby("model_name"):
        by_dimension = {str(row["dimension"]): float(row["score"]) for _, row in group.iterrows()}
        cells = []
        for dimension in dimensions:
            full = _DIMENSION_FULL_BY_LABEL.get(dimension, 0)
            score = by_dimension.get(dimension)
            if score is None or not full:
                cells.append({"dimension": dimension, "score": None, "full": full, "attainment": None, "level": "neutral"})
            else:
                attainment = score / full
                cells.append(
                    {
                        "dimension": dimension,
                        "score": score,
                        "full": full,
                        "attainment": attainment,
                        "level": _attainment_level(attainment),
                    }
                )
        rows.append({"model": str(model), "cells": cells})
    rows.sort(key=lambda item: item["model"])
    return {"dimensions": dimensions, "rows": rows}


def render_model_diagnosis_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    eval_status = data_bundle.get("eval_status") or {}
    render_page_shell(get_page_config("model_diagnosis"))
    render_review_caveat(eval_status)

    if not eval_status.get("live"):
        render_empty_state_with_actions(
            "当前暂无真实评测结果。请先发起一次评测，再查看模型能力诊断。",
            [("发起评测", "eval_run"), ("浏览任务样本", "tasks")],
        )
        return

    if data.model_outputs.empty:
        render_empty_state("暂无可展示的模型回答")
        return

    rows = build_model_comparison_rows(data.scores, data.errors, data.tasks)
    if not rows:
        render_empty_state("当前暂无可展示的评分数据。")
        return

    _render_boundary_line(data)
    _render_comparison_table(rows)
    _render_dimension_matrix(data.scores)
    _render_evidence_charts(data)


def _render_boundary_line(data) -> None:
    output_count = len(data.model_outputs)
    model_count = (
        data.model_outputs["model_name"].nunique() if "model_name" in data.model_outputs else 0
    )
    task_count = len(data.tasks)
    st.caption(
        f"评测边界：当前为 MVP 样本（{task_count} 道任务 · {model_count} 个模型 · "
        f"{output_count} 条模型回答），回答来自首页评测控制台的运行结果，结论仅用于当前评测集观察。"
    )


def _render_comparison_table(rows: list[dict]) -> None:
    render_section_title("模型对比", "平均分、维度强弱、高频错误与适用边界，均按当前评测集计算。")
    header = (
        "<th>模型</th><th>平均分</th><th>最强维度</th>"
        "<th>最弱维度</th><th>高频错误</th><th>适用边界</th>"
    )
    body = ""
    for row in rows:
        body += (
            f'<tr><td class="check-key">{escape(row["model"])}</td>'
            f'<td class="check-count">{row["avg_score"]:.1f}</td>'
            f'<td>{escape(row["strongest_dim"])}</td>'
            f'<td>{escape(row["weakest_dim"])}</td>'
            f'<td>{escape(row["top_error"])}</td>'
            f'<td>{escape(row["boundary"])}</td></tr>'
        )
    render_html(
        '<table class="check-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )


def _render_dimension_matrix(scores_df) -> None:
    render_section_title("维度得分矩阵", "行为模型、列为评分维度，颜色越浅玫瑰表示达成率越低。")
    matrix = build_dimension_matrix(scores_df)
    if not matrix["rows"]:
        render_empty_state("当前暂无分维度评分数据。")
        return

    header = "<th>模型</th>" + "".join(f"<th>{escape(dimension)}</th>" for dimension in matrix["dimensions"])
    body = ""
    for row in matrix["rows"]:
        cells = ""
        for cell in row["cells"]:
            if cell["score"] is None:
                cells += '<td><span class="status-badge status-neutral">—</span></td>'
            else:
                cells += (
                    f'<td><span class="status-badge status-{cell["level"]}">'
                    f'{cell["score"]:.0f}/{cell["full"]}</span></td>'
                )
        body += f'<tr><th>{escape(row["model"])}</th>{cells}</tr>'
    render_html(
        '<table class="matrix-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    st.caption("达成率 ≥85% 为浅绿，60–85% 为米色，<60% 为浅玫瑰。")


def _render_evidence_charts(data) -> None:
    render_section_title("分项证据", "用于核对对比表与矩阵中的结论。")
    tab_total, tab_errors, tab_domains = st.tabs(["综合得分", "错误类型", "领域表现"])

    with tab_total:
        themed_bar_chart(
            get_model_total_scores(data.scores), "model_name", "total_score", "模型", "平均总分"
        )

    with tab_errors:
        error_counts = get_model_error_type_counts(data.errors)
        if error_counts.empty:
            render_empty_state("当前暂无可展示的错误标签数据。")
        else:
            themed_bar_chart(
                error_counts, "error_type", "count", "错误类型", "出现次数", "model_name", "模型"
            )

    with tab_domains:
        _render_domain_chart(get_model_domain_scores(data.scores, data.tasks))


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


def collect_model_diagnosis_tables(data_bundle: dict) -> dict:
    data = data_bundle["data"]
    return {
        "total_scores": get_model_total_scores(data.scores),
        "dimension_scores": get_model_dimension_scores(data.scores),
        "error_counts": get_model_error_type_counts(data.errors),
        "domain_scores": get_model_domain_scores(data.scores, data.tasks),
        "summaries": get_model_capability_summaries(data.scores, data.errors, data.tasks),
    }
