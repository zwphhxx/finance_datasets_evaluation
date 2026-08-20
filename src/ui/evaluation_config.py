"""Selection, queue planning, and prompt-preview helpers for evaluations."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from html import escape
from typing import Any

import streamlit as st

from app.persistence import get_result_store
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import model_display as md
from app.services.evaluation_workflow import EvaluationConfig, WorkflowCheckpointError
from app.services.run_checkpoint import build_run_metadata
from src.ui.components import render_inline_status, render_numbered_section
from src.ui.labels import TASK_TYPE_LABELS, display_label, summarize_text

NO_TESTABLE_SAMPLE_MESSAGE = (
    "当前没有可测样本。可测样本需同时满足：正式题库存在任务题、"
    "专业标准答案具备完整评判标准，评分标准满分标准和扣分规则完整，且样本状态为已入库。"
)
SAMPLE_CHECKBOX_KEY_PREFIX = "test_run_case_checkbox_"
SAMPLE_TABLE_COLUMN_WIDTHS = [0.58, 1.0, 2.6, 1.15, 0.8, 0.95]
SAMPLE_TABLE_HEADERS = ["选择", "样本编号", "任务标题", "场景", "难度", "测试状态"]
SAMPLE_TABLE_HEIGHT = 330
EVAL_TEMPERATURE_DEFAULT = 0.1
EVAL_TEMPERATURE_ENV = "FINDUEVAL_EVAL_TEMPERATURE"
EVAL_TEMPERATURE_KEY = "test_run_temperature"
MODEL_DIALOG_TEMPERATURE_KEY = "test_run_model_dialog_temperature"
MODEL_OPTION_LIMIT = 30
EVAL_MAX_TOKENS_DEFAULT = 4096
EVAL_MAX_TOKENS_LIMIT = 8192
EVAL_MAX_TOKENS_ENV = "FINDUEVAL_EVAL_MAX_TOKENS"


def resolve_eval_max_tokens(raw_value: str | None = None) -> int:
    raw = os.getenv(EVAL_MAX_TOKENS_ENV, "") if raw_value is None else raw_value
    value = str(raw or "").strip()
    if not value:
        return EVAL_MAX_TOKENS_DEFAULT
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return EVAL_MAX_TOKENS_DEFAULT
    if parsed <= 0:
        return EVAL_MAX_TOKENS_DEFAULT
    return min(parsed, EVAL_MAX_TOKENS_LIMIT)


def resolve_eval_temperature(raw_value: str | None = None) -> float:
    raw = os.getenv(EVAL_TEMPERATURE_ENV, "") if raw_value is None else raw_value
    value = str(raw or "").strip()
    if not value:
        return EVAL_TEMPERATURE_DEFAULT
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return EVAL_TEMPERATURE_DEFAULT
    if parsed < 0.0 or parsed > 1.0:
        return EVAL_TEMPERATURE_DEFAULT
    return parsed


EVAL_MAX_TOKENS = resolve_eval_max_tokens()
EVAL_TEMPERATURE = resolve_eval_temperature()


def normalize_eval_temperature(value: object) -> float:
    return resolve_eval_temperature(str(value if value is not None else ""))


def current_eval_temperature() -> float:
    if EVAL_TEMPERATURE_KEY not in st.session_state:
        return EVAL_TEMPERATURE
    return normalize_eval_temperature(st.session_state.get(EVAL_TEMPERATURE_KEY))


def eligible_case_ids(
    task_records: list[dict[str, Any]],
    gold_map: Mapping[str, Mapping[str, Any]],
    rubric_dimensions: list[dict[str, Any]] | None,
) -> list[str]:
    return [
        str(row.get("case_id") or "").strip()
        for row in task_records
        if str(row.get("case_id") or "").strip()
        and ds.assess_sample_readiness(
            row,
            gold_map.get(str(row.get("case_id") or "").strip()) or {},
            rubric_dimensions,
        ).is_testable
    ]


def build_sample_options(
    task_records: list[dict[str, Any]],
    gold_map: Mapping[str, Mapping[str, Any]],
    rubric_dimensions: list[dict[str, Any]] | None,
    title_map: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    # Keep the legacy first-match behavior when malformed input contains a
    # duplicate case ID.  The page has always resolved the first task record.
    by_case: dict[str, dict[str, Any]] = {}
    for row in task_records:
        by_case.setdefault(str(row.get("case_id") or "").strip(), row)
    options: list[dict[str, Any]] = []
    for case_id in eligible_case_ids(task_records, gold_map, rubric_dimensions):
        row = by_case[case_id]
        scenario = _dash(row.get("scenario"))
        scene = scenario.split("——")[0].strip() or scenario
        title = summarize_text(
            (title_map or {}).get(case_id)
            or row.get("title")
            or row.get("expected_capability")
            or row.get("question"),
            32,
        )
        task_type = display_label(row.get("task_type"), TASK_TYPE_LABELS)
        options.append({
            "case_id": case_id,
            "label": f"{case_id} · {scene} · {task_type} · {title}",
            "scenario": scene,
            "task_type": task_type,
            "title": title,
            "difficulty": _dash(row.get("difficulty")),
            "task": row,
        })
    return options


def filter_sample_selection_options(
    sample_options: list[dict],
    keyword: str = "",
    scenario: str = "全部",
    difficulty: str = "全部",
) -> list[dict]:
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


def build_sample_selection_rows(
    sample_options: list[dict], selected_case_ids: list[str]
) -> list[dict]:
    selected = set(selected_case_ids or [])
    return [
        {
            "选择": str(item.get("case_id") or "").strip() in selected,
            "样本编号": str(item.get("case_id") or "").strip(),
            "任务标题": item.get("title") or "待补充",
            "场景": item.get("scenario") or "待补充",
            "难度": item.get("difficulty") or "待补充",
            "测试状态": "可测试",
        }
        for item in sample_options
    ]


def sample_checkbox_key(case_id: str) -> str:
    return f"{SAMPLE_CHECKBOX_KEY_PREFIX}{case_id}"


def merge_sample_checkbox_selection(
    selected_case_ids: list[str],
    filtered_options: list[dict],
    checkbox_values: dict[str, bool],
    all_case_ids: set[str],
) -> list[str]:
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


def build_model_selection_options(
    models: list[Any], keyword: str, limit: int = MODEL_OPTION_LIMIT
) -> tuple[list[str], int]:
    query = str(keyword or "").strip().lower()
    matched: list[str] = []
    for model in models or []:
        model_id = str(getattr(model, "id", "") or "").strip()
        if not model_id:
            continue
        raw = getattr(model, "raw", {}) or {}
        metadata = getattr(model, "metadata", {}) or {}
        haystack = " ".join([
            model_id,
            str(getattr(model, "owned_by", "") or ""),
            str(raw.get("name", "") or ""),
            str(raw.get("display_name", "") or ""),
            str(metadata.get("name", "") or ""),
            str(metadata.get("display_name", "") or ""),
        ]).lower()
        if not query or query in haystack:
            matched.append(model_id)
    deduped = _dedupe(matched)
    return deduped[:limit], len(deduped)


def prompt_preview_task_for_case(
    sample_options: list[dict],
    selected_case_ids: list[str],
    preview_case_id: str | None = None,
) -> dict:
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


def build_run_plan_summary(
    model_ids: list[str], selected_tasks: list[dict[str, Any]]
) -> dict[str, int | bool]:
    model_count = len(_dedupe(model_ids))
    sample_count = len(selected_tasks or [])
    return {
        "sample_count": sample_count,
        "model_count": model_count,
        "planned_responses": sample_count * model_count,
        "can_run": bool(sample_count and model_count),
    }


def build_run_queue_items(
    model_ids: list[str], selected_tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
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


def current_provider_name(provider_name: str) -> str:
    st.session_state["test_run_provider"] = provider_name
    return provider_name


def normalize_selected_cases(sample_options: list[dict]) -> None:
    """Keep only explicit, still-valid sample choices without selecting a default."""
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
    st.session_state["test_run_selected_cases"] = current


def selected_tasks_from_state(sample_options: list[dict]) -> list[dict]:
    by_case = {item["case_id"]: item for item in sample_options}
    return [
        by_case[case_id]
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in by_case
    ]


def selected_model_ids_from_state() -> list[str]:
    return _dedupe(list(st.session_state.get("test_run_selected_models", [])))


def render_evaluation_scope(
    sample_options: list[dict],
    selected_tasks: list[dict],
    model_ids: list[str],
    run_plan: dict[str, int | bool],
    *,
    provider_name: str,
) -> None:
    render_numbered_section("01", "评测范围")
    render_inline_status([
        _status_row("已选样本", _selected_sample_summary(selected_tasks), warn=not selected_tasks),
        _status_row("已选模型", _selected_model_summary(model_ids), warn=not model_ids),
        _status_row("计划评测", f"{run_plan['planned_responses']} 项", warn=not run_plan["planned_responses"]),
    ])
    with st.container(key="test_run_scope_actions"):
        if st.button(
            "选择样本",
            key="test_run_open_samples",
            type="secondary",
            use_container_width=True,
        ):
            _open_sample_dialog(sample_options)
        if st.button(
            "选择模型",
            key="test_run_open_models",
            type="secondary",
            use_container_width=True,
        ):
            _open_model_dialog()
    if selected_tasks and st.button(
        "查看发送给被测模型的提示词",
        key="test_run_open_prompt_preview",
        type="tertiary",
    ):
        _open_prompt_preview_dialog(selected_tasks)


def pending_dialog_name() -> str:
    return str(st.session_state.get("test_run_dialog") or "")


def render_pending_dialogs(
    sample_options: list[dict],
    *,
    provider_name: str,
    provider_label: str,
    provider_configured: bool,
    model_provider: Any | None = None,
) -> None:
    dialog = pending_dialog_name()
    if dialog == "samples":
        _render_sample_selection_dialog(sample_options)
    elif dialog == "models":
        if model_provider is None:
            st.warning("模型服务暂不可用。")
            return
        _render_model_selection_dialog(
            model_provider,
            provider_name=provider_name,
            provider_label=provider_label,
            provider_configured=provider_configured,
        )
    elif dialog == "prompt_preview":
        _render_prompt_preview_dialog(sample_options)


def _clear_session_state_prefix(prefix: str) -> None:
    for key in [key for key in st.session_state if str(key).startswith(prefix)]:
        st.session_state.pop(key, None)


def _open_sample_dialog(sample_options: list[dict]) -> None:
    option_ids = [item["case_id"] for item in sample_options]
    st.session_state["test_run_dialog"] = "samples"
    st.session_state["test_run_cases_dialog_selected"] = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
    st.session_state.pop("test_run_sample_search", None)
    st.session_state.pop("test_run_sample_scenario", None)
    st.session_state.pop("test_run_sample_difficulty", None)
    _clear_session_state_prefix(SAMPLE_CHECKBOX_KEY_PREFIX)


def _open_model_dialog() -> None:
    st.session_state["test_run_dialog"] = "models"
    st.session_state["test_run_model_dialog_selected"] = selected_model_ids_from_state()
    st.session_state[MODEL_DIALOG_TEMPERATURE_KEY] = current_eval_temperature()


def _open_prompt_preview_dialog(selected_tasks: list[dict]) -> None:
    first = next((item for item in selected_tasks or [] if str(item.get("case_id") or "").strip()), None)
    if first:
        st.session_state["test_run_prompt_preview_case"] = str(first.get("case_id") or "")
    st.session_state["test_run_dialog"] = "prompt_preview"


def _clear_dialog_state() -> None:
    st.session_state.pop("test_run_dialog", None)
    st.session_state.pop("test_run_cases_dialog_selected", None)
    st.session_state.pop(MODEL_DIALOG_TEMPERATURE_KEY, None)
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
        with st.container(key="test_run_prompt_dialog_actions"):
            if st.button("关闭", key="test_run_prompt_preview_close_empty", type="tertiary", use_container_width=True):
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
    with st.spinner("正在准备提示词…"):
        messages = er.build_messages(prompt_preview_task_for_case(sample_options, selected_ids, current))
    st.caption("以下为被测模型实际收到的全部内容，不包含专业标准答案、必须覆盖点、不可接受错误或评分标准。")
    for message in messages:
        role = str(message.get("role") or "")
        st.text_area(
            "系统提示词" if role == "system" else "用户提示词",
            value=str(message.get("content") or ""),
            height=210 if role == "system" else 340,
            disabled=True,
            key=f"test_run_prompt_preview_{role}",
        )
    with st.container(key="test_run_prompt_dialog_actions"):
        if st.button("关闭", key="test_run_prompt_preview_close", type="tertiary", use_container_width=True):
            _clear_dialog_state()
            st.rerun()


def _prompt_preview_case_label(item: dict) -> str:
    return f"{str(item.get('case_id') or '')}｜{str(item.get('title') or '样本任务')}"


@st.dialog("选择样本", width="large")
def _render_sample_selection_dialog(sample_options: list[dict]) -> None:
    if not sample_options:
        st.warning(NO_TESTABLE_SAMPLE_MESSAGE)
        with st.container(key="test_run_sample_dialog_actions"):
            if st.button("关闭", key="test_run_sample_dialog_close", type="tertiary", use_container_width=True):
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
        str(item.get("scenario") or "") for item in sample_options
        if str(item.get("scenario") or "").strip() and str(item.get("scenario") or "") != "—"
    })
    difficulties = ["全部"] + sorted({
        str(item.get("difficulty") or "") for item in sample_options
        if str(item.get("difficulty") or "").strip() and str(item.get("difficulty") or "") != "—"
    })
    filter_cols = st.columns([2.2, 1, 1])
    with filter_cols[0]:
        keyword = st.text_input("关键词搜索", key="test_run_sample_search", placeholder="输入样本编号、标题或背景关键词")
    with filter_cols[1]:
        scenario = st.selectbox("场景", scenes, key="test_run_sample_scenario")
    with filter_cols[2]:
        difficulty = st.selectbox("难度", difficulties, key="test_run_sample_difficulty")
    filtered_options = filter_sample_selection_options(sample_options, keyword, scenario, difficulty)
    bulk_cols = st.columns([0.72, 0.48, 3.8])
    with bulk_cols[0]:
        if st.button("全选当前筛选结果", key="test_run_sample_select_filtered", type="tertiary", disabled=not filtered_options):
            selected_cases = _dedupe(list(selected_cases) + [item["case_id"] for item in filtered_options])
            st.session_state["test_run_cases_dialog_selected"] = selected_cases
            for item in filtered_options:
                st.session_state[sample_checkbox_key(item["case_id"])] = True
            st.rerun()
    with bulk_cols[1]:
        if st.button("清空", key="test_run_sample_clear_selected", type="tertiary", disabled=not selected_cases):
            st.session_state["test_run_cases_dialog_selected"] = []
            for case_id in all_case_ids:
                st.session_state[sample_checkbox_key(case_id)] = False
            st.rerun()
    checkbox_values: dict[str, bool] = {}
    if not filtered_options:
        st.caption("当前没有符合条件的可测样本。")
    else:
        checkbox_values = _render_sample_checkbox_table(filtered_options, selected_cases)
    selected_cases = merge_sample_checkbox_selection(
        selected_cases, filtered_options, checkbox_values, all_case_ids
    )
    st.session_state["test_run_cases_dialog_selected"] = selected_cases
    st.caption(
        f"已选样本：{len(selected_cases)} 个。仅展示已入库且通过完整度校验的样本；"
        "被测模型不会看到专业标准答案或评分标准。"
    )
    with st.container(key="test_run_sample_dialog_actions"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("确认选择", key="test_run_sample_dialog_confirm", type="primary", disabled=not selected_cases, use_container_width=True):
                st.session_state["test_run_selected_cases"] = selected_cases
                _clear_dialog_state()
                st.rerun()
        with col2:
            if st.button("取消", key="test_run_sample_dialog_cancel", type="tertiary", use_container_width=True):
                _clear_dialog_state()
                st.rerun()


def _render_sample_checkbox_table(
    sample_options: list[dict], selected_cases: list[str]
) -> dict[str, bool]:
    rows = build_sample_selection_rows(sample_options, selected_cases)
    selected_set = set(selected_cases or [])
    checkbox_values: dict[str, bool] = {}
    with st.container(height=SAMPLE_TABLE_HEIGHT, border=True, key="test_run_sample_table"):
        with st.container(key="test_run_sample_table_header"):
            header_cols = st.columns(SAMPLE_TABLE_COLUMN_WIDTHS, gap="small")
            for col, header in zip(header_cols, SAMPLE_TABLE_HEADERS, strict=True):
                with col:
                    st.markdown(f"**{header}**")
            st.markdown(
                "<div style='border-top: 1px solid #E5E7EB; margin: 0.12rem 0 0.2rem 0;'></div>",
                unsafe_allow_html=True,
            )
        for row in rows:
            case_id = str(row["样本编号"])
            key = sample_checkbox_key(case_id)
            if key not in st.session_state:
                st.session_state[key] = case_id in selected_set
            with st.container(key=f"test_run_sample_row_{_safe_key(case_id)}"):
                cols = st.columns(SAMPLE_TABLE_COLUMN_WIDTHS, gap="small")
                with cols[0]:
                    checkbox_values[case_id] = bool(st.checkbox("选择", key=key, label_visibility="collapsed"))
                for column, value in zip(cols[1:], [case_id, row["任务标题"], row["场景"], row["难度"], row["测试状态"]], strict=True):
                    with column:
                        _render_sample_table_cell(str(value))
    return checkbox_values


def _render_sample_table_cell(value: str) -> None:
    st.markdown(
        "<div style='font-size: 0.9rem; line-height: 1.35; padding: 0.24rem 0; "
        f"color: #2F3947; overflow-wrap: anywhere;'>{escape(value)}</div>",
        unsafe_allow_html=True,
    )


@st.dialog("选择模型", width="large")
def _render_model_selection_dialog(
    provider: Any,
    *,
    provider_name: str,
    provider_label: str,
    provider_configured: bool,
) -> None:
    st.markdown(f"**模型服务：** {provider_label}")
    balance_text = _provider_balance_text(provider)
    if balance_text:
        st.caption(f"账户余额：{balance_text}")
    if not provider_configured:
        st.warning("当前未配置模型服务密钥，暂不能发起真实调用。")
    if MODEL_DIALOG_TEMPERATURE_KEY not in st.session_state:
        st.session_state[MODEL_DIALOG_TEMPERATURE_KEY] = current_eval_temperature()
    st.markdown("**回答设置**")
    st.slider(
        "回答随机性",
        min_value=0.0,
        max_value=1.0,
        step=0.1,
        key=MODEL_DIALOG_TEMPERATURE_KEY,
        help="同一批评测内所有被测模型使用相同设置；裁判评分固定为 0.0。",
    )
    st.caption("所有被测模型使用相同回答随机性，便于横向比较。")
    with st.spinner("正在获取模型列表…"):
        result = provider.list_models()
    available_models = list(result.models) if result.ok else []
    model_options = [str(model.id) for model in available_models if str(model.id).strip()]
    st.markdown("**可用模型**")
    if model_options:
        search_keyword = st.text_input("搜索模型", key="test_run_model_search", placeholder="输入模型名称、厂商或关键词")
        visible_options, matched_count = build_model_selection_options(
            available_models, search_keyword, MODEL_OPTION_LIMIT
        )
        if matched_count > MODEL_OPTION_LIMIT:
            st.caption(f"共匹配 {matched_count} 个模型，显示前 {len(visible_options)} 个；输入关键词可缩小范围。")
        if visible_options:
            if st.session_state.get("test_run_model_select") not in visible_options:
                st.session_state["test_run_model_select"] = visible_options[0]
            st.selectbox("模型", visible_options, key="test_run_model_select")
        else:
            st.caption("没有符合当前关键词的模型。")
        if st.button("添加到对比列表", key="test_run_add_model", type="secondary", disabled=not visible_options):
            selected = str(st.session_state.get("test_run_model_select") or "").strip()
            current = _dedupe(list(st.session_state.get("test_run_model_dialog_selected", [])))
            if selected and selected in visible_options and selected not in current:
                current.append(selected)
            st.session_state["test_run_model_dialog_selected"] = current
            st.rerun()
    else:
        st.caption("模型列表暂未获取，请检查模型服务配置。")
    chosen_models = _dedupe([
        model for model in st.session_state.get("test_run_model_dialog_selected", [])
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
    st.caption(f"已选模型：{len(chosen_models)} 个")
    with st.container(key="test_run_model_dialog_actions"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("确认选择", key="test_run_model_dialog_confirm", type="primary", disabled=not chosen_models, use_container_width=True):
                st.session_state["test_run_provider"] = provider_name
                st.session_state["test_run_selected_models"] = chosen_models
                st.session_state[EVAL_TEMPERATURE_KEY] = normalize_eval_temperature(
                    st.session_state.get(MODEL_DIALOG_TEMPERATURE_KEY)
                )
                _clear_dialog_state()
                st.rerun()
        with col2:
            if st.button("取消", key="test_run_model_dialog_cancel", type="tertiary", use_container_width=True):
                _clear_dialog_state()
                st.rerun()


def _provider_balance_text(provider: Any) -> str | None:
    try:
        balance = provider.get_balance()
    except Exception:
        balance = None
    if balance is None:
        return None
    if isinstance(balance, (int, float)):
        return f"¥{balance:.2f}"
    return str(balance).strip() or None


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


def _status_row(label: str, value: str, *, warn: bool = False) -> tuple[str, ...]:
    return (label, value, "warning") if warn else (label, value)


def _model_short_name(model_id: str) -> str:
    return md.display_model_name(model_id)


def _safe_key(value: object) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))
    return text[:80] or "item"


def build_evaluation_config_from_checkpoint(
    run_id: str,
    base: Any,
    *,
    store: Any | None = None,
    dataset_version: str | None = None,
    dimensions: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
) -> EvaluationConfig:
    """Rebuild a resumable config exclusively from a durable checkpoint.

    The current task and Gold records supply content, while the persisted queue
    and run metadata remain authoritative for scope, models, and parameters.
    UI form selections are intentionally not accepted by this boundary.
    """

    checkpoint_run_id = _required_checkpoint_text(run_id)
    result_store = store if store is not None else get_result_store()
    run_rows = result_store.list_rows("live_evaluation_runs", run_id=checkpoint_run_id)
    queue_rows = result_store.list_rows("live_run_queue", run_id=checkpoint_run_id)
    if len(run_rows) != 1 or not queue_rows:
        raise WorkflowCheckpointError("evaluation checkpoint is missing")

    saved = dict(run_rows[0])
    if _required_checkpoint_text(saved.get("run_id")) != checkpoint_run_id:
        raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
    provider_name = _required_checkpoint_text(saved.get("provider"))
    model_ids = tuple(_required_checkpoint_models(saved.get("model_ids_json")))
    generation_parameters = _required_checkpoint_mapping(
        saved.get("generation_parameters_json"), "generation parameters"
    )
    judge_parameters = _required_checkpoint_mapping(
        saved.get("judge_parameters_json"), "judge parameters"
    )
    if not generation_parameters or not judge_parameters.get("judge_model"):
        raise WorkflowCheckpointError("evaluation checkpoint is missing parameters")

    current_dataset_version = (
        str(dataset_version).strip()
        if dataset_version is not None
        else next((str(value).strip() for value in ds.list_dataset_versions() if str(value).strip()), "")
    )
    if not current_dataset_version:
        raise WorkflowCheckpointError("evaluation checkpoint is missing dataset version")

    tasks_by_case = _tasks_by_case(base)
    gold_source = _base_value(base, "gold_answer_map")
    if not isinstance(gold_source, Mapping):
        raise WorkflowCheckpointError("evaluation checkpoint has no current Gold records")

    ordered_rows = sorted(
        enumerate(queue_rows),
        key=lambda entry: (_queue_order(entry[1], entry[0]), entry[0]),
    )
    pairs: set[tuple[str, str]] = set()
    queue_items: list[dict[str, Any]] = []
    gold_map: dict[str, Mapping[str, Any]] = {}
    for _index, raw_row in ordered_rows:
        row = dict(raw_row)
        if _required_checkpoint_text(row.get("run_id")) != checkpoint_run_id:
            raise WorkflowCheckpointError("evaluation checkpoint is inconsistent")
        case_id = _required_checkpoint_text(row.get("case_id"))
        model_id = _required_checkpoint_text(row.get("model_id"))
        pair = (case_id, model_id)
        if pair in pairs:
            raise WorkflowCheckpointError("evaluation checkpoint contains a duplicate queue pair")
        pairs.add(pair)
        if model_id not in model_ids:
            raise WorkflowCheckpointError("evaluation checkpoint does not match saved models")
        task = tasks_by_case.get(case_id)
        if task is None:
            raise WorkflowCheckpointError(f"evaluation checkpoint current sample is missing: {case_id}")
        gold = gold_source.get(case_id)
        if not isinstance(gold, Mapping) or not gold:
            raise WorkflowCheckpointError(f"evaluation checkpoint current Gold is missing: {case_id}")
        queue_items.append({"case_id": case_id, "model_id": model_id, "task": dict(task)})
        gold_map.setdefault(case_id, dict(gold))

    if {model_id for _case_id, model_id in pairs} != set(model_ids):
        raise WorkflowCheckpointError("evaluation checkpoint does not match saved models")

    prompt_payload = tuple(
        {
            "case_id": item["case_id"],
            "messages": er.build_messages(item["task"]),
        }
        for item in queue_items
    )
    current_dimensions = dimensions if dimensions is not None else ds.get_rubric_dimensions()
    dimension_rows = tuple(
        dict(row) for row in current_dimensions or [] if isinstance(row, Mapping)
    )
    if not dimension_rows:
        raise WorkflowCheckpointError(
            "evaluation checkpoint has no current scoring dimensions"
        )
    current = build_run_metadata(
        run_id=checkpoint_run_id,
        provider=provider_name,
        model_ids=model_ids,
        queue_items=queue_items,
        generation_parameters=generation_parameters,
        judge_parameters=judge_parameters,
        dataset_version=current_dataset_version,
        prompt_payload=prompt_payload,
        gold_map=gold_map,
        dimensions=dimension_rows,
    )
    if any(
        str(saved.get(field) or "") != str(current.get(field) or "")
        for field in ("dataset_version", "dataset_hash", "prompt_hash")
    ):
        raise WorkflowCheckpointError("evaluation checkpoint does not match current samples or prompts")
    for field, default in (
        ("model_ids_json", []),
        ("generation_parameters_json", {}),
        ("judge_parameters_json", {}),
    ):
        if _canonical_checkpoint_json(saved.get(field), default) != _canonical_checkpoint_json(
            current.get(field), default
        ):
            raise WorkflowCheckpointError("evaluation checkpoint does not match current configuration")

    return EvaluationConfig(
        provider_name=provider_name,
        model_ids=model_ids,
        queue_items=tuple(queue_items),
        generation_parameters=generation_parameters,
        judge_parameters=judge_parameters,
        dataset_version=current_dataset_version,
        prompt_payload=prompt_payload,
        gold_map=gold_map,
        dimensions=dimension_rows,
    )


def _base_value(base: Any, name: str) -> Any:
    return base.get(name) if isinstance(base, Mapping) else getattr(base, name, None)


def _tasks_by_case(base: Any) -> dict[str, Mapping[str, Any]]:
    source = _base_value(base, "tasks")
    if source is None:
        raise WorkflowCheckpointError("evaluation checkpoint has no current samples")
    if hasattr(source, "to_dict"):
        records = source.to_dict("records")
    elif isinstance(source, (list, tuple)):
        records = list(source)
    else:
        raise WorkflowCheckpointError("evaluation checkpoint has invalid current samples")
    by_case: dict[str, Mapping[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise WorkflowCheckpointError("evaluation checkpoint has invalid current samples")
        case_id = str(raw.get("case_id") or "").strip()
        if not case_id:
            continue
        if case_id in by_case:
            raise WorkflowCheckpointError("evaluation checkpoint has duplicate current samples")
        by_case[case_id] = dict(raw)
    return by_case


def _required_checkpoint_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkflowCheckpointError("evaluation checkpoint is incomplete")
    return text


def _parse_checkpoint_json(value: Any, label: str) -> Any:
    if value in (None, ""):
        raise WorkflowCheckpointError(f"evaluation checkpoint is missing {label}")
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise WorkflowCheckpointError(f"evaluation checkpoint has invalid {label}") from exc


def _required_checkpoint_models(value: Any) -> list[str]:
    parsed = _parse_checkpoint_json(value, "models")
    if not isinstance(parsed, list):
        raise WorkflowCheckpointError("evaluation checkpoint has invalid models")
    models = [str(model).strip() for model in parsed]
    if not models or any(not model for model in models):
        raise WorkflowCheckpointError("evaluation checkpoint is missing models")
    if len(models) != len(set(models)):
        raise WorkflowCheckpointError("evaluation checkpoint has duplicate models")
    return models


def _required_checkpoint_mapping(value: Any, label: str) -> dict[str, Any]:
    parsed = _parse_checkpoint_json(value, label)
    if not isinstance(parsed, Mapping):
        raise WorkflowCheckpointError(f"evaluation checkpoint has invalid {label}")
    return dict(parsed)


def _canonical_checkpoint_json(value: Any, default: Any) -> str:
    parsed = default if value in (None, "") else _parse_checkpoint_json(value, "metadata")
    try:
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise WorkflowCheckpointError("evaluation checkpoint has invalid metadata") from exc


def _queue_order(row: Mapping[str, Any], fallback: int) -> int:
    try:
        return int(row.get("id"))
    except (TypeError, ValueError):
        return fallback


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    return [value for value in values if str(value) not in seen and not seen.add(str(value))]


def _dash(value: object) -> str:
    return str(value or "").strip() or "—"
