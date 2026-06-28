from __future__ import annotations

import streamlit as st

from src.metrics import get_dimension_gap_ranking
from src.ui.page_config import get_page_config
from src.ui.tasks import DOMAIN_LABELS, display_label
from src.ui.components import (
    render_context_grid,
    render_empty_state,
    render_info_panel,
    render_loop_rail,
    render_metric_card,
    render_page_shell,
    render_section_title,
    render_status_badge,
)


# Score columns that make up the Rubric, excluding the aggregate total_score.
_RUBRIC_TOTAL_COLUMN = "total_score"


def _distinct_count(df, column: str) -> int:
    if column in getattr(df, "columns", []):
        return int(df[column].dropna().nunique())
    return 0


def _rubric_dimension_count(scores_df) -> int:
    columns = getattr(scores_df, "columns", [])
    return sum(
        1
        for column in columns
        if column.endswith("_score") and column != _RUBRIC_TOTAL_COLUMN
    )


def get_overview_insight_cards(data) -> list[dict[str, str | int]]:
    """Three conclusion-first insight cards. Every number is read from data."""
    task_count = len(data.tasks)
    domain_count = _distinct_count(data.tasks, "domain")
    model_count = _distinct_count(data.model_outputs, "model_name")
    dimension_count = _rubric_dimension_count(data.scores)
    error_type_count = _distinct_count(data.errors, "error_type")
    optimization_count = len(data.optimizations)

    return [
        {
            "label": "样本资产",
            "value": task_count,
            "note": f"覆盖 {domain_count} 个专业领域的脱敏尽调任务。",
        },
        {
            "label": "评测机制",
            "value": model_count,
            "note": f"多模型回答对照 Gold Answer，按 {dimension_count} 维 Rubric 评分。",
        },
        {
            "label": "数据优化价值",
            "value": optimization_count,
            "note": f"由 {error_type_count} 类错误标签驱动的数据补强与验证。",
        },
    ]


def get_overview_asset_cards(data) -> list[dict[str, str | int]]:
    task_count = len(data.tasks)
    output_count = len(data.model_outputs)
    gold_count = len(data.gold_answer_map)
    error_count = len(data.errors)
    preference_count = len(data.preference_pairs)
    optimization_count = len(data.optimizations)

    return [
        {"label": "任务样本", "value": task_count, "note": "脱敏专业评测任务。"},
        {"label": "模型回答", "value": output_count, "note": "用于评分和错误分析的回答记录。"},
        {"label": "Gold Answer 覆盖", "value": f"{gold_count}/{task_count}", "note": "用于定义优秀回答边界。"},
        {"label": "错误标签", "value": error_count, "note": "用于定位扣分原因。"},
        {"label": "Preference Pair", "value": preference_count, "note": "用于记录回答偏好和改进方向。"},
        {"label": "优化动作", "value": optimization_count, "note": "用于承接数据补强任务。"},
    ]


def get_overview_summary_items(data) -> list[tuple[str, str]]:
    """Compact data-asset summary. Counts are derived from the loaded data."""
    task_count = len(data.tasks)
    domain_count = _distinct_count(data.tasks, "domain")
    task_type_count = _distinct_count(data.tasks, "task_type")
    model_count = _distinct_count(data.model_outputs, "model_name")
    output_count = len(data.model_outputs)
    gold_count = len(data.gold_answer_map)
    error_type_count = _distinct_count(data.errors, "error_type")
    error_rows = len(data.errors)
    optimization_count = len(data.optimizations)

    return [
        ("任务样本", f"{task_count} 道 · {domain_count} 个领域"),
        ("任务类型", f"{task_type_count} 类专业任务"),
        ("模型回答", f"{model_count} 个模型 · {output_count} 条回答"),
        ("Gold Answer", f"{gold_count}/{task_count} 覆盖"),
        ("错误标签", f"{error_type_count} 类 · {error_rows} 条标注"),
        ("数据补强", f"{optimization_count} 项优化动作"),
    ]


def get_dataset_metric_cards(data) -> list[dict[str, str | int]]:
    """Up-to-four headline numbers for the first screen. All values are read
    from the loaded data files; nothing is hardcoded."""
    return [
        {"label": "任务样本", "value": len(data.tasks), "note": "脱敏专业评测任务。"},
        {"label": "覆盖领域", "value": _distinct_count(data.tasks, "domain"), "note": "任务覆盖的专业领域数。"},
        {"label": "模型回答", "value": len(data.model_outputs), "note": "用于评分与错误分析的回答。"},
        {"label": "错误标签", "value": len(data.errors), "note": "可归因的扣分点标注。"},
    ]


def get_domain_coverage_items(tasks_df) -> list[tuple[str, str]]:
    """Per-domain task counts for the left coverage summary. Counts are live."""
    if "domain" not in getattr(tasks_df, "columns", []):
        return []
    counts = tasks_df["domain"].dropna().value_counts()
    return [(display_label(domain, DOMAIN_LABELS), f"{int(count)} 道") for domain, count in counts.items()]


def build_model_performance_summary(scores_df, errors_df) -> dict | None:
    """Average score, weakest dimension and most frequent error, all derived
    from the current scores and error labels. Returns None when no scores exist."""
    if scores_df is None or scores_df.empty or "total_score" not in getattr(scores_df, "columns", []):
        return None

    avg_score = float(scores_df["total_score"].mean())

    gap_ranking = get_dimension_gap_ranking(scores_df)
    if gap_ranking.empty:
        weakest_dimension, weakest_attainment = "暂无", 0.0
    else:
        weakest_dimension = str(gap_ranking.iloc[0]["dimension"])
        weakest_attainment = float(gap_ranking.iloc[0]["attainment"])

    top_error_type, top_error_count = "暂无", 0
    if errors_df is not None and not errors_df.empty and "error_type" in errors_df:
        counts = errors_df["error_type"].dropna().astype(str).value_counts()
        if not counts.empty:
            top_error_type = str(counts.index[0])
            top_error_count = int(counts.iloc[0])

    return {
        "avg_score": avg_score,
        "weakest_dimension": weakest_dimension,
        "weakest_attainment": weakest_attainment,
        "top_error_type": top_error_type,
        "top_error_count": top_error_count,
    }


def get_evaluation_loop_steps() -> list[str]:
    return [
        "专业任务",
        "Gold Answer",
        "模型回答",
        "Rubric 评分",
        "错误归因",
        "数据补强",
        "优化验证",
    ]


def render_data_quality_status(validation_result) -> None:
    render_section_title("数据质量状态")
    if validation_result.is_valid:
        render_status_badge("通过", "success")
    else:
        render_status_badge("需处理", "danger")

    for message in validation_result.errors:
        st.error(message)
    for message in validation_result.warnings:
        st.warning(message)


def _open_case_detail() -> None:
    st.session_state.current_page = "case_detail"


def render_overview_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    validation_result = data_bundle["validation_result"]
    render_page_shell(get_page_config("overview"))

    render_section_title("数据集核心指标", "关键数字均由当前数据文件动态计算。")
    metric_cards = get_dataset_metric_cards(data)
    metric_columns = st.columns(len(metric_cards))
    for column, card in zip(metric_columns, metric_cards):
        with column:
            render_metric_card(card["label"], card["value"], card["note"])

    render_info_panel(
        "评测边界",
        "本页基于 MVP 样本与脱敏任务，模型回答为模拟生成；下列结论仅用于当前样本内观察，"
        "不代表真实模型采购或业务决策。",
    )

    left, right = st.columns([1, 1], gap="large")
    with left:
        render_section_title("任务覆盖", "按专业领域统计的样本分布。")
        coverage_items = get_domain_coverage_items(data.tasks)
        if coverage_items:
            render_context_grid(coverage_items)
            task_type_count = _distinct_count(data.tasks, "task_type")
            st.caption(f"覆盖 {task_type_count} 类任务类型，详情见「数据集质量与扩展框架」。")
        else:
            render_empty_state("暂无任务样本。")

    with right:
        render_section_title("模型表现摘要", "基于当前样本动态计算，仅作样本内观察。")
        summary = build_model_performance_summary(data.scores, data.errors)
        if summary is None:
            render_empty_state("当前暂无可展示的评分数据。")
        else:
            top_error = (
                f"{summary['top_error_type']}（{summary['top_error_count']} 次）"
                if summary["top_error_count"] > 0
                else "暂无错误标签"
            )
            render_context_grid(
                [
                    ("平均总分", f"{summary['avg_score']:.1f} 分"),
                    (
                        "最弱维度",
                        f"{summary['weakest_dimension']}（达成率约 {summary['weakest_attainment']:.0%}）",
                    ),
                    ("高频错误", top_error),
                ]
            )

    st.button("进入样板题评测 →", on_click=_open_case_detail, key="overview_to_case_detail")

    render_data_quality_status(validation_result)

    with st.expander("关于本项目：评测定位与数据闭环", expanded=False):
        st.write(
            "FinDueEval 用结构化样例数据演示金融尽调场景下的模型评测与数据优化闭环："
            "专业任务 → Gold Answer → 模型回答 → Rubric 评分 → 错误归因 → 数据补强 → 优化验证。"
            "当前为 MVP 样本，重点说明数据如何组织、模型在哪里不稳定、后续应补什么数据。"
        )
        render_loop_rail(get_evaluation_loop_steps())
        summary_items = get_overview_summary_items(data)
        if summary_items:
            render_section_title("数据资产摘要", "各类资产的关键计数，详情见对应页面。")
            render_context_grid(summary_items)
