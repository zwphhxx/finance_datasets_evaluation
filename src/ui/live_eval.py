"""真实多模型评测对比 + LLM-as-judge 评分页（PR-34 / PR-35）。

从数据集中选择任务样本与一个或多个硅基流动模型，生成真实（或 mock）模型回答并并排对比；
可选地由「裁判模型」对照 Gold Answer 与 Rubric 产出**机器建议分**，建议分需人工复核确认后归档。

页面只通过 registry/provider 接口与 app.services.eval_runner / scorer 编排逻辑工作，本文件不含
任何模型调用细节、不构造评测 / 评分 prompt（prompt 在服务层构造）。被评测模型绝不会看到 Gold
Answer；裁判模型可见 Gold（评分必需）。模型调用失败时以结构化错误展示，页面不崩溃，也不输出 API Key。
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app.models import siliconflow as sf
from app.models.registry import available_providers, get_provider, get_text_provider
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import scorer as sc
from src.ui.components import (
    render_empty_state,
    render_html,
    render_info_panel,
    render_page_shell,
    render_section_title,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import TASK_TYPE_LABELS, display_label, summarize_text

# 页面固定显示的评测边界提示（不可省略）。
BOUNDARY_NOTE = (
    "模型回答仅用于评测，不构成金融、法律或投资建议；后续评分需结合 Gold Answer 与人工复核。"
)

_RUN_SCOPE_SINGLE = "单题"
_RUN_SCOPE_BATCH = "批量（多题）"

# 运行状态 → 徽标配色。mock 用中性色而非红色，避免误读为失败。
_STATUS_BADGE = {
    "success": ("成功", "success"),
    "mock": ("mock", "neutral"),
    "failed": ("失败", "danger"),
}


def render_live_eval_page(data_bundle: dict) -> None:
    render_page_shell(get_page_config("live_eval"))
    render_info_panel("评测边界", BOUNDARY_NOTE)

    data = data_bundle["data"]
    tasks_df = data.tasks
    if tasks_df is None or tasks_df.empty:
        render_empty_state("当前数据集没有可用任务样本。")
        return

    task_records = tasks_df.to_dict("records")

    selected_provider = _render_config_controls()
    model_ids = _render_model_selector(selected_provider)
    selected_tasks = _render_task_selector(task_records)
    temperature, max_tokens = _render_parameters()

    _render_run_button(selected_provider, model_ids, selected_tasks, temperature, max_tokens)
    _render_results()
    _render_scoring(data_bundle, selected_provider, task_records)


# --------------------------------------------------------------------------- #
# 选择区
# --------------------------------------------------------------------------- #
def _render_config_controls() -> str:
    render_section_title("数据集与模型来源", "选择数据集版本与模型供应商；未配置 API Key 时自动使用 mock。")

    versions = ds.list_dataset_versions()
    col1, col2 = st.columns(2)
    with col1:
        if versions:
            st.selectbox("数据集版本", versions, key="live_eval_version")
        else:
            st.caption("数据集版本：当前活跃样本。")

    providers = available_providers()
    default_index = providers.index("siliconflow") if (sf.is_configured() and "siliconflow" in providers) else 0
    with col2:
        provider_name = st.selectbox("Provider", providers, index=default_index, key="live_eval_provider")

    effective = get_text_provider(prefer=provider_name)
    if effective.name == "mock":
        if provider_name != "mock":
            st.warning("未配置 SiliconFlow API Key，已切换为 mock 模式：回答为模拟生成，不代表真实模型结果。")
        else:
            st.info("当前为 mock 模式：回答为模拟生成，不代表真实模型结果。")
    else:
        st.caption(f"当前为真实调用模式（{effective.name}）。请确认已在 .env 或 secrets 中配置 API Key。")
    return provider_name


def _render_model_selector(provider_name: str) -> list[str]:
    render_section_title("模型选择（可多选对比）", "模型列表从 Provider 实时获取，不硬编码；也可手动追加模型 ID。")
    provider = get_text_provider(prefer=provider_name)
    cache_key = f"live_eval_models::{provider.name}"

    if st.button("加载 / 刷新模型列表", key="live_eval_load_models"):
        st.session_state[cache_key] = provider.list_models()

    result = st.session_state.get(cache_key)
    model_options: list[str] = []
    if result is not None:
        if result.ok and result.models:
            model_options = [m.id for m in result.models]
            st.caption(f"已获取 {len(model_options)} 个文本对话模型（type=text、sub_type=chat）。")
        else:
            st.warning(result.error_message or "模型列表获取失败，可在下方手动追加模型 ID。")

    selected_from_list: list[str] = []
    if model_options:
        selected_from_list = st.multiselect("模型（可多选）", model_options, key="live_eval_models_select")

    manual_raw = st.text_input(
        "手动追加模型 ID（多个用逗号分隔）",
        key="live_eval_models_manual",
        placeholder="例如 THUDM/GLM-4-9B-0414, Qwen/Qwen2.5-7B-Instruct",
    )
    manual_ids = [item.strip() for item in manual_raw.split(",") if item.strip()]
    return _dedupe(list(selected_from_list) + manual_ids)


def _render_task_selector(task_records: list[dict]) -> list[dict]:
    render_section_title("任务范围", "支持单题运行或选择多题批量运行。")
    by_case = {str(r.get("case_id")): r for r in task_records}

    def _label(case_id: str) -> str:
        row = by_case.get(case_id, {})
        task_type = display_label(row.get("task_type"), TASK_TYPE_LABELS)
        return f"{case_id} · {task_type} · {summarize_text(row.get('question'), 24)}"

    scope = st.radio("运行范围", [_RUN_SCOPE_SINGLE, _RUN_SCOPE_BATCH], horizontal=True, key="live_eval_scope")
    case_ids = list(by_case.keys())
    if scope == _RUN_SCOPE_SINGLE:
        chosen = st.selectbox("任务", case_ids, format_func=_label, key="live_eval_single_case")
        return [by_case[chosen]] if chosen else []

    chosen_many = st.multiselect("任务（可多选）", case_ids, format_func=_label, key="live_eval_batch_cases")
    return [by_case[c] for c in chosen_many]


def _render_parameters() -> tuple[float, int]:
    render_section_title("生成参数", "控制随机性与最大输出长度，其余参数采用 Provider 默认值。")
    col1, col2 = st.columns(2)
    temperature = col1.slider("temperature", 0.0, 2.0, 0.2, 0.1, key="live_eval_temperature")
    max_tokens = int(col2.number_input("max_tokens", min_value=64, max_value=8192, value=1024, step=64, key="live_eval_max_tokens"))
    return temperature, max_tokens


# --------------------------------------------------------------------------- #
# 运行与结果
# --------------------------------------------------------------------------- #
def _render_run_button(provider_name, model_ids, selected_tasks, temperature, max_tokens) -> None:
    disabled = not model_ids or not selected_tasks
    if st.button("运行评测", type="primary", disabled=disabled, key="live_eval_run"):
        provider = get_text_provider(prefer=provider_name)
        total = len(model_ids) * len(selected_tasks)
        with st.spinner(f"正在运行 {len(model_ids)} 个模型 × {len(selected_tasks)} 道任务（共 {total} 次生成）……"):
            result = er.run_models(
                provider, model_ids, selected_tasks,
                temperature=temperature, max_tokens=max_tokens,
            )
        persisted = er.persist_compare_result(result)
        st.session_state["live_eval_last_run"] = result
        st.session_state["live_eval_persisted"] = persisted
        # 新一轮运行后清空旧评分，避免对应错乱。
        st.session_state.pop("live_eval_last_score", None)

    if disabled:
        st.caption("请先选择至少一个模型与至少一道任务，再运行评测。")


def _render_results() -> None:
    result = st.session_state.get("live_eval_last_run")
    if result is None:
        return

    render_section_title(
        "运行结果",
        f"run_id：{result.run_id} · 模式：{result.mode} · 模型 {len(result.model_ids)} 个 · "
        f"成功 {result.success_count}/{len(result.outcomes)}",
    )
    if er.is_mock_result(result):
        st.info("本次为 mock 模式运行，回答为模拟生成，不代表真实模型结果。")
    if st.session_state.get("live_eval_persisted"):
        st.caption("结果已写入 SQLite（live_run_responses），可供后续评分与对比复用。")
    else:
        st.caption("结果暂存于当前页面会话；初始化 SQLite 数据层后可持久化留存。")

    _render_results_table(result)
    _render_answer_viewer(result)


def _render_results_table(result) -> None:
    header = "".join(
        f"<th>{escape(name)}</th>"
        for name in ["模型", "任务编号", "任务类型", "状态", "耗时(ms)", "回答长度", "是否成功"]
    )
    body = ""
    for outcome in result.outcomes:
        label, level = _STATUS_BADGE.get(outcome.run_status, (outcome.run_status, "neutral"))
        latency = "—" if outcome.latency_ms is None else str(outcome.latency_ms)
        success_mark = "✓" if outcome.success else "✗"
        body += (
            f'<tr><td class="check-key">{escape(outcome.model_id)}</td>'
            f"<td>{escape(outcome.case_id)}</td>"
            f"<td>{escape(display_label(outcome.task_type, TASK_TYPE_LABELS))}</td>"
            f'<td><span class="status-badge status-{level}">{escape(label)}</span></td>'
            f'<td class="check-count">{escape(latency)}</td>'
            f'<td class="check-count">{escape(str(outcome.answer_length))}</td>'
            f"<td>{success_mark}</td></tr>"
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )


def _render_answer_viewer(result) -> None:
    render_section_title("查看模型回答", "按「任务 · 模型」查看完整回答与调用元信息。")
    outcomes = list(result.outcomes)
    if not outcomes:
        return

    options = list(range(len(outcomes)))

    def _fmt(idx: int) -> str:
        o = outcomes[idx]
        return f"{o.case_id} · {o.model_id}"

    selected = st.selectbox("任务 · 模型", options, format_func=_fmt, key="live_eval_view_outcome")
    outcome = outcomes[selected]

    label, level = _STATUS_BADGE.get(outcome.run_status, (outcome.run_status, "neutral"))
    meta = [
        ("模型", outcome.model_id),
        ("状态", label),
        ("耗时", "—" if outcome.latency_ms is None else f"{outcome.latency_ms} ms"),
        ("Token（输入/输出/合计）", f"{_n(outcome.input_tokens)}/{_n(outcome.output_tokens)}/{_n(outcome.total_tokens)}"),
    ]
    if outcome.trace_id:
        meta.append(("trace_id", outcome.trace_id))
    meta_html = "".join(
        f'<div class="fact-field"><div class="fact-label">{escape(k)}</div>'
        f'<div class="fact-value">{escape(str(v))}</div></div>'
        for k, v in meta
    )
    render_html(f'<div class="fact-grid">{meta_html}</div>')

    if outcome.success and outcome.answer_text:
        render_html(f'<div class="fde-card"><div class="answer-body">{escape(outcome.answer_text)}</div></div>')
    else:
        st.error(outcome.error_message or "本题未获得有效回答。")


# --------------------------------------------------------------------------- #
# 评分区（LLM-as-judge + 人工复核）
# --------------------------------------------------------------------------- #
def _render_scoring(data_bundle: dict, provider_name: str, task_records: list[dict]) -> None:
    result = st.session_state.get("live_eval_last_run")
    if result is None or result.success_count == 0:
        return

    render_section_title(
        "自动评分（裁判模型）",
        "由裁判模型对照 Gold Answer 与 Rubric 打出建议分；分数为机器建议，需人工复核确认后归档。",
    )
    st.caption("裁判模型可见 Gold Answer（评分必需），被评测模型全程不可见 Gold；并列对比不代表最终结论。")

    judge_model = st.text_input(
        "裁判模型 ID（留空则各自用被评测模型）",
        key="live_eval_judge_model",
        placeholder="例如 THUDM/GLM-4-9B-0414",
    ).strip()

    if st.button("运行自动评分（裁判模型）", key="live_eval_score_run"):
        provider = get_text_provider(prefer=provider_name)
        data = data_bundle["data"]
        gold_map = getattr(data, "gold_answer_map", {}) or {}
        tasks_by_case = {str(r.get("case_id")): r for r in task_records}
        dimensions = ds.get_rubric_dimensions()
        with st.spinner("裁判模型正在评分……"):
            score_result = sc.score_compare(
                provider, judge_model, result, gold_map, tasks_by_case, dimensions,
            )
        persisted = sc.persist_score_result(score_result)
        st.session_state["live_eval_last_score"] = score_result
        st.session_state["live_eval_score_persisted"] = persisted
        st.session_state["live_eval_score_dims"] = dimensions

    _render_score_results()


def _render_score_results() -> None:
    score_result = st.session_state.get("live_eval_last_score")
    if score_result is None:
        return
    dimensions = st.session_state.get("live_eval_score_dims") or []

    render_section_title(
        "评分结果（建议分 · 待人工复核）",
        f"score_run_id：{score_result.score_run_id} · 模式：{score_result.mode} · "
        f"已评分 {score_result.scored_count}/{len(score_result.outcomes)}",
    )
    if sc.is_mock_score(score_result):
        st.info("本次为 mock 模式：未产生真实评分，各维度留空，仅用于打通链路。")

    _render_score_compare_table(score_result, dimensions)

    if st.session_state.get("live_eval_score_persisted"):
        _render_score_review(score_result, dimensions)
    else:
        st.caption("评分暂存于当前页面会话；初始化 SQLite 数据层后可改分并归档为已复核。")


def _render_score_compare_table(score_result, dimensions) -> None:
    dim_headers = "".join(f"<th>{escape(d['name'])}</th>" for d in dimensions)
    header = (
        "<th>模型</th><th>任务编号</th>" + dim_headers + "<th>总分</th><th>裁判状态</th>"
    )

    # 纯呈现排序：成功的按总分从高到低，mock/失败置后。
    def _sort_key(o):
        return (0 if o.ok else 1, -(o.total_score or 0))

    body = ""
    for o in sorted(score_result.outcomes, key=_sort_key):
        label, level = _STATUS_BADGE.get(o.judge_status, (o.judge_status, "neutral"))
        dim_cells = "".join(
            f'<td class="check-count">{_n(o.scores.get(d["field"]))}</td>' for d in dimensions
        )
        total = "—" if o.total_score is None else str(o.total_score)
        body += (
            f'<tr><td class="check-key">{escape(o.eval_model)}</td>'
            f"<td>{escape(o.case_id)}</td>"
            f"{dim_cells}"
            f'<td class="check-count">{escape(total)}</td>'
            f'<td><span class="status-badge status-{level}">{escape(label)}</span></td></tr>'
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )


def _render_score_review(score_result, dimensions) -> None:
    rows = sc.load_score_rows(score_result.score_run_id)
    reviewable = [r for r in rows if r.get("judge_status") == "success"]
    if not reviewable:
        st.caption("当前无可复核的成功评分（mock / 失败的评分不进入人工复核）。")
        return

    render_section_title("人工复核", "可逐条修订各维度分与复核说明，确认后归档为已复核（review_status=confirmed）。")
    for row in reviewable:
        row_id = int(row["id"])
        status_text = str(row.get("review_status") or "pending")
        title = f"{row.get('eval_model')} · {row.get('case_id')} · 复核：{status_text}"
        with st.expander(title, expanded=False):
            cols = st.columns(len(dimensions))
            edited: dict[str, int] = {}
            for i, dim in enumerate(dimensions):
                field_name = dim["field"]
                full_mark = int(dim.get("full_mark") or 0)
                current = row.get(field_name)
                value = int(current) if current is not None and str(current) != "nan" else 0
                edited[field_name] = cols[i].number_input(
                    dim["name"], min_value=0, max_value=full_mark, value=min(value, full_mark),
                    step=1, key=f"score_edit::{row_id}::{field_name}",
                )
            note = st.text_area(
                "复核说明", value=str(row.get("review_note") or ""), key=f"score_note::{row_id}"
            )
            if st.button("确认并归档（人工复核通过）", key=f"score_confirm::{row_id}"):
                if sc.confirm_score_review(row_id, edited, note):
                    st.success("已归档为已复核（confirmed）。")
                else:
                    st.warning("归档失败：请确认 SQLite 数据层已初始化。")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = (item or "").strip()
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _n(value) -> str:
    return "—" if value is None else str(value)
