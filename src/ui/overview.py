from __future__ import annotations

from html import escape

import streamlit as st

from src.metrics import get_dimension_gap_ranking
from src.gold_quality import evaluate_gold_quality
from src.model_boundary import (
    build_data_actions,
    build_frequent_risks,
    summarize_usage_tiers,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import DOMAIN_LABELS, TASK_TYPE_LABELS, display_label
from src.ui.components import (
    render_action_cards,
    render_compact_hero,
    render_context_grid,
    render_empty_state_with_actions,
    render_flow_strip,
    render_html,
    render_info_panel,
    render_numbered_section,
    render_pull_quote,
    render_redline_verdict,
    render_status_summary,
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
        "复测验证",
    ]


def render_overview_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    validation_result = data_bundle["validation_result"]
    eval_status = data_bundle.get("eval_status") or {}

    # Portfolio case-study compact hero
    hero_stats = [
        (str(len(data.tasks)), "尽调任务样本"),
        (str(_distinct_count(data.tasks, "domain")), "专业领域"),
        (str(_rubric_dimension_count(data.scores)), "Rubric 维度"),
    ]
    render_compact_hero(
        eyebrow="FinDueEval",
        title=get_page_config("overview").title,
        question=get_page_config("overview").question,
        stats=hero_stats,
    )

    render_redline_verdict(
        "高分不代表可直接使用，[[红线错误一票否决]]。"
    )

    # 样本内评分是否存在，决定边界与风险用真实结论还是空状态引导。
    summary = build_model_performance_summary(data.scores, data.errors)
    has_results = summary is not None

    _render_usage_boundary(data, has_results)
    _render_top_risk(data, summary, eval_status, has_results)
    _render_evaluation_loop()
    _render_entries()

    render_numbered_section(
        "04",
        "数据资产",
        "关键数字均由当前数据动态计算。",
    )
    render_context_grid(get_overview_summary_items(data))

    render_info_panel(
        "口径与边界",
        "题库与 Gold Answer 为 MVP 脱敏样本；裁判给出的是建议分，需人工复核确认后归档；"
        "可用边界与风险均为当前样本内观察，不构成模型采购或业务决策建议。",
    )
    if not validation_result.is_valid:
        _render_data_quality_status(validation_result)


# 三类使用边界在首页用的简短标题（页内详版见「模型边界报告」）。
_BOUNDARY_HOME_TITLE = {
    "direct": "可直接使用",
    "review": "必须人工复核",
    "not_direct": "不可直接使用",
}


def _render_usage_boundary(data, has_results: bool) -> None:
    render_numbered_section(
        "01",
        "模型可用边界",
        "按风险等级、能力下限与红线错误，把当前任务归入三类使用边界。",
    )
    if not has_results:
        render_empty_state_with_actions(
            "运行一次真实评测后，这里按当前样本生成三类使用边界。",
            [("发起可复现实验", "eval_run"), ("浏览样本库", "tasks")],
        )
        return

    summaries = summarize_usage_tiers(data)
    cards = []
    for summary in summaries:
        key = summary["key"]
        title = _BOUNDARY_HOME_TITLE.get(key, summary["title"])
        if summary["redline_hits"] > 0:
            meta = f"其中 {summary['redline_hits']} 道触发高严重度红线错误"
        elif summary["task_types"]:
            labels = [display_label(t, TASK_TYPE_LABELS) for t in summary["task_types"][:3]]
            meta = "任务类型：" + "、".join(labels)
        else:
            meta = "当前样本中暂无归入此类的任务"
        cards.append(
            f"""
            <div class="boundary-card boundary-card-{escape(key)}">
                <div class="boundary-card-title">{escape(title)}</div>
                <div><span class="boundary-card-count">{summary['count']}</span>
                <span class="boundary-card-unit">道任务</span></div>
                <div class="boundary-card-desc">{escape(summary['definition'])}</div>
                <div class="boundary-card-meta">{escape(meta)}</div>
            </div>
            """
        )
    render_html(f'<div class="boundary-cards">{"".join(cards)}</div>')
    st.caption("红线错误一票否决：触发高严重度红线错误的任务不计入「可直接使用」。")


def _render_top_risk(data, summary, eval_status: dict, has_results: bool) -> None:
    render_numbered_section("02", "本轮最大风险", "当前样本内最薄弱的能力维度、高频错误与建议补强方向。")
    if not has_results:
        render_info_panel(
            "运行评测后生成",
            "尚无评分与错误标签。发起一次真实评测后，这里给出最弱维度、高频错误与对应的数据补强方向。",
        )
        return

    risks = build_frequent_risks(data)
    actions = build_data_actions(data)

    weakest = f"{summary['weakest_dimension']}（达成率约 {summary['weakest_attainment']:.0%}）"
    if risks:
        top = risks[0]
        top_error = f"{top['error_type']} · {top['count']} 次 · 影响{top['dimension']}"
    else:
        top_error = "暂无错误标签"
    action = actions[0]["data_action"] if actions else "暂无关联补强动作"

    render_status_summary([
        ("最弱能力维度", weakest, "warning"),
        ("高频错误", top_error, "danger"),
        ("建议补强方向", action, "accent"),
    ])
    run_id = str(eval_status.get("run_id") or "—")
    st.caption(f"基于当前评测样本（run_id：{run_id}），样本量有限，仅用于样本内观察。")


def _render_evaluation_loop() -> None:
    render_numbered_section("03", "评测闭环", "从专业任务到复测验证，问题反向沉淀为数据补强。")
    render_flow_strip(get_evaluation_loop_steps())


def _render_entries() -> None:
    render_action_cards([
        ("发起可复现实验 →", "eval_run"),
        ("模型边界报告 →", "model_boundary"),
        ("能力诊断 →", "model_diagnosis"),
    ], key_prefix="overview")


def _render_data_quality_status(validation_result) -> None:
    render_numbered_section("05", "数据质量状态")
    if validation_result.is_valid:
        render_status_summary([("数据质量", "通过", "success")])
    else:
        render_status_summary([("数据质量", "需处理", "danger")])
    for message in validation_result.errors:
        st.error(message)
    for message in validation_result.warnings:
        st.warning(message)


# Backward-compatible aliases for tests that import removed functions.
def get_overview_asset_cards(data):
    """Deprecated: kept for backward compatibility with PR-09 tests."""
    task_count = len(data.tasks)
    gold_count = len(data.gold_answer_map)
    output_count = len(data.model_outputs)
    error_type_count = _distinct_count(data.errors, "error_type")
    error_rows = len(data.errors)
    optimization_count = len(data.optimizations)
    return [
        {"label": "任务样本", "value": str(task_count), "note": "尽调任务样本"},
        {"label": "模型回答", "value": str(output_count), "note": "模型回答记录"},
        {"label": "Gold Answer 覆盖", "value": f"{gold_count}/{task_count}", "note": "Gold Answer 覆盖"},
        {"label": "错误标签", "value": f"{error_type_count} 类 · {error_rows} 条", "note": "错误标签"},
        {"label": "Preference Pair", "value": "0", "note": "Preference Pair"},
        {"label": "优化动作", "value": str(optimization_count), "note": "数据补强优化动作"},
    ]


def get_overview_insight_cards(data) -> list[dict]:
    """Deprecated: kept for backward compatibility."""
    task_count = len(data.tasks)
    domain_count = _distinct_count(data.tasks, "domain")
    model_count = _distinct_count(data.model_outputs, "model_name")
    optimization_count = len(data.optimizations)
    return [
        {"label": "样本资产", "value": task_count, "note": f"覆盖 {domain_count} 个专业领域"},
        {"label": "评测机制", "value": model_count, "note": "参与评测的模型数量"},
        {"label": "数据优化价值", "value": optimization_count, "note": "已记录的数据补强动作"},
    ]


def get_dataset_metric_cards(data) -> list[dict]:
    """Deprecated: kept for backward compatibility."""
    return [
        {"label": "任务样本", "value": len(data.tasks)},
        {"label": "覆盖领域", "value": _distinct_count(data.tasks, "domain")},
        {"label": "模型回答", "value": len(data.model_outputs)},
        {"label": "错误标签", "value": len(data.errors)},
    ]


def get_domain_coverage_items(tasks_df) -> list[tuple[str, str]]:
    """Deprecated: kept for backward compatibility."""
    if "domain" not in getattr(tasks_df, "columns", []):
        return []
    counts = tasks_df["domain"].dropna().astype(str).value_counts()
    from src.ui.tasks import DOMAIN_LABELS, display_label
    return [(display_label(domain, DOMAIN_LABELS), f"{count} 道") for domain, count in counts.items()]


def build_gold_quality_summary(gold_answer_map: dict, tasks_df) -> dict:
    """Deprecated: kept for backward compatibility."""
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
