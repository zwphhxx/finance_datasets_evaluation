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
    render_flow_strip,
    render_info_panel,
    render_numbered_section,
    render_page_shell,
    render_section_title,
    render_status_summary,
    render_text_block,
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

    render_page_shell(get_page_config("overview"))

    # 01 项目背景与目的
    render_section_title("项目背景与目的", "为什么做 FinDueEval")
    st.markdown(
        """
        FinDueEval 面向投行、财务与法律尽职调查场景，评估大模型在专业尽调任务上的回答质量，
        并把评测中暴露的问题反向沉淀为数据补强。核心只回答一个问题：
        **在尽调这种高风险、强合规的工作里，模型的回答哪些能直接用、哪些必须人工复核、哪些不能用。**
        """
    )

    # 02 初步模型分析
    render_section_title(
        "初步模型分析（基于投行/财务/法律尽调资料）",
        "先讲先验判断，再用样本内数据验证。",
    )
    st.markdown(
        """
        我先用投行、财务、法律的历史尽调资料做了一轮人工分析，把“一份好的尽调回答应该长什么样”
        拆成可评测的标准：优秀回答的 5 个要素 → Rubric 五个评分维度；不可触碰的红线 → 每道题的
        Gold Answer；反复出现的失误 → 错误标签体系。基于这套先验，真正的风险集中在
        **风险识别** 与 **边界意识** ——该提示的风险没提示、不确定的地方不标注。
        """
    )

    summary = build_model_performance_summary(data.scores, data.errors)
    if summary:
        st.markdown(
            f"样本内验证：平均总分 **{summary['avg_score']:.1f}** · 最弱维度 "
            f"**{summary['weakest_dimension']}（达成率约 {summary['weakest_attainment']:.0%}）** · "
            f"高频错误 **{summary['top_error_type']}（{summary['top_error_count']} 次）**"
        )
        run_id = str(eval_status.get("run_id") or "—")
        st.caption(f"当前评测样本内观察（run_id：{run_id}），样本量有限，不代表模型整体能力。")
    else:
        render_info_panel(
            "还没有样本内数据",
            "上面的判断目前只是基于历史资料的先验。运行一次真实评测后，这里会显示当前样本的"
            "平均分、最弱维度与高频错误。",
        )

    if st.button("发起测试 →", type="primary", key="overview_cta"):
        st.session_state.current_page = "test_run"
        st.rerun()

    # 03 怎么用
    render_section_title("怎么用", "三步走完“评测 → 看结论 → 数据补强”闭环。")
    render_flow_strip(get_evaluation_loop_steps())
    st.markdown(
        """
        1. 在“发起测试”页选择模型与任务，裁判对照 Gold + Rubric 打出建议分；
        2. 在“评测复核”与“评测结论”页看分维度表现、可用边界与单题拆解；
        3. 把高频错误带回样本管理做补强，形成“发现错误 → 补充数据 → 复测验证”的闭环。
        """
    )

    # 04 数据资产
    render_section_title("数据资产", "关键数字均由当前数据动态计算。")
    items = get_overview_summary_items(data)
    st.markdown(" · ".join(f"**{label}**：{value}" for label, value in items))

    # 05 边界与说明
    render_info_panel(
        "边界与说明",
        "题库与 Gold Answer 为 MVP 脱敏样本；模型回答来自评测控制台的真实运行；"
        "裁判给出的是建议分，需人工复核确认后归档；所有结论均为样本内观察，"
        "不构成模型采购或业务决策建议。",
    )
    if not validation_result.is_valid:
        _render_data_quality_status(validation_result)


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
