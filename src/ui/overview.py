from __future__ import annotations

import streamlit as st

from src.metrics import get_dimension_gap_ranking
from src.gold_quality import evaluate_gold_quality
from src.ui.page_config import get_page_config
from src.ui.tasks import DOMAIN_LABELS, display_label
from src.ui.components import (
    render_card,
    render_context_grid,
    render_empty_state,
    render_info_panel,
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


def build_gold_quality_summary(gold_answer_map: dict, tasks_df) -> dict:
    """Gold Answer 质量摘要：满足 / 部分满足评测使用条件的任务数，全部按数据推导。"""
    case_ids: list[str] = []
    if "case_id" in getattr(tasks_df, "columns", []):
        case_ids = [str(c) for c in tasks_df["case_id"].dropna().tolist()]

    usable = 0
    partial_cases: list[str] = []
    for case_id in case_ids:
        if evaluate_gold_quality(gold_answer_map.get(case_id, {}))["is_usable"]:
            usable += 1
        else:
            partial_cases.append(case_id)

    total = len(case_ids)
    return {
        "total": total,
        "usable": usable,
        "partial": total - usable,
        "partial_cases": partial_cases,
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


def _open_page(page_key: str) -> None:
    st.session_state.current_page = page_key


def render_overview_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    validation_result = data_bundle["validation_result"]
    eval_status = data_bundle.get("eval_status") or {}
    data_context = data_bundle.get("data_context") or {}
    render_page_shell(get_page_config("overview"))

    render_section_title("当前数据上下文", "当前结论基于以下数据源与运行状态。")
    _render_data_context(data_context)

    render_section_title("快速入口", "根据当前状态选择下一步操作。")
    _render_quick_entry_cards(eval_status)

    render_section_title("数据集核心指标", "关键数字均由当前数据文件动态计算。")
    metric_cards = get_dataset_metric_cards(data)
    metric_columns = st.columns(len(metric_cards))
    for column, card in zip(metric_columns, metric_cards):
        with column:
            render_metric_card(card["label"], card["value"], card["note"])

    if eval_status.get("live"):
        _render_recent_run_status(eval_status)

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

    render_section_title("Gold Answer 质量", "结构化结论、依据、边界与红线的完整度，按数据动态检查。")
    gold_summary = build_gold_quality_summary(data.gold_answer_map, data.tasks)
    if gold_summary["total"] == 0:
        render_empty_state("暂无 Gold Answer 记录。")
    else:
        status_level = "success" if gold_summary["partial"] == 0 else "warning"
        render_status_badge(
            f"{gold_summary['usable']}/{gold_summary['total']} 满足评测使用条件",
            status_level,
        )
        if gold_summary["partial"] > 0:
            st.caption(
                f"部分满足评测使用条件：{gold_summary['partial']} 道"
                f"（{'、'.join(gold_summary['partial_cases'])}），可在「数据集质量与扩展框架」查看缺失要素。"
            )

    render_data_quality_status(validation_result)


def _render_data_context(context: dict) -> None:
    items = [
        ("数据源", context.get("data_source", "未知")),
        ("可用任务", context.get("task_count", "—")),
        ("当前运行", context.get("run_id", "—")),
        ("评分状态", context.get("score_status", "—")),
    ]
    render_context_grid(items)


def _render_quick_entry_cards(eval_status: dict) -> None:
    live = bool(eval_status.get("live"))
    cols = st.columns(4)
    cards = [
        ("发起评测", "选择模型与任务并运行", "eval_run", True),
        ("浏览任务", "查看题库与 Gold 覆盖", "tasks", True),
        ("单题评测", "查看模型回答与评分矩阵", "case_detail", live),
        ("模型诊断", "多模型能力对比与边界", "model_diagnosis", live),
    ]
    for col, (title, desc, page, enabled) in zip(cols, cards):
        with col:
            render_card(
                f'<div style="font-weight:750;color:var(--fde-blue);margin-bottom:0.3rem;">{title}</div>'
                f'<div style="font-size:0.88rem;color:var(--fde-muted);">{desc}</div>'
            )
            st.button(
                "进入 →",
                key=f"overview_entry_{page}",
                on_click=_open_page,
                args=(page,),
                disabled=not enabled,
                use_container_width=True,
            )


def _render_recent_run_status(eval_status: dict) -> None:
    render_section_title("最近运行状态", "来自当前会话的真实评测运行。")
    run_id = str(eval_status.get("run_id") or "—")
    scored = int(eval_status.get("scored", 0) or 0)
    confirmed = int(eval_status.get("confirmed", 0) or 0)
    pending = int(eval_status.get("pending", 0) or 0)
    status_text = (
        f"run_id：{run_id} · 已评分 {scored} 条 · 已复核 {confirmed} 条 · 待复核 {pending} 条"
    )
    if pending > 0:
        render_info_panel("待复核", status_text)
    else:
        render_info_panel("运行完成", status_text)


def _open_case_detail() -> None:
    st.session_state.current_page = "case_detail"