"""发起真实评测页面（从 overview 中拆出的独立页面）。

把原「真实模型评测」控制台从 overview 顶部搬到独立页，按向导式流程组织：
选 Provider / 模型（可多选）/ 任务 → 运行真实（或 mock）生成 → 裁判对照 Gold + Rubric 打建议分 →
评分确认。运行结果经 data_resolver 组装后注入各分析页。

边界：被评测模型只看到任务白名单字段，绝不发送 Gold；裁判可见 Gold（评分必需，链路独立）。
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
    render_action_cards,
    render_compact_hero,
    render_empty_state,
    render_evidence_panel,
    render_html,
    render_info_panel,
    render_numbered_section,
    render_section_title,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import TASK_TYPE_LABELS, display_label, summarize_text

BOUNDARY_NOTE = (
    "模型回答仅用于评测，不构成金融、法律或投资建议；评分为裁判模型建议分，需人工确认后才纳入正式结论。"
)

REPRODUCIBILITY_NOTE = (
    "本页是面试官可选的现场可复现实验，不是项目主线。这里的“本次现场运行”受 API Key、网络、"
    "模型版本与限流影响，结果可能波动；它默认进入草稿（待复核），不会覆盖各分析页默认展示的"
    "“离线样本评价”。只有经人工复核确认后，现场结果才计入正式评测结论。"
    "（离线样本评价 vs 本次现场运行）"
)

_STATUS_BADGE = {
    "success": ("成功", "success"),
    "mock": ("mock", "neutral"),
    "failed": ("失败", "danger"),
}


def _set_page(page_key: str) -> None:
    st.session_state.current_page = page_key


def render_eval_run_page(data_bundle: dict) -> None:
    base = data_bundle["base"]

    config = get_page_config("eval_run")
    render_compact_hero(
        eyebrow="FinDueEval",
        title=config.title,
        question=config.question,
    )
    st.caption(REPRODUCIBILITY_NOTE)

    tasks_df = base.tasks
    if tasks_df is None or tasks_df.empty:
        render_empty_state("当前数据集没有可用任务样本。")
        return
    task_records = tasks_df.to_dict("records")

    # Light experiment flow: 4 steps
    _render_step_rail()

    has_run = eval_state.has_run()

    # Step 01 选择样本
    render_numbered_section("Step 01", "选择样本", "选择任务与模型，配置生成参数。")
    with st.expander("展开配置", expanded=not has_run):
        provider_name = _render_config_controls()
        model_ids = _render_model_selector(provider_name)
        selected_tasks = _render_task_selector(task_records, getattr(base, "gold_answer_map", {}) or {})
        temperature, max_tokens = _render_parameters()
        _render_run_button(provider_name, model_ids, selected_tasks, temperature, max_tokens)

    # Step 02 调用模型
    render_numbered_section("Step 02", "调用模型", "查看本次模型调用状态、回答与元信息。")
    _render_results()

    # Step 03 查看回答
    render_numbered_section("Step 03", "查看回答", "按任务与模型查看完整回答与调用元信息。")
    _render_answer_viewer_from_results()

    # Step 04 进入草稿评测
    render_numbered_section("Step 04", "进入草稿评测", "由裁判模型对照 Gold Answer 与 Rubric 打出建议分。")
    with st.expander("展开评分", expanded=False):
        _render_scoring(base, provider_name, task_records)

    _render_score_results()
    _render_completion_cta()


def _render_step_rail() -> None:
    steps = ["选择样本", "调用模型", "查看回答", "草稿评测"]
    current = 0
    if eval_state.has_run():
        current = 1
    if eval_state.get_last_score() is not None:
        current = 3
    html = '<div class="loop-rail" style="border:none;background:transparent;box-shadow:none;">'
    for idx, label in enumerate(steps, start=1):
        muted = "opacity:0.4;" if idx - 1 > current else ""
        html += (
            f'<div class="loop-step" style="{muted}">'
            f'<div class="loop-step-index">步骤 {idx:02d}</div>'
            f'<div class="loop-step-label">{escape(label)}</div></div>'
        )
    html += "</div>"
    render_html(html)


def _render_config_controls() -> str:
    providers = available_providers()
    default_index = providers.index("siliconflow") if (sf.is_configured() and "siliconflow" in providers) else 0
    provider_name = st.selectbox("Provider", providers, index=default_index, key="live_eval_provider")

    effective = get_text_provider(prefer=provider_name)
    if effective.name == "mock":
        if provider_name != "mock":
            st.warning("未配置 SiliconFlow API Key，已切换为 mock 模式：回答为模拟生成，不代表真实模型结果。")
        else:
            st.info("当前为 mock 模式：回答为模拟生成，不代表真实模型结果。")
    else:
        st.caption(f"当前为真实调用模式（{effective.name}）。请确认已在 .env 或 secrets 中配置 API Key。")

    _render_connectivity_check(provider_name)
    return provider_name


def _render_connectivity_check(provider_name: str) -> None:
    if st.button("连通性检查", key="live_eval_connectivity"):
        provider = get_text_provider(prefer=provider_name)
        key_configured = sf.is_configured() if provider_name == "siliconflow" else (provider.name == "mock")
        listing = provider.list_models()
        mode = "mock" if provider.name == "mock" else "live"
        lines = [
            f"Provider：{provider.name}",
            f"模式：{mode}",
            f"API Key：{'已配置' if key_configured else '未配置'}",
            f"list_models：{'成功' if listing.ok else '失败'}",
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
        st.caption("连通性检查仅核对配置与可达性，不回显 API Key。")


def _render_model_selector(provider_name: str) -> list[str]:
    st.caption("模型列表从 Provider 实时获取，不硬编码；也可手动追加模型 ID。")
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


def _render_task_selector(task_records: list[dict], gold_map: dict) -> list[dict]:
    by_case = {str(r.get("case_id")): r for r in task_records}

    def _label(case_id: str) -> str:
        row = by_case.get(case_id, {})
        task_type = display_label(row.get("task_type"), TASK_TYPE_LABELS)
        return f"{case_id} · {task_type} · {summarize_text(row.get('question'), 24)}"

    # Only allow formally testable samples into testing.
    dimensions = ds.get_testable_rubric_dimensions()
    eligible = []
    for case_id, row in by_case.items():
        gold = gold_map.get(case_id) or {}
        if ds.can_enter_formal_testing(row, gold, dimensions):
            eligible.append(case_id)

    if not eligible:
        st.warning(
            "当前没有可测样本。可测样本需同时满足：正式题库存在任务题、"
            "Gold Answer 具备完整评判标准、Rubric 评分标准存在，且样本状态为已入库。"
        )
        return []

    default_cases = [str(r.get("case_id")) for r in er.default_task_selection(task_records) if str(r.get("case_id")) in by_case]
    # Filter default to eligible
    default_cases = [c for c in default_cases if c in eligible]
    if not default_cases and eligible:
        default_cases = eligible[:1]

    chosen = st.multiselect(
        "任务范围（默认仅 1 道活跃任务，可手动多选；仅显示评判标准完整的样本）",
        eligible,
        default=default_cases,
        format_func=_label,
        key="live_eval_cases",
    )
    st.caption(
        "默认只跑 1 道活跃任务以快速看到结果、避免长时间无反馈；如需更多请手动多选。"
        "注意：实际生成次数 = 模型数 × 任务数，选得越多耗时越长。"
        "仅评判标准完整（具备 Gold Answer、必须覆盖点、不可接受错误）的样本可进入测试。"
    )
    return [by_case[c] for c in chosen]


def _render_parameters() -> tuple[float, int]:
    col1, col2 = st.columns(2)
    temperature = col1.slider("temperature", 0.0, 2.0, 0.2, 0.1, key="live_eval_temperature")
    max_tokens = int(
        col2.number_input("max_tokens", min_value=64, max_value=8192, value=1024, step=64, key="live_eval_max_tokens")
    )
    return temperature, max_tokens


def _render_run_button(provider_name, model_ids, selected_tasks, temperature, max_tokens) -> None:
    disabled = not model_ids or not selected_tasks
    if st.button("运行评测", type="primary", disabled=disabled, key="live_eval_run"):
        provider = get_text_provider(prefer=provider_name)
        total = len(model_ids) * len(selected_tasks)
        progress = st.progress(0.0)
        status = st.empty()

        def _on_progress(done: int, total_count: int, model_id: str, case_id: str) -> None:
            ratio = (done / total_count) if total_count else 1.0
            progress.progress(min(1.0, ratio))
            if model_id:
                status.caption(
                    f"已完成 {done}/{total_count} · 正在生成：模型 {model_id} · 任务 {case_id}"
                )
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
        st.session_state["live_eval_persisted"] = persisted
        st.rerun()

    if disabled:
        st.caption("请先选择至少一个模型与至少一道任务，再运行评测。")


def _render_results() -> None:
    result = eval_state.get_last_run()
    if result is None:
        return

    render_section_title(
        "本次运行",
        f"run_id：{result.run_id} · 模式：{result.mode} · 模型 {len(result.model_ids)} 个 · "
        f"成功 {result.success_count}/{len(result.outcomes)}",
    )
    _render_run_summary(result)
    if er.is_mock_result(result):
        st.info("本次为 mock 模式运行，回答为模拟生成，不代表真实模型结果。")
    persisted = st.session_state.get("live_eval_persisted")
    if persisted:
        st.caption("结果已写入 SQLite（live_run_responses），并驱动各分析页展示真实回答。")
    else:
        st.caption("结果暂存于当前页面会话（未落库 / SQLite 未初始化），仍可驱动各分析页展示。")

    with st.expander("查看运行明细（回答与调用元信息）", expanded=result.success_count == 0):
        _render_results_table(result)


def _render_run_summary(result) -> None:
    summary = er.summarize_outcomes(result.outcomes)
    cards = [
        ("成功", summary.success, "success"),
        ("空回答", summary.empty_response, "warning" if summary.empty_response else "neutral"),
        ("超时", summary.timeout, "danger" if summary.timeout else "neutral"),
        ("鉴权/权限失败", summary.auth, "danger" if summary.auth else "neutral"),
        ("其他失败", summary.other, "danger" if summary.other else "neutral"),
    ]
    cells = "".join(
        f'<div class="context-item"><div class="context-label">{escape(label)}</div>'
        f'<div class="context-copy"><span class="status-badge status-{level}">{count}</span></div></div>'
        for label, count, level in cards
    )
    render_html(f'<div class="context-grid">{cells}</div>')
    if summary.total and summary.success == 0:
        st.warning("本次运行没有任何成功回答；请查看下方明细中的错误码与错误信息，或先做连通性检查。")


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


def _render_answer_viewer_from_results() -> None:
    result = eval_state.get_last_run()
    if result is None:
        return
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


def _render_scoring(base, provider_name: str, task_records: list[dict]) -> None:
    result = eval_state.get_last_run()
    if result is None:
        st.info("请先完成步骤 1 的运行，再进行裁判评分。")
        return

    render_section_title(
        "自动评分（裁判模型）",
        "由裁判模型对照 Gold Answer 与 Rubric 打出建议分；分数为机器建议，需人工确认后才纳入正式结论。",
    )
    st.caption(f"评分模型：{sc.DEFAULT_JUDGE_MODEL}（系统默认）。被评测模型全程不可见 Gold；并列对比不代表最终结论。")

    no_success = result.success_count == 0
    if no_success:
        st.warning("本次运行没有成功回答，无法评分。请先在步骤 1 获得至少一条成功回答（可先做连通性检查排查失败原因）。")

    if st.button(
        "运行自动评分（裁判模型）", type="primary", disabled=no_success, key="live_eval_score_run"
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
        st.session_state["live_eval_score_dims"] = dimensions
        st.rerun()


def _render_score_results() -> None:
    score_result = eval_state.get_last_score()
    if score_result is None:
        return
    dimensions = st.session_state.get("live_eval_score_dims") or ds.get_rubric_dimensions()

    render_section_title(
        "评分结果（建议分 · 待人工复核）",
        f"score_run_id：{score_result.score_run_id} · 模式：{score_result.mode} · "
        f"已评分 {score_result.scored_count}/{len(score_result.outcomes)}",
    )
    if sc.is_mock_score(score_result):
        st.info("本次为 mock 模式：未产生真实评分，各维度留空，仅用于打通链路。")

    _render_score_compare_table(score_result, dimensions)

    if ds.database_ready():
        _render_score_review(score_result, dimensions)
    else:
        st.caption("评分暂存于当前页面会话；初始化 SQLite 数据层后可改分并确认生效。")


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
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )
    render_evidence_panel("评分对比表", table_html)
    st.caption("裁判状态为 failed 且错误码为 judge_parse_error 时，表示裁判输出无法解析为有效 JSON 评分。")


def _render_score_review(score_result, dimensions) -> None:
    rows = sc.load_score_rows(score_result.score_run_id)
    reviewable = [r for r in rows if r.get("judge_status") == "success"]
    if not reviewable:
        st.caption("当前无可复核的成功评分（mock / 失败的评分不进入人工复核）。")
        return

    render_section_title(
        "人工复核（批量）",
        "可逐条修订各维度分与复核说明，确认后纳入正式结论；更推荐到「单题深度评测」页对照 Gold 复核。",
    )
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
            if st.button("确认生效（人工复核通过）", key=f"score_confirm::{row_id}"):
                if sc.confirm_score_review(row_id, edited, note):
                    st.success("已确认（confirmed）。")
                    st.rerun()
                else:
                    st.warning("确认失败：请确认 SQLite 数据层已初始化。")


def _render_completion_cta() -> None:
    if not eval_state.has_run():
        return
    render_action_cards([
        ("查看评测复核 →", "case_detail"),
        ("查看评测结论 →", "evaluation_conclusions"),
    ], key_prefix="eval_run")


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


def _dash(value) -> str:
    text = "" if value is None else str(value).strip()
    return text or "—"


def _short(value, limit: int = 40) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "—"
    return text if len(text) <= limit else text[:limit] + "…"
