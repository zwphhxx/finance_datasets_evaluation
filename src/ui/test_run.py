"""发起测试页面。

Replaces eval_run_page.
- 选择可进入测试的样本与被测模型。
- 裁判模型使用系统默认配置，页面不提供裁判模型输入。
- 被测模型提示词不包含理想回复标准 / Gold Answer。
- 默认仅选择一道样本，降低面试演示时的等待时间。
"""

from __future__ import annotations

from html import escape

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
    render_html,
    render_numbered_section,
    render_text_block,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import TASK_TYPE_LABELS, display_label, summarize_text

BOUNDARY_NOTE = (
    "模型回答仅用于评测，不构成金融、法律或投资建议；评分为裁判模型建议分，需人工复核确认后归档。"
)

MAIN_PROMPT = "选择已入库样本和模型，运行后生成评分草稿；草稿需人工复核后才进入正式结论。"

RUN_BOUNDARY_NOTE = (
    "本页运行受密钥、网络、模型版本与限流影响，结果可能波动。新评分默认进入评分草稿，"
    "不会覆盖正式结论；只有人工复核确认后才会归档。"
)

_STATUS_BADGE = {
    "success": ("成功", "success"),
    "mock": ("模拟回退", "neutral"),
    "failed": ("失败", "danger"),
}

_MODE_LABEL = {"mock": "模拟回退", "live": "真实调用"}
_REVIEW_STATUS_LABEL = {"pending": "待复核", "confirmed": "已复核"}


def render_test_run_page(data_bundle: dict) -> None:
    base = data_bundle["base"]

    config = get_page_config("test_run")
    render_compact_hero(
        eyebrow="FinDueEval",
        title=config.title,
        question=config.question,
    )
    st.info(MAIN_PROMPT)
    with st.expander("运行边界", expanded=False):
        st.write(RUN_BOUNDARY_NOTE)
        st.caption("裁判评分使用系统默认配置；被测模型全程不可见理想回复标准 / Gold Answer。")

    tasks_df = base.tasks
    if tasks_df is None or tasks_df.empty:
        render_empty_state("当前数据集没有可用任务样本。")
        return
    task_records = tasks_df.to_dict("records")

    # Configuration + advanced settings
    provider_name = _render_config_controls()
    _render_advanced_settings(provider_name)
    model_ids = _render_model_selector(provider_name)
    selected_tasks = _render_task_selector(task_records, getattr(base, "gold_answer_map", {}) or {})
    temperature, max_tokens = _render_parameters()
    _render_run_button(provider_name, model_ids, selected_tasks, temperature, max_tokens)

    # 01 测试结果
    render_numbered_section("01", "测试结果", "本次模型回答与调用状态。")
    _render_results()

    # 02 评分草稿
    render_numbered_section("02", "评分草稿", "由裁判模型对照理想回复标准 / Gold Answer 与 Rubric 评分标准给出建议分。")
    _render_scoring(base, provider_name, task_records)
    _render_score_results()


def _render_config_controls() -> str:
    providers = available_providers()
    default_index = providers.index("siliconflow") if (sf.is_configured() and "siliconflow" in providers) else 0
    provider_name = st.selectbox("模型服务", providers, index=default_index, key="test_run_provider")

    effective = get_text_provider(prefer=provider_name)
    if effective.name == "mock":
        if provider_name != "mock":
            st.warning("未配置模型服务密钥，已切换为模拟回退模式：回答为模拟生成。")
        else:
            st.caption("当前为模拟回退模式：回答为模拟生成。")
    else:
        st.caption("当前为真实调用模式。请确认已在本地配置中提供模型服务密钥。")

    return provider_name


def _render_advanced_settings(provider_name: str) -> None:
    with st.expander("高级设置（连通性检查 / 加载模型列表）", expanded=False):
        _render_connectivity_check(provider_name)
        _render_load_model_list_button(provider_name)


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


def _render_model_selector(provider_name: str) -> list[str]:
    provider = get_text_provider(prefer=provider_name)
    cache_key = f"test_run_models::{provider.name}"
    result = st.session_state.get(cache_key)

    selected_from_list: list[str] = []
    if result is not None:
        if result.ok and result.models:
            model_options = [m.id for m in result.models]
            selected_from_list = st.multiselect("模型（可多选）", model_options, key="test_run_models_select")
        else:
            st.warning(result.error_message or "模型列表获取失败，可手动追加模型 ID。")

    manual_raw = st.text_input(
        "手动追加模型 ID（多个用逗号分隔）",
        key="test_run_models_manual",
        placeholder="输入模型 ID，多个用逗号分隔",
    )
    manual_ids = [item.strip() for item in manual_raw.split(",") if item.strip()]
    return _dedupe(list(selected_from_list) + manual_ids)


def _render_task_selector(task_records: list[dict], gold_map: dict) -> list[dict]:
    by_case = {str(r.get("case_id")): r for r in task_records}

    def _label(case_id: str) -> str:
        row = by_case.get(case_id, {})
        task_type = display_label(row.get("task_type"), TASK_TYPE_LABELS)
        return f"{case_id} · {task_type} · {summarize_text(row.get('question'), 24)}"

    dimensions = ds.get_testable_rubric_dimensions()
    eligible = eligible_case_ids(task_records, gold_map, dimensions)

    if not eligible:
        st.warning(
            "当前没有可测样本。可测样本需同时满足：正式题库存在任务题、"
            "Gold Answer 具备完整评判标准、Rubric 评分标准存在，且样本状态为已入库。"
        )
        return []

    default_cases = [str(r.get("case_id")) for r in er.default_task_selection(task_records) if str(r.get("case_id")) in by_case]
    default_cases = [c for c in default_cases if c in eligible]
    if not default_cases and eligible:
        default_cases = eligible[:1]

    chosen = st.multiselect(
        "样本范围（默认仅 1 道已入库样本，可手动多选）",
        eligible,
        default=default_cases,
        format_func=_label,
        key="test_run_cases",
    )
    st.caption(
        "默认只跑 1 道已入库样本以快速看到结果。实际生成次数 = 模型数 × 任务数。"
        "只有正式数据层中状态为「已入库」且评判标准完整的样本可进入测试。"
    )
    return [by_case[c] for c in chosen]


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


def _render_parameters() -> tuple[float, int]:
    col1, col2 = st.columns(2)
    temperature = col1.slider("temperature", 0.0, 2.0, 0.2, 0.1, key="test_run_temperature")
    max_tokens = int(
        col2.number_input("max_tokens", min_value=64, max_value=8192, value=1024, step=64, key="test_run_max_tokens")
    )
    return temperature, max_tokens


def _render_run_button(provider_name, model_ids, selected_tasks, temperature, max_tokens) -> None:
    disabled = not model_ids or not selected_tasks
    if st.button("运行模型回答", type="primary", disabled=disabled, key="test_run_run"):
        provider = get_text_provider(prefer=provider_name)
        total = len(model_ids) * len(selected_tasks)
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
    st.markdown(
        f"本次运行 **成功 {summary.success} / {summary.total}** · "
        f"模型 {len(result.model_ids)} 个 · 运行模式：{_mode_label(result.mode)}"
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
        st.caption("请先运行模型回答，再进行裁判评分。")
        return

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
        f"已评分 {score_result.scored_count}/{len(score_result.outcomes)} · "
        f"运行模式：{_mode_label(score_result.mode)}"
    )
    if sc.is_mock_score(score_result):
        st.caption("本次为模拟回退模式：未产生真实评分，各维度留空。")

    _render_score_compare_table(score_result, dimensions)

    if ds.database_ready():
        _render_score_review(score_result, dimensions)
    else:
        st.caption("评分暂存于当前页面会话；初始化 SQLite 数据层后可改分并归档。")


def _render_score_compare_table(score_result, dimensions) -> None:
    dim_headers = "".join(f"<th>{escape(d['name'])}</th>" for d in dimensions)
    header = (
        "<th>模型</th><th>任务编号</th>" + dim_headers
        + "<th>总分</th><th>裁判状态</th><th>错误码</th><th>错误信息</th>"
    )

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
            f'<td><span class="status-badge status-{level}">{escape(label)}</span></td>'
            f"<td>{escape(_dash(o.error_code))}</td>"
            f"<td>{escape(_short(o.error_message))}</td></tr>"
        )
    table_html = (
        f'<table class="check-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    render_evidence_panel("评分对比表", table_html)


def _render_score_review(score_result, dimensions) -> None:
    rows = sc.load_score_rows(score_result.score_run_id)
    reviewable = [r for r in rows if r.get("judge_status") == "success"]
    if not reviewable:
        st.caption("当前无可复核的成功评分。")
        return

    render_numbered_section("03", "人工复核", "逐条修订各维度分与复核说明，确认后归档。")
    for row in reviewable:
        row_id = int(row["id"])
        status_text = _review_status_label(row.get("review_status"))
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
            if st.button("确认并归档", key=f"score_confirm::{row_id}"):
                if sc.confirm_score_review(row_id, edited, note):
                    st.success("已归档为已复核。")
                    st.rerun()
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


def _mode_label(value) -> str:
    return _MODE_LABEL.get(str(value or "").strip().lower(), str(value or "未知"))


def _status_label(value) -> str:
    label, _ = _STATUS_BADGE.get(str(value or "").strip().lower(), (value or "未知", "neutral"))
    return str(label)


def _review_status_label(value) -> str:
    return _REVIEW_STATUS_LABEL.get(str(value or "pending").strip().lower(), "待复核")


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
