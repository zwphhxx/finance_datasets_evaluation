"""样本库页面（Sample Library）。

基于 app.services.sample_repository 的轻量样本管理：
- 支持按状态、场景、难度、错误标签筛选与关键词搜索；
- 紧凑表格展示样本；
- 新增、编辑、状态流转、归档（软删除）。
"""

from __future__ import annotations

import json
from html import escape

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from app.services import sample_repository as sr
from src.gold_quality import field_list, field_text, field_value
from src.metrics import get_task_by_case_id, merge_case_outputs_with_scores
from src.ui.components import (
    render_clean_list,
    render_compact_hero,
    render_empty_state,
    render_evidence_panel,
    render_html,
    render_key_value_list,
    render_numbered_section,
    render_section_title,
    render_tag_cloud,
    render_text_block,
    render_two_column_panel,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    RISK_LABELS,
    TASK_TYPE_LABELS,
    display_label,
    summarize_text,
)


_STATUS_LEVEL = {
    "待复核": "warning",
    "已入库": "success",
    "需优化": "danger",
    "已归档": "neutral",
}

_DIFFICULTY_OPTIONS = list(DIFFICULTY_LABELS.keys())
_RISK_OPTIONS = ["", "高", "中", "低"]


def _clean_text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def _truncate(value, limit: int = 40) -> str:
    text = _clean_text(value, fallback="暂无记录")
    if text == "暂无记录":
        return text
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _difficulty_label(value) -> str:
    return DIFFICULTY_LABELS.get(str(value).strip(), str(value).strip() or "未标注")


def _status_badge(status: str) -> str:
    level = _STATUS_LEVEL.get(status, "neutral")
    return f'<span class="status-badge status-{level}">{escape(status)}</span>'


def _as_lines(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(v).strip() for v in value if str(v).strip())
    return str(value) if value else ""


def _parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _format_json_text(text: str) -> str:
    """If text is valid JSON, pretty-print; otherwise return as-is."""
    if not text:
        return ""
    try:
        obj = json.loads(text)
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return text


def _searchable_text(sample: sr.Sample) -> str:
    """Return a lower-cased string covering common searchable fields."""
    parts = [
        sample.sample_id,
        sample.title,
        sample.scenario,
        sample.task_prompt,
        sample.business_context,
        sample.reviewer_note,
        " ".join(sample.error_tags),
    ]
    return " ".join(str(p) for p in parts if p).lower()


# --------------------------------------------------------------------------- #
# Backward-compatible helpers (kept for existing tests)
# --------------------------------------------------------------------------- #
def build_case_overview_rows(data) -> list[dict]:
    """One compact row per task, with Gold Answer / model-answer / error-label
    status derived from the linked data files. Includes judgment criteria completeness (draft vs active)."""
    tasks_df = data.tasks
    if tasks_df.empty or "case_id" not in tasks_df.columns:
        return []

    answer_counts: dict[str, int] = {}
    if "case_id" in getattr(data.model_outputs, "columns", []):
        answer_counts = data.model_outputs["case_id"].dropna().astype(str).value_counts().to_dict()
    error_counts: dict[str, int] = {}
    if "case_id" in getattr(data.errors, "columns", []):
        error_counts = data.errors["case_id"].dropna().astype(str).value_counts().to_dict()

    rows: list[dict] = []
    for row in tasks_df.to_dict(orient="records"):
        case_id = _clean_text(row.get("case_id"))
        difficulty_raw = _clean_text(row.get("difficulty"))
        gold = data.gold_answer_map.get(case_id) or {}
        has_gold = field_value(gold, "core_conclusion") is not None
        has_criteria = bool(
            has_gold
            and field_value(gold, "must_have_points")
            and field_value(gold, "unacceptable_errors")
        )
        sample_status = "active" if has_criteria else "draft"
        rows.append(
            {
                "case_id": case_id,
                "domain_label": display_label(row.get("domain"), DOMAIN_LABELS),
                "task_type_label": display_label(row.get("task_type"), TASK_TYPE_LABELS),
                "difficulty_label": DIFFICULTY_LABELS.get(difficulty_raw, difficulty_raw),
                "difficulty_badge": "neutral",
                "capability": _truncate(row.get("expected_capability")),
                "has_gold": has_gold,
                "has_criteria": has_criteria,
                "sample_status": sample_status,
                "model_answer_count": int(answer_counts.get(case_id, 0)),
                "error_label_count": int(error_counts.get(case_id, 0)),
            }
        )
    return rows


def _build_sample_coverage_summary(rows) -> list[tuple[str, str]]:
    """Sample coverage summary derived from the case rows."""
    total = len(rows)
    with_gold = sum(1 for r in rows if r["has_gold"])
    with_criteria = sum(1 for r in rows if r["has_criteria"])
    return [
        ("任务总数", f"{total} 道"),
        ("Gold Answer 覆盖", f"{with_gold}/{total}"),
        ("评判标准完整", f"{with_criteria}/{total}"),
    ]


def filter_case_rows(
    rows,
    domain="全部",
    task_type="全部",
    difficulty="全部",
    gold="全部",
    answer="全部",
    status="全部",
) -> list[dict]:
    """Apply lightweight top filters to the pre-built case rows."""
    filtered = []
    for row in rows:
        if domain != "全部" and row["domain_label"] != domain:
            continue
        if task_type != "全部" and row["task_type_label"] != task_type:
            continue
        if difficulty != "全部" and row["difficulty_label"] != difficulty:
            continue
        if gold == "有" and not row["has_gold"]:
            continue
        if gold == "无" and row["has_gold"]:
            continue
        if answer == "有" and row["model_answer_count"] == 0:
            continue
        if answer == "无" and row["model_answer_count"] > 0:
            continue
        if status == "可测试" and row["sample_status"] != "active":
            continue
        if status == "草稿" and row["sample_status"] != "draft":
            continue
        filtered.append(row)
    return filtered


# --------------------------------------------------------------------------- #
# New sample-library UI
# --------------------------------------------------------------------------- #
def render_samples_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    config = get_page_config("samples")

    domain_count = 0
    if not data.tasks.empty and "domain" in data.tasks.columns:
        domain_count = data.tasks["domain"].dropna().nunique()
    hero_stats = [
        (str(len(data.tasks)), "尽调任务样本"),
        (str(int(domain_count)), "专业领域"),
    ]
    render_compact_hero(
        eyebrow="FinDueEval",
        title=config.title,
        question=config.question,
        stats=hero_stats,
    )

    # 自动初始化 samples.json（从已有 task/gold 生成，幂等）
    samples = sr.load_samples()
    if not samples:
        render_empty_state("暂无可展示的样本。请检查 data/tasks.csv 与 data/gold_answers.json 是否存在。")
        return

    # 01 状态统计（inline，无卡片）
    counts = sr.count_by_status()
    status_parts = [f"{status} {count}" for status, count in counts.items()]
    st.markdown(" · ".join(f"**{label}**：{counts[label]}" for label in sr.SAMPLE_STATUSES))

    # 02 筛选与搜索
    render_numbered_section("02", "筛选与搜索", "按状态、场景、难度、错误标签筛选，或使用关键词搜索。")
    status, scenario, difficulty, error_tag, keyword = _render_filters(samples)

    filtered = sr.filter_samples(status=status, scenario=scenario, difficulty=difficulty, error_tag=error_tag)
    if keyword:
        kw = keyword.lower()
        filtered = [s for s in filtered if kw in _searchable_text(s)]

    # 03 样本表格
    render_numbered_section("03", "样本清单", "一行一样本，状态用轻量标签标识。")
    if not filtered:
        render_empty_state("没有符合当前筛选条件的样本。")
    else:
        _render_samples_table(filtered)

    # 04 样本详情
    render_numbered_section("04", "选中样本详情", "查看并维护样本的完整信息。")
    _render_sample_detail(filtered)

    # 05 样本管理
    render_numbered_section("05", "样本管理", "新增样本，或在高级管理中编辑、变更状态、归档。")
    _render_sample_management()

    st.caption(
        "样本数据保存在本地 data/samples.json；部署到无持久化卷的环境时，新增/编辑/归档内容可能随会话结束而丢失。"
        "请使用上方「导出」定期备份，或挂载持久化存储。"
    )


def _render_filters(samples: list[sr.Sample]) -> tuple[str, str, str, str, str]:
    status_options = ["全部"] + sr.SAMPLE_STATUSES
    scenarios = sorted({s.scenario for s in samples if s.scenario})
    scenario_options = ["全部"] + scenarios
    difficulties = sorted({s.difficulty for s in samples if s.difficulty})
    difficulty_options = ["全部"] + difficulties
    error_tags = sorted({tag for s in samples for tag in s.error_tags})
    error_tag_options = ["全部"] + error_tags

    col1, col2, col3, col4 = st.columns(4)
    status = col1.selectbox("状态", status_options, key="samples_filter_status")
    scenario = col2.selectbox("场景", scenario_options, key="samples_filter_scenario")
    difficulty = col3.selectbox("难度", difficulty_options, key="samples_filter_difficulty")
    error_tag = col4.selectbox("错误标签", error_tag_options, key="samples_filter_error_tag")

    keyword = st.text_input("关键词搜索", placeholder="搜索标题、场景、任务描述、业务背景…", key="samples_keyword_search")
    return status, scenario, difficulty, error_tag, keyword


def _render_samples_table(samples: list[sr.Sample]) -> None:
    header_cells = "".join(
        f"<th>{escape(name)}</th>"
        for name in ["样本编号", "标题", "场景", "难度", "状态", "操作"]
    )
    body = ""
    for sample in samples:
        body += (
            f'<tr><td class="check-key">{escape(sample.sample_id)}</td>'
            f'<td>{escape(_truncate(sample.title, 32))}</td>'
            f'<td>{escape(_truncate(sample.scenario, 24))}</td>'
            f'<td>{escape(_difficulty_label(sample.difficulty))}</td>'
            f'<td>{_status_badge(sample.status)}</td>'
            f'<td class="check-note">—</td></tr>'
        )
    table_html = f'<table class="check-table"><thead><tr>{header_cells}</tr></thead><tbody>{body}</tbody></table>'
    render_evidence_panel("样本列表", table_html)


def _render_sample_detail(samples: list[sr.Sample]) -> None:
    if not samples:
        render_empty_state("没有可查看的样本。")
        return

    sample_ids = [s.sample_id for s in samples]
    selected_id = st.selectbox("选择样本", sample_ids, key="samples_detail_select")
    sample = sr.get_sample(selected_id)
    if sample is None:
        render_empty_state("未找到该样本记录。")
        return

    col1, col2 = st.columns(2)
    with col1:
        render_text_block("标题", sample.title)
        render_text_block("场景", sample.scenario)
        render_text_block("任务描述", sample.task_prompt)
        render_text_block("业务背景", sample.business_context or "未标注")
    with col2:
        render_key_value_list([
            ("样本编号", sample.sample_id),
            ("难度", _difficulty_label(sample.difficulty)),
            ("状态", sample.status),
            ("创建时间", sample.created_at or "—"),
            ("更新时间", sample.updated_at or "—"),
        ])
        if sample.reviewer_note:
            render_text_block("复核备注", sample.reviewer_note)

    gold_formatted = _format_json_text(sample.gold_answer)
    rubric_formatted = _format_json_text(sample.rubric)
    col3, col4 = st.columns(2)
    with col3:
        render_text_block("Gold Answer", gold_formatted or "未填写")
    with col4:
        render_text_block("Rubric", rubric_formatted or "未填写")

    if sample.model_answers or sample.error_tags or sample.improvement_suggestions:
        col5, col6, col7 = st.columns(3)
        with col5:
            render_text_block("模型回答", "")
            render_clean_list(sample.model_answers or ["暂无"])
        with col6:
            render_text_block("错误标签", "")
            render_clean_list(sample.error_tags or ["暂无"])
        with col7:
            render_text_block("优化建议", "")
            render_clean_list(sample.improvement_suggestions or ["暂无"])


def _render_sample_management() -> None:
    _render_backup_controls()
    _render_create_form()

    with st.expander("高级管理（编辑 / 状态变更 / 归档）", expanded=False):
        _render_edit_form()
        _render_status_transition()
        _render_archive_form()


def _render_backup_controls() -> None:
    st.markdown("**备份与恢复**")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="导出 samples.json",
            data=sr.export_samples_json(),
            file_name="samples.json",
            mime="application/json",
            key="samples_export",
        )
    with col2:
        uploaded = st.file_uploader("导入 samples.json", type=["json"], key="samples_import")
        if uploaded is not None:
            if st.button("确认导入并合并", key="samples_import_confirm"):
                try:
                    raw = json.loads(uploaded.getvalue().decode("utf-8"))
                    sr.import_samples(raw)
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success("导入成功，样本已合并到当前库。")
                    st.rerun()


def _render_create_form() -> None:
    with st.form("samples_create", clear_on_submit=True):
        sample_id = st.text_input("样本编号 sample_id", help="唯一编号，例如 SM-001。")
        title = st.text_input("标题 title")
        col1, col2 = st.columns(2)
        scenario = col1.text_input("场景 scenario")
        difficulty = col2.selectbox(
            "难度 difficulty",
            _DIFFICULTY_OPTIONS,
            format_func=lambda v: DIFFICULTY_LABELS.get(v, v) if v else "未标注",
            key="samples_create_difficulty",
        )
        task_prompt = st.text_area("任务描述 task_prompt", height=110)
        business_context = st.text_area("业务背景 business_context", height=80)
        gold_answer = st.text_area("Gold Answer *", height=120, help="可填写文本或 JSON。")
        rubric = st.text_area("Rubric *", height=80, help="可填写文本或 JSON。")
        col3, col4 = st.columns(2)
        model_answers = col3.text_area("模型回答（每行一条）", height=80)
        error_tags = col4.text_area("错误标签（每行一条）", height=80)
        improvement_suggestions = st.text_area("优化建议（每行一条）", height=80)
        reviewer_note = st.text_area("复核备注 reviewer_note", height=60)
        status = st.selectbox("状态 *", sr.SAMPLE_STATUSES, key="samples_create_status")
        submitted = st.form_submit_button("新增样本", type="primary")

    if submitted:
        try:
            sr.create_sample({
                "sample_id": sample_id,
                "title": title,
                "scenario": scenario,
                "task_prompt": task_prompt,
                "business_context": business_context,
                "gold_answer": gold_answer,
                "rubric": rubric,
                "model_answers": _parse_lines(model_answers),
                "error_tags": _parse_lines(error_tags),
                "improvement_suggestions": _parse_lines(improvement_suggestions),
                "status": status,
                "difficulty": difficulty,
                "reviewer_note": reviewer_note,
            })
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"已新增样本 {sample_id.strip()}。")
            st.rerun()


def _render_edit_form() -> None:
    samples = sr.load_samples()
    if not samples:
        render_empty_state("暂无可编辑的样本。")
        return

    sample_ids = [s.sample_id for s in samples]
    selected_id = st.selectbox("选择样本编辑", sample_ids, key="samples_edit_select")
    sample = sr.get_sample(selected_id)
    if sample is None:
        return

    with st.form("samples_edit"):
        title = st.text_input("标题 title", value=sample.title)
        col1, col2 = st.columns(2)
        scenario = col1.text_input("场景 scenario", value=sample.scenario)
        difficulty = col2.selectbox(
            "难度 difficulty",
            _DIFFICULTY_OPTIONS,
            index=_index_of(_DIFFICULTY_OPTIONS, sample.difficulty),
            format_func=lambda v: DIFFICULTY_LABELS.get(v, v) if v else "未标注",
            key="samples_edit_difficulty",
        )
        task_prompt = st.text_area("任务描述 task_prompt", value=sample.task_prompt, height=110)
        business_context = st.text_area("业务背景 business_context", value=sample.business_context, height=80)
        gold_answer = st.text_area("Gold Answer *", value=sample.gold_answer, height=120)
        rubric = st.text_area("Rubric *", value=sample.rubric, height=80)
        col3, col4 = st.columns(2)
        model_answers = col3.text_area("模型回答（每行一条）", value=_as_lines(sample.model_answers), height=80)
        error_tags = col4.text_area("错误标签（每行一条）", value=_as_lines(sample.error_tags), height=80)
        improvement_suggestions = st.text_area(
            "优化建议（每行一条）", value=_as_lines(sample.improvement_suggestions), height=80
        )
        reviewer_note = st.text_area("复核备注 reviewer_note", value=sample.reviewer_note, height=60)
        status = st.selectbox(
            "状态 *",
            sr.SAMPLE_STATUSES,
            index=sr.SAMPLE_STATUSES.index(sample.status),
            key="samples_edit_status",
        )
        save = st.form_submit_button("保存修改", type="primary")

    if save:
        try:
            sr.update_sample(
                selected_id,
                {
                    "title": title,
                    "scenario": scenario,
                    "task_prompt": task_prompt,
                    "business_context": business_context,
                    "gold_answer": gold_answer,
                    "rubric": rubric,
                    "model_answers": _parse_lines(model_answers),
                    "error_tags": _parse_lines(error_tags),
                    "improvement_suggestions": _parse_lines(improvement_suggestions),
                    "status": status,
                    "difficulty": difficulty,
                    "reviewer_note": reviewer_note,
                },
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"已保存样本 {selected_id}。")
            st.rerun()


def _render_status_transition() -> None:
    samples = [s for s in sr.load_samples() if s.status != "已归档"]
    if not samples:
        st.caption("没有可变更状态的样本（已归档样本需先激活）。")
        return

    sample_ids = [s.sample_id for s in samples]
    selected_id = st.selectbox("选择样本变更状态", sample_ids, key="samples_status_select")
    sample = sr.get_sample(selected_id)
    if sample is None:
        return

    transitions = {
        "待复核": ["已入库", "需优化"],
        "已入库": ["需优化", "已归档"],
        "需优化": ["待复核", "已入库"],
    }
    allowed = transitions.get(sample.status, [])
    st.markdown(f"当前状态：**{sample.status}**")

    cols = st.columns(len(allowed)) if allowed else []
    for col, new_status in zip(cols, allowed):
        with col:
            if st.button(f"设为「{new_status}」", key=f"samples_status_{selected_id}_{new_status}"):
                try:
                    sr.set_sample_status(selected_id, new_status)
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success(f"样本 {selected_id} 已变更为 {new_status}。")
                    st.rerun()


def _render_archive_form() -> None:
    samples = [s for s in sr.load_samples() if s.status != "已归档"]
    if not samples:
        render_empty_state("没有可归档的样本。")
        return

    sample_ids = [s.sample_id for s in samples]
    selected_id = st.selectbox("选择样本归档", sample_ids, key="samples_archive_select")
    if st.button("归档样本", key="samples_archive_btn"):
        try:
            sr.archive_sample(selected_id)
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"样本 {selected_id} 已归档。可在高级管理中重新激活。")
            st.rerun()


def _index_of(options: list, value: object) -> int:
    text = "" if value is None else str(value).strip()
    return options.index(text) if text in options else 0
