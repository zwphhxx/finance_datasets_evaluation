"""评测结论页面。

结论页只汇总成功的正式评分；失败和被排除记录不进入结论。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from app.services import scorer as sc
from app.services.conclusion_read_model import ConclusionReport
from app.services.evidence_index import EvidenceItem
from src.ui import conclusions_data as cd
from src.ui.components import (
    PROJECT_DISPLAY_NAME,
    render_empty_state,
    render_executive_takeaway,
    render_html,
    render_inline_status,
    render_numbered_section,
    render_persistence_status,
    render_trusted_markdown_html,
)
from src.ui.page_config import get_page_config
from src.ui.report_components import (
    evidence_index_html,
    render_report_masthead,
    render_scope_ledger,
    report_index_row_html,
)
from src.ui.scroll import request_scroll


def render_conclusions_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    tasks = getattr(base, "tasks", None)
    allowed_case_ids = tuple(
        sorted(
            {
                str(case_id).strip()
                for case_id in (
                    tasks["case_id"].tolist()
                    if isinstance(tasks, pd.DataFrame) and "case_id" in tasks.columns
                    else []
                )
                if str(case_id).strip()
            }
        )
    )
    task_records = tuple(tasks.to_dict("records")) if isinstance(tasks, pd.DataFrame) else ()
    gold_map = getattr(base, "gold_answer_map", {})
    gold_records = tuple(sorted(
        ((str(case_id), record) for case_id, record in gold_map.items()),
        key=lambda item: item[0],
    )) if isinstance(gold_map, Mapping) else ()
    dimensions = tuple(ds.get_rubric_dimensions())

    source = cd.load_conclusion_source(
        allowed_case_ids,
        task_records,
        gold_records,
        dimensions,
    )

    config = get_page_config("conclusions")
    render_report_masthead(PROJECT_DISPLAY_NAME, config.question)
    if not source.available:
        render_persistence_status(source.message)
        return
    report = source.report
    if report is None:
        render_persistence_status(source.message)
        return
    model_summaries = report.model_summaries

    render_scope_ledger(
        [
            ("样本范围", f"{report.scope.sample_count} 个专业任务样本"),
            ("比较范围", f"{report.scope.model_count} 个模型"),
            ("证据记录", f"{report.scope.formal_score_count} 条正式评分"),
            ("数据口径", report.scope.data_basis),
        ]
    )
    _render_executive_conclusion(model_summaries)
    selected_model = _render_model_recommendations(model_summaries)
    _render_evidence_index(report, selected_model)
    _render_all_records(report)
    _render_data_source_notice(report.scope)


def _render_executive_conclusion(model_summaries: Sequence[Mapping[str, object]]) -> None:
    if not model_summaries:
        return
    item = model_summaries[0]
    display = str(item.get("display_name") or item.get("model_name") or "未标注模型")
    render_executive_takeaway(f"{display}：{_current_judgment(item)}")


# --------------------------------------------------------------------------- #
# 数据源与导入导出
# --------------------------------------------------------------------------- #
def _render_data_source_notice(scope) -> None:
    source_line = f"当前结论来源：评测运行数据｜{scope.data_basis}｜仅代表当前样本范围内的自动评测结果。"
    with st.container(key="conclusion_data_notice"):
        st.caption(source_line)
    with st.container(key="conclusion_maintenance_entry"):
        with st.popover("数据维护", type="tertiary", width="stretch"):
            _render_score_data_maintenance_controls()
    message = st.session_state.get("conclusion_score_io_message")
    if isinstance(message, dict) and message.get("text"):
        level = str(message.get("level") or "info")
        if level == "success":
            st.toast(str(message["text"]))
        elif level == "warning":
            st.warning(str(message["text"]))
        else:
            st.info(str(message["text"]))


def _render_score_data_maintenance_controls() -> None:
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
        if rows and st.button("导入评分文件", type="primary", key="conclusion_import_scores_submit"):
            result = sc.import_score_rows(rows, duplicate_action=action_map[duplicate_label])
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
) -> str:
    render_numbered_section(
        "01",
        "模型当前判断",
        "按模型汇总 AI 评分与当前判断。",
    )

    if not model_summaries:
        render_empty_state("暂无模型判断。请先在评测操作页运行评测。")
        if st.button("评测操作", key="conclusion_goto_test_run_models", type="secondary"):
            st.session_state.current_page = "test_run"
            st.rerun()
        return ""

    raw_ids = tuple(str(item.get("model_name") or "") for item in model_summaries)
    current = str(st.session_state.get("conclusion_selected_model_id") or "")
    selected_model = current if current in raw_ids else raw_ids[0]
    labels = ("模型", "样本数／平均分", "当前判断", "主要依据")
    st.caption("选择模型，在下方证据索引中查证代表样本。")
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
                    active=raw_model_id == selected_model,
                )
                + "</div>"
            )
            with st.container(key=f"conclusion_model_action_{_stable_key(raw_model_id)}"):
                if st.button(
                    _model_evidence_action_label(raw_model_id),
                    key=f"conclusion_select_model_{_stable_key(raw_model_id)}",
                    type="tertiary",
                ):
                    _select_model_evidence(raw_model_id)
                    st.rerun()
    return selected_model


def _select_model_evidence(model_id: str) -> None:
    st.session_state["conclusion_selected_model_id"] = str(model_id)
    request_scroll("#fde-evidence-index")


def _model_evidence_action_label(model_id: str) -> str:
    return f"查看证据：{model_id}"


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
def _render_evidence_index(
    report: ConclusionReport,
    selected_model: str,
) -> None:
    render_html('<a id="fde-evidence-index"></a>')
    render_numbered_section(
        "02",
        "证据索引",
        "从模型判断进入代表样本，查看专业标准答案、模型回答和评分理由。",
    )
    if not selected_model:
        return
    items = tuple(report.evidence_by_model.get(selected_model, ()))
    if not items:
        st.caption("当前模型暂无代表样本证据。")
        return
    for item in items:
        record_key = _stable_key(item.run_id, item.case_id, item.model_name)
        with st.container(key=f"conclusion_evidence_record_{record_key}"):
            render_html(evidence_index_html([item], include_full_details=False))
            with st.container(key=f"conclusion_evidence_actions_{record_key}"):
                action_columns = st.columns(3, gap="small")
                with action_columns[0]:
                    if st.button(
                        "查看专业标准答案",
                        key=f"conclusion_evidence_gold_{record_key}",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        _render_gold_evidence_dialog(item)
                with action_columns[1]:
                    if st.button(
                        "查看模型回答全文",
                        key=f"conclusion_evidence_answer_{record_key}",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        _render_answer_evidence_dialog(item)
                with action_columns[2]:
                    if st.button(
                        "查看评分理由",
                        key=f"conclusion_evidence_rationale_{record_key}",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        _render_rationale_evidence_dialog(item)


@st.dialog("专业标准答案", width="large")
def _render_gold_evidence_dialog(item: EvidenceItem) -> None:
    render_trusted_markdown_html(_gold_evidence_markdown(item))


@st.dialog("模型回答全文", width="large")
def _render_answer_evidence_dialog(item: EvidenceItem) -> None:
    render_trusted_markdown_html(_answer_evidence_markdown(item))


@st.dialog("评分理由", width="large")
def _render_rationale_evidence_dialog(item: EvidenceItem) -> None:
    render_trusted_markdown_html(_rationale_evidence_markdown(item))


def _gold_evidence_markdown(item: EvidenceItem) -> str:
    return _structured_markdown(item.gold_answer)


def _answer_evidence_markdown(item: EvidenceItem) -> str:
    return str(item.answer_text or "")


def _rationale_evidence_markdown(item: EvidenceItem) -> str:
    rationale = _structured_markdown(item.rationale)
    review_note = str(item.review_note or "—")
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
    response = _formal_response_for_score(report.formal_responses, score)
    case_id = str(score.get("case_id") or "—")
    model_id = str(score.get("eval_model") or "—")
    st.caption(f"{case_id}｜{model_id}")
    st.markdown("**模型回答**")
    render_trusted_markdown_html(str(response.get("answer_text") or "暂无模型回答。"))
    st.markdown("**评分维度与理由**")
    render_trusted_markdown_html(_formal_score_markdown(score))


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
