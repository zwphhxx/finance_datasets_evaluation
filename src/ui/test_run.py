"""发起评测页面。

- 选择可进入测试的样本与被测模型。
- 裁判模型使用系统默认配置，页面不提供裁判模型输入。
- 被测模型提示词不包含专业标准答案。
- 运行评测后生成模型回答与 AI 评分。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st

from app.models import siliconflow as sf
from app.models.registry import get_text_provider
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import eval_state
from app.services import model_display as md
from app.services import scorer as sc
from src.ui import conclusions_data as cd
from src.ui.components import (
    render_empty_state,
    render_inline_status,
    render_markdown_detail_panel,
    render_numbered_section,
    render_page_heading,
)
from src.ui.labels import TASK_TYPE_LABELS, display_label, summarize_text
from src.ui.page_config import get_page_config

MAIN_PROMPT = "选择样本和模型，运行评测并生成 AI 评分。"

RUN_BOUNDARY_NOTE = (
    "本页运行受密钥、网络、模型版本与限流影响，结果可能波动。"
    "AI 评分成功后会写入运行期数据，并直接用于评测结论。"
)
PROMPT_ISOLATION_NOTE = (
    "被测模型只看到任务题、业务背景和输出要求，不看到专业标准答案、必须覆盖点、不可接受错误或评分标准；"
    "AI 评分链路才读取专业标准答案和评分标准。"
)
NO_TESTABLE_SAMPLE_MESSAGE = (
    "当前没有可测样本。可测样本需同时满足：正式题库存在任务题、"
    "专业标准答案具备完整评判标准，评分标准满分标准和扣分规则完整，且样本状态为已入库。"
)

TEST_RUN_STEPS = ["评测配置", "模型回答", "AI 评分"]
_STATUS_BADGE = {
    "success": ("成功", "success"),
    "mock": ("模拟回退", "neutral"),
    "failed": ("失败", "danger"),
}

_MODE_LABEL = {"mock": "模拟回退", "live": "真实调用", "unconfigured": "未配置"}
_REVIEW_STATUS_LABEL = {
    "ai_final": "已生成结论",
    "pending": "已生成结论",
    "confirmed": "已生成结论",
    "skipped": "不进入结论",
}
_SILICONFLOW_LABEL = "硅基流动"
SAMPLE_CHECKBOX_KEY_PREFIX = "test_run_case_checkbox_"
SAMPLE_TABLE_COLUMN_WIDTHS = [0.58, 1.0, 2.6, 1.15, 0.8, 0.95]
SAMPLE_TABLE_HEADERS = ["选择", "样本编号", "任务标题", "场景", "难度", "测试状态"]
SAMPLE_TABLE_HEIGHT = 330
_EVAL_TEMPERATURE_DEFAULT = 0.1
_EVAL_TEMPERATURE_ENV = "FINDUEVAL_EVAL_TEMPERATURE"
_EVAL_TEMPERATURE_KEY = "test_run_temperature"
_MODEL_DIALOG_TEMPERATURE_KEY = "test_run_model_dialog_temperature"
_MODEL_OPTION_LIMIT = 30
_ANSWER_PREVIEW_LIMIT = 1500
_SLOW_MODEL_KEYWORDS = ("longcat", "r1", "reasoning", "thinking")
_RUN_STATE_KEY = "test_run_run_state"
_ANSWER_RUN_ID_KEY = "test_run_answer_run_id"
_PARTIAL_OUTCOMES_KEY = "test_run_partial_outcomes"
_LAST_RUN_STATUS_KEY = "test_run_last_run_status"
_SCORE_STATE_KEY = "test_run_score_state"
_PARTIAL_SCORE_OUTCOMES_KEY = "test_run_partial_score_outcomes"
_LAST_SCORE_STATUS_KEY = "test_run_last_score_status"
_SCORE_RETRY_RUNNING_KEY = "test_run_score_retry_running"
_JUDGE_TEMPERATURE = 0.0
_JUDGE_MAX_TOKENS = 2048
_EVAL_MAX_TOKENS_DEFAULT = 4096
_EVAL_MAX_TOKENS_LIMIT = 8192
_EVAL_MAX_TOKENS_ENV = "FINDUEVAL_EVAL_MAX_TOKENS"


def _persistence_gate(result: bool) -> None:
    if not result:
        raise RuntimeError("runtime persistence required")


def _require_persistence_preflight(provider_name: str) -> None:
    from app.persistence import (
        ResultStoreSettings,
        get_result_store,
        require_durable_live_store,
    )

    store = get_result_store()
    settings = ResultStoreSettings(url="", is_postgresql=store.is_postgresql)
    require_durable_live_store(provider_name, settings)
    _persistence_gate(store.ping())


def _run_checkpoint_metadata(
    run_id: str,
    provider: str,
    model_ids: list[str],
    queue_items: list[dict],
    temperature,
    max_tokens,
) -> dict:
    from app.services.run_checkpoint import build_run_metadata

    versions = ds.list_dataset_versions()
    prompt_payload = [
        {
            "case_id": str(item.get("case_id") or ""),
            "messages": er.build_messages(item.get("task") or {}),
        }
        for item in queue_items
    ]
    return build_run_metadata(
        run_id=run_id,
        provider=provider,
        model_ids=model_ids,
        queue_items=queue_items,
        generation_parameters={"temperature": temperature, "max_tokens": max_tokens},
        judge_parameters={
            "temperature": _JUDGE_TEMPERATURE,
            "max_tokens": _JUDGE_MAX_TOKENS,
            "judge_model": sc.DEFAULT_JUDGE_MODEL,
        },
        dataset_version=versions[0] if versions else "",
        prompt_payload=prompt_payload,
    )


def _checkpoint_matches_current(
    saved: dict | None,
    current: dict,
) -> bool:
    if not saved:
        return False
    return all(
        str(saved.get(field) or "") == str(current.get(field) or "")
        for field in ("dataset_version", "dataset_hash", "prompt_hash")
    )


def resolve_eval_max_tokens(raw_value: str | None = None) -> int:
    """Resolve the hidden answer-generation token budget with a defensive cap."""
    raw = os.getenv(_EVAL_MAX_TOKENS_ENV, "") if raw_value is None else raw_value
    value = str(raw or "").strip()
    if not value:
        return _EVAL_MAX_TOKENS_DEFAULT
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _EVAL_MAX_TOKENS_DEFAULT
    if parsed <= 0:
        return _EVAL_MAX_TOKENS_DEFAULT
    return min(parsed, _EVAL_MAX_TOKENS_LIMIT)


def resolve_eval_temperature(raw_value: str | None = None) -> float:
    """Resolve the answer-generation temperature while keeping runs comparable."""
    raw = os.getenv(_EVAL_TEMPERATURE_ENV, "") if raw_value is None else raw_value
    value = str(raw or "").strip()
    if not value:
        return _EVAL_TEMPERATURE_DEFAULT
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return _EVAL_TEMPERATURE_DEFAULT
    if parsed < 0.0 or parsed > 1.0:
        return _EVAL_TEMPERATURE_DEFAULT
    return parsed


_EVAL_MAX_TOKENS = resolve_eval_max_tokens()
_EVAL_TEMPERATURE = resolve_eval_temperature()


def _normalize_eval_temperature(value) -> float:
    return resolve_eval_temperature(str(value if value is not None else ""))


def _current_eval_temperature() -> float:
    if _EVAL_TEMPERATURE_KEY not in st.session_state:
        return _EVAL_TEMPERATURE
    return _normalize_eval_temperature(st.session_state.get(_EVAL_TEMPERATURE_KEY))


def resolve_persisted_answer_run_id(
    run_summaries: list[dict],
    *,
    selected_run_id: str = "",
    current_run_id: str = "",
) -> str:
    """Resolve a stable persisted run selection without inventing a run ID."""
    available = [
        str(row.get("run_id") or "").strip()
        for row in run_summaries or []
        if str(row.get("run_id") or "").strip()
    ]
    selected = str(selected_run_id or "").strip()
    current = str(current_run_id or "").strip()
    if selected in available:
        return selected
    if current in available:
        return current
    return available[0] if available else ""


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
    """Build compact rows for selecting testable samples in the dialog table."""
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


def sample_checkbox_key(case_id: str) -> str:
    return f"{SAMPLE_CHECKBOX_KEY_PREFIX}{case_id}"


def merge_sample_checkbox_selection(
    selected_case_ids: list[str],
    filtered_options: list[dict],
    checkbox_values: dict[str, bool],
    all_case_ids: set[str],
) -> list[str]:
    """Merge visible checkbox state while preserving selected hidden samples."""
    current = [
        case_id
        for case_id in _dedupe([str(value) for value in (selected_case_ids or [])])
        if case_id in all_case_ids
    ]
    visible_ids = [str(item.get("case_id") or "") for item in (filtered_options or [])]
    visible_set = {case_id for case_id in visible_ids if case_id}
    if not visible_set:
        return current

    checked_visible = [
        case_id
        for case_id in visible_ids
        if case_id in visible_set and bool(checkbox_values.get(case_id))
    ]
    return _dedupe([
        *[case_id for case_id in current if case_id not in visible_set],
        *checked_visible,
    ])


def _clear_session_state_prefix(prefix: str) -> None:
    for key in [key for key in st.session_state if str(key).startswith(prefix)]:
        st.session_state.pop(key, None)


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


def batch_run_notice(run_plan: dict[str, int | bool]) -> str | None:
    """Batch execution is the default; no warning banner is shown for larger runs."""
    return None


def requires_large_run_confirmation(run_plan: dict[str, int | bool]) -> bool:
    return False


def slow_model_notice(model_ids: list[str]) -> str | None:
    """Soft warning for model names that commonly imply longer reasoning latency."""
    slow_models: list[str] = []
    for model_id in _dedupe(model_ids):
        lowered = str(model_id or "").lower()
        if any(keyword in lowered for keyword in _SLOW_MODEL_KEYWORDS):
            slow_models.append(_model_short_name(model_id))
    if not slow_models:
        return None
    return "部分模型响应时间可能较长，系统会保留已完成结果，可继续未完成项或重试失败项。"


def build_run_queue_items(model_ids: list[str], selected_tasks: list[dict]) -> list[dict]:
    """Build the ordered model x sample queue used during execution."""
    items: list[dict] = []
    unique_models = _dedupe(model_ids)
    for selected in selected_tasks or []:
        task = selected.get("task") if isinstance(selected.get("task"), dict) else selected
        for model_id in unique_models:
            items.append({
                "model_id": model_id,
                "case_id": str(selected.get("case_id") or task.get("case_id") or ""),
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
    """Convert model-authored Markdown headings into small text headings."""
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
        indent, _hashes, text = match.groups()
        lines.append(f"{indent}**{text.strip()}**")
    return "\n".join(lines)


def build_remaining_queue_items(queue_items: list[dict], outcomes: list[er.RunOutcome]) -> list[dict]:
    """Return queue items that do not yet have an outcome."""
    completed = {(str(outcome.model_id), str(outcome.case_id)) for outcome in outcomes or []}
    return [
        item
        for item in queue_items or []
        if (str(item.get("model_id") or ""), str(item.get("case_id") or "")) not in completed
    ]


def build_failed_run_queue_items(queue_items: list[dict], outcomes: list[er.RunOutcome]) -> list[dict]:
    """Return queue items whose latest model answer failed and can be retried."""
    failed = {
        (str(outcome.model_id), str(outcome.case_id))
        for outcome in outcomes or []
        if not outcome.success
    }
    return [
        item
        for item in queue_items or []
        if (str(item.get("model_id") or ""), str(item.get("case_id") or "")) in failed
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
    """Build the score comparison rows with dynamic scoring dimensions."""
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


def build_score_result_index_rows(score_result, dimensions) -> list[dict[str, str]]:
    """Build the compact score-result index table. Detail stays in the panel below."""
    return [
        {
            "模型": _model_short_name(outcome.eval_model),
            "样本": outcome.case_id,
            "总分": _score_total_label(outcome, dimensions),
            "状态": _score_status_label(outcome),
        }
        for outcome in getattr(score_result, "outcomes", []) or []
    ]


def build_score_draft_detail_panel(outcome: sc.ScoreOutcome, dimensions) -> dict[str, str]:
    """Build the lightweight detail-panel content for one AI score."""
    title = (
        f"{outcome.case_id}｜"
        f"{_model_short_name(outcome.eval_model)}｜"
        f"{_score_total_label(outcome, dimensions)}｜"
        f"{_score_status_label(outcome)}"
    )
    meta = (
        f"裁判模型：{_model_short_name(outcome.judge_model)}｜"
        f"模型 ID：{outcome.eval_model}"
    )
    if outcome.ok:
        markdown = _score_success_markdown(outcome, dimensions)
    elif _is_mock_score_outcome(outcome):
        markdown = _score_mock_markdown()
    else:
        markdown = _score_failure_markdown(outcome)
    return {"title": title, "meta": meta, "markdown": markdown}


def has_confirmable_score_drafts(score_result) -> bool:
    """Return whether a score result contains successful AI scores."""
    return any(
        getattr(outcome, "ok", False)
        for outcome in getattr(score_result, "outcomes", []) or []
    )


def build_score_queue_items(compare_result, existing_score_result=None) -> list[er.RunOutcome]:
    """Return successful model answers that can enter judge scoring."""
    if compare_result is None:
        return []
    scored_pairs = _successful_score_pairs(existing_score_result)
    return [
        outcome for outcome in getattr(compare_result, "outcomes", [])
        if outcome.success and (str(outcome.case_id), str(outcome.model_id)) not in scored_pairs
    ]


def build_failed_score_retry_items(score_result, compare_result) -> list[er.RunOutcome]:
    """Return successful model answers whose judge score failed and can be retried."""
    if score_result is None or compare_result is None:
        return []
    failed_pairs = {
        (str(outcome.case_id), str(outcome.eval_model))
        for outcome in getattr(score_result, "outcomes", []) or []
        if str(getattr(outcome, "judge_status", "") or "").strip().lower() == "failed"
    }
    retry_items: list[er.RunOutcome] = []
    seen: set[tuple[str, str]] = set()
    for outcome in getattr(compare_result, "outcomes", []) or []:
        key = (str(outcome.case_id), str(outcome.model_id))
        if key in failed_pairs and key not in seen and outcome.success:
            seen.add(key)
            retry_items.append(outcome)
    return retry_items


def build_score_plan_summary(compare_result, existing_score_result=None) -> dict[str, int | bool]:
    """Summarize which model answers will enter AI scoring."""
    outcomes = list(getattr(compare_result, "outcomes", []) or [])
    scored_pairs = _successful_score_pairs(existing_score_result)
    scoreable = sum(
        1 for outcome in outcomes
        if outcome.success and (str(outcome.case_id), str(outcome.model_id)) not in scored_pairs
    )
    skipped = sum(1 for outcome in outcomes if not outcome.success)
    return {
        "total": len(outcomes),
        "scoreable": scoreable,
        "skipped": skipped,
        "can_score": scoreable > 0,
    }


def _successful_score_pairs(score_result) -> set[tuple[str, str]]:
    return {
        (str(outcome.case_id), str(outcome.eval_model))
        for outcome in getattr(score_result, "outcomes", []) or []
        if getattr(outcome, "ok", False)
    }


def _filter_score_queue_for_existing(
    queue_items: list[er.RunOutcome],
    existing_outcomes: list[sc.ScoreOutcome],
) -> list[er.RunOutcome]:
    scored_pairs = {
        (str(outcome.case_id), str(outcome.eval_model))
        for outcome in existing_outcomes or []
        if getattr(outcome, "ok", False)
    }
    return [
        item for item in queue_items or []
        if (str(item.case_id), str(item.model_id)) not in scored_pairs
    ]


def build_score_view_options(score_outcomes: list[sc.ScoreOutcome]) -> list[dict[str, int | str]]:
    """Build selector options for viewing one AI score at a time."""
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


def prompt_preview_task_for_case(
    sample_options: list[dict],
    selected_case_ids: list[str],
    preview_case_id: str | None = None,
) -> dict:
    """Return the exact task object used for both prompt preview and run queue."""
    by_case = {str(item.get("case_id") or ""): item for item in sample_options or []}
    preview_ids = [
        str(case_id)
        for case_id in selected_case_ids or []
        if str(case_id) in by_case
    ] or list(by_case)
    current = str(preview_case_id or "")
    if current not in preview_ids:
        current = preview_ids[0] if preview_ids else ""
    return (by_case.get(current) or {}).get("task") or {}


def render_test_run_page(data_bundle: dict) -> None:
    base = data_bundle["base"]

    config = get_page_config("test_run")
    render_page_heading(config.title, config.question)

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
    _render_configuration_panel(sample_options, selected_tasks, model_ids, provider_name, run_plan, base, task_records)

    render_numbered_section("02", TEST_RUN_STEPS[1])
    _render_results(provider_name, _current_eval_temperature(), _EVAL_MAX_TOKENS, task_records)

    render_numbered_section("03", TEST_RUN_STEPS[2])
    _render_scoring(base, provider_name, task_records)
    _render_score_results(base, provider_name, task_records)
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
    ids = [str(item["case_id"]) for item in selected_tasks[:3]]
    suffix = f" 等 {len(selected_tasks)} 个" if len(selected_tasks) > 3 else ""
    return "、".join(ids) + suffix


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
    base,
    task_records: list[dict],
) -> None:
    mode = _current_run_mode(provider_name)
    eval_temperature = _current_eval_temperature()
    rows = [
        ("已选样本", _selected_sample_summary(selected_tasks)),
        ("已选模型", _selected_model_summary(model_ids)),
        ("预计模型回答", f"{run_plan['planned_responses']} 条"),
        ("回答随机性", f"{eval_temperature:.1f}"),
        ("当前运行模式", _mode_label(mode)),
    ]
    render_inline_status(rows)
    if mode == "unconfigured":
        st.caption("当前未配置模型服务密钥，暂不能发起真实调用。模拟回退仅用于开发兜底，不作为页面可选服务。")
    st.caption("当前任务在页面内执行。运行中不建议刷新或关闭页面；已完成结果会保留，未完成项可继续运行。")
    slow_notice = slow_model_notice(model_ids)
    if slow_notice:
        st.caption(slow_notice)

    start_run = False
    with st.container(key="test_run_actions"):
        with st.container(key="test_run_action_samples"):
            if st.button("选择样本", key="test_run_open_samples", type="secondary", use_container_width=True):
                _open_sample_dialog(sample_options)
        with st.container(key="test_run_action_models"):
            if st.button("选择模型", key="test_run_open_models", type="secondary", use_container_width=True):
                _open_model_dialog(provider_name)
        with st.container(key="test_run_action_primary"):
            start_run = _render_run_button(
                run_plan,
                service_ready=(mode == "live"),
            )
    if selected_tasks:
        if st.button(
            "查看本题发送给被测模型的提示词",
            key="test_run_open_prompt_preview",
            type="tertiary",
        ):
            _open_prompt_preview_dialog(selected_tasks)
    if start_run:
        queue_items = build_run_queue_items(model_ids, selected_tasks)
        _execute_run_queue(
            provider_name,
            queue_items,
            model_ids,
            eval_temperature,
            _EVAL_MAX_TOKENS,
            score_after_run=True,
            score_base=base,
            task_records=task_records,
        )


def _open_sample_dialog(sample_options: list[dict]) -> None:
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
    st.session_state["test_run_dialog"] = "samples"
    st.session_state["test_run_cases_dialog_selected"] = current
    st.session_state.pop("test_run_sample_search", None)
    st.session_state.pop("test_run_sample_scenario", None)
    st.session_state.pop("test_run_sample_difficulty", None)
    _clear_session_state_prefix(SAMPLE_CHECKBOX_KEY_PREFIX)


def _open_model_dialog(provider_name: str) -> None:
    st.session_state["test_run_dialog"] = "models"
    st.session_state["test_run_model_dialog_selected"] = _selected_model_ids_from_state()
    st.session_state[_MODEL_DIALOG_TEMPERATURE_KEY] = _current_eval_temperature()


def _open_prompt_preview_dialog(selected_tasks: list[dict]) -> None:
    first = next((item for item in selected_tasks or [] if str(item.get("case_id") or "").strip()), None)
    if first:
        st.session_state["test_run_prompt_preview_case"] = str(first.get("case_id") or "")
    st.session_state["test_run_dialog"] = "prompt_preview"


def _render_pending_dialogs(sample_options: list[dict]) -> None:
    dialog = st.session_state.get("test_run_dialog")
    if dialog == "samples":
        _render_sample_selection_dialog(sample_options)
    elif dialog == "models":
        _render_model_selection_dialog()
    elif dialog == "prompt_preview":
        _render_prompt_preview_dialog(sample_options)


def _clear_dialog_state() -> None:
    st.session_state.pop("test_run_dialog", None)
    st.session_state.pop("test_run_cases_dialog_selected", None)
    st.session_state.pop(_MODEL_DIALOG_TEMPERATURE_KEY, None)
    st.session_state.pop("test_run_prompt_preview_case", None)
    _clear_session_state_prefix(SAMPLE_CHECKBOX_KEY_PREFIX)


@st.dialog("发送给被测模型的提示词", width="large")
def _render_prompt_preview_dialog(sample_options: list[dict]) -> None:
    by_case = {str(item.get("case_id") or ""): item for item in sample_options}
    selected_ids = [
        str(case_id)
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if str(case_id) in by_case
    ]
    preview_ids = selected_ids or list(by_case)
    if not preview_ids:
        st.caption("当前没有可预览的样本。")
        if st.button("关闭", key="test_run_prompt_preview_close_empty", type="tertiary"):
            _clear_dialog_state()
            st.rerun()
        return

    current = str(st.session_state.get("test_run_prompt_preview_case") or "")
    if current not in preview_ids:
        current = preview_ids[0]
    if len(preview_ids) > 1:
        current = st.selectbox(
            "预览样本",
            options=preview_ids,
            index=preview_ids.index(current),
            format_func=lambda case_id: _prompt_preview_case_label(by_case.get(case_id, {})),
            key="test_run_prompt_preview_case_select",
        )
    st.session_state["test_run_prompt_preview_case"] = current

    task = prompt_preview_task_for_case(sample_options, selected_ids, current)
    messages = er.build_messages(task)
    st.caption("仅展示被测模型可见字段，不包含专业标准答案、必须覆盖点、不可接受错误或评分标准。")
    st.caption("请以本弹窗内容为准判断被测模型实际收到的信息。")
    for message in messages:
        role = str(message.get("role") or "")
        label = "系统提示词" if role == "system" else "用户提示词"
        height = 210 if role == "system" else 340
        st.text_area(
            label,
            value=str(message.get("content") or ""),
            height=height,
            disabled=True,
            key=f"test_run_prompt_preview_{role}",
        )
    if st.button("关闭", key="test_run_prompt_preview_close", type="tertiary"):
        _clear_dialog_state()
        st.rerun()


def _prompt_preview_case_label(item: dict) -> str:
    case_id = str(item.get("case_id") or "")
    title = str(item.get("title") or "样本任务")
    return f"{case_id}｜{title}"


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
    checkbox_values: dict[str, bool] = {}
    if not filtered_options:
        st.caption("当前没有符合条件的可测样本。")
    else:
        checkbox_values = _render_sample_checkbox_table(filtered_options, selected_cases)

    selected_cases = merge_sample_checkbox_selection(
        selected_cases,
        filtered_options,
        checkbox_values,
        all_case_ids,
    )
    st.session_state["test_run_cases_dialog_selected"] = selected_cases
    st.caption(
        f"已选样本：{len(selected_cases)} 个。仅展示已入库且通过完整度校验的样本；"
        "被测模型不会看到专业标准答案或评分标准。"
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


def _render_sample_checkbox_table(sample_options: list[dict], selected_cases: list[str]) -> dict[str, bool]:
    rows = build_sample_selection_rows(sample_options, selected_cases)
    selected_set = set(selected_cases or [])
    checkbox_values: dict[str, bool] = {}

    with st.container(
        height=SAMPLE_TABLE_HEIGHT,
        border=True,
        key="test_run_sample_table",
    ):
        header_cols = st.columns(SAMPLE_TABLE_COLUMN_WIDTHS, gap="small")
        for col, header in zip(header_cols, SAMPLE_TABLE_HEADERS, strict=True):
            with col:
                st.markdown(f"**{header}**")
        st.markdown(
            "<div style='border-top: 1px solid #E5E7EB; margin: 0.12rem 0 0.2rem 0;'></div>",
            unsafe_allow_html=True,
        )

        for index, row in enumerate(rows):
            case_id = str(row["样本编号"])
            key = sample_checkbox_key(case_id)
            if key not in st.session_state:
                st.session_state[key] = case_id in selected_set

            cols = st.columns(SAMPLE_TABLE_COLUMN_WIDTHS, gap="small")
            with cols[0]:
                checkbox_values[case_id] = bool(st.checkbox(
                    "选择",
                    key=key,
                    label_visibility="collapsed",
                ))
            with cols[1]:
                _render_sample_table_cell(case_id)
            with cols[2]:
                _render_sample_table_cell(str(row["任务标题"]))
            with cols[3]:
                _render_sample_table_cell(str(row["场景"]))
            with cols[4]:
                _render_sample_table_cell(str(row["难度"]))
            with cols[5]:
                _render_sample_table_cell(str(row["测试状态"]))
            if index < len(rows) - 1:
                st.markdown(
                    "<div style='border-top: 1px solid #F0F2F5; margin: 0.06rem 0 0.1rem 0;'></div>",
                    unsafe_allow_html=True,
                )

    return checkbox_values


def _render_sample_table_cell(value: str) -> None:
    st.markdown(
        "<div style='font-size: 0.9rem; line-height: 1.35; padding: 0.24rem 0; "
        f"color: #2F3947; overflow-wrap: anywhere;'>{escape(value)}</div>",
        unsafe_allow_html=True,
    )


@st.dialog("选择模型", width="large")
def _render_model_selection_dialog() -> None:
    provider = sf.SiliconFlowProvider()
    st.markdown(f"**模型服务：** {_SILICONFLOW_LABEL}")
    balance_text = _siliconflow_balance_text(provider)
    if balance_text:
        st.caption(f"账户余额：{balance_text}")
    if not sf.is_configured():
        st.warning("当前未配置模型服务密钥，暂不能发起真实调用。")
    if _MODEL_DIALOG_TEMPERATURE_KEY not in st.session_state:
        st.session_state[_MODEL_DIALOG_TEMPERATURE_KEY] = _current_eval_temperature()
    st.markdown("**回答设置**")
    st.slider(
        "回答随机性",
        min_value=0.0,
        max_value=1.0,
        step=0.1,
        key=_MODEL_DIALOG_TEMPERATURE_KEY,
        help="同一批评测内所有被测模型使用相同设置；裁判评分固定为 0.0。",
    )
    st.caption("同一批评测内所有被测模型使用相同回答随机性，便于横向比较。")

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
            st.session_state[_EVAL_TEMPERATURE_KEY] = _normalize_eval_temperature(
                st.session_state.get(_MODEL_DIALOG_TEMPERATURE_KEY)
            )
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
    resume_allowed: bool = True,
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
        "resume_allowed": bool(resume_allowed),
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
    st.session_state.pop(_SCORE_RETRY_RUNNING_KEY, None)


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


def _persisted_run_option_label(summary: dict) -> str:
    created_at = str(summary.get("created_at") or "")[:19].replace("T", " ")
    return (
        f"{created_at or '时间未记录'}｜"
        f"{int(summary.get('model_count') or 0)} 个模型｜"
        f"{int(summary.get('case_count') or 0)} 个样本｜"
        f"{int(summary.get('response_count') or 0)} 条回答"
    )


def _render_persisted_answer_run_selector(result) -> str:
    summaries = er.list_persisted_answer_runs()
    if not summaries:
        return ""
    current_run_id = str(
        getattr(result, "run_id", "")
        or _run_state().get("run_id")
        or ""
    )
    available_ids = {
        str(row.get("run_id") or "")
        for row in summaries
    }
    if current_run_id and current_run_id not in available_ids:
        return current_run_id
    selected_run_id = resolve_persisted_answer_run_id(
        summaries,
        selected_run_id=str(st.session_state.get(_ANSWER_RUN_ID_KEY) or ""),
        current_run_id=current_run_id,
    )
    if st.session_state.get(_ANSWER_RUN_ID_KEY) not in available_ids:
        st.session_state[_ANSWER_RUN_ID_KEY] = selected_run_id
    by_id = {str(row["run_id"]): row for row in summaries}
    return st.selectbox(
        "查看持久化批次",
        options=list(by_id),
        format_func=lambda run_id: _persisted_run_option_label(by_id[run_id]),
        key=_ANSWER_RUN_ID_KEY,
    )


def _recover_persisted_run(run_id: str, task_records: list[dict]) -> object | None:
    rows = er.load_run_queue(run_id)
    result = er.restore_compare_result_from_db(run_id)
    if result is None:
        return None
    queue_items = _run_queue_items_from_rows(rows, task_records)
    model_ids = _dedupe(
        [str(row.get("model_id") or "") for row in rows]
        or list(getattr(result, "model_ids", ()) or ())
    )
    provider = str(
        (rows[0].get("provider") if rows else "")
        or getattr(result, "provider", "")
    )
    current_metadata = _run_checkpoint_metadata(
        run_id,
        provider,
        model_ids,
        queue_items,
        _EVAL_TEMPERATURE_DEFAULT,
        resolve_eval_max_tokens(),
    )
    resume_allowed = bool(rows) and _checkpoint_matches_current(
        er.load_run_metadata(run_id),
        current_metadata,
    )
    summary = er.summarize_run_queue(run_id)
    status = "interrupted" if summary.get("unfinished") else "completed"
    eval_state.set_last_run(result)
    _set_run_state(
        status=status,
        run_id=run_id,
        provider=provider,
        model_ids=model_ids,
        mode=str(getattr(result, "mode", "") or "live"),
        created_at=str(
            (rows[0].get("created_at") if rows else "")
            or getattr(result, "created_at", "")
            or datetime.now().isoformat(timespec="seconds")
        ),
        queue_items=queue_items,
        outcomes=list(getattr(result, "outcomes", ()) or ()),
        message="检测到持久化运行记录。已完成结果会保留，未完成项可稍后继续。",
        resume_allowed=resume_allowed,
    )
    st.session_state["test_run_persisted"] = True
    return result


def _recover_latest_run(task_records: list[dict]) -> object | None:
    if _run_state() or eval_state.get_last_run() is not None:
        return eval_state.get_last_run()
    summaries = er.list_persisted_answer_runs()
    if not summaries:
        return None
    run_id = str(summaries[0].get("run_id") or "")
    if not run_id:
        return None
    return _recover_persisted_run(run_id, task_records)


def _recover_latest_score(compare_result) -> object | None:
    if _score_state() or eval_state.get_last_score() is not None:
        return eval_state.get_last_score()
    rows = sc.latest_score_queue()
    if not rows:
        return None
    score_run_id = str(rows[0].get("score_run_id") or "")
    if not score_run_id:
        return None
    score_result = sc.restore_score_result_from_db(score_run_id)
    queue_items = _score_queue_items_from_rows(rows, compare_result)
    summary = sc.summarize_score_queue(score_run_id)
    status = "interrupted" if summary.get("unfinished") else "completed"
    if score_result is not None:
        eval_state.set_last_score(score_result)
    _set_score_state(
        status=status,
        score_run_id=score_run_id,
        run_id=str(rows[0].get("run_id") or getattr(compare_result, "run_id", "")),
        judge_provider=str(rows[0].get("judge_provider") or getattr(score_result, "judge_provider", "")),
        judge_model=str(rows[0].get("judge_model") or getattr(score_result, "judge_model", sc.DEFAULT_JUDGE_MODEL)),
        mode=str(getattr(score_result, "mode", "") or "live"),
        created_at=str(rows[0].get("created_at") or datetime.now().isoformat(timespec="seconds")),
        queue_items=queue_items,
        outcomes=list(getattr(score_result, "outcomes", []) or []),
        skipped_count=0,
            message="检测到已生成 AI 评分。已生成评分会保留，未完成项可稍后继续。",
    )
    st.session_state["test_run_score_persisted"] = bool(score_result is not None and getattr(score_result, "outcomes", None))
    return score_result


def _run_queue_items_from_rows(rows: list[dict], task_records: list[dict]) -> list[dict]:
    tasks_by_case = {str(row.get("case_id") or ""): row for row in task_records or []}
    items: list[dict] = []
    for row in rows or []:
        case_id = str(row.get("case_id") or "")
        task = tasks_by_case.get(case_id) or {"case_id": case_id, "task_type": str(row.get("task_type") or "")}
        items.append({
            "model_id": str(row.get("model_id") or ""),
            "case_id": case_id,
            "task": task,
        })
    return items


def _score_queue_items_from_rows(rows: list[dict], compare_result) -> list[er.RunOutcome]:
    outcomes = list(getattr(compare_result, "outcomes", []) or [])
    by_pair = {(str(outcome.case_id), str(outcome.model_id)): outcome for outcome in outcomes}
    items: list[er.RunOutcome] = []
    for row in rows or []:
        key = (str(row.get("case_id") or ""), str(row.get("eval_model") or ""))
        existing = by_pair.get(key)
        if existing is not None:
            items.append(existing)
            continue
        items.append(er.RunOutcome(
            case_id=key[0],
            task_type=str(row.get("task_type") or ""),
            provider="",
            model_id=key[1],
            run_status="success",
            success=True,
        ))
    return items


def _finalize_run_result(status: str, state: dict, outcomes: list[er.RunOutcome], message: str = "") -> None:
    queue_items = list(state.get("queue_items") or [])
    run_id = str(state.get("run_id") or er.generate_run_id())
    _set_run_state(
        status=status,
        run_id=run_id,
        provider=str(state.get("provider") or ""),
        model_ids=list(state.get("model_ids") or []),
        mode=str(state.get("mode") or "live"),
        created_at=str(state.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        queue_items=queue_items,
        outcomes=outcomes,
        message=message,
    )
    st.session_state[_ANSWER_RUN_ID_KEY] = run_id
    result = _compare_result_from_state(_run_state(), outcomes)
    if result is not None:
        persisted_from_queue = bool(st.session_state.get("test_run_persisted"))
        if persisted_from_queue:
            persisted = True
        else:
            persisted = er.persist_compare_result(result)
        eval_state.set_last_run(result)
        _clear_score_state()
        st.session_state["test_run_persisted"] = persisted
        if persisted:
            cd.clear_conclusions_caches()


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
    score_after_run: bool = False,
    score_base=None,
    task_records: list[dict] | None = None,
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
    interruption_message = "本次运行出现单条失败。已完成结果会保留，未完成项可稍后继续。"
    try:
        _require_persistence_preflight(state_provider)
        metadata = _run_checkpoint_metadata(
            run_id,
            state_provider,
            model_list,
            all_queue,
            temperature,
            max_tokens,
        )
        _persistence_gate(
            er.initialize_run_queue(
                run_id,
                state_provider,
                all_queue,
                metadata=metadata,
            )
        )
    except Exception:
        _finalize_run_result("interrupted", state, outcomes, interruption_message)
        st.rerun()
        return
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
            _persistence_gate(
                er.mark_run_queue_item_running(
                    run_id,
                    item["case_id"],
                    item["model_id"],
                )
            )
        except RuntimeError:
            interrupted = True
            message = interruption_message
            break
        try:
            outcome = er.run_single(
                provider,
                item["model_id"],
                item["task"],
                temperature=temperature,
                max_tokens=max_tokens,
                retry_max_tokens=_EVAL_MAX_TOKENS_LIMIT,
            )
        except Exception:
            outcome = _unexpected_failure_outcome(provider, item)
            message = interruption_message
        outcomes.append(outcome)
        persisted = er.persist_run_outcome(run_id, mode, outcome)
        try:
            _persistence_gate(persisted)
        except RuntimeError:
            interrupted = True
            message = interruption_message
        st.session_state["test_run_persisted"] = (
            bool(st.session_state.get("test_run_persisted") or persisted)
            if persisted
            else False
        )
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
    if score_after_run and score_base is not None:
        result = _compare_result_from_state(_run_state(), outcomes)
        if result is not None and build_score_plan_summary(result)["can_score"]:
            dimensions = ds.get_rubric_dimensions()
            st.session_state["test_run_score_dims"] = dimensions
            _execute_score_queue(
                provider_name,
                result,
                score_base,
                task_records or [],
                dimensions,
            )
            return
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
        cd.clear_conclusions_caches()


def _replace_score_outcomes(
    existing: list[sc.ScoreOutcome],
    updates: list[sc.ScoreOutcome],
) -> list[sc.ScoreOutcome]:
    update_by_pair = {
        (str(outcome.case_id), str(outcome.eval_model)): outcome
        for outcome in updates
    }
    replaced: list[sc.ScoreOutcome] = []
    seen: set[tuple[str, str]] = set()
    for outcome in existing:
        key = (str(outcome.case_id), str(outcome.eval_model))
        seen.add(key)
        replaced.append(update_by_pair.get(key, outcome))
    for key, outcome in update_by_pair.items():
        if key not in seen:
            replaced.append(outcome)
    return replaced


def _execute_retry_score_queue(
    provider_name: str,
    score_result: sc.ScoreResult,
    compare_result,
    base,
    task_records: list[dict],
    dimensions: list[dict],
) -> None:
    retry_items = build_failed_score_retry_items(score_result, compare_result)
    if not retry_items:
        return
    provider = get_text_provider(prefer=provider_name)
    judge_model = str(getattr(score_result, "judge_model", "") or sc.DEFAULT_JUDGE_MODEL)
    score_run_id = str(getattr(score_result, "score_run_id", "") or sc.generate_score_run_id())
    run_id = str(getattr(score_result, "run_id", "") or getattr(compare_result, "run_id", ""))
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    judge_provider = str(getattr(provider, "name", ""))
    gold_map = getattr(base, "gold_answer_map", {}) or {}
    tasks_by_case = {str(row.get("case_id") or ""): row for row in task_records}
    state = _score_state() or {}
    original_queue = list(state.get("queue_items") or build_score_queue_items(compare_result))
    skipped_count = int(state.get("skipped_count") or build_score_plan_summary(compare_result)["skipped"])
    created_at = str(getattr(score_result, "created_at", "") or datetime.now().isoformat(timespec="seconds"))
    updated_outcomes = list(getattr(score_result, "outcomes", []) or [])
    retried_outcomes: list[sc.ScoreOutcome] = []
    queue_slot = st.empty()
    st.session_state[_SCORE_RETRY_RUNNING_KEY] = True
    _render_live_score_queue(queue_slot, retry_items, retried_outcomes, retry_items[0], retry_items[1:], 0, mode)

    interruption_message = "本次评分未完成。已生成的 AI 评分已保留，未完成项可重新评分。"
    interrupted = False
    try:
        _require_persistence_preflight(judge_provider)
        _persistence_gate(
            sc.initialize_score_queue(
                score_run_id,
                run_id,
                original_queue,
                judge_provider,
                judge_model,
            )
        )
    except Exception:
        interrupted = True

    for index, run_outcome in enumerate(retry_items):
        if interrupted:
            break
        waiting = retry_items[index + 1:]
        _render_live_score_queue(queue_slot, retry_items, retried_outcomes, run_outcome, waiting, 0, mode)
        try:
            _persistence_gate(
                sc.mark_score_queue_item_running(
                    score_run_id,
                    run_outcome.case_id,
                    run_outcome.model_id,
                )
            )
        except RuntimeError:
            interrupted = True
            break
        task = tasks_by_case.get(run_outcome.case_id) or {
            "case_id": run_outcome.case_id,
            "task_type": run_outcome.task_type,
        }
        gold = gold_map.get(run_outcome.case_id) or {}
        try:
            retry_outcome = sc.score_single(
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
            retry_outcome = _unexpected_score_failure_outcome(provider, judge_model, run_outcome, dimensions)
        retried_outcomes.append(retry_outcome)
        updated_outcomes = _replace_score_outcomes(updated_outcomes, [retry_outcome])
        persisted = sc.persist_score_outcome(
            score_run_id,
            run_id,
            judge_provider,
            judge_model,
            mode,
            retry_outcome,
        )
        try:
            _persistence_gate(persisted)
        except RuntimeError:
            interrupted = True
        st.session_state["test_run_score_persisted"] = (
            bool(st.session_state.get("test_run_score_persisted") or persisted)
            if persisted
            else False
        )
        _set_score_state(
            status="running",
            score_run_id=score_run_id,
            run_id=run_id,
            judge_provider=judge_provider,
            judge_model=judge_model,
            mode=mode,
            created_at=created_at,
            queue_items=original_queue,
            outcomes=updated_outcomes,
            skipped_count=skipped_count,
        )
        next_item = waiting[0] if waiting else None
        next_waiting = waiting[1:] if waiting else []
        _render_live_score_queue(queue_slot, retry_items, retried_outcomes, next_item, next_waiting, 0, mode)
        if interrupted:
            break

    success_count = sum(1 for outcome in retried_outcomes if outcome.ok)
    failed_count = len(retried_outcomes) - success_count
    message = (
        interruption_message
        if interrupted
        else f"已重试 {len(retried_outcomes)} 条，成功 {success_count} 条，仍失败 {failed_count} 条。"
    )
    _set_score_state(
        status="interrupted" if interrupted else "completed",
        score_run_id=score_run_id,
        run_id=run_id,
        judge_provider=judge_provider,
        judge_model=judge_model,
        mode=mode,
        created_at=created_at,
        queue_items=original_queue,
        outcomes=updated_outcomes,
        skipped_count=skipped_count,
        message=message,
    )
    score_result = _score_result_from_state(_score_state(), updated_outcomes)
    if score_result is not None:
        eval_state.set_last_score(score_result)
    st.session_state[_SCORE_RETRY_RUNNING_KEY] = False
    st.rerun()


def _execute_score_queue(
    provider_name: str,
    compare_result,
    base,
    task_records: list[dict],
    dimensions: list[dict],
    *,
    queue_items_override: list[er.RunOutcome] | None = None,
    existing_outcomes: list[sc.ScoreOutcome] | None = None,
    base_state: dict | None = None,
) -> None:
    st.session_state["test_run_score_dims"] = list(dimensions or [])
    existing_outcomes = list(existing_outcomes or [])
    full_queue = list((base_state or {}).get("queue_items") or build_score_queue_items(compare_result))
    queue_items = list(queue_items_override or _filter_score_queue_for_existing(full_queue, existing_outcomes))
    skipped_count = int((base_state or {}).get("skipped_count") or build_score_plan_summary(compare_result)["skipped"])
    if not queue_items:
        return

    provider = get_text_provider(prefer=provider_name)
    judge_model = sc.DEFAULT_JUDGE_MODEL
    score_run_id = str((base_state or {}).get("score_run_id") or sc.generate_score_run_id())
    created_at = str((base_state or {}).get("created_at") or datetime.now().isoformat(timespec="seconds"))
    mode = "mock" if getattr(provider, "name", "") == "mock" else "live"
    judge_provider = str(getattr(provider, "name", ""))
    gold_map = getattr(base, "gold_answer_map", {}) or {}
    tasks_by_case = {str(row.get("case_id") or ""): row for row in task_records}
    outcomes: list[sc.ScoreOutcome] = list(existing_outcomes or [])
    state = {
        "score_run_id": score_run_id,
        "run_id": str(getattr(compare_result, "run_id", "")),
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "mode": mode,
        "created_at": created_at,
        "queue_items": full_queue,
        "skipped_count": int(skipped_count),
    }
    interruption_message = "本次评分未完成。已生成的 AI 评分已保留，未完成项可重新评分。"
    try:
        _require_persistence_preflight(judge_provider)
        _persistence_gate(
            sc.initialize_score_queue(
                score_run_id,
                state["run_id"],
                full_queue,
                judge_provider,
                judge_model,
            )
        )
    except Exception:
        _finalize_score_result("interrupted", state, outcomes, interruption_message)
        st.rerun()
        return
    _set_score_state(
        status="running",
        score_run_id=score_run_id,
        run_id=state["run_id"],
        judge_provider=judge_provider,
        judge_model=judge_model,
        mode=mode,
        created_at=created_at,
        queue_items=full_queue,
        outcomes=outcomes,
        skipped_count=int(skipped_count),
    )

    queue_slot = st.empty()
    _render_live_score_queue(queue_slot, full_queue, outcomes, queue_items[0], queue_items[1:], skipped_count, mode)

    interrupted = False
    message = ""
    for index, run_outcome in enumerate(queue_items):
        waiting = queue_items[index + 1:]
        _render_live_score_queue(queue_slot, full_queue, outcomes, run_outcome, waiting, skipped_count, mode)
        try:
            _persistence_gate(
                sc.mark_score_queue_item_running(
                    score_run_id,
                    run_outcome.case_id,
                    run_outcome.model_id,
                )
            )
        except RuntimeError:
            interrupted = True
            message = interruption_message
            break
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
            message = interruption_message
        outcomes.append(score_outcome)
        persisted = sc.persist_score_outcome(
            score_run_id,
            state["run_id"],
            judge_provider,
            judge_model,
            mode,
            score_outcome,
        )
        try:
            _persistence_gate(persisted)
        except RuntimeError:
            interrupted = True
            message = interruption_message
        st.session_state["test_run_score_persisted"] = (
            bool(st.session_state.get("test_run_score_persisted") or persisted)
            if persisted
            else False
        )
        _set_score_state(
            status="running",
            score_run_id=score_run_id,
            run_id=state["run_id"],
            judge_provider=judge_provider,
            judge_model=judge_model,
            mode=mode,
            created_at=created_at,
            queue_items=full_queue,
            outcomes=outcomes,
            skipped_count=int(skipped_count),
            message=message,
        )
        next_item = None if interrupted else (waiting[0] if waiting else None)
        next_waiting = [] if interrupted or not waiting else waiting[1:]
        _render_live_score_queue(queue_slot, full_queue, outcomes, next_item, next_waiting, skipped_count, mode)
        if interrupted:
            break

    remaining = len(full_queue) - len(outcomes)
    status = "interrupted" if interrupted or remaining else "completed"
    _finalize_score_result(status, state, outcomes, message)
    st.rerun()


def _render_run_button(
    run_plan,
    *,
    service_ready: bool = True,
) -> bool:
    disabled = not run_plan["can_run"] or not service_ready
    clicked = st.button("运行评测", type="primary", disabled=disabled, key="test_run_run")

    if disabled:
        if not service_ready:
            st.caption("当前未配置模型服务密钥，暂不能发起真实调用。")
        else:
            st.caption("请先选择至少一个模型与至少一道任务，再运行评测。")
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
    failed = sum(1 for outcome in outcomes if not outcome.success)
    covered = len({outcome.case_id for outcome in outcomes})
    unfinished = max(0, total - done)
    with slot.container():
        st.markdown("**运行队列**")
        st.caption(
            f"计划样本 {len({item['case_id'] for item in queue_items})} 个 · "
            f"模型 {len({item['model_id'] for item in queue_items})} 个 · "
            f"计划回答 {total} 条 · 已完成 {done} 条 · 未完成 {unfinished} 条 · "
            f"失败 {failed} 条 · 已覆盖样本 {covered} 个 · 运行模式：{_mode_label(mode)}"
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
            st.markdown(f"已完成 {done} / {total} · 正在汇总 AI 评分")

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
    selected_run_id = _render_persisted_answer_run_selector(result)
    if selected_run_id and selected_run_id != str(getattr(result, "run_id", "") or ""):
        result = _recover_persisted_run(selected_run_id, task_records)
    state = _run_state()
    if result is None and not state:
        result = _recover_latest_run(task_records)
        state = _run_state()
    if result is None and state and _partial_outcomes():
        result = _compare_result_from_state(state, _partial_outcomes())
    if result is None:
        if state and state.get("status") in {"running", "interrupted", "failed"}:
            _render_unfinished_run_without_result(state, provider_name, temperature, max_tokens)
            return
        render_empty_state("尚未运行评测。配置样本与模型后点击「运行评测」。")
        return

    summary = er.summarize_outcomes(result.outcomes)
    failed = summary.total - summary.success
    run_status = _run_status_for_result(result)
    state_queue = list((state or {}).get("queue_items") or [])
    planned = len(state_queue) if state_queue else summary.total
    unfinished = len(build_remaining_queue_items(state_queue, list(result.outcomes))) if state_queue else 0
    covered_cases = len({o.case_id for o in result.outcomes})
    st.markdown(
        f"本次运行：计划回答 {planned} 条 · 已完成 {summary.total} 条 · 未完成 {unfinished} 条 · "
        f"成功 {summary.success} 条 · 失败 {failed} 条 · 已覆盖样本 {covered_cases} 个 · "
        f"模型 {len(result.model_ids)} 个 · "
        f"运行模式：{_mode_label(result.mode)}"
    )
    if run_status in {"running", "interrupted", "failed"}:
        _render_partial_run_notice(result, provider_name, temperature, max_tokens)
    elif failed:
        _render_retry_failed_run_action(result, provider_name, temperature, max_tokens)
    if summary.total and summary.success == 0:
        st.caption("本次运行没有成功回答，默认展示第一条失败原因。")
    elif failed:
        st.caption("失败项不会进入 AI 评分。")
    if er.is_mock_result(result):
        st.caption("本次为模拟回退模式运行，回答为模拟生成。")

    if _render_answer_viewer(result, task_records) == "technical_details":
        _render_technical_details_dialog(result)


def _render_unfinished_run_without_result(state: dict, provider_name: str, temperature, max_tokens) -> None:
    queue_items = list(state.get("queue_items") or [])
    resume_allowed = bool(state.get("resume_allowed", True))
    st.markdown("**本次运行未完成**")
    st.caption(f"已完成 0 条 · 未完成 {len(queue_items)} 条 · 失败 0 条。未完成项可继续运行。")
    if not resume_allowed:
        st.caption("当前运行可查看已保存回答，但运行元数据与当前任务不一致，不能继续未完成项。")
    resume_clicked = False
    col1, col2 = st.columns([1, 1])
    with col1:
        resume_clicked = st.button(
            "继续未完成项",
            key="test_run_resume_empty",
            type="secondary",
            disabled=not queue_items or not resume_allowed,
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
    resume_allowed = bool(state.get("resume_allowed", True))
    queue_items = list(state.get("queue_items") or [])
    outcomes = list(result.outcomes)
    remaining = build_remaining_queue_items(queue_items, outcomes)
    failed_items = build_failed_run_queue_items(queue_items, outcomes)
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
    if not resume_allowed:
        st.caption("当前运行可查看已保存回答，但运行元数据与当前任务不一致，不能继续未完成项。")
    resume_clicked = False
    retry_clicked = False
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        resume_clicked = st.button(
            "继续未完成项",
            key="test_run_resume",
            type="secondary",
            disabled=not remaining or not resume_allowed,
            use_container_width=True,
        )
    with col2:
        retry_clicked = st.button(
            "重试失败项",
            key="test_run_retry_failed_run_partial",
            type="secondary",
            disabled=not failed_items or not resume_allowed,
            use_container_width=True,
        )
    with col3:
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
    if retry_clicked:
        successful = [outcome for outcome in outcomes if outcome.success]
        _execute_run_queue(
            provider_name,
            failed_items,
            list(state.get("model_ids") or []),
            temperature,
            max_tokens,
            existing_outcomes=successful,
            base_state=state,
        )


def _render_retry_failed_run_action(result, provider_name: str, temperature, max_tokens) -> None:
    state = _run_state()
    resume_allowed = bool(state.get("resume_allowed", True))
    queue_items = list(state.get("queue_items") or [])
    outcomes = list(getattr(result, "outcomes", []) or [])
    failed_items = build_failed_run_queue_items(queue_items, outcomes)
    if not failed_items:
        return
    st.caption("部分模型回答失败，可只重试失败项；已完成回答不会重新生成。")
    if not resume_allowed:
        st.caption("当前运行可查看已保存回答，但运行元数据与当前任务不一致，不能重试失败项。")
    if st.button(
        "重试失败项",
        key="test_run_retry_failed_run",
        type="secondary",
        disabled=not resume_allowed,
    ):
        successful = [outcome for outcome in outcomes if outcome.success]
        _execute_run_queue(
            provider_name,
            failed_items,
            list(state.get("model_ids") or []),
            temperature,
            max_tokens,
            existing_outcomes=successful,
            base_state=state,
        )


def _render_run_outcome_card(
    outcome: er.RunOutcome,
    index: int,
    *,
    compact: bool = False,
) -> None:
    status = _outcome_display_status(outcome)
    elapsed = "—" if outcome.latency_ms is None else f"{outcome.latency_ms} ms"
    st.markdown(f"**{index}. {_model_short_name(outcome.model_id)}**")
    st.caption(f"任务编号：{outcome.case_id} · 状态：{status} · 耗时：{elapsed}")
    if outcome.success:
        answer = outcome.answer_text or "—"
        render_model_answer_detail(outcome, preview=True)
        if len(answer) > _ANSWER_PREVIEW_LIMIT and not compact:
            if st.button(
                "查看全文",
                key=f"test_run_full_answer_{index}_{_safe_key(outcome.model_id)}_{_safe_key(outcome.case_id)}",
                type="tertiary",
            ):
                _render_full_answer_dialog(outcome)
        return

    is_incomplete = str(outcome.error_code or "").strip().lower() == "incomplete_response"
    st.markdown(f"原因：{_short(_failure_reason_text(outcome), 180)}")
    retry_text = _retry_count_text(outcome)
    if retry_text:
        st.caption(retry_text)
    guidance = "不会进入 AI 评分，可重试失败项或更换模型。" if is_incomplete else _failure_guidance(outcome)
    if guidance:
        st.caption(f"处理：{guidance}")


@st.dialog("模型回答全文", width="large")
def _render_full_answer_dialog(outcome: er.RunOutcome) -> None:
    st.caption(f"任务编号：{outcome.case_id} · 模型：{_model_short_name(outcome.model_id)}")
    render_model_answer_detail(outcome, preview=False)


@st.dialog("技术明细", width="large")
def _render_technical_details_dialog(result) -> None:
    _render_results_table(result)


def build_technical_detail_rows(result) -> list[dict[str, str]]:
    return [
        {
            "模型": outcome.model_id,
            "任务编号": outcome.case_id,
            "状态": _outcome_display_status(outcome),
            "max_tokens": _n(getattr(outcome, "max_tokens", None)),
            "temperature": _n(getattr(outcome, "temperature", None)),
            "HTTP状态": _n(outcome.http_status),
            "错误码": _dash(outcome.error_code),
            "错误信息": _short(outcome.error_message),
            "provider_error_code": _dash(getattr(outcome, "provider_error_code", None)),
            "provider_error_message": _short(getattr(outcome, "provider_error_message", None), 160),
            "provider_error_body_excerpt": _short(getattr(outcome, "provider_error_body_excerpt", None), 220),
            "finish_reason": _dash(getattr(outcome, "finish_reason", None)),
            "incomplete_reason": _dash(getattr(outcome, "incomplete_reason", None)),
            "retry_count": _n(getattr(outcome, "retry_count", 0)),
            "timeout_seconds": _n(getattr(outcome, "timeout_seconds", None)),
            "timeout_source": _dash(getattr(outcome, "timeout_source", None)),
            "first_finish_reason": _dash(getattr(outcome, "first_finish_reason", None)),
            "final_finish_reason": _dash(getattr(outcome, "final_finish_reason", None)),
            "trace_id": _dash(outcome.trace_id),
            "耗时(ms)": _n(outcome.latency_ms),
            "输入tokens": _n(outcome.input_tokens),
            "输出tokens": _n(outcome.output_tokens),
            "总tokens": _n(outcome.total_tokens),
            "回答长度": str(outcome.answer_length),
        }
        for outcome in result.outcomes
    ]


def _render_results_table(result) -> None:
    rows = build_technical_detail_rows(result)
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
    )


def _render_answer_viewer(result, task_records: list[dict]) -> str | None:
    outcomes = list(result.outcomes)
    if not outcomes:
        st.caption("暂无回答可查看。")
        return None

    with st.container(key="test_run_answer_viewer"):
        task_lookup = _task_lookup_for_result(result, task_records)
        options = build_outcome_view_options(outcomes, task_lookup)
        selected = st.selectbox(
            "查看回答",
            options=[int(item["index"]) for item in options],
            index=default_outcome_view_index(outcomes),
            format_func=lambda idx: str(options[idx]["label"]),
            key=f"test_run_view_outcome_{_safe_key(getattr(result, 'run_id', 'current'))}",
        )
        return _render_selected_outcome_detail(outcomes[int(selected)], task_lookup)


def _render_selected_outcome_detail(outcome: er.RunOutcome, task_lookup: dict[str, dict]) -> str | None:
    st.markdown("**当前回答**")
    action_clicked = render_model_answer_detail(
        outcome,
        task_lookup=task_lookup,
        preview=True,
        action_label="查看技术明细",
        action_key=f"test_run_technical_details::{_safe_key(outcome.model_id)}::{_safe_key(outcome.case_id)}",
        action_type="secondary",
    )
    if outcome.success:
        answer = outcome.answer_text or "—"
        if len(answer) > _ANSWER_PREVIEW_LIMIT:
            if st.button(
                "查看全文",
                key=f"test_run_selected_full_answer_{_safe_key(outcome.model_id)}_{_safe_key(outcome.case_id)}",
                type="tertiary",
            ):
                _render_full_answer_dialog(outcome)
    return "technical_details" if action_clicked else None


def render_model_answer_detail(
    outcome: er.RunOutcome,
    *,
    task_lookup: dict[str, dict] | None = None,
    preview: bool = True,
    action_label: str | None = None,
    action_key: str | None = None,
    action_type: str = "secondary",
) -> bool:
    title = (
        f"{outcome.case_id}｜"
        f"{_model_short_name(outcome.model_id)}｜"
        f"{_outcome_display_status(outcome)}"
    )
    meta_parts = [f"耗时：{_latency_label(outcome.latency_ms)}"]
    if outcome.success or outcome.answer_length:
        meta_parts.append(f"回答长度：{_answer_length_label(outcome)}")
    meta = "｜".join(meta_parts) + f"\n模型 ID：{outcome.model_id}"
    answer = outcome.answer_text or "—"
    display_text = _answer_preview(answer) if preview else answer
    if outcome.success:
        markdown = f"**模型回答**\n\n{display_text}"
    else:
        guidance = _failure_guidance(outcome)
        if str(outcome.error_code or "").strip().lower() == "incomplete_response":
            reason = _failure_reason_text(outcome)
            lines = [
                "**回答不完整**",
                "",
                f"原因：{_short(reason, 220)}",
            ]
            retry_text = _retry_count_text(outcome)
            if retry_text:
                lines.extend(["", retry_text])
            lines.extend(["", "处理：不会进入 AI 评分，可重试失败项或更换模型。"])
            if outcome.answer_text:
                lines.extend(["", "**部分回答**", "", display_text])
        else:
            lines = [
                f"**{_outcome_display_status(outcome)}**",
                "",
                f"原因：{_short(_failure_reason_text(outcome), 220)}",
            ]
            retry_text = _retry_count_text(outcome)
            if retry_text:
                lines.extend(["", retry_text])
            if guidance:
                lines.extend(["", f"处理：{guidance}"])
        markdown = "\n".join(lines)
    return render_markdown_detail_panel(
        title=title,
        meta=meta,
        markdown_text=markdown,
        action_label=action_label,
        action_key=action_key,
        action_type=action_type,
    )


def _render_scoring(base, provider_name: str, task_records: list[dict]) -> None:
    result = eval_state.get_last_run()
    if result is None:
        result = _recover_latest_run(task_records)
    if result is None:
        st.caption("请先运行评测，系统会基于成功回答生成 AI 评分。")
        return

    run_status = _run_status_for_result(result)
    partial_run = run_status in {"running", "interrupted", "failed"}
    existing_score_result = eval_state.get_last_score()
    if existing_score_result is None:
        existing_score_result = _recover_latest_score(result)
    score_plan = build_score_plan_summary(result, existing_score_result)
    existing_scores = list(getattr(existing_score_result, "outcomes", []) or [])
    if partial_run:
        st.caption("本次运行未完成；AI 评分将仅处理已完成且成功的回答。")
    else:
        st.caption("AI 评分成功后直接用于评测结论；被测模型未看到专业标准答案或评分标准。")
    st.caption(
        f"可评分回答：{score_plan['scoreable']} 条 · "
        f"跳过失败回答：{score_plan['skipped']} 条。失败回答不会进入 AI 评分。"
    )
    no_success = not score_plan["can_score"]
    if no_success:
        if any(getattr(outcome, "ok", False) for outcome in existing_scores):
            st.caption("当前成功回答已完成 AI 评分，可直接查看评测结论。")
        else:
            st.warning("没有成功回答，无法生成 AI 评分。")
        failed = next((outcome for outcome in result.outcomes if not outcome.success), None)
        if failed is not None and not existing_scores:
            _render_selected_outcome_detail(failed, _task_lookup_for_result(result, task_records))
        return

    button_label = "仅对已完成回答生成 AI 评分" if partial_run else "生成 AI 评分"
    if st.button(
        button_label, type="secondary", disabled=no_success, key="test_run_score_run"
    ):
        dimensions = ds.get_rubric_dimensions()
        st.session_state["test_run_score_dims"] = dimensions
        _execute_score_queue(
            provider_name,
            result,
            base,
            task_records,
            dimensions,
            existing_outcomes=existing_scores,
            base_state=_score_state() or None,
        )


def _render_score_results(base, provider_name: str, task_records: list[dict]) -> None:
    score_result = eval_state.get_last_score()
    compare_result = eval_state.get_last_run()
    state = _score_state()
    if compare_result is None:
        compare_result = _recover_latest_run(task_records)
    if score_result is None and not state:
        score_result = _recover_latest_score(compare_result)
        state = _score_state()
    if score_result is None and state and _partial_score_outcomes():
        score_result = _score_result_from_state(state, _partial_score_outcomes())
    if score_result is None:
        if state and state.get("status") in {"running", "interrupted", "failed"}:
            _render_unfinished_score_notice(state, base, provider_name, compare_result, task_records)
        return
    dimensions = st.session_state.get("test_run_score_dims") or ds.get_rubric_dimensions()
    state_skipped = int((state or {}).get("skipped_count") or 0)
    mock_scores = sum(1 for outcome in score_result.outcomes if _is_mock_score_outcome(outcome))
    failed_scores = sum(
        1 for outcome in score_result.outcomes
        if not outcome.ok and not _is_mock_score_outcome(outcome)
    )
    generated = sum(1 for outcome in score_result.outcomes if outcome.ok)
    persisted = bool(st.session_state.get("test_run_score_persisted"))

    st.markdown(
        f"AI 评分已生成：成功评分 {score_result.scored_count}/{len(score_result.outcomes)} · "
        f"已生成结论 {generated} 条 · 跳过失败回答 {state_skipped} 条 · "
        f"模拟评分 {mock_scores} 条 · 评分失败 {failed_scores} 条 · "
        f"裁判模式：{_mode_label(score_result.mode)}"
    )
    if persisted:
        st.caption("AI 评分已写入数据库，可在评测结论页查看。")
    else:
        st.caption("当前评分仅在会话内展示；初始化运行期数据层后可写入评测结论。")
    if state and state.get("status") in {"running", "interrupted", "failed"}:
        _render_partial_score_notice(score_result, state, base, provider_name, compare_result, task_records, dimensions)
    elif state and state.get("message"):
        st.caption(str(state.get("message")))
    if sc.is_mock_score(score_result):
        st.caption("本次为模拟回退模式：未产生真实评分，各维度留空。")

    _render_score_result_list(score_result, dimensions)
    if _render_score_detail_viewer(score_result, dimensions):
        _render_score_compare_dialog(score_result, dimensions)
    if not (state and state.get("status") in {"running", "interrupted", "failed"}):
        _render_retry_failed_scores_action(base, provider_name, score_result, compare_result, task_records, dimensions)

    has_ai_scores = has_confirmable_score_drafts(score_result)
    if ds.database_ready() and has_ai_scores:
        if st.button("查看评测结论", key="test_run_to_conclusions", type="secondary"):
            st.session_state.current_page = "conclusions"
            st.rerun()
    elif has_ai_scores:
        st.caption("评分数据层未初始化，AI 评分仅在当前会话展示。")


def _render_retry_failed_scores_action(
    base,
    provider_name: str,
    score_result,
    compare_result,
    task_records: list[dict],
    dimensions,
) -> None:
    retry_items = build_failed_score_retry_items(score_result, compare_result)
    if not retry_items:
        return
    st.caption("模型回答已生成，裁判评分失败的项目可单独重试；不会重新生成模型回答。")
    retrying = bool(st.session_state.get(_SCORE_RETRY_RUNNING_KEY))
    if st.button(
        "重试失败评分",
        key="test_run_retry_failed_scores",
        type="secondary",
        disabled=retrying,
    ):
        st.session_state[_SCORE_RETRY_RUNNING_KEY] = True
        _execute_retry_score_queue(
            provider_name,
            score_result,
            compare_result,
            base,
            task_records,
            list(dimensions or []),
        )


def _render_unfinished_score_notice(state: dict, base=None, provider_name: str = "", compare_result=None, task_records: list[dict] | None = None) -> None:
    queue_items = list(state.get("queue_items") or [])
    skipped = int(state.get("skipped_count") or 0)
    st.markdown("**本次评分未完成**")
    st.caption(
        f"已评分 0 条 · 未评分 {len(queue_items)} 条 · 失败 0 条 · "
        f"跳过失败回答 {skipped} 条。已生成评分会保留，未完成项可稍后继续。"
    )
    _render_score_recovery_actions(state, [], base, provider_name, compare_result, task_records or [])


def _render_partial_score_notice(score_result, state: dict, base=None, provider_name: str = "", compare_result=None, task_records: list[dict] | None = None, dimensions=None) -> None:
    queue_items = list(state.get("queue_items") or [])
    remaining = max(0, len(queue_items) - len(score_result.outcomes))
    failed = sum(1 for outcome in score_result.outcomes if not outcome.ok)
    st.markdown("**本次评分未完成**")
    st.caption(
        f"已评分 {len(score_result.outcomes)} 条 · 未评分 {remaining} 条 · 失败 {failed} 条。"
        "已生成的 AI 评分已保留，未完成项可重新评分。"
    )
    if state.get("message"):
        st.caption(str(state.get("message")))
    _render_score_recovery_actions(state, list(score_result.outcomes), base, provider_name, compare_result, task_records or [], dimensions)


def _render_score_recovery_actions(
    state: dict,
    outcomes: list[sc.ScoreOutcome],
    base,
    provider_name: str,
    compare_result,
    task_records: list[dict],
    dimensions=None,
) -> None:
    if base is None or compare_result is None:
        return
    queue_items = list(state.get("queue_items") or [])
    completed = {(str(outcome.case_id), str(outcome.eval_model)) for outcome in outcomes or []}
    failed_pairs = {
        (str(outcome.case_id), str(outcome.eval_model))
        for outcome in outcomes or []
        if not outcome.ok and not _is_mock_score_outcome(outcome)
    }
    remaining_items = [
        item for item in queue_items
        if (str(item.case_id), str(item.model_id)) not in completed
    ]
    failed_items = [
        item for item in queue_items
        if (str(item.case_id), str(item.model_id)) in failed_pairs
    ]
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        continue_clicked = st.button(
            "继续未完成评分",
            key="test_run_continue_score_queue",
            type="secondary",
            disabled=not remaining_items,
            use_container_width=True,
        )
    with col2:
        retry_clicked = st.button(
            "重试失败评分",
            key="test_run_retry_failed_score_queue",
            type="secondary",
            disabled=not failed_items,
            use_container_width=True,
        )
    with col3:
        discard_clicked = st.button(
            "放弃本次评分",
            key="test_run_discard_score_queue",
            type="tertiary",
            use_container_width=True,
        )
    dims = list(dimensions or st.session_state.get("test_run_score_dims") or ds.get_rubric_dimensions())
    if continue_clicked:
        _execute_score_queue(
            provider_name,
            compare_result,
            base,
            task_records,
            dims,
            queue_items_override=remaining_items,
            existing_outcomes=outcomes,
            base_state=state,
        )
    if retry_clicked:
        kept = [outcome for outcome in outcomes if (str(outcome.case_id), str(outcome.eval_model)) not in failed_pairs]
        _execute_score_queue(
            provider_name,
            compare_result,
            base,
            task_records,
            dims,
            queue_items_override=failed_items,
            existing_outcomes=kept,
            base_state=state,
        )
    if discard_clicked:
        _clear_score_state()
        st.rerun()


def _render_score_result_list(score_result, dimensions) -> None:
    if not score_result.outcomes:
        st.caption("暂无 AI 评分。")
        return
    rows = build_score_result_index_rows(score_result, dimensions)
    st.markdown("**评分结果**")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
    )


def _render_score_detail_viewer(score_result, dimensions) -> bool:
    outcomes = list(score_result.outcomes)
    if not outcomes:
        return False
    options = build_score_view_options(outcomes)
    selected = st.selectbox(
        "查看 AI 评分",
        options=[int(item["index"]) for item in options],
        index=default_score_view_index(outcomes),
        format_func=lambda idx: str(options[idx]["label"]),
        key=f"test_run_score_view_{_safe_key(getattr(score_result, 'score_run_id', 'current'))}",
    )
    return _render_score_detail(outcomes[int(selected)], dimensions, score_result)


def _render_score_detail(outcome: sc.ScoreOutcome, dimensions, score_result=None) -> bool:
    panel = build_score_draft_detail_panel(outcome, dimensions)
    return render_markdown_detail_panel(
        title=panel["title"],
        meta=panel["meta"],
        markdown_text=panel["markdown"],
        action_label="查看评分对比表",
        action_key=f"test_run_score_compare_details::{_safe_key(getattr(score_result, 'score_run_id', 'current'))}",
        action_type="secondary",
    )


def _score_success_markdown(outcome: sc.ScoreOutcome, dimensions) -> str:
    lines = [
        "**评分说明**",
        "",
        str(outcome.review_note or "").strip() or "未返回明确评分说明。",
        "",
        "**维度评分**",
        "",
    ]
    dimension_lines = _score_dimension_markdown_sections(outcome, dimensions)
    if dimension_lines:
        lines.extend(dimension_lines)
    else:
        lines.append("暂无维度评分。")
    return "\n".join(lines).strip()


def _score_dimension_markdown_sections(outcome: sc.ScoreOutcome, dimensions) -> list[str]:
    lines: list[str] = []
    for dim in dimensions or []:
        field = str(dim.get("field") or "")
        name = str(dim.get("name") or field)
        full_mark = _n(dim.get("full_mark"))
        score = _n((outcome.scores or {}).get(field))
        rationale = str((outcome.rationale or {}).get(field) or "").strip() or "未返回明确依据。"
        lines.extend([
            f"**{name}：{score} / {full_mark}**",
            "",
            f"评分依据：{rationale}",
            "",
        ])
    return lines


def _score_failure_markdown(outcome: sc.ScoreOutcome) -> str:
    lines = [
        "**评分失败**",
        "",
        "模型回答已生成，裁判评分失败。",
        "",
        f"错误码：`{_dash(outcome.error_code)}`",
        "",
        f"错误信息：{_short(outcome.error_message, 260)}",
    ]
    retry_count = getattr(outcome, "retry_count", 0)
    if retry_count:
        lines.extend(["", f"已自动重试 {retry_count} 次。"])
    guidance = _score_failure_guidance(outcome)
    lines.extend([
        "",
        "**处理建议**",
        "",
        "可稍后重试失败评分；失败评分不会进入评测结论。",
    ])
    if guidance:
        lines.extend(["", guidance])
    return "\n".join(lines).strip()


def _score_mock_markdown() -> str:
    return (
        "**模拟评分**\n\n"
        "未配置真实模型服务，未产生真实评分。该结果仅用于链路调试，不进入评测结论。"
    )


@st.dialog("评分对比表", width="large")
def _render_score_compare_dialog(score_result, dimensions) -> None:
    _render_score_compare_table(score_result, dimensions)


def _render_score_compare_table(score_result, dimensions) -> None:
    rows = build_score_summary_rows(score_result, dimensions)
    frame = pd.DataFrame(rows).drop(columns=["模型ID"], errors="ignore")
    st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
    )


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
    code = str(getattr(outcome, "error_code", "") or "").strip().lower()
    if outcome.success:
        return "已完成"
    if code in {"timeout", "gateway_timeout"}:
        return "响应超时"
    if code == "incomplete_response":
        return "回答不完整"
    if code == "rate_limited":
        return "触发限流"
    if code in {"missing_api_key", "unauthorized", "forbidden"}:
        return "权限异常"
    if code == "model_not_available":
        return "模型不可用"
    if code == "empty_response":
        return "空回答"
    if status == "running":
        return "生成中"
    if status == "waiting":
        return "等待中"
    if status == "interrupted":
        return "已中断"
    return "未获得有效回答"


def _failure_reason_text(outcome) -> str:
    code = str(getattr(outcome, "error_code", "") or "").strip().lower()
    if code in {"timeout", "gateway_timeout"}:
        return "模型服务未在当前等待时间内返回。"
    if code == "incomplete_response":
        if str(getattr(outcome, "finish_reason", "") or "").strip().lower() == "length":
            return "回答超过输出长度限制。"
        return getattr(outcome, "incomplete_reason", None) or getattr(outcome, "error_message", None) or "模型回答未完整结束。"
    if code == "rate_limited":
        return "模型服务触发限流。"
    if code in {"missing_api_key", "unauthorized", "forbidden"}:
        return "模型服务配置或权限异常。"
    if code == "empty_response":
        return "模型返回成功但回答为空。"
    if code in {"bad_request", "not_found"}:
        return "模型 ID 或请求参数异常。"
    if code == "model_not_available":
        return getattr(outcome, "error_message", None) or "当前模型不在可用模型列表中。"
    return getattr(outcome, "error_message", None) or "未获得有效回答。"


def _retry_count_text(outcome) -> str:
    try:
        count = int(getattr(outcome, "retry_count", 0) or 0)
    except (TypeError, ValueError):
        count = 0
    return f"已自动重试 {count} 次。" if count > 0 else ""


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
    return _REVIEW_STATUS_LABEL.get(str(value or "ai_final").strip().lower(), "已生成结论")


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
        return "可稍后重试失败项或调大 SILICONFLOW_TIMEOUT_SECONDS。"
    if code == "rate_limited":
        return "请求触发限流，请稍后重试。"
    if code == "empty_response":
        return "模型返回成功但回答为空，建议重试或更换模型。"
    if code == "incomplete_response":
        if str(getattr(outcome, "finish_reason", "") or "").strip().lower() == "length":
            return "系统可使用压缩提示词重试；不完整回答不会进入 AI 评分。"
        return "模型回答未完整结束，不会进入 AI 评分；可重试失败项或更换模型。"
    if code == "bad_request":
        return "请查看技术明细中的供应商错误信息，判断是模型不可用、权限不足、上下文过长或参数超限。"
    if code == "not_found":
        return "请检查模型 ID 或请求参数。"
    if code == "model_not_available":
        return "请重新选择模型后再运行。"
    if code == "runtime_error":
        return "已停止后续任务，已完成回答仍保留。"
    return ""


def _score_failure_guidance(outcome) -> str:
    code = str(getattr(outcome, "error_code", "") or "").strip().lower()
    if code in {"missing_api_key", "unauthorized", "forbidden"}:
        return "API Key 无效或缺失，请检查配置。"
    if code in {"timeout", "gateway_timeout"}:
        return "模型服务响应超时，可稍后重试或调大 SILICONFLOW_TIMEOUT_SECONDS。"
    if code == "rate_limited":
        return "模型服务触发限流，可稍后重试。"
    if code == "service_unavailable":
        return "模型服务暂不可用，可稍后重试。"
    if code == "connection_error":
        return "网络连接异常，可稍后重试或检查模型服务地址。"
    if code == "judge_parse_error":
        return "裁判输出未能解析为评分 JSON，可重试或更换裁判模型。"
    if code == "empty_response":
        return "裁判模型返回为空，可重试。"
    if code == "runtime_error":
        return "已停止后续评分，已生成的 AI 评分仍保留。"
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
