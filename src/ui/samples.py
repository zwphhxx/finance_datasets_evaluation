"""样本库页面（Sample Library）。

Sample = task content + judgment criteria.
- 展示样本列表，含评判标准完整性（draft vs active）
- 包含 add/edit sample UI（合并自 dataset_admin.py 的样本管理）
- 缺少评判标准的样本为 draft，不可进入正式测试
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from src.gold_quality import field_list, field_text, field_value
from src.metrics import get_task_by_case_id
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
)


_STATUS_TEXT = {"active": "可测试", "inactive": "已停用", "draft": "草稿"}
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


def build_case_overview_rows(data) -> list[dict]:
    """One compact row per task, with Gold Answer / judgment criteria completeness."""
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

    if data.tasks.empty:
        render_empty_state("暂无可展示数据")
        return

    rows = build_case_overview_rows(data)

    domains = sorted({row["domain_label"] for row in rows})
    render_tag_cloud(domains)

    # 01 Inline meta line (replaces card grid)
    total, with_gold, with_criteria = _build_sample_coverage_summary(rows)[:3]
    st.markdown(
        f"**{total[1]}** 样本 · **{with_criteria[1]}** 评判标准完整 · "
        f"**{with_gold[1]}** 已配 Gold Answer"
    )

    # 02 Filters: domain + sample status only
    render_numbered_section("02", "筛选条件", "按领域与样本状态过滤。")
    filtered = _render_filters(rows)

    # 03 Task table
    render_numbered_section("03", "任务清单", "评判标准完整的样本可进入正式测试。")
    if not filtered:
        render_empty_state("没有符合当前筛选条件的任务。")
    else:
        _render_overview_table(filtered)

    # 04 Selected task detail
    render_numbered_section("04", "选中任务详情", "查看任务背景、要求与 Gold Answer。")
    _render_selected_task_detail(data, filtered)

    # 05 Sample management: create form visible, advanced ops folded
    render_numbered_section("05", "样本管理", "新增样本或进入高级管理编辑、停用/启用。")
    _render_sample_management(data)


def _render_filters(rows) -> list[dict]:
    domains = ["全部"] + sorted({row["domain_label"] for row in rows})
    col1, col2 = st.columns(2)
    domain = col1.selectbox("领域", domains, key="samples_filter_domain")
    status = col2.selectbox("样本状态", ["全部", "可测试", "草稿"], key="samples_filter_status")
    return filter_case_rows(rows, domain, status)


def _render_overview_table(rows) -> None:
    header_cells = "".join(
        f"<th>{escape(name)}</th>"
        for name in ["任务编号", "领域", "任务类型", "评判标准状态", "操作"]
    )
    body = ""
    for row in rows:
        status_text = _STATUS_TEXT.get(row["sample_status"], row["sample_status"])
        body += (
            f'<tr><td class="check-key">{escape(row["case_id"])}</td>'
            f"<td>{escape(row['domain_label'])}</td>"
            f"<td>{escape(row['task_type_label'])}</td>"
            f'<td>{escape(status_text)}</td>'
            f'<td class="check-note">—</td></tr>'
        )
    table_html = f'<table class="check-table"><thead><tr>{header_cells}</tr></thead><tbody>{body}</tbody></table>'
    render_evidence_panel("任务列表", table_html)


def _render_selected_task_detail(data, rows) -> None:
    if not rows:
        render_empty_state("请调整筛选条件后再查看任务详情。")
        return

    domain_by_case = {row["case_id"]: row["domain_label"] for row in rows}
    case_ids = [row["case_id"] for row in rows]
    selected = st.selectbox(
        "选择任务",
        case_ids,
        format_func=lambda case_id: f"{case_id} · {domain_by_case.get(case_id, '未标注领域')}",
        key="samples_task_select",
    )

    task_rows = get_task_by_case_id(data.tasks, selected)
    if task_rows.empty:
        render_empty_state("未找到该任务的记录。")
        return
    task = task_rows.iloc[0]

    scenario = _clean_text(task.get("scenario"), fallback=_clean_text(task.get("question"), fallback="暂无任务场景"))
    context = _clean_text(task.get("context"), fallback="暂无背景材料")
    capability = _clean_text(task.get("expected_capability"), fallback="暂无任务要求")

    col1, col2 = st.columns(2)
    with col1:
        render_text_block("任务场景", scenario)
        render_text_block("任务背景", context)
    with col2:
        render_text_block("任务要求", capability)
        render_key_value_list([
            ("领域", display_label(task.get("domain"), DOMAIN_LABELS)),
            ("类型", display_label(task.get("task_type"), TASK_TYPE_LABELS)),
            ("难度", DIFFICULTY_LABELS.get(_clean_text(task.get("difficulty")), _clean_text(task.get("difficulty")))),
            ("风险", RISK_LABELS.get(_clean_text(task.get("risk_level")), _clean_text(task.get("risk_level")))),
        ])

    _render_gold_summary(data.gold_answer_map.get(selected))


def _render_gold_summary(gold) -> None:
    if not isinstance(gold, dict) or field_value(gold, "core_conclusion") is None:
        render_empty_state("该任务暂无 Gold Answer 记录。")
        return

    from src.gold_quality import evaluate_gold_quality
    quality = evaluate_gold_quality(gold)
    st.markdown(f"**Gold Answer 状态：** {quality['status']}")

    col1, col2 = st.columns(2)
    with col1:
        render_text_block("标准结论", field_text(gold, "core_conclusion", "暂无记录"))
        render_text_block("关键依据", field_text(gold, "key_evidence", "暂无记录"))
    with col2:
        render_text_block("边界条件", field_text(gold, "boundary_conditions", "暂无记录"))

    col3, col4 = st.columns(2)
    with col3:
        render_text_block("必须覆盖点", "")
        must_points = field_list(gold, "must_have_points")
        if must_points:
            render_clean_list(must_points)
        else:
            st.caption("暂无")
    with col4:
        render_text_block("不可接受错误（红线）", "")
        red_lines = field_list(gold, "unacceptable_errors")
        if red_lines:
            render_clean_list(red_lines)
        else:
            st.caption("暂无")

    review = quality["manual_review"]
    if review:
        st.caption(f"人工复核提示：{review}")


# --------------------------------------------------------------------------- #
# Sample management
# --------------------------------------------------------------------------- #

def _render_sample_management(data) -> None:
    """Render add sample form; advanced ops folded."""
    db_ready = ds.database_ready()
    if not db_ready:
        render_text_block(
            "SQLite 未初始化",
            "SQLite 运行时数据层未初始化，样本管理以只读模式展示。初始化后可新增/编辑样本。",
        )
        if st.button("从 seed 文件初始化 SQLite 数据层", key="samples_init_db"):
            try:
                counts = ds.ensure_seed_database(force=False)
            except Exception as exc:
                st.error(f"初始化失败：{exc}")
            else:
                st.success(f"初始化完成，共导入 {sum(counts.values())} 条 seed 记录。")
                st.rerun()
        return

    _render_task_create_form()

    with st.expander("高级管理（编辑 / 停用 / 启用）", expanded=False):
        _render_task_edit_form()
        _render_gold_edit_form()


def _domain_options() -> list[str]:
    return sorted(set(DOMAIN_LABELS.keys()))


def _task_type_options() -> list[str]:
    return sorted(set(TASK_TYPE_LABELS.keys()))


def _render_task_create_form() -> None:
    """Create a new task sample."""
    with st.form("samples_task_create", clear_on_submit=True):
        case_id = st.text_input("任务编号 case_id", help="唯一编号，例如 CM-016。")
        col1, col2 = st.columns(2)
        domain = col1.selectbox(
            "领域 domain", _domain_options(),
            format_func=lambda v: display_label(v, DOMAIN_LABELS), key="samples_create_domain",
        )
        task_type = col2.selectbox(
            "任务类型 task_type", _task_type_options(),
            format_func=lambda v: display_label(v, TASK_TYPE_LABELS), key="samples_create_task_type",
        )
        col3, col4 = st.columns(2)
        difficulty = col3.selectbox(
            "难度 difficulty", _DIFFICULTY_OPTIONS,
            format_func=lambda v: display_label(v, DIFFICULTY_LABELS), key="samples_create_difficulty",
        )
        risk_level = col4.selectbox(
            "风险等级 risk_level", _RISK_OPTIONS,
            format_func=lambda v: display_label(v, RISK_LABELS) if v else "未标注", key="samples_create_risk",
        )
        scenario = st.text_area("任务场景 scenario", height=80)
        task_prompt = st.text_area("任务题干 task_prompt", height=110)
        context = st.text_area("背景材料 context", height=80)
        expected = st.text_area("考察能力 expected_capabilities", height=80)
        submitted = st.form_submit_button("新增样本", type="primary")

    if submitted:
        try:
            ds.create_task_case(
                {
                    "case_id": case_id,
                    "domain": domain,
                    "task_type": task_type,
                    "difficulty": difficulty,
                    "risk_level": risk_level,
                    "scenario": scenario,
                    "question": task_prompt,
                    "context": context,
                    "expected_capability": expected,
                    "status": ds.ACTIVE_STATUS,
                }
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"已新增样本 {case_id.strip()}。请到「高级管理」补充评判标准，否则该样本为草稿状态，不可进入测试。")
            st.rerun()


def _render_task_edit_form() -> None:
    """Edit existing task sample."""
    tasks = ds.list_task_cases()
    records = tasks.to_dict(orient="records")
    if not records:
        render_empty_state("暂无样本可编辑。")
        return

    case_ids = [str(r.get("case_id")) for r in records]
    selected = st.selectbox("选择样本", case_ids, key="samples_edit_select")
    row = next((r for r in records if str(r.get("case_id")) == selected), None)
    if not row:
        return

    domain_options = _domain_options()
    task_type_options = _task_type_options()
    with st.form("samples_task_edit"):
        col1, col2 = st.columns(2)
        domain = col1.selectbox(
            "领域 domain", domain_options,
            index=_index_of(domain_options, row.get("domain")),
            format_func=lambda v: display_label(v, DOMAIN_LABELS), key="samples_edit_domain",
        )
        task_type = col2.selectbox(
            "任务类型 task_type", task_type_options,
            index=_index_of(task_type_options, row.get("task_type")),
            format_func=lambda v: display_label(v, TASK_TYPE_LABELS), key="samples_edit_task_type",
        )
        col3, col4 = st.columns(2)
        difficulty = col3.selectbox(
            "难度 difficulty", _DIFFICULTY_OPTIONS,
            index=_index_of(_DIFFICULTY_OPTIONS, row.get("difficulty")),
            format_func=lambda v: display_label(v, DIFFICULTY_LABELS), key="samples_edit_difficulty",
        )
        risk_level = col4.selectbox(
            "风险等级 risk_level", _RISK_OPTIONS,
            index=_index_of(_RISK_OPTIONS, row.get("risk_level")),
            format_func=lambda v: display_label(v, RISK_LABELS) if v else "未标注", key="samples_edit_risk",
        )
        scenario = st.text_area("任务场景 scenario", value=_clean_text(row.get("scenario"), ""), height=80)
        task_prompt = st.text_area("任务题干 task_prompt", value=_clean_text(row.get("question"), ""), height=110)
        expected = st.text_area("考察能力 expected_capabilities", value=_clean_text(row.get("expected_capability"), ""), height=80)
        save = st.form_submit_button("保存修改", type="primary")

    if save:
        ds.update_task_case(
            selected,
            {
                "domain": domain,
                "task_type": task_type,
                "difficulty": difficulty,
                "risk_level": risk_level,
                "scenario": scenario,
                "question": task_prompt,
                "expected_capability": expected,
            },
        )
        st.success(f"已保存样本 {selected}。")
        st.rerun()

    status = str(row.get("status") or "active").strip().lower()
    if status == ds.INACTIVE_STATUS:
        if st.button("启用样本", key="samples_activate"):
            ds.set_task_case_status(selected, ds.ACTIVE_STATUS)
            st.success(f"已启用样本 {selected}。")
            st.rerun()
    else:
        if st.button("停用样本（软删除）", key="samples_deactivate"):
            ds.set_task_case_status(selected, ds.INACTIVE_STATUS)
            st.success(f"已停用样本 {selected}，记录保留为 inactive。")
            st.rerun()


def _render_gold_edit_form() -> None:
    """Edit Gold Answer / judgment criteria for a sample."""
    case_ids = ds.list_gold_answer_case_ids()
    if not case_ids:
        render_empty_state("暂无 Gold Answer 记录。")
        return

    selected = st.selectbox("选择样本编辑 Gold Answer", case_ids, key="samples_gold_select")
    entry = ds.get_gold_answer_record(selected) or {}

    with st.form("samples_gold_edit"):
        core = st.text_area("核心结论 core_conclusion", value=field_text(entry, "core_conclusion", ""), height=90)
        evidence = st.text_area("关键依据 key_evidence", value=field_text(entry, "key_evidence", ""), height=90)
        boundary = st.text_area("边界条件 boundary_conditions", value=field_text(entry, "boundary_conditions", ""), height=80)
        must_have = st.text_area(
            "必须覆盖点 must_have_points（每行一条）",
            value="\n".join(field_list(entry, "must_have_points")), height=110,
        )
        unacceptable = st.text_area(
            "不可接受错误 unacceptable_errors（每行一条）",
            value="\n".join(field_list(entry, "unacceptable_errors")), height=110,
        )
        review = st.text_area("人工复核说明 manual_review_notes", value=field_text(entry, "manual_review_notes", ""), height=80)
        save = st.form_submit_button("保存 Gold Answer", type="primary")

    if save:
        try:
            ds.update_gold_answer(
                selected,
                {
                    "core_conclusion": core,
                    "key_evidence": evidence,
                    "boundary_conditions": boundary,
                    "must_have_points": must_have,
                    "unacceptable_errors": unacceptable,
                    "manual_review_notes": review,
                },
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"已保存 {selected} 的 Gold Answer。")
            st.rerun()


def _index_of(options: list, value: object) -> int:
    text = "" if value is None else str(value).strip()
    return options.index(text) if text in options else 0
