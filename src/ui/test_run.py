"""发起测试页面。

Replaces eval_run_page.
- 选择可进入测试的样本与被测模型。
- 裁判模型使用系统默认配置，页面不提供裁判模型输入。
- 被测模型提示词不包含理想回复标准 / Gold Answer。
- 默认仅选择一道样本，降低面试演示时的等待时间。
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from app.models import siliconflow as sf
from app.models.registry import available_providers, get_text_provider
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import eval_state
from app.services import scorer as sc
from src.ui.components import (
    render_compact_hero,
    render_empty_state,
    render_evidence_panel,
    render_numbered_section,
    render_text_block,
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
ADVANCED_SETTING_ITEMS = [
    "模型服务 provider",
    "连通性检查",
    "加载 / 刷新模型列表",
    "手动追加模型 ID",
    "temperature",
    "max_tokens",
    "trace_id",
    "HTTP 状态码",
    "错误码和原始错误信息",
]

_STATUS_BADGE = {
    "success": ("成功", "success"),
    "mock": ("模拟回退", "neutral"),
    "failed": ("失败", "danger"),
}

_MODE_LABEL = {"mock": "模拟回退", "live": "真实调用"}
_REVIEW_STATUS_LABEL = {"pending": "待人工复核", "confirmed": "已复核"}
_DEFAULT_TEMPERATURE = 0.2
_DEFAULT_MAX_TOKENS = 1024


def get_test_run_steps() -> list[str]:
    """Return the visible execution steps for the test-run page."""
    return TEST_RUN_STEPS[:]


def get_advanced_setting_items() -> list[str]:
    """Return technical controls/details that belong in collapsed advanced areas."""
    return ADVANCED_SETTING_ITEMS[:]


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


def build_score_summary_rows(score_result, dimensions) -> list[dict[str, str]]:
    """Build the score comparison rows with dynamic Rubric dimensions."""
    rows: list[dict[str, str]] = []
    for outcome in sorted(score_result.outcomes, key=lambda o: (0 if o.ok else 1, -(o.total_score or 0))):
        row = {
            "模型": str(outcome.eval_model),
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
    _render_results()

    render_numbered_section("03", TEST_RUN_STEPS[2])
    _render_scoring(base, provider_name, task_records)
    _render_score_results()
    _render_pending_dialogs(sample_options)


def _default_provider_name() -> str:
    providers = available_providers()
    if sf.is_configured() and "siliconflow" in providers:
        return "siliconflow"
    return providers[0] if providers else "mock"


def _current_provider_name() -> str:
    providers = available_providers()
    current = str(st.session_state.get("test_run_provider") or _default_provider_name())
    if current not in providers and providers:
        current = _default_provider_name()
    st.session_state["test_run_provider"] = current
    st.session_state.setdefault("test_run_temperature", _DEFAULT_TEMPERATURE)
    st.session_state.setdefault("test_run_max_tokens", _DEFAULT_MAX_TOKENS)
    return current


def _ensure_default_selected_cases(sample_options: list[dict]) -> None:
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", [])
        if case_id in option_ids
    ]
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
    labels = model_ids[:2]
    suffix = f" 等 {len(model_ids)} 个" if len(model_ids) > 2 else f"（{len(model_ids)} 个）"
    return "；".join(labels) + suffix


def _current_run_mode(provider_name: str) -> str:
    provider = get_text_provider(prefer=provider_name)
    return "mock" if provider.name == "mock" else "live"


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
        ("预计模型回答", f"{run_plan['planned_responses']} 条"),
        ("当前运行模式", _mode_label(mode)),
    ]
    render_evidence_panel("评测配置", _kv_table_html(rows))
    if mode == "mock":
        st.caption("当前为模拟回退模式：回答为模拟生成，不代表真实模型结果。")

    col1, col2, col3 = st.columns([1, 1, 1.2])
    with col1:
        if st.button("选择样本", key="test_run_open_samples", type="secondary", use_container_width=True):
            st.session_state["test_run_dialog"] = "samples"
    with col2:
        if st.button("选择模型", key="test_run_open_models", type="secondary", use_container_width=True):
            _open_model_dialog(provider_name)
    with col3:
        _render_run_button(
            provider_name,
            model_ids,
            selected_tasks,
            float(st.session_state.get("test_run_temperature", _DEFAULT_TEMPERATURE)),
            int(st.session_state.get("test_run_max_tokens", _DEFAULT_MAX_TOKENS)),
            run_plan,
        )
    if not run_plan["can_run"]:
        st.caption("请选择样本和模型后运行。")


def _open_model_dialog(provider_name: str) -> None:
    st.session_state["test_run_dialog"] = "models"
    st.session_state["test_run_provider_dialog"] = provider_name
    st.session_state["test_run_temperature_dialog"] = float(
        st.session_state.get("test_run_temperature", _DEFAULT_TEMPERATURE)
    )
    st.session_state["test_run_max_tokens_dialog"] = int(
        st.session_state.get("test_run_max_tokens", _DEFAULT_MAX_TOKENS)
    )
    st.session_state["test_run_models_manual_dialog"] = ",".join(
        st.session_state.get("test_run_manual_model_ids", [])
    )


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

    rows = [
        {
            "样本编号": item["case_id"],
            "场景": item["scenario"],
            "任务标题": item["title"],
            "难度": item["difficulty"],
        }
        for item in sample_options
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        height=min(320, max(118, 42 + len(rows) * 35)),
        column_config={
            "样本编号": st.column_config.TextColumn("样本编号", width="small"),
            "场景": st.column_config.TextColumn("场景", width="medium"),
            "任务标题": st.column_config.TextColumn("任务标题", width="large"),
            "难度": st.column_config.TextColumn("难度", width="small"),
        },
    )
    by_case = {item["case_id"]: item for item in sample_options}
    option_ids = [item["case_id"] for item in sample_options]
    current = [
        case_id
        for case_id in st.session_state.get("test_run_selected_cases", option_ids[:1])
        if case_id in by_case
    ] or option_ids[:1]
    dialog_cases = [
        case_id
        for case_id in st.session_state.get("test_run_cases_dialog", current)
        if case_id in by_case
    ]
    st.session_state["test_run_cases_dialog"] = dialog_cases or current
    chosen = st.multiselect(
        "可测样本",
        option_ids,
        format_func=lambda case_id: by_case[case_id]["label"],
        key="test_run_cases_dialog",
    )
    st.caption("仅展示已入库且通过完整度校验的样本。被测模型不会看到 Gold Answer 或 Rubric。")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认选择", key="test_run_sample_dialog_confirm", type="secondary", use_container_width=True):
            st.session_state["test_run_selected_cases"] = list(chosen)
            _clear_dialog_state()
            st.rerun()
    with col2:
        if st.button("取消", key="test_run_sample_dialog_cancel", type="tertiary", use_container_width=True):
            _clear_dialog_state()
            st.rerun()


@st.dialog("选择模型", width="large")
def _render_model_selection_dialog() -> None:
    providers = available_providers()
    if not providers:
        render_empty_state("当前没有可用模型服务。")
        return

    current_provider = str(st.session_state.get("test_run_provider_dialog") or _current_provider_name())
    provider_index = providers.index(current_provider) if current_provider in providers else 0
    provider_name = st.selectbox(
        "模型服务 provider",
        providers,
        index=provider_index,
        key="test_run_provider_dialog",
    )
    _render_provider_mode_notice(provider_name)

    provider = get_text_provider(prefer=provider_name)
    cache_key = f"test_run_models::{provider.name}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = provider.list_models()
    result = st.session_state.get(cache_key)

    selected_from_list: list[str] = []
    if result is not None and result.ok and result.models:
        model_options = [m.id for m in result.models]
        current_models = [model for model in st.session_state.get("test_run_selected_models", []) if model in model_options]
        dialog_models = [
            model
            for model in st.session_state.get("test_run_models_select_dialog", current_models)
            if model in model_options
        ]
        st.session_state["test_run_models_select_dialog"] = dialog_models or current_models
        selected_from_list = st.multiselect(
            "模型列表",
            model_options,
            key="test_run_models_select_dialog",
        )
    else:
        st.warning("模型列表暂不可用。可刷新模型列表，或在高级设置中手动追加模型 ID。")

    with st.expander("高级设置", expanded=False):
        _render_connectivity_check(provider_name)
        _render_load_model_list_button(provider_name)
        manual_ids = _render_manual_model_ids(key="test_run_models_manual_dialog")
        temperature, max_tokens = _render_parameters(
            temperature_key="test_run_temperature_dialog",
            max_tokens_key="test_run_max_tokens_dialog",
        )
        st.caption("trace_id、HTTP 状态码、错误码和原始错误信息只在运行明细中展示。")
    manual_ids = _parse_manual_model_ids(st.session_state.get("test_run_models_manual_dialog", ""))
    chosen_models = _dedupe(list(selected_from_list) + manual_ids)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认选择", key="test_run_model_dialog_confirm", type="secondary", use_container_width=True):
            st.session_state["test_run_provider"] = provider_name
            st.session_state["test_run_selected_models"] = chosen_models
            st.session_state["test_run_manual_model_ids"] = manual_ids
            st.session_state["test_run_temperature"] = float(
                st.session_state.get("test_run_temperature_dialog", _DEFAULT_TEMPERATURE)
            )
            st.session_state["test_run_max_tokens"] = int(
                st.session_state.get("test_run_max_tokens_dialog", _DEFAULT_MAX_TOKENS)
            )
            _clear_dialog_state()
            st.rerun()
    with col2:
        if st.button("取消", key="test_run_model_dialog_cancel", type="tertiary", use_container_width=True):
            _clear_dialog_state()
            st.rerun()


def _render_provider_mode_notice(provider_name: str) -> None:
    effective = get_text_provider(prefer=provider_name)
    if effective.name == "mock":
        if provider_name != "mock":
            st.warning("未配置模型服务密钥，已切换为模拟回退模式：回答为模拟生成。")
        else:
            st.caption("当前为模拟回退模式：回答为模拟生成。")
    else:
        st.caption("当前为真实调用模式。请确认已在本地配置中提供模型服务密钥。")


def _render_connectivity_check(provider_name: str) -> None:
    if st.button("连通性检查", key="test_run_connectivity"):
        provider = get_text_provider(prefer=provider_name)
        key_configured = sf.is_configured() if provider_name == "siliconflow" else (provider.name == "mock")
        listing = provider.list_models()
        mode = "模拟回退" if provider.name == "mock" else "真实调用"
        lines = [
            f"服务标识：{provider.name}",
            f"模式：{mode}",
            f"密钥：{'已配置' if key_configured else '未配置'}",
            f"模型列表：{'成功' if listing.ok else '失败'}",
        ]
        if listing.ok and listing.models:
            lines.append(f"可用模型数：{len(listing.models)}")
        if listing.error_code:
            lines.append(f"错误码：{listing.error_code}")
        if listing.error_message:
            lines.append(f"错误信息：{listing.error_message}")
        report = " ｜ ".join(lines)
        if listing.ok:
            st.success(report)
        else:
            st.error(report)


def _render_load_model_list_button(provider_name: str) -> None:
    st.caption("模型列表从服务实时获取；加载后可在下方多选。")
    provider = get_text_provider(prefer=provider_name)
    cache_key = f"test_run_models::{provider.name}"
    if st.button("加载 / 刷新模型列表", key="test_run_load_models"):
        st.session_state[cache_key] = provider.list_models()


def _render_manual_model_ids(key: str = "test_run_models_manual") -> list[str]:
    manual_raw = st.text_input(
        "手动追加模型 ID（多个用逗号分隔）",
        key=key,
        placeholder="输入模型 ID，多个用逗号分隔",
    )
    return _parse_manual_model_ids(manual_raw)


def _parse_manual_model_ids(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


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


def _render_parameters(
    *,
    temperature_key: str = "test_run_temperature",
    max_tokens_key: str = "test_run_max_tokens",
) -> tuple[float, int]:
    col1, col2 = st.columns(2)
    temperature_default = float(st.session_state.get(temperature_key, _DEFAULT_TEMPERATURE))
    max_tokens_default = int(st.session_state.get(max_tokens_key, _DEFAULT_MAX_TOKENS))
    temperature = col1.slider("temperature", 0.0, 2.0, temperature_default, 0.1, key=temperature_key)
    max_tokens = int(
        col2.number_input(
            "max_tokens",
            min_value=64,
            max_value=8192,
            value=max_tokens_default,
            step=64,
            key=max_tokens_key,
        )
    )
    return temperature, max_tokens


def _render_run_button(provider_name, model_ids, selected_tasks, temperature, max_tokens, run_plan) -> None:
    disabled = not run_plan["can_run"]
    if st.button("运行模型回答", type="primary", disabled=disabled, key="test_run_run"):
        provider = get_text_provider(prefer=provider_name)
        total = int(run_plan["planned_responses"])
        st.caption(
            f"本次选择 {run_plan['sample_count']} 个样本、{run_plan['model_count']} 个模型，"
            f"预计生成 {run_plan['planned_responses']} 条模型回答。"
        )
        progress = st.progress(0.0)
        status = st.empty()

        def _on_progress(done: int, total_count: int, model_id: str, case_id: str) -> None:
            ratio = (done / total_count) if total_count else 1.0
            progress.progress(min(1.0, ratio))
            if model_id:
                status.caption(f"已完成 {done}/{total_count} · 正在生成：模型 {model_id} · 任务 {case_id}")
            else:
                status.caption(f"已完成 {done}/{total_count} · 正在汇总结果……")

        result = er.run_models(
            provider, model_ids, selected_tasks,
            temperature=temperature, max_tokens=max_tokens,
            progress_callback=_on_progress,
        )
        progress.empty()
        status.empty()
        persisted = er.persist_compare_result(result)
        eval_state.set_last_run(result)
        st.session_state["test_run_persisted"] = persisted
        st.rerun()

    if disabled:
        st.caption("请先选择至少一个模型与至少一道任务，再运行评测。")


def _render_results() -> None:
    result = eval_state.get_last_run()
    if result is None:
        render_empty_state("尚未运行模型回答。配置模型与任务后点击「运行模型回答」。")
        return

    summary = er.summarize_outcomes(result.outcomes)
    failed = summary.total - summary.success
    st.markdown(
        f"本次运行：样本 {len({o.case_id for o in result.outcomes})} 个 · "
        f"模型 {len(result.model_ids)} 个 · 成功 {summary.success} 条 · 失败 {failed} 条 · "
        f"运行模式：{_mode_label(result.mode)}"
    )
    if summary.total and summary.success == 0:
        st.warning("本次运行没有任何成功回答；请查看明细中的错误码与错误信息，或先做连通性检查。")
    if er.is_mock_result(result):
        st.caption("本次为模拟回退模式运行，回答为模拟生成。")

    with st.expander("查看回答", expanded=False):
        _render_answer_viewer(result)

    with st.expander("查看运行明细", expanded=False):
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


def _render_answer_viewer(result) -> None:
    outcomes = list(result.outcomes)
    if not outcomes:
        st.caption("暂无回答可查看。")
        return

    options = list(range(len(outcomes)))

    def _fmt(idx: int) -> str:
        o = outcomes[idx]
        return f"{o.case_id} · {o.model_id}"

    selected = st.selectbox("任务 · 模型", options, format_func=_fmt, key="test_run_view_outcome")
    outcome = outcomes[selected]

    st.markdown(
        f"状态：{_status_label(outcome.run_status)} · 耗时："
        f"{'—' if outcome.latency_ms is None else f'{outcome.latency_ms} ms'} · "
        f"Token：{_n(outcome.input_tokens)}/{_n(outcome.output_tokens)}/{_n(outcome.total_tokens)}"
    )
    if outcome.trace_id:
        st.caption(f"trace_id：{outcome.trace_id}")

    if outcome.success and outcome.answer_text:
        render_text_block("模型回答", outcome.answer_text)
    else:
        st.error(outcome.error_message or "本题未获得有效回答。")


def _render_scoring(base, provider_name: str, task_records: list[dict]) -> None:
    result = eval_state.get_last_run()
    if result is None:
        st.caption("请先运行模型回答，再生成评分草稿。")
        return

    st.caption("评分草稿需人工复核后才进入正式结论；被测模型未看到 Gold Answer 或 Rubric。")
    no_success = result.success_count == 0
    if no_success:
        st.warning("本次运行没有成功回答，无法评分。")

    if st.button(
        "生成评分草稿", type="primary", disabled=no_success, key="test_run_score_run"
    ):
        provider = get_text_provider(prefer=provider_name)
        gold_map = getattr(base, "gold_answer_map", {}) or {}
        tasks_by_case = {str(r.get("case_id")): r for r in task_records}
        dimensions = ds.get_rubric_dimensions()
        with st.spinner("裁判模型正在评分……"):
            score_result = sc.score_compare(
                provider, result, gold_map, tasks_by_case, dimensions,
            )
        sc.persist_score_result(score_result)
        eval_state.set_last_score(score_result)
        st.session_state["test_run_score_dims"] = dimensions
        st.rerun()


def _render_score_results() -> None:
    score_result = eval_state.get_last_score()
    if score_result is None:
        return
    dimensions = st.session_state.get("test_run_score_dims") or ds.get_rubric_dimensions()

    st.markdown(
        f"评分草稿已生成：成功 {score_result.scored_count}/{len(score_result.outcomes)} · "
        f"裁判模式：{_mode_label(score_result.mode)}"
    )
    st.info("评分草稿已生成，需在评测复核页确认或修订后才会进入正式结论。")
    if sc.is_mock_score(score_result):
        st.caption("本次为模拟回退模式：未产生真实评分，各维度留空。")

    with st.expander("评分对比表", expanded=False):
        _render_score_compare_table(score_result, dimensions)

    if ds.database_ready():
        if st.button("进入评测复核", key="test_run_to_review", type="secondary"):
            st.session_state.current_page = "review"
            st.rerun()
    else:
        st.caption("SQLite 数据层未初始化，评分草稿仅在当前会话展示，暂不能进入复核页归档。")


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
        outcome = outcome_by_key.get((row["模型"], row["样本"]))
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


def _review_status_label(value) -> str:
    return _REVIEW_STATUS_LABEL.get(str(value or "pending").strip().lower(), "待复核")


def _score_status_label(outcome) -> str:
    if getattr(outcome, "ok", False):
        return _review_status_label(getattr(outcome, "review_status", "pending"))
    return _status_label(getattr(outcome, "judge_status", ""))


def _score_status_level(outcome) -> str:
    if getattr(outcome, "ok", False):
        return "success" if str(getattr(outcome, "review_status", "")).lower() == "confirmed" else "warning"
    _, level = _STATUS_BADGE.get(str(getattr(outcome, "judge_status", "")).strip().lower(), ("未知", "neutral"))
    return level


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
