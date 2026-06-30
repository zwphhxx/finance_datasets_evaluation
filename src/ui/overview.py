from __future__ import annotations

import streamlit as st

from src.metrics import get_dimension_gap_ranking
from src.gold_quality import evaluate_gold_quality
from src.ui.page_config import get_page_config
from src.ui.tasks import DOMAIN_LABELS, display_label
from src.ui.components import (
    render_context_grid,
    render_info_panel,
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
    render_page_shell(get_page_config("overview"))

    _render_project_purpose()
    _render_preliminary_analysis(data, eval_status)
    _render_how_to_use()

    render_section_title("数据资产", "关键数字均由当前数据动态计算。")
    render_context_grid(get_overview_summary_items(data))

    render_info_panel(
        "边界与说明",
        "题库与 Gold Answer 为 MVP 脱敏样本；模型回答来自评测控制台的真实运行；"
        "裁判给出的是建议分，需人工复核确认后归档；所有结论均为样本内观察，"
        "不构成模型采购或业务决策建议。",
    )
    if not validation_result.is_valid:
        render_data_quality_status(validation_result)


def _render_project_purpose() -> None:
    render_section_title("这是什么", "一句话讲清项目目的。")
    st.markdown(
        "**FinDueEval** 面向投行、财务与法律尽职调查场景，评估大模型在专业尽调任务上的回答质量，"
        "并把评测中暴露的问题反向沉淀为数据补强。核心只回答一个问题：在尽调这种高风险、强合规的工作里，"
        "模型的回答**哪些能直接用、哪些必须人工复核、哪些不能用**。"
    )


def _render_preliminary_analysis(data, eval_status: dict) -> None:
    render_section_title(
        "初步模型分析（基于投行/财务/法律尽调资料）",
        "先讲基于历史资料的先验判断，再用样本内数据验证。",
    )
    st.markdown(
        "我先用投行、财务、法律的历史尽调资料做了一轮人工分析，把“一份好的尽调回答应该长什么样”"
        "拆成可评测的标准：\n\n"
        "- 优秀回答的 5 个要素 → **Rubric 五个评分维度**（事实依据、推理完整性、风险识别、专业表达、边界意识）；\n"
        "- 不可触碰的红线 → 每道题的 **Gold Answer**（结论 / 依据 / 边界 / 红线）；\n"
        "- 反复出现的失误 → **错误标签体系**（如风险遗漏、依据错误、合规误判）。\n\n"
        "基于这套先验，我的**初步判断**是：模型在“事实复述、专业表达”上通常较稳，真正的风险集中在"
        "“**风险识别**”与“**边界意识**”——该提示的风险没提示、不确定的地方不标注。"
        "下面的样本内数据用来验证或修正这个判断。"
    )

    summary = build_model_performance_summary(data.scores, data.errors)
    if summary is not None:
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
        run_id = str(eval_status.get("run_id") or "—")
        st.caption(
            f"以上为当前评测样本内观察（run_id：{run_id}），样本量有限，"
            "仅用于验证上述先验，不代表模型整体能力。"
        )
    else:
        render_info_panel(
            "还没有样本内数据",
            "上面的判断目前只是基于历史资料的先验。运行一次真实评测后，这里会显示当前样本的"
            "平均分、最弱维度与高频错误，下面三个分析页也会基于真实结果生成。",
        )

    st.markdown("**想看完整的初步模型分析结果，进入：**")
    cols = st.columns(3)
    entries = [
        ("模型能力诊断 →", "model_diagnosis"),
        ("模型边界报告 →", "model_boundary"),
        ("样板题深度评测 →", "case_detail"),
    ]
    for col, (label, page) in zip(cols, entries):
        with col:
            st.button(
                label,
                key=f"overview_analysis_{page}",
                on_click=_open_page,
                args=(page,),
                use_container_width=True,
            )
    st.caption("这三页基于真实评测结果生成；若尚未运行评测，进入后会引导你先发起一次评测。")


def _render_how_to_use() -> None:
    render_section_title("怎么用", "三步走完“评测 → 看结论 → 数据补强”闭环。")
    st.markdown(
        "1. **发起评测**：选 Provider / 模型 / 任务运行真实评测，裁判模型对照 Gold + Rubric 打建议分；\n"
        "2. **看结论**：在“模型能力诊断 / 模型边界报告 / 样板题深度评测”看分维度表现、可用边界与单题拆解；\n"
        "3. **数据补强**：把高频错误带到“数据集管理”，按错误标签补强样本并回到第 1 步验证。"
    )
    cols = st.columns(2)
    actions = [("发起评测 →", "eval_run"), ("浏览任务样本 →", "tasks")]
    for col, (label, page) in zip(cols, actions):
        with col:
            st.button(
                label,
                key=f"overview_howto_{page}",
                on_click=_open_page,
                args=(page,),
                use_container_width=True,
            )