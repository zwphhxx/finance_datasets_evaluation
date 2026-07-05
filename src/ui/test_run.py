"""发起测试页面。

Replaces eval_run_page.
- 选择可进入测试的样本与被测模型。
- 裁判模型使用系统默认配置，页面不提供裁判模型输入。
- 被测模型提示词不包含理想回复标准 / Gold Answer。
- 默认仅选择一道样本，降低面试演示时的等待时间。
"""

from __future__ import annotations

from datetime import datetime
from html import escape
import re

import pandas as pd
import streamlit as st

from app.models import siliconflow as sf
from app.models.registry import get_text_provider
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import eval_state
from app.services import model_display as md
from app.services import scorer as sc
from src.ui.components import (
    render_compact_hero,
    render_empty_state,
    render_evidence_panel,
    render_html,
    render_numbered_section,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import TASK_TYPE_LABELS, display_label, summarize_text

MAIN_PROMPT = "选择样本和模型，生成模型回答与评分草稿。"

RUN_BOUNDARY_NOTE = (
    "本页运行受密钥、网络、模型版本与限流影响，结果可能波动。新评分默认进入评分草稿，"
    "不会覆盖正式结论；只有人工复核确认后才会归档。"
)
PROMPT_ISOLATION_NOTE = (
    "被测模型只看到任务题、业务背景和输出要求，不看到 Gold Answer、必须覆盖点、不可接受错误或 Rubric；"
    "裁判评分链路才读取 Gold Answer 和 Rubric。评分结果是建议分，需人工复核后才进入正式结论。"
)
NO_TESTABLE_SAMPLE_MESSAGE = (
    "当前没有可测样本。可测样本需同时满足：正式题库存在任务题、"
    "Gold Answer 具备完整评判标准、Rubric 评分标准存在，且样本状态为已入库。"
)

TEST_RUN_STEPS = ["评测配置", "运行结果", "评分草稿"]
_STATUS_BADGE = {
    "success": ("成功", "success"),
    "mock": ("模拟回退", "neutral"),
    "failed": ("失败", "danger"),
}

_MODE_LABEL = {"mock": "模拟回退", "live": "真实调用", "unconfigured": "未配置"}
_REVIEW_STATUS_LABEL = {"pending": "待人工复核", "confirmed": "已复核"}
_SILICONFLOW_LABEL = "硅基流动"
_EVAL_TEMPERATURE = 0.1
_EVAL_MAX_TOKENS = 2048
_MODEL_OPTION_LIMIT = 30
_ANSWER_PREVIEW_LIMIT = 1500
_RUN_STATE_KEY = "test_run_run_state"
_PARTIAL_OUTCOMES_KEY = "test_run_partial_outcomes"
_LAST_RUN_STATUS_KEY = "test_run_last_run_status"
_SCORE_STATE_KEY = "test_run_score_state"
_PARTIAL_SCORE_OUTCOMES_KEY = "test_run_partial_score_outcomes"
_LAST_SCORE_STATUS_KEY = "test_run_last_score_status"
_JUDGE_TEMPERATURE = 0.0
_JUDGE_MAX_TOKENS = 2048


def get_test_run_steps() -> list[str]:
    """Return the visible execution steps for the test-run page."""
    return TEST_RUN_STEPS[:]


def get_advanced_setting_items() -> list[str]:
    """No advanced controls are exposed on the test-run page."""
    return []


def build_sample_options(
    task_records: list[dict],
    gold_map: dict,
    rubric_dimensions: list[dict] | None,
) -> list[dict]:
    """Build compact selectable samples using the shared formal readiness gate."""
    options: list[dict] = []
    for case_id in eligible_case_ids(task_records, gold_map, rubric_dimensions):
        row = next((item for item in task_records if str(item.get("case_id") or "").strip() == case_id), {})
        scenario = _dash(row.get("scenario"))
        task_type = display_label(row.get("task_type"), TASK_TYPE_LABELS)
        title_source = row.get("title") or row.get("expected_capability") or row.get("question")
        summary = summarize_text(title_source, 24)
        difficulty = _dash(row.get("difficulty"))
        label = f"{case_id} · {scenario} · {task_type} · {summary}"
        options.append({
            "case_id": case_id,
            "label": label,
            "scenario": scenario,
            "task_type": task_type,
            "title": summary,
            "difficulty": difficulty,
            "task": row,
        })
    return options


def filter_sample_selection_options(
    sample_options: list[dict],
    keyword: str = "",
    scenario: str = "全部",
    difficulty: str = "全部",
) -> list[dict]:
    """Filter testable sample options for the dialog table."""
    query = str(keyword or "").strip().lower()
    scenario_value = str(scenario or "全部")
    difficulty_value = str(difficulty or "全部")
    filtered: list[dict] = []
    for item in sample_options:
        task = item.get("task") or {}
        searchable = " ".join(
            str(value or "")
            for value in [
                item.get("case_id"),
                item.get("title"),
                item.get("scenario"),
                item.get("difficulty"),
                task.get("title"),
                task.get("question"),
                task.get("context"),
                task.get("expected_capability"),
            ]
        ).lower()
        if query and query not in searchable:
            continue
        if scenario_value != "全部" and str(item.get("scenario") or "") != scenario_value:
            continue
        if difficulty_value != "全部" and str(item.get("difficulty") or "") != difficulty_value:
            continue
        filtered.append(item)
    return filtered


def build_sample_selection_rows(sample_options: list[dict], selected_case_ids: list[str]) -> list[dict]:
    """Build compact rows for selecting testable samples in a data editor."""
    selected = set(selected_case_ids or [])
    rows: list[dict] = []
    for item in sample_options:
        case_id = str(item.get("case_id") or "").strip()
        rows.append({
            "选择": case_id in selected,
            "样本编号": case_id,
            "任务标题": item.get("title") or "待补充",
            "场景": item.get("scenario") or "待补充",
            "难度": item.get("difficulty") or "待补充",
            "测试状态": "可测试",
        })
    return rows


def build_run_plan_summary(model_ids: list[str], selected_tasks: list[dict]) -> dict[str, int | bool]:
    """Summarize the planned model-answer run before execution."""
    model_count = len(_dedupe(model_ids))
    sample_count = len(selected_tasks or [])
    return {
        "sample_count": sample_count,
        "model_count": model_count,
        "planned_responses": sample_count * model_count,
        "can_run": bool(sample_count and model_count),
    }


def build_run_queue_items(model_ids: list[str], selected_tasks: list[dict]) -> list[dict]:
    """Build the ordered model x sample queue used during execution."""
    items: list[dict] = []
    for model_id in _dedupe(model_ids):
        for task in selected_tasks or []:
            items.append({
                "model_id": model_id,
                "case_id": str(task.get("case_id") or ""),
                "task": task,
            })
    return items


def build_outcome_view_options(
    outcomes: list[er.RunOutcome],
    task_lookup: dict[str, dict] | None = None,
) -> list[dict[str, int | str]]:
    """Build selector options for reviewing one model answer at a time."""
    return [
        {
            "index": index,
            "label": _outcome_option_label(outcome, task_lookup),
        }
        for index, outcome in enumerate(outcomes or [])
    ]


def default_outcome_view_index(outcomes: list[er.RunOutcome]) -> int:
    """Prefer the first successful answer; otherwise show the first failure."""
    for index, outcome in enumerate(outcomes or []):
        if outcome.success:
            return index
    return 0


def normalize_answer_markdown(answer: str) -> str:
    """Downgrade model-authored Markdown headings so answers do not overpower the page."""
    lines: list[str] = []
    in_fence = False
    for line in str(answer or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence:
            lines.append(line)
            continue
        match = re.match(r"^(\s{0,3})(#{1,6})(\s+.+)$", line)
        if not match:
            lines.append(line)
            continue
        indent, hashes, text = match.groups()
        level = len(hashes)
        downgraded = {1: 4, 2: 4, 3: 5, 4: 5, 5: 6, 6: 6}[level]
        lines.append(f"{indent}{'#' * downgraded}{text}")
    return "\n".join(lines)


def build_remaining_queue_items(queue_items: list[dict], outcomes: list[er.RunOutcome]) -> list[dict]:
    """Return queue items that do not yet have an outcome."""
    completed = {(str(outcome.model_id), str(outcome.case_id)) for outcome in outcomes or []}
    return [
        item
        for item in queue_items or []
        if (str(item.get("model_id") or ""), str(item.get("case_id") or "")) not in completed
    ]


def build_model_selection_options(models, keyword: str, limit: int = _MODEL_OPTION_LIMIT) -> tuple[list[str], int]:
    """Filter provider models into a bounded selectbox option list."""
    query = str(keyword or "").strip().lower()
    matched: list[str] = []
    for model in models or []:
        model_id = str(getattr(model, "id", "") or "").strip()
        if not model_id:
            continue
        raw = getattr(model, "raw", {}) or {}
        metadata = getattr(model, "metadata", {}) or {}
        searchable_parts = [
            model_id,
            str(getattr(model, "owned_by", "") or ""),
            str(raw.get("name", "") or ""),
            str(raw.get("display_name", "") or ""),
            str(metadata.get("name", "") or ""),
            str(metadata.get("display_name", "") or ""),
        ]
        haystack = " ".join(searchable_parts).lower()
        if not query or query in haystack:
            matched.append(model_id)
    deduped = _dedupe(matched)
    return deduped[:limit], len(deduped)


def build_score_summary_rows(score_result, dimensions) -> list[dict[str, str]]:
    """Build the score comparison rows with dynamic Rubric dimensions."""
    rows: list[dict[str, str]] = []
    for outcome in sorted(score_result.outcomes, key=lambda o: (0 if o.ok else 1, -(o.total_score or 0))):
        row = {
            "模型": _model_short_name(outcome.eval_model),
            "模型ID": str(outcome.eval_model),
            "样本": str(outcome.case_id),
            "总分": _n(outcome.total_score),
            "裁判状态": _score_status_label(outcome),
            "错误码": _dash(outcome.error_code),
            "错误信息": _short(outcome.error_message),
        }
        for dim in dimensions:
            row[str(dim["name"])] = _n(outcome.scores.get(dim["field"]))
        rows.append(row)
    return rows


def build_score_queue_items(compare_result) -> list[er.RunOutcome]:
    """Return successful model answers that can enter judge scoring."""
    if compare_result is None:
        return []
    return [outcome for outcome in getattr(compare_result, "outcomes", []) if outcome.success]


def build_score_plan_summary(compare_result) -> dict[str, int | bool]:
    """Summarize which model answers will enter score draft generation."""
    outcomes = list(getattr(compare_result, "outcomes", []) or [])
    scoreable = sum(1 for outcome in outcomes if outcome.success)
    skipped = len(outcomes) - scoreable
    return {
        "total": len(outcomes),
        "scoreable": scoreable,
        "skipped": skipped,
        "can_score": scoreable > 0,
    }


def build_score_view_options(score_outcomes: list[sc.ScoreOutcome]) -> list[dict[str, int | str]]:
    """Build selector options for reviewing one score draft at a time."""
    return [
        {
            "index": index,
            "label": _score_option_label(outcome),
        }
        for index, outcome in enumerate(score_outcomes or [])
    ]


def default_score_view_index(score_outcomes: list[sc.ScoreOutcome]) -> int:
    """Prefer the first successful score; otherwise show the first judge failure."""
    for index, outcome in enumerate(score_outcomes or []):
        if outcome.ok:
            return index
    return 0


def render_test_run_page(data_bundle: dict) -> None:
    base = data_bundle["base"]

    config = get_page_config("test_run")
    render_compact_hero(
        eyebrow="评测执行",
        title=config.title,
        question=config.question,
    )
    st.caption(MAIN_PROMPT)

    tasks_df = base.tasks
    if tasks_df is None or tasks_df.empty:
        render_empty_state("当前数据集没有可用任务样本。")
        return
    task_records = tasks_df.to_dict("records")
    gold_map = getattr(base, "gold_answer_map", {}) or {}
    testable_dimensions = ds.get_testable_rubric_dimensions()

    sample_options = build_sample_options(task_records, gold_map, testable_dimensions)
    _ensure_default_selected_cases(sample_options)
    provider_name = _current_provider_name()
    selected_tasks = _selected_tasks_from_state(sample_options)
    model_ids = _selected_model_ids_from_state()
    run_plan = build_run_plan_summary(model_ids, selected_tasks)

    render_numbered_section("01", TEST_RUN_STEPS[0])
    _render_configuration_panel(sample_options, selected_tasks, model_ids, provider_name, run_plan)

    render_numbered_section("02", TEST_RUN_STEPS[1])
    _render_results(provider_name, _EVAL_TEMPERATURE, _EVAL_MAX_TOKENS, task_records)

    render_numbered_section("03", TEST_RUN_STEPS[2])
    _render_scoring(base, provider_name, task_records)
    _render_score_results(task_records)
    _render_pending_dialogs(sample_options)


def _default_provider_name() -> str:
    return sf.PROVIDER_NAME


def _current_provider_name() -> str:
    current = _default_provider_name()
    st.session_state["test_run_provider"] = current
    return current


def _ensure_default_selected_cases(sample_options: list[dict]) -> None:
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
    if "test_run_selected_cases" in st.session_state:
        st.session_state["test_run_selected_cases"] = current
        return
    if current:
        st.session_state["test_run_selected_cases"] = current
        return
    default_cases = [
        str(r.get("case_id"))
        for r in er.default_task_selection([item["task"] for item in sample_options])
        if str(r.get("case_id")) in option_ids
    ]
    st.session_state["test_run_selected_cases"] = default_cases[:1] if default_cases else option_ids[:1]


def _selected_tasks_from_state(sample_options: list[dict]) -> list[dict]:
    by_case = {item["case_id"]: item for item in sample_options}
    return [
        by_case[case_id]
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in by_case
    ]


def _selected_model_ids_from_state() -> list[str]:
    return _dedupe(list(st.session_state.get("test_run_selected_models", [])))


def _selected_sample_summary(selected_tasks: list[dict]) -> str:
    if not selected_tasks:
        return "未选择"
    labels = [f'{item["case_id"]} · {item["title"]}' for item in selected_tasks[:2]]
    suffix = f" 等 {len(selected_tasks)} 个" if len(selected_tasks) > 2 else f"（{len(selected_tasks)} 个）"
    return "；".join(labels) + suffix


def _selected_model_summary(model_ids: list[str]) -> str:
    if not model_ids:
        return "未选择"
    labels = [_model_short_name(model_id) for model_id in model_ids[:2]]
    suffix = f" 等 {len(model_ids)} 个" if len(model_ids) > 2 else f"（{len(model_ids)} 个）"
    return "；".join(labels) + suffix


def _current_run_mode(provider_name: str) -> str:
    return "live" if provider_name == sf.PROVIDER_NAME and sf.is_configured() else "unconfigured"


def _render_configuration_panel(
    sample_options: list[dict],
    selected_tasks: list[dict],
    model_ids: list[str],
    provider_name: str,
    run_plan: dict[str, int | bool],
) -> None:
    mode = _current_run_mode(provider_name)
    rows = [
        ("已选样本", _selected_sample_summary(selected_tasks)),
        ("已选模型", _selected_model_summary(model_ids)),
        ("当前模型服务", _SILICONFLOW_LABEL),
        ("预计模型回答", f"{run_plan['planned_responses']} 条"),
        ("当前运行模式", _mode_label(mode)),
    ]
    render_evidence_panel("评测配置", _kv_table_html(rows))
    if mode == "unconfigured":
        st.caption("当前未配置模型服务密钥，暂不能发起真实调用。模拟回退仅用于开发兜底，不作为页面可选服务。")
    st.caption("建议首次运行选择 1 个样本和 1 个模型，确认链路后再扩大范围。")

    col1, col2, col3 = st.columns([1, 1, 1.2])
    with col1:
        if st.button("选择样本", key="test_run_open_samples", type="secondary", use_container_width=True):
            _open_sample_dialog(sample_options)
    with col2:
        if st.button("选择模型", key="test_run_open_models", type="secondary", use_container_width=True):
            _open_model_dialog(provider_name)
    start_run = False
    with col3:
        start_run = _render_run_button(
            run_plan,
            service_ready=(mode == "live"),
        )
    if not run_plan["can_run"]:
        st.caption("请选择样本和模型后运行。")
    if start_run:
        queue_items = build_run_queue_items(model_ids, selected_tasks)
        _execute_run_queue(
            provider_name,
            queue_items,
            model_ids,
            _EVAL_TEMPERATURE,
            _EVAL_MAX_TOKENS,
        )


def _open_sample_dialog(sample_options: list[dict]) -> None:
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
    st.session_state["test_run_dialog"] = "samples"
    st.session_state["test_run_cases_dialog_selected"] = current or option_ids[:1]
    st.session_state.pop("test_run_sample_search", None)
    st.session_state.pop("test_run_sample_scenario", None)
    st.session_state.pop("test_run_sample_difficulty", None)


def _open_model_dialog(provider_name: str) -> None:
    st.session_state["test_run_dialog"] = "models"
    st.session_state["test_run_model_dialog_selected"] = _selected_model_ids_from_state()


def _render_pending_dialogs(sample_options: list[dict]) -> None:
    dialog = st.session_state.get("test_run_dialog")
    if dialog == "samples":
        _render_sample_selection_dialog(sample_options)
    elif dialog == "models":
        _render_model_selection_dialog()


def _clear_dialog_state() -> None:
    st.session_state.pop("test_run_dialog", None)


@st.dialog("选择样本", width="large")
def _render_sample_selection_dialog(sample_options: list[dict]) -> None:
    if not sample_options:
        st.warning(NO_TESTABLE_SAMPLE_MESSAGE)
        if st.button("关闭", key="test_run_sample_dialog_close", type="tertiary"):
            _clear_dialog_state()
            st.rerun()
        return

    by_case = {item["case_id"]: item for item in sample_options}
    all_case_ids = set(by_case)
    selected_cases = [
        case_id
        for case_id in st.session_state.get("test_run_cases_dialog_selected", [])
        if case_id in all_case_ids
    ]
    st.session_state["test_run_cases_dialog_selected"] = selected_cases

    scenes = ["全部"] + sorted({
        str(item.get("scenario") or "")
        for item in sample_options
        if str(item.get("scenario") or "").strip() and str(item.get("scenario") or "") != "—"
    })
    difficulties = ["全部"] + sorted({
        str(item.get("difficulty") or "")
        for item in sample_options
        if str(item.get("difficulty") or "").strip() and str(item.get("difficulty") or "") != "—"
    })

    filter_cols = st.columns([2.2, 1, 1])
    with filter_cols[0]:
        keyword = st.text_input(
            "关键词搜索",
            key="test_run_sample_search",
            placeholder="输入样本编号、标题或背景关键词",
        )
    with filter_cols[1]:
        scenario = st.selectbox("场景", scenes, key="test_run_sample_scenario")
    with filter_cols[2]:
        difficulty = st.selectbox("难度", difficulties, key="test_run_sample_difficulty")

    filtered_options = filter_sample_selection_options(sample_options, keyword, scenario, difficulty)
    if not filtered_options:
        st.caption("当前没有符合条件的可测样本。")
        edited_rows: list[dict] = []
    else:
        rows = build_sample_selection_rows(filtered_options, selected_cases)
        editor_key = "test_run_cases_editor_" + "_".join(str(item["case_id"]) for item in filtered_options)[:120]
        edited_df = st.data_editor(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            height=min(330, max(140, 44 + len(rows) * 36)),
            column_order=["选择", "样本编号", "任务标题", "场景", "难度", "测试状态"],
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", width="small"),
                "样本编号": st.column_config.TextColumn("样本编号", width="small"),
                "任务标题": st.column_config.TextColumn("任务标题", width="large"),
                "场景": st.column_config.TextColumn("场景", width="medium"),
                "难度": st.column_config.TextColumn("难度", width="small"),
                "测试状态": st.column_config.TextColumn("测试状态", width="small"),
            },
            disabled=["样本编号", "任务标题", "场景", "难度", "测试状态"],
            key=editor_key,
        )
        edited_rows = edited_df.to_dict("records") if hasattr(edited_df, "to_dict") else list(edited_df)

    visible_ids = {str(item.get("case_id") or "") for item in filtered_options}
    checked_visible = [
        str(row.get("样本编号") or "")
        for row in edited_rows
        if bool(row.get("选择")) and str(row.get("样本编号") or "") in by_case
    ]
    selected_cases = _dedupe([
        *[case_id for case_id in selected_cases if case_id not in visible_ids],
        *checked_visible,
    ])
    st.session_state["test_run_cases_dialog_selected"] = selected_cases
    st.caption(
        f"已选样本：{len(selected_cases)} 个。仅展示已入库且通过完整度校验的样本；"
        "被测模型不会看到 Gold Answer 或 Rubric。"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "确认选择",
            key="test_run_sample_dialog_confirm",
            type="primary",
            disabled=not selected_cases,
            use_container_width=True,
        ):
            st.session_state["test_run_selected_cases"] = selected_cases
            _clear_dialog_state()
            st.rerun()
    with col2:
        if st.button("取消", key="test_run_sample_dialog_cancel", type="tertiary", use_container_width=True):
            _clear_dialog_state()
            st.rerun()


@st.dialog("选择模型", width="large")
def _render_model_selection_dialog() -> None:
    provider = sf.SiliconFlowProvider()
    st.markdown(f"**模型服务：** {_SILICONFLOW_LABEL}")
    balance_text = _siliconflow_balance_text(provider)
    if balance_text:
        st.caption(f"账户余额：{balance_text}")
    if not sf.is_configured():
        st.warning("当前未配置模型服务密钥，暂不能发起真实调用。")

    result = provider.list_models()
    available_models = list(result.models) if result.ok else []
    model_options = [str(model.id) for model in available_models if str(model.id).strip()]
    st.markdown("**可用模型**")
    if model_options:
        search_keyword = st.text_input(
            "搜索模型",
            key="test_run_model_search",
            placeholder="输入模型名称、厂商或关键词",
        )
        visible_options, matched_count = build_model_selection_options(
            available_models, search_keyword, _MODEL_OPTION_LIMIT,
        )
        if matched_count > _MODEL_OPTION_LIMIT:
            st.caption("结果较多，请继续输入关键词缩小范围。")
        if visible_options:
            if st.session_state.get("test_run_model_select") not in visible_options:
                st.session_state["test_run_model_select"] = visible_options[0]
            st.selectbox("模型", visible_options, key="test_run_model_select")
        else:
            st.caption("没有符合当前关键词的模型。")
        if st.button(
            "添加到对比列表",
            key="test_run_add_model",
            type="secondary",
            disabled=not visible_options,
        ):
            selected = str(st.session_state.get("test_run_model_select") or "").strip()
            current = _dedupe(list(st.session_state.get("test_run_model_dialog_selected", [])))
            if selected and selected in visible_options and selected not in current:
                current.append(selected)
            st.session_state["test_run_model_dialog_selected"] = current
            st.rerun()
    else:
        st.caption("模型列表暂未获取，请检查模型服务配置。")

    chosen_models = _dedupe([
        model
        for model in st.session_state.get("test_run_model_dialog_selected", [])
        if model in model_options
    ])
    st.session_state["test_run_model_dialog_selected"] = chosen_models
    st.markdown("**已选模型**")
    if chosen_models:
        for index, model_id in enumerate(chosen_models):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"- {_model_short_name(model_id)}")
                if _model_short_name(model_id) != model_id:
                    st.caption(f"模型 ID：{model_id}")
            with col2:
                if st.button("移除", key=f"test_run_remove_model_{index}", type="tertiary", use_container_width=True):
                    st.session_state["test_run_model_dialog_selected"] = [
                        item for item in chosen_models if item != model_id
                    ]
                    st.rerun()
    else:
        st.caption("尚未选择模型。")
    st.caption(f"已选模型：{len(chosen_models)} 个")
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "确认选择",
            key="test_run_model_dialog_confirm",
            type="primary",
            disabled=not chosen_models,
            use_container_width=True,
        ):
            st.session_state["test_run_provider"] = sf.PROVIDER_NAME
            st.session_state["test_run_selected_models"] = chosen_models
            _clear_dialog_state()
            st.rerun()
    with col2:
        if st.button("取消", key="test_run_model_dialog_cancel", type="tertiary", use_container_width=True):
            _clear_dialog_state()
            st.rerun()


def _siliconflow_balance_text(provider: sf.SiliconFlowProvider) -> str | None:
    try:
        balance = provider.get_balance()
    except Exception:
        balance = None
    if balance is None:
        return None
    if isinstance(balance, (int, float)):
        return f"¥{balance:.2f}"
    text = str(balance).strip()
    return text or None


def eligible_case_ids(task_records: list[dict], gold_map: dict, rubric_dimensions: list[dict] | None) -> list[str]:
    """返回正式数据层中可进入测试的样本编号。"""
    eligible: list[str] = []
    for row in task_records:
        case_id = str(row.get("case_id") or "").strip()
        if not case_id:
            continue
        gold = gold_map.get(case_id) or {}
        if ds.assess_sample_readiness(row, gold, rubric_dimensions).is_testable:
            eligible.append(case_id)
    return eligible


def _run_state() -> dict:
    state = st.session_state.get(_RUN_STATE_KEY)
    return state if isinstance(state, dict) else {}


def _partial_outcomes() -> list[er.RunOutcome]:
    return list(st.session_state.get(_PARTIAL_OUTCOMES_KEY, []) or [])


def _set_run_state(
    *,
    status: str,
    run_id: str,
    provider: str,
    model_ids: list[str],
    mode: str,
    created_at: str,
    queue_items: list[dict],
    outcomes: list[er.RunOutcome],
    message: str = "",
) -> None:
    st.session_state[_RUN_STATE_KEY] = {
        "status": status,
        "run_id": run_id,
        "provider": provider,
        "model_ids": list(model_ids),
        "mode": mode,
        "created_at": created_at,
        "queue_items": list(queue_items),
        "message": message,
    }
    st.session_state[_PARTIAL_OUTCOMES_KEY] = list(outcomes)
    st.session_state[_LAST_RUN_STATUS_KEY] = status


def _clear_run_state() -> None:
    st.session_state.pop(_RUN_STATE_KEY, None)
    st.session_state.pop(_PARTIAL_OUTCOMES_KEY, None)
    st.session_state.pop(_LAST_RUN_STATUS_KEY, None)
    st.session_state.pop("test_run_persisted", None)


def _score_state() -> dict:
    state = st.session_state.get(_SCORE_STATE_KEY)
    return state if isinstance(state, dict) else {}


def _partial_score_outcomes() -> list[sc.ScoreOutcome]:
    return list(st.session_state.get(_PARTIAL_SCORE_OUTCOMES_KEY, []) or [])


def _set_score_state(
    *,
    status: str,
    score_run_id: str,
    run_id: str,
    judge_provider: str,
    judge_model: str,
    mode: str,
    created_at: str,
    queue_items: list[er.RunOutcome],
    outcomes: list[sc.ScoreOutcome],
    skipped_count: int,
    message: str = "",
) -> None:
    st.session_state[_SCORE_STATE_KEY] = {
        "status": status,
        "score_run_id": score_run_id,
        "run_id": run_id,
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "mode": mode,
        "created_at": created_at,
        "queue_items": list(queue_items),
        "skipped_count": int(skipped_count),
        "message": message,
    }
    st.session_state[_PARTIAL_SCORE_OUTCOMES_KEY] = list(outcomes)
    st.session_state[_LAST_SCORE_STATUS_KEY] = status


def _clear_score_state() -> None:
    st.session_state.pop(_SCORE_STATE_KEY, None)
    st.session_state.pop(_PARTIAL_SCORE_OUTCOMES_KEY, None)
    st.session_state.pop(_LAST_SCORE_STATUS_KEY, None)
    st.session_state.pop("test_run_score_persisted", None)


def _score_result_from_state(state: dict | None = None, outcomes: list[sc.ScoreOutcome] | None = None):
    state = state or _score_state()
    outcomes = _partial_score_outcomes() if outcomes is None else list(outcomes)
    if not state:
        return None
    return sc.ScoreResult(
        score_run_id=str(state.get("score_run_id") or sc.generate_score_run_id()),
        run_id=str(state.get("run_id") or ""),
        judge_provider=str(state.get("judge_provider") or ""),
        judge_model=str(state.get("judge_model") or sc.DEFAULT_JUDGE_MODEL),
        mode=str(state.get("mode") or "live"),
        created_at=str(state.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        outcomes=tuple(outcomes),
    )


def _compare_result_from_state(state: dict | None = None, outcomes: list[er.RunOutcome] | None = None):
    state = state or _run_state()
    outcomes = _partial_outcomes() if outcomes is None else list(outcomes)
    if not state:
        return None
    return er.CompareRunResult(
        run_id=str(state.get("run_id") or er.generate_run_id()),
        provider=str(state.get("provider") or ""),
        model_ids=tuple(_dedupe(list(state.get("model_ids") or []))),
        mode=str(state.get("mode") or "live"),
        created_at=str(state.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        outcomes=tuple(outcomes),
    )


def _finalize_run_result(status: str, state: dict, outcomes: list[er.RunOutcome], message: str = "") -> None:
    queue_items = list(state.get("queue_items") or [])
    _set_run_state(
        status=status,
        run_id=str(state.get("run_id") or er.generate_run_id()),
        provider=str(state.get("provider") or ""),
        model_ids=list(state.get("model_ids") or []),
        mode=str(state.get("mode") or "live"),
        created_at=str(state.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        queue_items=queue_items,
        outcomes=outcomes,
        message=message,
    )
    result = _compare_result_from_state(_run_state(), outcomes)
    if result is not None:
        persisted = er.persist_compare_result(result)
        eval_state.set_last_run(result)
        _clear_score_state()
        st.session_state["test_run_persisted"] = persisted


def _unexpected_failure_outcome(provider, item: dict) -> er.RunOutcome:
    task = item.get("task") or {}
    return er.RunOutcome(
        case_id=str(item.get("case_id") or task.get("case_id") or ""),
        task_type=str(task.get("task_type") or ""),
        provider=str(getattr(provider, "name", "")),
        model_id=str(item.get("model_id") or ""),
        run_status="failed",
        success=False,
        error_code="runtime_error",
        error_message="运行过程中出现未预期错误，已停止后续任务。",
    )


def _execute_run_queue(
    provider_name: str,
    queue_items: list[dict],
    model_ids: list[str],
    temperature,
    max_tokens,
    *,
    existing_outcomes: list[er.RunOutcome] | None = None,
    base_state: dict | None = None,
) -> None:
    provider = get_text_provider(prefer=provider_name)
    existing_outcomes = list(existing_outcomes or [])
    all_queue = list((base_state or {}).get("queue_items") or queue_items)
    run_id = str((base_state or {}).get("run_id") or er.generate_run_id())
    created_at = str((base_state or {}).get("created_at") or datetime.now().isoformat(timespec="seconds"))
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    state_provider = str(getattr(provider, "name", ""))
    model_list = list((base_state or {}).get("model_ids") or _dedupe(model_ids))
    outcomes = list(existing_outcomes)
    state = {
        "run_id": run_id,
        "provider": state_provider,
        "model_ids": model_list,
        "mode": mode,
        "created_at": created_at,
        "queue_items": all_queue,
    }
    _set_run_state(
        status="running",
        run_id=run_id,
        provider=state_provider,
        model_ids=model_list,
        mode=mode,
        created_at=created_at,
        queue_items=all_queue,
        outcomes=outcomes,
    )
    queue_slot = st.empty()
    _render_live_run_queue(queue_slot, all_queue, outcomes, queue_items[0] if queue_items else None, queue_items[1:], mode)

    interrupted = False
    message = ""
    for index, item in enumerate(queue_items):
        waiting = queue_items[index + 1:]
        _render_live_run_queue(queue_slot, all_queue, outcomes, item, waiting, mode)
        try:
            outcome = er.run_single(
                provider,
                item["model_id"],
                item["task"],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            outcome = _unexpected_failure_outcome(provider, item)
            interrupted = True
            message = "本次运行未完成。已保留已完成回答；未完成项可继续运行。"
        outcomes.append(outcome)
        _set_run_state(
            status="running",
            run_id=run_id,
            provider=state_provider,
            model_ids=model_list,
            mode=mode,
            created_at=created_at,
            queue_items=all_queue,
            outcomes=outcomes,
            message=message,
        )
        next_item = None if interrupted else (waiting[0] if waiting else None)
        next_waiting = [] if interrupted or not waiting else waiting[1:]
        _render_live_run_queue(queue_slot, all_queue, outcomes, next_item, next_waiting, mode)
        if interrupted:
            break

    status = "interrupted" if interrupted or build_remaining_queue_items(all_queue, outcomes) else "completed"
    _finalize_run_result(status, state, outcomes, message)
    st.rerun()


def _unexpected_score_failure_outcome(
    provider,
    judge_model: str,
    run_outcome: er.RunOutcome,
    dimensions,
) -> sc.ScoreOutcome:
    return sc.ScoreOutcome(
        case_id=run_outcome.case_id,
        task_type=run_outcome.task_type,
        eval_model=run_outcome.model_id,
        judge_provider=str(getattr(provider, "name", "")),
        judge_model=judge_model,
        judge_status="failed",
        scores={d["field"]: None for d in dimensions},
        total_score=None,
        error_code="runtime_error",
        error_message="评分过程中出现未预期错误，已停止后续评分。",
    )


def _finalize_score_result(status: str, state: dict, outcomes: list[sc.ScoreOutcome], message: str = "") -> None:
    queue_items = list(state.get("queue_items") or [])
    _set_score_state(
        status=status,
        score_run_id=str(state.get("score_run_id") or sc.generate_score_run_id()),
        run_id=str(state.get("run_id") or ""),
        judge_provider=str(state.get("judge_provider") or ""),
        judge_model=str(state.get("judge_model") or sc.DEFAULT_JUDGE_MODEL),
        mode=str(state.get("mode") or "live"),
        created_at=str(state.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        queue_items=queue_items,
        outcomes=outcomes,
        skipped_count=int(state.get("skipped_count") or 0),
        message=message,
    )
    score_result = _score_result_from_state(_score_state(), outcomes)
    if score_result is not None and score_result.outcomes:
        persisted = sc.persist_score_result(score_result)
        eval_state.set_last_score(score_result)
        st.session_state["test_run_score_dims"] = list(st.session_state.get("test_run_score_dims") or [])
        st.session_state["test_run_score_persisted"] = persisted


def _execute_score_queue(
    provider_name: str,
    compare_result,
    base,
    task_records: list[dict],
    dimensions: list[dict],
) -> None:
    st.session_state["test_run_score_dims"] = list(dimensions or [])
    queue_items = build_score_queue_items(compare_result)
    skipped_count = build_score_plan_summary(compare_result)["skipped"]
    if not queue_items:
        return

    provider = get_text_provider(prefer=provider_name)
    judge_model = sc.DEFAULT_JUDGE_MODEL
    score_run_id = sc.generate_score_run_id()
    created_at = datetime.now().isoformat(timespec="seconds")
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    judge_provider = str(getattr(provider, "name", ""))
    gold_map = getattr(base, "gold_answer_map", {}) or {}
    tasks_by_case = {str(row.get("case_id") or ""): row for row in task_records}
    outcomes: list[sc.ScoreOutcome] = []
    state = {
        "score_run_id": score_run_id,
        "run_id": str(getattr(compare_result, "run_id", "")),
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "mode": mode,
        "created_at": created_at,
        "queue_items": queue_items,
        "skipped_count": int(skipped_count),
    }
    _set_score_state(
        status="running",
        score_run_id=score_run_id,
        run_id=state["run_id"],
        judge_provider=judge_provider,
        judge_model=judge_model,
        mode=mode,
        created_at=created_at,
        queue_items=queue_items,
        outcomes=outcomes,
        skipped_count=int(skipped_count),
    )

    queue_slot = st.empty()
    _render_live_score_queue(queue_slot, queue_items, outcomes, queue_items[0], queue_items[1:], skipped_count, mode)

    interrupted = False
    message = ""
    for index, run_outcome in enumerate(queue_items):
        waiting = queue_items[index + 1:]
        _render_live_score_queue(queue_slot, queue_items, outcomes, run_outcome, waiting, skipped_count, mode)
        task = tasks_by_case.get(run_outcome.case_id) or {
            "case_id": run_outcome.case_id,
            "task_type": run_outcome.task_type,
        }
        gold = gold_map.get(run_outcome.case_id) or {}
        try:
            score_outcome = sc.score_single(
                provider,
                judge_model,
                task,
                run_outcome.answer_text,
                gold,
                dimensions,
                eval_model=run_outcome.model_id,
                temperature=_JUDGE_TEMPERATURE,
                max_tokens=_JUDGE_MAX_TOKENS,
            )
        except Exception:
            score_outcome = _unexpected_score_failure_outcome(provider, judge_model, run_outcome, dimensions)
            interrupted = True
            message = "本次评分未完成。已生成的评分草稿已保留，未完成项可重新评分。"
        outcomes.append(score_outcome)
        _set_score_state(
            status="running",
            score_run_id=score_run_id,
            run_id=state["run_id"],
            judge_provider=judge_provider,
            judge_model=judge_model,
            mode=mode,
            created_at=created_at,
            queue_items=queue_items,
            outcomes=outcomes,
            skipped_count=int(skipped_count),
            message=message,
        )
        next_item = None if interrupted else (waiting[0] if waiting else None)
        next_waiting = [] if interrupted or not waiting else waiting[1:]
        _render_live_score_queue(queue_slot, queue_items, outcomes, next_item, next_waiting, skipped_count, mode)
        if interrupted:
            break

    remaining = len(queue_items) - len(outcomes)
    status = "interrupted" if interrupted or remaining else "completed"
    _finalize_score_result(status, state, outcomes, message)
    st.rerun()


def _render_run_button(
    run_plan,
    *,
    service_ready: bool = True,
) -> bool:
    disabled = not run_plan["can_run"] or not service_ready
    clicked = st.button("运行模型回答", type="primary", disabled=disabled, key="test_run_run")

    if disabled:
        if service_ready:
            st.caption("请先选择至少一个模型与至少一道任务，再运行评测。")
        else:
            st.caption("当前未配置模型服务密钥，暂不能发起真实调用。")
    return bool(clicked and not disabled)


def _render_live_run_queue(
    slot,
    queue_items: list[dict],
    outcomes: list[er.RunOutcome],
    current: dict | None,
    waiting: list[dict],
    mode: str,
) -> None:
    total = len(queue_items)
    done = len(outcomes)
    with slot.container():
        st.markdown("**运行队列**")
        st.caption(
            f"样本 {len({item['case_id'] for item in queue_items})} 个 · "
            f"模型 {len({item['model_id'] for item in queue_items})} 个 · "
            f"预计回答 {total} 条 · 运行模式：{_mode_label(mode)}"
        )
        st.progress((done / total) if total else 0.0)
        if current:
            st.markdown(
                f"已完成 {done} / {total} · 正在生成："
                f"{_model_short_name(current['model_id'])} · 任务 {current['case_id']}"
            )
        else:
            st.markdown(f"已完成 {done} / {total} · 正在汇总结果")

        if outcomes:
            st.markdown("**已完成结果**")
            for index, outcome in enumerate(outcomes, start=1):
                _render_run_outcome_card(outcome, index, compact=True)
        if waiting:
            waiting_text = "；".join(
                f"{item['case_id']} · {_model_short_name(item['model_id'])}" for item in waiting[:5]
            )
            suffix = f" 等 {len(waiting)} 条" if len(waiting) > 5 else ""
            st.caption(f"等待中：{waiting_text}{suffix}")


def _render_live_score_queue(
    slot,
    queue_items: list[er.RunOutcome],
    outcomes: list[sc.ScoreOutcome],
    current: er.RunOutcome | None,
    waiting: list[er.RunOutcome],
    skipped_count: int,
    mode: str,
) -> None:
    total = len(queue_items)
    done = len(outcomes)
    with slot.container():
        st.markdown("**评分队列**")
        st.caption(
            f"待评分回答 {total} 条 · 已完成 {done} / {total} · "
            f"跳过失败回答 {skipped_count} 条 · 裁判模式：{_mode_label(mode)}"
        )
        st.progress((done / total) if total else 0.0)
        if current:
            st.markdown(
                f"正在评分：{current.case_id} · {_model_short_name(current.model_id)}"
            )
        else:
            st.markdown(f"已完成 {done} / {total} · 正在汇总评分草稿")

        if outcomes:
            st.markdown("**已生成评分**")
            for index, outcome in enumerate(outcomes, start=1):
                st.caption(_score_compact_line(outcome, index))
        if waiting:
            waiting_text = "；".join(
                f"{item.case_id} · {_model_short_name(item.model_id)}" for item in waiting[:5]
            )
            suffix = f" 等 {len(waiting)} 条" if len(waiting) > 5 else ""
            st.caption(f"等待中：{waiting_text}{suffix}")


def _render_results(provider_name: str, temperature, max_tokens, task_records: list[dict]) -> None:
    result = eval_state.get_last_run()
    state = _run_state()
    if result is None and state and _partial_outcomes():
        result = _compare_result_from_state(state, _partial_outcomes())
    if result is None:
        if state and state.get("status") in {"running", "interrupted", "failed"}:
            _render_unfinished_run_without_result(state, provider_name, temperature, max_tokens)
            return
        render_empty_state("尚未运行模型回答。配置模型与任务后点击「运行模型回答」。")
        return

    summary = er.summarize_outcomes(result.outcomes)
    failed = summary.total - summary.success
    run_status = _run_status_for_result(result)
    st.markdown(
        f"本次运行：样本 {len({o.case_id for o in result.outcomes})} 个 · "
        f"模型 {len(result.model_ids)} 个 · 成功 {summary.success} 条 · 失败 {failed} 条 · "
        f"运行模式：{_mode_label(result.mode)}"
    )
    if run_status in {"running", "interrupted", "failed"}:
        _render_partial_run_notice(result, provider_name, temperature, max_tokens)
    if summary.total and summary.success == 0:
        st.caption("本次运行没有成功回答，默认展示第一条失败原因。")
    elif failed:
        st.caption("失败项不会进入评分草稿。")
    if er.is_mock_result(result):
        st.caption("本次为模拟回退模式运行，回答为模拟生成。")

    _render_answer_viewer(result, task_records)

    if st.button("查看技术明细", key="test_run_technical_details", type="tertiary"):
        _render_technical_details_dialog(result)


def _render_unfinished_run_without_result(state: dict, provider_name: str, temperature, max_tokens) -> None:
    queue_items = list(state.get("queue_items") or [])
    st.markdown("**本次运行未完成**")
    st.caption(f"已完成 0 条 · 未完成 {len(queue_items)} 条 · 失败 0 条。未完成项可继续运行。")
    resume_clicked = False
    col1, col2 = st.columns([1, 1])
    with col1:
        resume_clicked = st.button(
            "继续未完成项",
            key="test_run_resume_empty",
            type="secondary",
            disabled=not queue_items,
            use_container_width=True,
        )
    with col2:
        if st.button("放弃本次运行", key="test_run_discard_empty", type="tertiary", use_container_width=True):
            _clear_run_state()
            eval_state.clear()
            st.rerun()
    if resume_clicked:
        _execute_run_queue(
            provider_name,
            queue_items,
            list(state.get("model_ids") or []),
            temperature,
            max_tokens,
            existing_outcomes=[],
            base_state=state,
        )


def _render_partial_run_notice(result, provider_name: str, temperature, max_tokens) -> None:
    state = _run_state()
    queue_items = list(state.get("queue_items") or [])
    outcomes = list(result.outcomes)
    remaining = build_remaining_queue_items(queue_items, outcomes)
    failed = sum(1 for outcome in outcomes if not outcome.success)
    status = _run_status_for_result(result)
    if status == "completed":
        return
    st.markdown("**本次运行未完成**")
    st.caption(
        f"已完成 {len(outcomes)} 条 · 未完成 {len(remaining)} 条 · 失败 {failed} 条。"
        "已完成回答已保留；未完成项可继续运行。"
    )
    if state.get("message"):
        st.caption(str(state.get("message")))
    resume_clicked = False
    col1, col2 = st.columns([1, 1])
    with col1:
        resume_clicked = st.button(
            "继续未完成项",
            key="test_run_resume",
            type="secondary",
            disabled=not remaining,
            use_container_width=True,
        )
    with col2:
        if st.button("放弃本次运行", key="test_run_discard_partial", type="tertiary", use_container_width=True):
            _clear_run_state()
            eval_state.clear()
            st.rerun()
    if resume_clicked:
        _execute_run_queue(
            provider_name,
            remaining,
            list(state.get("model_ids") or []),
            temperature,
            max_tokens,
            existing_outcomes=outcomes,
            base_state=state,
        )


def _render_run_outcome_card(
    outcome: er.RunOutcome,
    index: int,
    *,
    compact: bool = False,
) -> None:
    with st.container(border=True):
        status = "已完成" if outcome.success else "未获得有效回答"
        elapsed = "—" if outcome.latency_ms is None else f"{outcome.latency_ms} ms"
        st.markdown(f"**{index}. {_model_short_name(outcome.model_id)}**")
        st.caption(f"任务编号：{outcome.case_id} · 状态：{status} · 耗时：{elapsed}")
        if outcome.success:
            answer = outcome.answer_text or "—"
            preview = _answer_preview(answer)
            st.markdown(normalize_answer_markdown(preview))
            if len(answer) > _ANSWER_PREVIEW_LIMIT and not compact:
                if st.button(
                    "查看全文",
                    key=f"test_run_full_answer_{index}_{_safe_key(outcome.model_id)}_{_safe_key(outcome.case_id)}",
                    type="tertiary",
                ):
                    _render_full_answer_dialog(outcome)
        else:
            st.markdown(f"错误码：`{_dash(outcome.error_code)}`")
            st.markdown(f"错误信息：{_short(outcome.error_message, 180)}")
            guidance = _failure_guidance(outcome)
            if guidance:
                st.caption(guidance)


@st.dialog("模型回答全文", width="large")
def _render_full_answer_dialog(outcome: er.RunOutcome) -> None:
    st.caption(f"任务编号：{outcome.case_id} · 模型：{_model_short_name(outcome.model_id)}")
    st.markdown("#### 模型回答")
    st.markdown(normalize_answer_markdown(outcome.answer_text or "—"))


@st.dialog("技术明细", width="large")
def _render_technical_details_dialog(result) -> None:
    _render_results_table(result)


def _render_results_table(result) -> None:
    header = "".join(
        f"<th>{escape(name)}</th>"
        for name in [
            "模型", "任务编号", "状态", "HTTP状态", "错误码", "错误信息",
            "trace_id", "耗时(ms)", "回答长度",
        ]
    )
    body = ""
    for outcome in result.outcomes:
        label, level = _STATUS_BADGE.get(outcome.run_status, (outcome.run_status, "neutral"))
        body += (
            f'<tr><td class="check-key">{escape(outcome.model_id)}</td>'
            f"<td>{escape(outcome.case_id)}</td>"
            f'<td><span class="status-badge status-{level}">{escape(label)}</span></td>'
            f'<td class="check-count">{escape(_n(outcome.http_status))}</td>'
            f"<td>{escape(_dash(outcome.error_code))}</td>"
            f"<td>{escape(_short(outcome.error_message))}</td>"
            f"<td>{escape(_dash(outcome.trace_id))}</td>"
            f'<td class="check-count">{escape(_n(outcome.latency_ms))}</td>'
            f'<td class="check-count">{escape(str(outcome.answer_length))}</td></tr>'
        )
    table_html = (
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )
    render_evidence_panel("运行明细", table_html)


def _render_answer_viewer(result, task_records: list[dict]) -> None:
    outcomes = list(result.outcomes)
    if not outcomes:
        st.caption("暂无回答可查看。")
        return

    task_lookup = _task_lookup_for_result(result, task_records)
    options = build_outcome_view_options(outcomes, task_lookup)
    selected = st.selectbox(
        "查看回答",
        options=[int(item["index"]) for item in options],
        index=default_outcome_view_index(outcomes),
        format_func=lambda idx: str(options[idx]["label"]),
        key=f"test_run_view_outcome_{_safe_key(getattr(result, 'run_id', 'current'))}",
    )
    _render_selected_outcome_detail(outcomes[int(selected)], task_lookup)


def _render_selected_outcome_detail(outcome: er.RunOutcome, task_lookup: dict[str, dict]) -> None:
    status = _outcome_display_status(outcome)
    elapsed = _latency_label(outcome.latency_ms)
    sample_label = _outcome_sample_label(outcome, task_lookup)
    model_short = _model_short_name(outcome.model_id)
    with st.container(border=True):
        st.markdown("**当前回答**")
        summary_items = [
            ("样本", sample_label),
            ("模型", model_short),
            ("状态", status),
            ("耗时", elapsed),
        ]
        if outcome.success:
            summary_items.append(("回答长度", _answer_length_label(outcome)))
            _render_answer_summary(summary_items, outcome.model_id if outcome.model_id != model_short else "")
            answer = outcome.answer_text or "—"
            st.markdown("#### 模型回答")
            st.markdown(normalize_answer_markdown(_answer_preview(answer)))
            if len(answer) > _ANSWER_PREVIEW_LIMIT:
                if st.button(
                    "查看全文",
                    key=f"test_run_selected_full_answer_{_safe_key(outcome.model_id)}_{_safe_key(outcome.case_id)}",
                    type="tertiary",
                ):
                    _render_full_answer_dialog(outcome)
            return

        _render_answer_summary(summary_items, outcome.model_id if outcome.model_id != model_short else "")
        st.markdown("#### 未获得有效回答")
        st.markdown(f"错误码：`{_dash(outcome.error_code)}`")
        st.markdown(f"错误信息：{_short(outcome.error_message, 220)}")
        guidance = _failure_guidance(outcome)
        if guidance:
            st.caption(guidance)


def _render_answer_summary(items: list[tuple[str, str]], model_id: str = "") -> None:
    item_html = "".join(
        f'<div class="answer-viewer-item"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in items
    )
    model_html = (
        f'<div class="answer-viewer-muted">模型 ID：{escape(model_id)}</div>'
        if model_id
        else ""
    )
    render_html(
        f"""
        <div class="answer-viewer-summary">
            <div class="answer-viewer-grid">{item_html}</div>
            {model_html}
        </div>
        """
    )


def _render_scoring(base, provider_name: str, task_records: list[dict]) -> None:
    result = eval_state.get_last_run()
    if result is None:
        st.caption("请先运行模型回答，再生成评分草稿。")
        return

    run_status = _run_status_for_result(result)
    partial_run = run_status in {"running", "interrupted", "failed"}
    score_plan = build_score_plan_summary(result)
    if partial_run:
        st.caption("本次运行未完成；如生成评分草稿，将仅对已完成且成功的回答评分。")
    else:
        st.caption("评分草稿需人工复核后才进入正式结论；被测模型未看到 Gold Answer 或 Rubric。")
    st.caption(
        f"可评分回答：{score_plan['scoreable']} 条 · "
        f"跳过失败回答：{score_plan['skipped']} 条。失败回答不会进入评分草稿。"
    )
    no_success = not score_plan["can_score"]
    if no_success:
        st.warning("没有成功回答，无法生成评分草稿。")
        failed = next((outcome for outcome in result.outcomes if not outcome.success), None)
        if failed is not None:
            _render_selected_outcome_detail(failed, _task_lookup_for_result(result, task_records))
        return

    button_label = "仅对已完成回答生成评分草稿" if partial_run else "生成评分草稿"
    if st.button(
        button_label, type="primary", disabled=no_success, key="test_run_score_run"
    ):
        dimensions = ds.get_rubric_dimensions()
        st.session_state["test_run_score_dims"] = dimensions
        _execute_score_queue(provider_name, result, base, task_records, dimensions)


def _render_score_results(task_records: list[dict]) -> None:
    score_result = eval_state.get_last_score()
    state = _score_state()
    if score_result is None and state and _partial_score_outcomes():
        score_result = _score_result_from_state(state, _partial_score_outcomes())
    if score_result is None:
        if state and state.get("status") in {"running", "interrupted", "failed"}:
            _render_unfinished_score_notice(state)
        return
    dimensions = st.session_state.get("test_run_score_dims") or ds.get_rubric_dimensions()
    state_skipped = int((state or {}).get("skipped_count") or 0)
    mock_scores = sum(1 for outcome in score_result.outcomes if _is_mock_score_outcome(outcome))
    failed_scores = sum(
        1 for outcome in score_result.outcomes
        if not outcome.ok and not _is_mock_score_outcome(outcome)
    )
    pending = sum(1 for outcome in score_result.outcomes if outcome.ok and outcome.review_status == "pending")

    st.markdown(
        f"评分草稿已生成：成功评分 {score_result.scored_count}/{len(score_result.outcomes)} · "
        f"待人工复核 {pending} 条 · 跳过失败回答 {state_skipped} 条 · "
        f"模拟评分 {mock_scores} 条 · 评分失败 {failed_scores} 条 · "
        f"裁判模式：{_mode_label(score_result.mode)}"
    )
    st.caption("评分草稿需人工复核后才进入正式结论。")
    if state and state.get("status") in {"running", "interrupted", "failed"}:
        _render_partial_score_notice(score_result, state)
    if sc.is_mock_score(score_result):
        st.caption("本次为模拟回退模式：未产生真实评分，各维度留空。")

    _render_score_result_list(score_result, dimensions)
    _render_score_detail_viewer(score_result, dimensions)
    if st.button("查看评分对比表", key="test_run_score_compare_details", type="tertiary"):
        _render_score_compare_dialog(score_result, dimensions)

    if ds.database_ready():
        if st.button("进入评测复核", key="test_run_to_review", type="secondary"):
            st.session_state.current_page = "review"
            st.rerun()
    else:
        st.caption("SQLite 数据层未初始化，评分草稿仅在当前会话展示，暂不能进入复核页归档。")


def _render_unfinished_score_notice(state: dict) -> None:
    queue_items = list(state.get("queue_items") or [])
    skipped = int(state.get("skipped_count") or 0)
    st.markdown("**本次评分未完成**")
    st.caption(
        f"已评分 0 条 · 未评分 {len(queue_items)} 条 · 失败 0 条 · "
        f"跳过失败回答 {skipped} 条。页面刷新或连接中断可能导致未完成评分丢失。"
    )


def _render_partial_score_notice(score_result, state: dict) -> None:
    queue_items = list(state.get("queue_items") or [])
    remaining = max(0, len(queue_items) - len(score_result.outcomes))
    failed = sum(1 for outcome in score_result.outcomes if not outcome.ok)
    st.markdown("**本次评分未完成**")
    st.caption(
        f"已评分 {len(score_result.outcomes)} 条 · 未评分 {remaining} 条 · 失败 {failed} 条。"
        "已生成的评分草稿已保留，未完成项可重新评分。"
    )
    if state.get("message"):
        st.caption(str(state.get("message")))


def _render_score_result_list(score_result, dimensions) -> None:
    if not score_result.outcomes:
        st.caption("暂无评分草稿。")
        return
    headers = ["模型", "样本", "总分", "状态"]
    header_html = "".join(f"<th>{escape(item)}</th>" for item in headers)
    rows = ""
    for outcome in score_result.outcomes:
        rows += (
            f"<tr><td>{escape(_model_short_name(outcome.eval_model))}</td>"
            f"<td>{escape(outcome.case_id)}</td>"
            f'<td class="check-count">{escape(_score_total_label(outcome, dimensions))}</td>'
            f"<td>{escape(_score_status_label(outcome))}</td></tr>"
        )
    render_evidence_panel(
        "评分结果",
        f'<table class="check-table"><thead><tr>{header_html}</tr></thead><tbody>{rows}</tbody></table>',
    )


def _render_score_detail_viewer(score_result, dimensions) -> None:
    outcomes = list(score_result.outcomes)
    if not outcomes:
        return
    options = build_score_view_options(outcomes)
    selected = st.selectbox(
        "当前评分详情",
        options=[int(item["index"]) for item in options],
        index=default_score_view_index(outcomes),
        format_func=lambda idx: str(options[idx]["label"]),
        key=f"test_run_score_view_{_safe_key(getattr(score_result, 'score_run_id', 'current'))}",
    )
    _render_score_detail(outcomes[int(selected)], dimensions)


def _render_score_detail(outcome: sc.ScoreOutcome, dimensions) -> None:
    with st.container(border=True):
        st.markdown("**当前评分详情**")
        summary_items = [
            ("样本", outcome.case_id),
            ("模型", _model_short_name(outcome.eval_model)),
            ("总分", _score_total_label(outcome, dimensions)),
            ("裁判模型", _model_short_name(outcome.judge_model)),
            ("复核状态", _score_status_label(outcome)),
        ]
        _render_answer_summary(
            summary_items,
            outcome.eval_model if outcome.eval_model != _model_short_name(outcome.eval_model) else "",
        )
        if outcome.ok:
            st.markdown("#### 复核提示")
            st.caption(outcome.review_note or "未返回明确复核提示。")
            st.markdown("#### 维度评分")
            _render_score_dimensions_table(outcome, dimensions)
            return

        if _is_mock_score_outcome(outcome):
            st.markdown("#### 模拟评分")
            st.caption(outcome.review_note or "未配置模型服务密钥，未产生真实评分。")
            return

        st.markdown("#### 评分失败")
        st.markdown(f"错误码：`{_dash(outcome.error_code)}`")
        st.markdown(f"错误信息：{_short(outcome.error_message, 220)}")
        guidance = _score_failure_guidance(outcome)
        if guidance:
            st.caption(guidance)


def _render_score_dimensions_table(outcome: sc.ScoreOutcome, dimensions) -> None:
    header = "".join(f"<th>{escape(name)}</th>" for name in ["维度", "得分", "满分", "评分依据"])
    body = ""
    for dim in dimensions or []:
        field = str(dim.get("field") or "")
        name = str(dim.get("name") or field)
        full_mark = _n(dim.get("full_mark"))
        score = _n((outcome.scores or {}).get(field))
        rationale = str((outcome.rationale or {}).get(field) or "").strip() or "未返回明确依据"
        body += (
            f"<tr><td>{escape(name)}</td>"
            f'<td class="check-count">{escape(score)}</td>'
            f'<td class="check-count">{escape(full_mark)}</td>'
            f"<td>{escape(rationale)}</td></tr>"
        )
    render_evidence_panel(
        "维度评分",
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>',
    )


@st.dialog("评分对比表", width="large")
def _render_score_compare_dialog(score_result, dimensions) -> None:
    _render_score_compare_table(score_result, dimensions)


def _render_score_compare_table(score_result, dimensions) -> None:
    headers = ["模型", "样本"] + [str(d["name"]) for d in dimensions] + ["总分", "裁判状态", "错误码", "错误信息"]
    header = "".join(f"<th>{escape(name)}</th>" for name in headers)
    rows = build_score_summary_rows(score_result, dimensions)
    body = ""
    outcome_by_key = {
        (str(o.eval_model), str(o.case_id)): o
        for o in score_result.outcomes
    }
    for row in rows:
        outcome = outcome_by_key.get((row.get("模型ID", row["模型"]), row["样本"]))
        level = _score_status_level(outcome) if outcome is not None else "neutral"
        dim_cells = "".join(f'<td class="check-count">{escape(row[str(d["name"])])}</td>' for d in dimensions)
        body += (
            f'<tr><td class="check-key">{escape(row["模型"])}</td>'
            f"<td>{escape(row['样本'])}</td>"
            f"{dim_cells}"
            f'<td class="check-count">{escape(row["总分"])}</td>'
            f'<td><span class="status-badge status-{level}">{escape(row["裁判状态"])}</span></td>'
            f"<td>{escape(row['错误码'])}</td>"
            f"<td>{escape(row['错误信息'])}</td></tr>"
        )
    table_html = (
        f'<table class="check-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    render_evidence_panel("评分对比表", table_html)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = (item or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _mode_label(value) -> str:
    return _MODE_LABEL.get(str(value or "").strip().lower(), str(value or "未知"))


def _status_label(value) -> str:
    label, _ = _STATUS_BADGE.get(str(value or "").strip().lower(), (value or "未知", "neutral"))
    return str(label)


def _task_lookup_for_result(result, task_records: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in task_records or []:
        case_id = str(row.get("case_id") or "").strip()
        if case_id:
            lookup[case_id] = row
    state = _run_state()
    if state and str(state.get("run_id") or "") == str(getattr(result, "run_id", "")):
        for item in state.get("queue_items") or []:
            task = item.get("task") or {}
            case_id = str(item.get("case_id") or task.get("case_id") or "").strip()
            if case_id and task:
                lookup[case_id] = task
    return lookup


def _outcome_option_label(
    outcome: er.RunOutcome,
    task_lookup: dict[str, dict] | None = None,
) -> str:
    return (
        f"{outcome.case_id}｜"
        f"{_sample_title_summary(outcome, task_lookup)}｜"
        f"{_model_short_name(outcome.model_id)}｜"
        f"{_outcome_display_status(outcome)}"
    )


def _outcome_sample_label(outcome: er.RunOutcome, task_lookup: dict[str, dict] | None = None) -> str:
    return f"{outcome.case_id}｜{_sample_title_summary(outcome, task_lookup)}"


def _sample_title_summary(
    outcome: er.RunOutcome,
    task_lookup: dict[str, dict] | None = None,
    limit: int = 22,
) -> str:
    row = (task_lookup or {}).get(str(outcome.case_id), {}) or {}
    source = (
        row.get("title")
        or row.get("expected_capability")
        or row.get("question")
        or row.get("scenario")
        or outcome.task_type
        or "样本任务"
    )
    return summarize_text(source, limit)


def _model_short_name(model_id: str) -> str:
    return md.display_model_name(model_id)


def _outcome_display_status(outcome: er.RunOutcome) -> str:
    status = str(outcome.run_status or "").strip().lower()
    if outcome.success:
        return "已完成"
    if status == "running":
        return "生成中"
    if status == "waiting":
        return "等待中"
    if status == "interrupted":
        return "已中断"
    return "未获得有效回答"


def _latency_label(value) -> str:
    if value is None:
        return "—"
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return str(value)
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.1f}s"
    return f"{int(milliseconds)} ms"


def _answer_length_label(outcome: er.RunOutcome) -> str:
    length = outcome.answer_length or len(outcome.answer_text or "")
    return f"{length:,} 字"


def _review_status_label(value) -> str:
    return _REVIEW_STATUS_LABEL.get(str(value or "pending").strip().lower(), "待复核")


def _score_status_label(outcome) -> str:
    if getattr(outcome, "ok", False):
        return _review_status_label(getattr(outcome, "review_status", "pending"))
    return _status_label(getattr(outcome, "judge_status", ""))


def _score_option_label(outcome: sc.ScoreOutcome) -> str:
    return (
        f"{outcome.case_id}｜"
        f"{_model_short_name(outcome.eval_model)}｜"
        f"{_score_option_total_label(outcome)}｜"
        f"{_score_status_label(outcome)}"
    )


def _score_option_total_label(outcome: sc.ScoreOutcome) -> str:
    return "未评分" if outcome.total_score is None else f"{outcome.total_score}分"


def _score_total_label(outcome: sc.ScoreOutcome, dimensions=None) -> str:
    if outcome.total_score is None:
        return "未评分"
    full = _dimension_total_full_mark(dimensions)
    return f"{outcome.total_score} / {full}" if full else str(outcome.total_score)


def _score_compact_line(outcome: sc.ScoreOutcome, index: int) -> str:
    return (
        f"{index}. {outcome.case_id} · {_model_short_name(outcome.eval_model)} · "
        f"{_score_option_total_label(outcome)} · {_score_status_label(outcome)}"
    )


def _dimension_total_full_mark(dimensions) -> int:
    total = 0
    for dim in dimensions or []:
        try:
            total += int(dim.get("full_mark") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
    return total


def _score_status_level(outcome) -> str:
    if getattr(outcome, "ok", False):
        return "success" if str(getattr(outcome, "review_status", "")).lower() == "confirmed" else "warning"
    _, level = _STATUS_BADGE.get(str(getattr(outcome, "judge_status", "")).strip().lower(), ("未知", "neutral"))
    return level


def _is_mock_score_outcome(outcome) -> bool:
    return str(getattr(outcome, "judge_status", "")).strip().lower() == "mock"


def _run_status_for_result(result) -> str:
    state = _run_state()
    if state and str(state.get("run_id") or "") == str(getattr(result, "run_id", "")):
        return str(state.get("status") or "completed")
    return "completed"


def _answer_preview(answer: str) -> str:
    text = str(answer or "").strip() or "—"
    if len(text) <= _ANSWER_PREVIEW_LIMIT:
        return text
    return text[:_ANSWER_PREVIEW_LIMIT].rstrip() + "…"


def _failure_guidance(outcome) -> str:
    code = str(getattr(outcome, "error_code", "") or "").strip().lower()
    if code in {"missing_api_key", "unauthorized", "forbidden"}:
        return "请检查 SILICONFLOW_API_KEY、账户权限或模型访问权限。"
    if code in {"timeout", "gateway_timeout"}:
        return "模型服务响应超时，可稍后重试或更换模型。"
    if code == "rate_limited":
        return "请求触发限流，请稍后重试。"
    if code == "empty_response":
        return "模型返回成功但回答为空，建议重试或更换模型。"
    if code in {"bad_request", "not_found"}:
        return "请检查模型 ID 或请求参数。"
    if code == "runtime_error":
        return "已停止后续任务，已完成回答仍保留。"
    return ""


def _score_failure_guidance(outcome) -> str:
    code = str(getattr(outcome, "error_code", "") or "").strip().lower()
    if code in {"missing_api_key", "unauthorized", "forbidden"}:
        return "请检查模型服务密钥或账户权限。"
    if code in {"timeout", "gateway_timeout"}:
        return "模型服务响应超时，可稍后重试。"
    if code == "rate_limited":
        return "请求触发限流，请稍后重试。"
    if code == "judge_parse_error":
        return "裁判输出未能解析为评分 JSON，可重试或更换裁判模型。"
    if code == "empty_response":
        return "裁判模型返回为空，可重试。"
    if code == "runtime_error":
        return "已停止后续评分，已生成的评分草稿仍保留。"
    return ""


def _kv_table_html(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><td>{escape(str(key))}</td><td>{escape(str(value))}</td></tr>"
        for key, value in rows
    )
    return f'<table class="check-table"><tbody>{body}</tbody></table>'


def _n(value) -> str:
    return "—" if value is None else str(value)


def _dash(value) -> str:
    text = "" if value is None else str(value).strip()
    return text or "—"


def _short(value, limit: int = 40) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "—"
    return text if len(text) <= limit else text[:limit] + "…"


def _safe_key(value) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))
    return text[:80] or "item"
