"""评测结论页面。

结论页只汇总成功的正式评分；失败和被排除记录不进入结论。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256

import pandas as pd
import streamlit as st

from app.access import READ_ONLY_MESSAGE, management_enabled
from app.services import scorer as sc
from app.services.conclusion_read_model import ConclusionReport
from app.services.evidence_index import EvidenceItem
from app.services.model_display import display_model_name
from app.services.snapshot import _safe
from src.ui import conclusions_data as cd
from src.ui.components import (
    render_empty_state,
    render_executive_takeaway,
    render_html,
    render_inline_status,
    render_numbered_section,
    render_persistence_status,
    render_trusted_markdown_html,
)
from src.ui.history_view import (
    render_comparison_and_runtime,
    render_runtime_details,
)
from src.ui.report_components import (
    evidence_model_context_html,
    evidence_selection_reason_label,
    evidence_selector_item_html,
    render_report_masthead,
    render_scope_ledger,
    report_index_row_html,
)
from src.ui.scroll import request_scroll
from src.ui.trust_details import render_score_detail
from src.ui.workbench import (
    historical_dimensions,
    render_common_dimensions,
    render_report_filters,
)

_STREAMLIT_MARKDOWN_PUNCTUATION_RE = re.compile(
    r"([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])"
)


def render_conclusions_page(data_bundle: dict) -> None:
    from src.ui.workbench import load_workbench_source, overview_facts

    base = data_bundle.get("base") or data_bundle["data"]
    render_report_masthead("专业场景大模型评测", "通过财务、法律及投行专业任务，观察大模型在事实提取、逻辑推理、风险识别和专业表达方面的表现。")
    source = load_workbench_source(base)
    full_report = source.report
    readonly = bool(st.session_state.get("readonly_evaluation_snapshot"))
    if not source.available:
        with st.container(key="results_scope"):
            render_scope_ledger([("本次比较对象", "—"), ("可比任务", "—"), ("有效AI评分记录", "—")])
        render_persistence_status(source.message)
        _render_public_case_entry()
        return
    if full_report is None or not full_report.scope.formal_score_count:
        st.info("暂未发布评测结果。可以先查看专业任务与评价标准，了解本项目的评测方法。")
        _render_public_case_entry()
        return
    tasks = getattr(base, "tasks", pd.DataFrame())
    records = tasks.to_dict("records") if isinstance(tasks, pd.DataFrame) else []
    with st.expander("筛选专业场景、模型与任务"):
        report = render_report_filters(full_report, records)
    with st.container(key="results_scope"):
        render_scope_ledger([
            ("本次比较对象", str(len(report.comparison.get("models", [])))),
            ("可比任务", str(report.comparison.get("common_count", 0))),
            ("有效AI评分记录", str(report.scope.formal_score_count)),
        ])
    facts = overview_facts(base, full_report)
    st.caption("当前筛选范围；不同服务配置分别比较。评分记录包含各自任务，平均分只使用共同有效任务。")
    st.caption("最近测试：" + str(facts["latest"] or "时间未记录")
               + " · " + ("只读历史快照（来源声明未经独立认证）" if readonly else "已保存的实测记录"))
    if not report.scope.formal_score_count:
        st.info("当前筛选没有有效AI评分记录，请调整条件。")
    render_comparison_and_runtime(report, include_runtime=False)
    if report.scope.formal_score_count:
        st.subheader("低分案例与评价依据")
        render_saved_observations(report)
        with st.expander("维度比较与使用边界"):
            render_common_dimensions(report, historical_dimensions(report))
            st.caption("小样本差异仅供观察；失败记录不参与平均分。")
    render_runtime_details(report, compact=True)


def _render_public_case_entry():
    if st.button("查看专业案例", key="results_view_tasks", type="primary"):
        st.query_params["page"] = "review"
        for field in ("case", "model", "run", "score"):
            st.query_params.pop(field, None)
        request_scroll("top")
        st.rerun()


def render_saved_observations(report) -> None:
    from src.ui.review import case_label, historical_task, open_case_review
    from src.ui.workbench import overview_score_observation

    def open_feedback(row):
        open_case_review(str(row["case_id"]), str(row["eval_model"]), str(row["run_id"]),
                         str(row.get("score_run_id") or row.get("id") or ""))

    st.caption("摘录各比较对象的低分单题反馈，不代表模型整体表现。")
    metadata = {str(r["run_id"]): r for r in report.runtime_tables.get("live_evaluation_runs", [])}
    groups = {}
    for row in report.formal_scores.to_dict("records"):
        run = metadata.get(str(row.get("run_id")), {})
        unit = (str(row["eval_model"]), str(run.get("provider") or ""), str(run.get("service_endpoint") or ""))
        groups.setdefault(unit, []).append(row)
    model_counts = Counter(unit[0] for unit in groups)
    for index, (unit, rows) in enumerate(sorted(groups.items())):
        name = display_model_name(unit[0], source="live")
        observation = overview_score_observation(report, unit[0], run_ids={str(r["run_id"]) for r in rows})
        selected = min(rows, key=lambda r: float(r.get("total_score", 0)))
        if observation:
            selected = next(r for r in rows if str(r["run_id"]) == observation["run_id"] and str(r["case_id"]) == observation["case_id"]
                            and str(r.get("score_run_id") or r.get("id") or "") == observation["score_run_id"])
        task, _, _ = historical_task(report, str(selected["case_id"]), str(selected["run_id"]))
        with st.container(key=f"feedback_{index}"):
            st.markdown("**" + _escape_streamlit_markdown_label(name) + "**")
            if model_counts[unit[0]] > 1:
                st.caption(str(_safe(f"{unit[1] or '服务商未记录'} · {unit[2] or '端点未记录'}")))
            st.text(case_label(task, str(selected["case_id"])))
            if observation:
                feedback = observation["text"]
                st.text(f"{observation['source']}：" + feedback[:220] + ("…" if len(feedback) > 220 else ""))
            else:
                st.text("未保存可展示的评分说明或维度理由；不能据此判断没有问题。")
            button_key = "results_review_case" if index == 0 else "feedback_case_" + _stable_key(selected.get("run_id"), selected.get("eval_model"), selected.get("case_id"), selected.get("score_run_id"))
            st.button("查看该案例", key=button_key, on_click=open_feedback, args=(selected,))


def _render_executive_conclusion(model_summaries: Sequence[Mapping[str, object]]) -> None:
    if not model_summaries:
        return
    render_executive_takeaway("先查看共同样本质量，再核对运行覆盖与逐条评分依据；当前结论仅代表样本内观察。")


# --------------------------------------------------------------------------- #
# 数据源与导入导出
# --------------------------------------------------------------------------- #
def _render_data_source_notice(scope, result_store=None) -> None:
    source_line = f"当前结论来源：评测运行数据｜{scope.data_basis}｜仅代表当前样本范围内的自动评测结果。"
    with st.container(key="conclusion_data_notice"):
        st.caption(source_line)
    with st.container(key="conclusion_maintenance_entry"):
        with st.popover("数据维护", type="tertiary", width="stretch"):
            _render_score_data_maintenance_controls(result_store)
    render_score_io_message()


def render_score_io_message() -> None:
    message = st.session_state.get("conclusion_score_io_message")
    if isinstance(message, dict) and message.get("text"):
        level = str(message.get("level") or "info")
        if level == "success":
            st.toast(str(message["text"]))
        elif level == "warning":
            st.warning(str(message["text"]))
        else:
            st.info(str(message["text"]))


def _render_score_data_maintenance_controls(result_store=None) -> None:
    if not management_enabled():
        st.info(READ_ONLY_MESSAGE)
        return
    st.markdown("**导出**")
    st.caption("导出当前已生成的正式评分结果；仅纳入正式评分。")
    payload = sc.export_score_payload(include_pending=False)
    export_text = sc.serialize_score_export_payload(payload)
    file_name = f"ai_scores_{datetime.now():%Y%m%d_%H%M}.json"
    st.download_button(
        "导出 AI 评测结果",
        data=export_text,
        file_name=file_name,
        mime="application/json",
        type="secondary",
        disabled=not bool(payload.get("records")),
        key="conclusion_export_scores",
    )

    st.markdown("**导入**")
    st.caption("仅导入本项目导出的评分 JSON；重复记录按运行批次、样本和模型判断。")
    uploaded = st.file_uploader(
        "上传评分 JSON 文件",
        type=["json"],
        key="conclusion_import_scores_file",
    )
    duplicate_label = st.radio(
        "重复记录处理",
        ["跳过重复记录", "更新已有记录", "取消导入"],
        horizontal=True,
        key="conclusion_import_duplicate_action",
    )
    action_map = {
        "跳过重复记录": "skip",
        "更新已有记录": "update",
        "取消导入": "cancel",
    }
    if not uploaded:
        st.caption("可上传 AI 评测结果导出文件。")
    else:
        parsed = sc.parse_score_import_content(uploaded.name, uploaded.getvalue())
        rows = parsed.get("rows") or []
        errors = parsed.get("errors") or []
        render_inline_status(
            [
                ("可导入记录", f"{len(rows)} 条"),
                ("校验问题", f"{len(errors)} 条"),
            ]
        )
        if errors:
            st.warning("；".join(str(error) for error in errors[:3]))
        if rows and st.button(
            "导入评分文件",
            type="primary",
            key="conclusion_import_scores_submit",
            disabled=result_store is None,
        ):
            result = sc.import_score_rows(
                rows,
                duplicate_action=action_map[duplicate_label],
                result_store=result_store,
            )
            _record_score_io_message(result)
            cd.clear_conclusions_caches()
            st.rerun()


def _record_score_io_message(result: dict) -> None:
    level = "success" if result.get("imported_count") or result.get("updated_count") else "warning"
    st.session_state["conclusion_score_io_message"] = {
        "level": level,
        "text": result.get("summary") or "导入已处理。",
    }


# --------------------------------------------------------------------------- #
# 01 模型当前判断
# --------------------------------------------------------------------------- #
def _render_model_recommendations(
    model_summaries: Sequence[Mapping[str, object]],
) -> None:
    render_numbered_section(
        "01",
        "模型当前判断",
        "按模型汇总 AI 评分与当前判断。",
    )

    if not model_summaries:
        render_empty_state("暂无模型判断。请先在发起评测页运行评测。")
        if st.button("发起评测", key="conclusion_goto_test_run_models", type="secondary"):
            st.session_state.current_page = "test_run"
            st.rerun()
        return

    labels = ("模型", "样本数／平均分", "当前判断", "主要依据")
    st.caption("以下均分基于各模型自身有效样本，仅用于单模型观察；跨模型优劣请查看上方共同样本比较。")
    with st.container(key="conclusion_model_index"):
        render_html('<div class="conclusion-model-index">' + report_index_row_html(labels, header=True) + "</div>")
        for item in model_summaries:
            raw_model_id = str(item.get("model_name") or "")
            row = _recommendation_row(item)
            values = (
                row["模型"],
                f"{int(row['AI 评分样本数'])} 个／{float(row['平均分']):.1f} 分",
                row["当前判断"],
                row["主要依据"],
            )
            render_html(
                '<div class="conclusion-model-index">'
                + report_index_row_html(
                    values,
                    labels=labels,
                    accessible_label=_model_review_accessible_label(raw_model_id, values),
                )
                + "</div>"
            )


def _model_selector_labels(
    model_summaries: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    names = [
        str(item.get("display_name") or item.get("model_name") or "未标注模型")
        for item in model_summaries
    ]
    totals = Counter(names)
    occurrences: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for item, display_name in zip(model_summaries, names):
        raw_model_id = str(item.get("model_name") or "")
        occurrences[display_name] += 1
        suffix = f"（{occurrences[display_name]}）" if totals[display_name] > 1 else ""
        labels[raw_model_id] = f"{display_name}{suffix}"
    return labels


def _select_conclusion_model(model_id: str) -> None:
    st.session_state["conclusion_selected_model_id"] = str(model_id)
    st.session_state.pop("conclusion_selected_evidence_key", None)


def _evidence_identity(item: EvidenceItem) -> tuple[str, str, str]:
    return (str(item.run_id), str(item.case_id), str(item.model_name))


def _resolve_review_selection(
    model_summaries: Sequence[Mapping[str, object]],
    evidence_by_model: Mapping[str, Sequence[EvidenceItem]],
    *,
    requested_model: object,
    requested_evidence_key: object,
) -> tuple[str, tuple[EvidenceItem, ...], EvidenceItem | None]:
    model_ids = tuple(str(item.get("model_name") or "") for item in model_summaries)
    requested_model_id = str(requested_model or "")
    selected_model = (
        requested_model_id
        if requested_model_id in model_ids
        else (model_ids[0] if model_ids else "")
    )
    items = tuple(evidence_by_model.get(selected_model, ()))
    requested_key = (
        tuple(str(part) for part in requested_evidence_key)
        if isinstance(requested_evidence_key, (tuple, list)) and len(requested_evidence_key) == 3
        else ()
    )
    selected = next(
        (item for item in items if _evidence_identity(item) == requested_key),
        items[0] if items else None,
    )
    return selected_model, items, selected


def _model_review_accessible_label(
    model_id: str,
    values: Sequence[object],
) -> str:
    return f"模型：{model_id}；样本数／平均分：{values[1]}；当前判断：{values[2]}"


def _recommendation_row(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "模型": str(item.get("display_name") or item.get("model_name") or "未标注模型"),
        "AI 评分样本数": int(item.get("sample_count") or 0),
        "平均分": float(item.get("avg_total") or 0),
        "当前判断": _current_judgment(item),
        "主要依据": _primary_basis(item),
    }


# --------------------------------------------------------------------------- #
# 02 证据索引
# --------------------------------------------------------------------------- #
def _render_evidence_review(
    report: ConclusionReport,
    model_summaries: Sequence[Mapping[str, object]],
) -> None:
    selected_model, items, selected_item = _resolve_review_selection(
        model_summaries,
        report.evidence_by_model,
        requested_model=st.session_state.get("conclusion_selected_model_id"),
        requested_evidence_key=st.session_state.get("conclusion_selected_evidence_key"),
    )
    if selected_model:
        st.session_state["conclusion_selected_model_id"] = selected_model
    if selected_item is not None:
        st.session_state["conclusion_selected_evidence_key"] = _evidence_identity(selected_item)
    else:
        st.session_state.pop("conclusion_selected_evidence_key", None)

    render_html('<a id="fde-evidence-review"></a>')
    render_numbered_section(
        "02",
        "证据审阅",
        "选择模型和代表样本，核对评分理由、专业标准答案和模型回答。",
    )
    if not selected_model:
        return

    _render_model_selector(model_summaries, selected_model)
    if not items:
        st.caption("当前模型暂无代表样本证据。")
        return

    _render_evidence_selector(items, selected_item)
    if selected_item is not None:
        _render_selected_evidence(selected_item)


def _render_model_selector(
    model_summaries: Sequence[Mapping[str, object]],
    selected_model: str,
) -> None:
    model_ids = tuple(str(item.get("model_name") or "") for item in model_summaries)
    if not model_ids:
        return
    labels = _model_selector_labels(model_summaries)
    _sync_model_selector_widgets(selected_model)

    with st.container(key="conclusion_model_selector_desktop_region"):
        st.radio(
            "当前模型",
            options=model_ids,
            format_func=lambda model_id: labels[model_id],
            horizontal=True,
            label_visibility="collapsed",
            key="conclusion_model_selector_desktop",
            on_change=_apply_model_selector_change,
            args=("conclusion_model_selector_desktop",),
        )
    with st.container(key="conclusion_model_selector_mobile_region"):
        st.selectbox(
            "当前模型",
            options=model_ids,
            format_func=lambda model_id: labels[model_id],
            key="conclusion_model_selector_mobile",
            on_change=_apply_model_selector_change,
            args=("conclusion_model_selector_mobile",),
        )

    if st.session_state.get("conclusion_multiple_endpoints"):
        st.caption("当前模型包含多个服务配置，按逐题运行批次核对；不展示跨端点综合判断。")
        return

    summary = next(
        (item for item in model_summaries if str(item.get("model_name") or "") == selected_model),
        {},
    )
    row = _recommendation_row(summary)
    render_html(
        evidence_model_context_html(
            model_id=selected_model,
            display_name=labels[selected_model],
            sample_count=row["AI 评分样本数"],
            average_score=f"{float(row['平均分']):.1f}",
            judgment=row["当前判断"],
        )
    )


def _sync_model_selector_widgets(selected_model: str) -> None:
    st.session_state["conclusion_model_selector_desktop"] = str(selected_model)
    st.session_state["conclusion_model_selector_mobile"] = str(selected_model)


def _apply_model_selector_change(widget_key: str) -> None:
    _select_conclusion_model(str(st.session_state.get(widget_key) or ""))


def _render_evidence_selector(
    items: Sequence[EvidenceItem],
    selected_item: EvidenceItem | None,
) -> None:
    selected_key = _evidence_identity(selected_item) if selected_item is not None else None
    with st.container(key="conclusion_evidence_selector"):
        columns = st.columns(len(items), gap="small")
        for column, item in zip(columns, items):
            identity = _evidence_identity(item)
            record_key = _stable_key(*identity)
            with column:
                with st.container(key=f"conclusion_evidence_choice_{record_key}"):
                    render_html(
                        evidence_selector_item_html(item, full_mark=sum(d.get("full_mark", 0) for d in st.session_state.get("conclusion_historical_dimensions", [])) or None, active=identity == selected_key)
                    )
                    if st.button(
                        _evidence_action_label(item),
                        key=f"conclusion_select_evidence_{record_key}",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        _select_conclusion_evidence(item)
                        st.rerun()


def _select_conclusion_evidence(item: EvidenceItem) -> None:
    st.session_state["conclusion_selected_evidence_key"] = _evidence_identity(item)


def _escape_streamlit_markdown_label(value: object) -> str:
    return _STREAMLIT_MARKDOWN_PUNCTUATION_RE.sub(r"\\\1", str(value))


def _evidence_action_label(item: EvidenceItem) -> str:
    case_id = _escape_streamlit_markdown_label(item.case_id)
    reason = _escape_streamlit_markdown_label(
        evidence_selection_reason_label(item.selection_reason)
    )
    return f"审阅 {case_id}（{reason}）"


def _render_selected_evidence(item: EvidenceItem) -> None:
    record_key = _stable_key(*_evidence_identity(item))
    with st.container(key=f"conclusion_selected_evidence_{record_key}"):
        st.caption(f"{item.case_id} · {item.model_name} · {item.run_id} · {item.title}")
        render_score_detail(task=item.task, answer=item.answer_text, score=item.score_record,
                            dimensions=st.session_state.get("conclusion_historical_dimensions", []), key=f"conclusion_{record_key}")
        with st.container(key="conclusion_evidence_open_action"):
            if st.button(
                "打开完整证据",
                key=f"conclusion_evidence_open_{record_key}",
                type="tertiary",
            ):
                _render_full_evidence_dialog(item)


def _full_evidence_tab_labels() -> tuple[str, str, str]:
    return ("评分理由", "专业标准答案", "模型回答")


def _full_evidence_dialog_title(item: EvidenceItem, model_name: str) -> str:
    return (
        f"{_escape_streamlit_markdown_label(item.case_id)}｜"
        f"{_escape_streamlit_markdown_label(model_name)}"
    )


def _render_full_evidence_dialog(item: EvidenceItem) -> None:
    model_name = display_model_name(item.model_name, source="live")

    @st.dialog(_full_evidence_dialog_title(item, model_name), width="large")
    def _dialog() -> None:
        rationale_tab, gold_tab, answer_tab = st.tabs(_full_evidence_tab_labels())
        with rationale_tab:
            render_score_detail(task=item.task, answer=item.answer_text, score=item.score_record,
                                dimensions=st.session_state.get("conclusion_historical_dimensions", []), key="evidence_dialog")
        with gold_tab:
            render_trusted_markdown_html(_gold_evidence_markdown(item))
            with st.expander("运行时任务与材料"):
                st.json(_safe(dict(item.task)), expanded=True)
        with answer_tab:
            render_trusted_markdown_html(_answer_evidence_markdown(item))
        with st.expander("技术明细", expanded=False):
            st.code(
                json.dumps(
                    {
                        "run_id": item.run_id,
                        "case_id": item.case_id,
                        "model_id": item.model_name,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                language="json",
            )

    _dialog()


def _gold_evidence_markdown(item: EvidenceItem) -> str:
    if not item.gold_answer:
        return "历史记录未保存运行时专业标准答案；不使用当前题库补造评分依据。"
    return _structured_markdown(_safe(dict(item.gold_answer)))


def _answer_evidence_markdown(item: EvidenceItem) -> str:
    return _safe(str(item.answer_text or ""))


def _rationale_evidence_markdown(item: EvidenceItem) -> str:
    rationale = _structured_markdown(_safe(item.rationale))
    review_note = _safe(str(item.review_note or "—"))
    return f"**评分理由**\n\n{rationale}\n\n**审阅备注**\n\n{review_note}"


def _structured_markdown(value: object) -> str:
    if isinstance(value, Mapping) or (isinstance(value, Sequence) and not isinstance(value, (str, bytes))):
        serialized = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        return f"```json\n{serialized}\n```"
    return str(value or "")


# --------------------------------------------------------------------------- #
# 全部正式评测记录
# --------------------------------------------------------------------------- #
def _render_all_records(report: ConclusionReport) -> None:
    with st.expander("查看全部评测记录", expanded=False):
        score_rows = report.formal_scores.to_dict("records")
        if not score_rows:
            st.caption("当前没有可查看的正式评测记录。")
            return
        selected_index = st.selectbox(
            "选择评测记录",
            options=list(range(len(score_rows))),
            format_func=lambda index: _formal_record_label(score_rows[index]),
            key="conclusion_all_records_select",
        )
        score = score_rows[int(selected_index)]
        render_inline_status(
            [
                ("样本", str(score.get("case_id") or "—")),
                ("模型", str(score.get("eval_model") or "—")),
                ("总分", str(score.get("total_score") if score.get("total_score") is not None else "—")),
            ]
        )
        if st.button(
            "查看完整记录",
            key=f"conclusion_all_records_open_{_stable_key(score.get('run_id'), score.get('case_id'), score.get('eval_model'))}",
            type="tertiary",
        ):
            _render_formal_record_dialog(report, score)


@st.dialog("完整评测记录", width="large")
def _render_formal_record_dialog(
    report: ConclusionReport,
    score: Mapping[str, object],
) -> None:
    response = dict(_formal_response_for_score(report.formal_responses, score))
    score = dict(score)
    case_id = str(score.get("case_id") or "—")
    model_id = str(score.get("eval_model") or "—")
    st.caption(f"{case_id}｜{model_id}")
    task, context = {}, {}
    with st.expander("运行时任务、版本与配置"):
        run = next((r for r in report.runtime_tables.get("live_evaluation_runs", []) if str(r.get("run_id")) == str(score.get("run_id"))), {})
        st.json(_safe({k: run.get(k) for k in ("run_id", "created_at", "provider", "service_endpoint", "dataset_version", "dataset_hash", "prompt_hash", "generation_parameters_json", "judge_parameters_json")}), expanded=False)
        try:
            context = json.loads(run.get("evaluation_context_json") or "{}")
            task = next((r.get("task") for r in context.get("samples", []) if str(r.get("case_id")) == case_id), None)
            gold = next((r.get("record") for r in context.get("gold", []) if str(r.get("case_id")) == case_id), None)
            if task:
                st.json(_safe(task), expanded=True)
            else:
                st.caption("历史任务正文未保存，不使用当前任务补造历史。")
            if gold:
                st.json(_safe(gold), expanded=False)
        except (ValueError, TypeError, AttributeError):
            st.caption("历史任务与标准无法解析。")
    render_score_detail(task=task, answer=response.get("answer_text"), score=score,
                        dimensions=context.get("dimensions") or [], key="formal_dialog")


def _formal_response_for_score(
    responses: pd.DataFrame,
    score: Mapping[str, object],
) -> Mapping[str, object]:
    target = (
        str(score.get("run_id") or ""),
        str(score.get("case_id") or ""),
        str(score.get("eval_model") or ""),
    )
    for row in responses.to_dict("records"):
        key = (
            str(row.get("run_id") or ""),
            str(row.get("case_id") or ""),
            str(row.get("model_name") or ""),
        )
        if key == target:
            return row
    return {}


def _formal_record_label(row: Mapping[str, object]) -> str:
    return f"{row.get('case_id') or '—'}｜{row.get('eval_model') or '—'}"


def _formal_score_markdown(row: Mapping[str, object]) -> str:
    dimension_lines = [
        f"- {field}：{value}"
        for field, value in row.items()
        if str(field).endswith("_score") and field != "total_score"
    ]
    rationale = _structured_markdown(row.get("rationale"))
    review_note = str(row.get("review_note") or "—")
    dimensions = "\n".join(dimension_lines) or "—"
    return f"{dimensions}\n\n**评分理由**\n\n{rationale}\n\n**审阅备注**\n\n{review_note}"


def _stable_key(*values: object) -> str:
    payload = "\x1f".join(str(value or "") for value in values)
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def _current_judgment(item: dict) -> str:
    if int(item.get("sample_count") or 0) < 3:
        return "样本不足，暂不形成判断"
    suggestion = str(item.get("current_suggestion") or "暂不形成判断")
    return f"{_judgment_symbol(suggestion)}{suggestion}"


def _judgment_symbol(judgment: str) -> str:
    if "谨慎" in judgment or "不建议" in judgment:
        return "⚠ "
    if "可作为" in judgment:
        return "✓ "
    return ""


def _primary_basis(item: dict) -> str:
    basis = item.get("detail_basis") or []
    if basis:
        return _join_texts(basis[:2], "基于 AI 评分判断")
    return str(item.get("basis_summary") or "基于 AI 评分判断")


def _join_texts(values, fallback: str) -> str:
    texts = [str(value).strip() for value in values if str(value).strip()]
    return "；".join(texts) if texts else fallback
