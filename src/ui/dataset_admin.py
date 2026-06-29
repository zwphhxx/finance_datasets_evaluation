"""数据集管理页面（dataset management）。

提供任务题、Gold Answer 与 Rubric 的最小可用维护能力：新增 / 编辑 / 停用任务题，
编辑 Gold Answer 核心要素，查看与维护评分维度。所有写入仅落到 SQLite 运行时数据层，
不回写 data/ 下的 CSV/JSON/YAML——后者仍是初始化 seed 与可审阅的版本化数据资产。

页面不直接写 SQL，全部通过 app.services.dataset_service 操作；删除统一做 status=inactive，
不做物理删除。数据库不存在时回退到 seed 文件只读展示，并提供一键初始化入口。
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app.services import dataset_service as ds
from src.data_service import load_label_taxonomy
from src.gold_quality import field_list, field_text
from src.ui.components import (
    render_empty_state,
    render_html,
    render_page_shell,
    render_section_title,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    RISK_LABELS,
    TASK_TYPE_LABELS,
    display_label,
)


CRUD_NOTE = "当前 CRUD 写入 SQLite；CSV/JSON/YAML 仍为初始化 seed 和可审阅数据资产。"

# 难度与风险等级使用固定的展示词表（非业务数据），其余可选项从现有数据动态取值。
_DIFFICULTY_OPTIONS = list(DIFFICULTY_LABELS.keys())
_RISK_OPTIONS = ["", "高", "中", "低"]
_STATUS_BADGE = {"active": ("启用中", "success"), "inactive": ("已停用", "neutral")}

# 错误标签默认低饱和呈现：仅显式标为「红线/高」的严重度使用浅玫瑰底（danger），
# 中等用米色（warning），其余保持中性，避免把全部错误标签渲染成红色。
_RED_LINE_TOKENS = {"红线", "高", "high", "critical"}
_MID_TOKENS = {"中", "medium"}
_PRIORITY_BADGE = {"高": "warning", "中": "neutral", "低": "neutral"}
# 配置校验问题：error 用浅玫瑰、warning 用米色。
_ISSUE_BADGE = {"error": "danger", "warning": "warning"}


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def render_dataset_admin_page(data_bundle: dict) -> None:
    render_page_shell(get_page_config("dataset_admin"))
    st.caption(CRUD_NOTE)
    _render_rerun_prompt()

    if not ds.database_ready():
        _render_uninitialized(data_bundle)
        return

    tasks_tab, gold_tab, rubric_tab, label_tab, action_tab = st.tabs(
        ["任务题管理", "Gold Answer 管理", "Rubric 管理", "错误标签管理", "数据补强动作管理"]
    )
    with tasks_tab:
        _render_task_admin()
    with gold_tab:
        _render_gold_admin()
    with rubric_tab:
        _render_rubric_admin()
    with label_tab:
        _render_error_label_admin()
    with action_tab:
        _render_action_admin()


def _render_uninitialized(data_bundle: dict) -> None:
    """数据库未初始化：回退 seed 只读展示，并提供一键初始化入口。"""
    st.info(
        "尚未初始化 SQLite 运行时数据层，当前页面仅以 seed 文件只读展示。"
        "维护任务题、Gold Answer 与 Rubric 需先从 seed 初始化数据库。"
    )
    if st.button("从 seed 文件初始化 SQLite 数据层", type="primary"):
        try:
            counts = ds.ensure_seed_database(force=False)
        except Exception as exc:  # noqa: BLE001 - 初始化失败需如实反馈
            st.error(f"初始化失败：{exc}")
        else:
            st.success(f"初始化完成，共导入 {sum(counts.values())} 条 seed 记录。")
            _mark_data_changed()
            st.rerun()

    data = data_bundle.get("data")
    if data is None or data.tasks.empty:
        return
    render_section_title("当前任务题（只读）", "数据来自 seed 文件，初始化后可在此维护。")
    _render_task_table(data.tasks.to_dict(orient="records"))


# --------------------------------------------------------------------------- #
# 任务题管理
# --------------------------------------------------------------------------- #
def _render_task_admin() -> None:
    tasks = ds.list_task_cases()
    records = tasks.to_dict(orient="records")

    render_section_title("任务清单", "含启用与停用任务，停用任务以软删除标记保留。")
    if records:
        _render_task_table(records)
    else:
        render_empty_state("暂无任务题记录。")

    _render_task_detail(records)
    _render_task_create_form(records)
    _render_task_edit_form(records)


def _domain_options(records: list[dict]) -> list[str]:
    present = [str(r.get("domain")).strip() for r in records if str(r.get("domain") or "").strip()]
    options = sorted(set(present)) or list(DOMAIN_LABELS.keys())
    return options


def _task_type_options(records: list[dict]) -> list[str]:
    present = [str(r.get("task_type")).strip() for r in records if str(r.get("task_type") or "").strip()]
    return sorted(set(present)) or list(TASK_TYPE_LABELS.keys())


def _render_task_table(records: list[dict]) -> None:
    header = "".join(
        f"<th>{escape(name)}</th>"
        for name in ["任务编号", "领域", "任务类型", "难度", "风险等级", "状态"]
    )
    body = ""
    for row in records:
        status = str(row.get("status") or "active").strip().lower()
        label, level = _STATUS_BADGE.get(status, (status or "未知", "neutral"))
        body += (
            f'<tr><td class="check-key">{escape(str(row.get("case_id", "")))}</td>'
            f"<td>{escape(display_label(row.get('domain'), DOMAIN_LABELS))}</td>"
            f"<td>{escape(display_label(row.get('task_type'), TASK_TYPE_LABELS))}</td>"
            f"<td>{escape(display_label(row.get('difficulty'), DIFFICULTY_LABELS))}</td>"
            f"<td>{escape(display_label(row.get('risk_level'), RISK_LABELS))}</td>"
            f'<td><span class="status-badge status-{level}">{escape(label)}</span></td></tr>'
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )


def _render_task_detail(records: list[dict]) -> None:
    if not records:
        return
    render_section_title("任务详情", "选择任务查看完整字段。")
    case_ids = [str(r.get("case_id")) for r in records]
    selected = st.selectbox("查看任务", case_ids, key="admin_task_detail_select")
    row = next((r for r in records if str(r.get("case_id")) == selected), None)
    if not row:
        return
    fields = [
        ("领域", display_label(row.get("domain"), DOMAIN_LABELS)),
        ("任务类型", display_label(row.get("task_type"), TASK_TYPE_LABELS)),
        ("难度", display_label(row.get("difficulty"), DIFFICULTY_LABELS)),
        ("风险等级", display_label(row.get("risk_level"), RISK_LABELS)),
        ("任务场景", _text(row.get("scenario"))),
        ("任务题干", _text(row.get("question"))),
        ("任务背景", _text(row.get("context"))),
        ("考察能力", _text(row.get("expected_capability"))),
        ("状态", _STATUS_BADGE.get(str(row.get("status") or "active"), ("未知", "neutral"))[0]),
        ("更新时间", _text(row.get("updated_at"))),
    ]
    render_html(
        '<div class="fact-card">'
        + "".join(
            f'<div class="fact-field"><div class="fact-label">{escape(label)}</div>'
            f'<div class="fact-value">{escape(value)}</div></div>'
            for label, value in fields
        )
        + "</div>"
    )


def _render_task_create_form(records: list[dict]) -> None:
    render_section_title("新增任务", "新建一道任务题，写入 SQLite。")
    with st.form("admin_task_create", clear_on_submit=True):
        case_id = st.text_input("任务编号 case_id", help="唯一编号，例如 CM-016。")
        col1, col2 = st.columns(2)
        domain = col1.selectbox(
            "领域 domain", _domain_options(records),
            format_func=lambda v: display_label(v, DOMAIN_LABELS), key="create_domain",
        )
        task_type = col2.selectbox(
            "任务类型 task_type", _task_type_options(records),
            format_func=lambda v: display_label(v, TASK_TYPE_LABELS), key="create_task_type",
        )
        col3, col4 = st.columns(2)
        difficulty = col3.selectbox(
            "难度 difficulty", _DIFFICULTY_OPTIONS,
            format_func=lambda v: display_label(v, DIFFICULTY_LABELS), key="create_difficulty",
        )
        risk_level = col4.selectbox(
            "风险等级 risk_level", _RISK_OPTIONS,
            format_func=lambda v: display_label(v, RISK_LABELS) if v else "未标注", key="create_risk",
        )
        scenario = st.text_area("任务场景 scenario", height=80)
        task_prompt = st.text_area("任务题干 task_prompt", height=110)
        expected = st.text_area("考察能力 expected_capabilities", height=80)
        submitted = st.form_submit_button("新增任务", type="primary")

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
                    "expected_capability": expected,
                    "status": ds.ACTIVE_STATUS,
                }
            )
        except Exception as exc:  # noqa: BLE001 - 校验失败如实反馈
            st.error(str(exc))
        else:
            st.success(f"已新增任务 {case_id.strip()}。")
            _mark_data_changed()
            st.rerun()


def _render_task_edit_form(records: list[dict]) -> None:
    if not records:
        return
    render_section_title("编辑 / 停用任务", "修改任务字段，或将任务停用（软删除）。")
    case_ids = [str(r.get("case_id")) for r in records]
    selected = st.selectbox("选择任务", case_ids, key="admin_task_edit_select")
    row = next((r for r in records if str(r.get("case_id")) == selected), None)
    if not row:
        return

    domain_options = _domain_options(records)
    task_type_options = _task_type_options(records)
    with st.form("admin_task_edit"):
        col1, col2 = st.columns(2)
        domain = col1.selectbox(
            "领域 domain", domain_options,
            index=_index_of(domain_options, row.get("domain")),
            format_func=lambda v: display_label(v, DOMAIN_LABELS), key="edit_domain",
        )
        task_type = col2.selectbox(
            "任务类型 task_type", task_type_options,
            index=_index_of(task_type_options, row.get("task_type")),
            format_func=lambda v: display_label(v, TASK_TYPE_LABELS), key="edit_task_type",
        )
        col3, col4 = st.columns(2)
        difficulty = col3.selectbox(
            "难度 difficulty", _DIFFICULTY_OPTIONS,
            index=_index_of(_DIFFICULTY_OPTIONS, row.get("difficulty")),
            format_func=lambda v: display_label(v, DIFFICULTY_LABELS), key="edit_difficulty",
        )
        risk_level = col4.selectbox(
            "风险等级 risk_level", _RISK_OPTIONS,
            index=_index_of(_RISK_OPTIONS, row.get("risk_level")),
            format_func=lambda v: display_label(v, RISK_LABELS) if v else "未标注", key="edit_risk",
        )
        scenario = st.text_area("任务场景 scenario", value=_text(row.get("scenario"), ""), height=80)
        task_prompt = st.text_area("任务题干 task_prompt", value=_text(row.get("question"), ""), height=110)
        expected = st.text_area("考察能力 expected_capabilities", value=_text(row.get("expected_capability"), ""), height=80)
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
        st.success(f"已保存任务 {selected}。")
        _mark_data_changed()
        st.rerun()

    _render_status_toggle(row, selected)


def _render_status_toggle(row: dict, case_id: str) -> None:
    status = str(row.get("status") or "active").strip().lower()
    if status == ds.INACTIVE_STATUS:
        if st.button("启用任务", key="admin_task_activate"):
            ds.set_task_case_status(case_id, ds.ACTIVE_STATUS)
            st.success(f"已启用任务 {case_id}。")
            _mark_data_changed()
            st.rerun()
    else:
        if st.button("停用任务（软删除）", key="admin_task_deactivate"):
            ds.set_task_case_status(case_id, ds.INACTIVE_STATUS)
            st.success(f"已停用任务 {case_id}，记录保留为 inactive。")
            _mark_data_changed()
            st.rerun()


# --------------------------------------------------------------------------- #
# Gold Answer 管理
# --------------------------------------------------------------------------- #
def _render_gold_admin() -> None:
    case_ids = ds.list_gold_answer_case_ids()
    render_section_title("编辑 Gold Answer", "在原始条目上就地修改，raw_json 无损保留其余内容。")
    if not case_ids:
        render_empty_state("暂无 Gold Answer 记录。")
        return

    selected = st.selectbox("选择任务", case_ids, key="admin_gold_select")
    entry = ds.get_gold_answer_record(selected) or {}

    with st.form("admin_gold_edit"):
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
        except Exception as exc:  # noqa: BLE001 - 如实反馈
            st.error(str(exc))
        else:
            st.success(f"已保存 {selected} 的 Gold Answer。")
            _mark_data_changed()
            st.rerun()


# --------------------------------------------------------------------------- #
# Rubric 管理
# --------------------------------------------------------------------------- #
def _render_rubric_admin() -> None:
    rubrics = ds.list_rubrics()
    records = rubrics.to_dict(orient="records")
    if not records:
        render_empty_state("暂无 Rubric 维度记录。")
        return

    _render_weight_check(records)
    _render_rubric_table(records)
    _render_rubric_edit_form(records)


def _render_weight_check(records: list[dict]) -> None:
    weight_sum = sum(int(r.get("weight") or 0) for r in records)
    totals = {int(r.get("total")) for r in records if r.get("total") is not None}
    total = next(iter(totals)) if len(totals) == 1 else None
    render_section_title("评分维度", f"共 {len(records)} 个维度，权重合计 {weight_sum}。")
    if total is not None and weight_sum != total:
        # 权重合计异常给出提示，但不阻断保存。
        st.warning(f"当前权重合计 {weight_sum} 与声明满分 {total} 不一致，请按需调整（不影响保存）。")


def _render_rubric_table(records: list[dict]) -> None:
    taxonomy = load_label_taxonomy()
    labels_by_dimension = _labels_by_dimension(taxonomy)
    header = "".join(
        f"<th>{escape(name)}</th>"
        for name in ["维度", "权重", "满分标准", "扣分规则", "关联错误标签"]
    )
    body = ""
    for row in records:
        name = str(row.get("name") or row.get("dimension_field") or "")
        linked = labels_by_dimension.get(name, [])
        linked_text = "、".join(linked) if linked else "暂无匹配标签"
        body += (
            f'<tr><td class="check-key">{escape(name)}</td>'
            f'<td class="check-count">{escape(str(row.get("weight") if row.get("weight") is not None else "—"))}</td>'
            f'<td class="check-note">{escape(_text(row.get("full_mark_standard"), "待补充"))}</td>'
            f'<td class="check-note">{escape(_text(row.get("deduction_rules"), "待补充"))}</td>'
            f'<td class="check-note">{escape(linked_text)}</td></tr>'
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )


def _render_rubric_edit_form(records: list[dict]) -> None:
    render_section_title("编辑维度", "维护权重、满分标准与扣分规则。")
    fields = [str(r.get("dimension_field")) for r in records]
    name_by_field = {str(r.get("dimension_field")): str(r.get("name") or r.get("dimension_field")) for r in records}
    selected = st.selectbox(
        "选择维度", fields, format_func=lambda f: name_by_field.get(f, f), key="admin_rubric_select"
    )
    row = next((r for r in records if str(r.get("dimension_field")) == selected), None)
    if not row:
        return

    with st.form("admin_rubric_edit"):
        weight = st.number_input(
            "权重 weight", min_value=0, max_value=100,
            value=int(row.get("weight") or 0), step=1,
        )
        standard = st.text_area("满分标准 full_mark_standard", value=_text(row.get("full_mark_standard"), ""), height=90)
        rules = st.text_area("扣分规则 deduction_rules", value=_text(row.get("deduction_rules"), ""), height=90)
        save = st.form_submit_button("保存维度", type="primary")

    if save:
        ds.update_rubric(
            selected,
            {"weight": weight, "full_mark": weight, "full_mark_standard": standard, "deduction_rules": rules},
        )
        st.success(f"已保存维度 {name_by_field.get(selected, selected)}。")
        _mark_data_changed()
        st.rerun()


def _labels_by_dimension(taxonomy: dict) -> dict[str, list[str]]:
    """按 impacted_dimension 将错误标签关联到评分维度（来自 label_taxonomy.yml）。"""
    mapping: dict[str, list[str]] = {}
    for label in taxonomy.get("labels", []) or []:
        if not isinstance(label, dict):
            continue
        dimension = str(label.get("impacted_dimension") or "").strip()
        name = str(label.get("name") or "").strip()
        if dimension and name:
            mapping.setdefault(dimension, []).append(name)
    return mapping


# --------------------------------------------------------------------------- #
# 错误标签管理
# --------------------------------------------------------------------------- #
def _severity_level(value: object) -> str:
    token = _text(value, "").strip().lower()
    if token in {t.lower() for t in _RED_LINE_TOKENS}:
        return "danger"
    if token in {t.lower() for t in _MID_TOKENS}:
        return "warning"
    return "neutral"


def _render_error_label_admin() -> None:
    labels = ds.list_error_taxonomy().to_dict(orient="records")
    render_section_title("错误标签清单", "含启用与停用标签；默认低饱和呈现，仅红线/高严重度使用浅玫瑰底。")
    if labels:
        _render_label_table(labels)
    else:
        render_empty_state("暂无错误标签记录。")

    _render_label_create_form(labels)
    _render_label_edit_form(labels)
    _render_config_check()


def _render_label_table(records: list[dict]) -> None:
    header = "".join(
        f"<th>{escape(name)}</th>"
        for name in ["错误标签", "关联维度", "严重度", "建议补强方向", "验证指标", "状态"]
    )
    body = ""
    for row in records:
        status = str(row.get("status") or "active").strip().lower()
        s_label, s_level = _STATUS_BADGE.get(status, (status or "未知", "neutral"))
        severity = _text(row.get("severity_level"), "未标注")
        sev_badge = f'<span class="status-badge status-{_severity_level(row.get("severity_level"))}">{escape(severity)}</span>'
        body += (
            f'<tr><td class="check-key">{escape(_text(row.get("error_label"), ""))}</td>'
            f'<td>{escape(_text(row.get("related_dimension"), "未标注"))}</td>'
            f"<td>{sev_badge}</td>"
            f'<td class="check-note">{escape(_text(row.get("suggested_data_action"), "待补充"))}</td>'
            f'<td class="check-note">{escape(_text(row.get("validation_metric"), "待补充"))}</td>'
            f'<td><span class="status-badge status-{s_level}">{escape(s_label)}</span></td></tr>'
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )


def _dimension_options() -> list[str]:
    """Rubric 维度名称（动态读取），供错误标签关联维度选择。"""
    rubrics = ds.list_rubrics()
    if "name" in rubrics.columns:
        names = [str(name) for name in rubrics["name"].dropna().tolist()]
        if names:
            return [""] + names
    return [""]


def _render_label_create_form(records: list[dict]) -> None:
    render_section_title("新增错误标签", "登记一类错误标签，写入 SQLite。")
    dimensions = _dimension_options()
    with st.form("admin_label_create", clear_on_submit=True):
        error_label = st.text_input("错误标签 error_label")
        definition = st.text_area("定义 definition", height=70)
        symptom = st.text_area("典型表现 typical_symptom", height=70)
        col1, col2 = st.columns(2)
        severity = col1.selectbox("严重度 severity_level", ["", "高", "中", "低"], format_func=lambda v: v or "未标注")
        dimension = col2.selectbox(
            "关联维度 related_dimension", dimensions, format_func=lambda v: v or "未关联"
        )
        suggested = st.text_area("建议补强方向 suggested_data_action", height=70)
        metric = st.text_input("验证指标 validation_metric")
        submitted = st.form_submit_button("新增错误标签", type="primary")

    if submitted:
        try:
            ds.create_error_label(
                {
                    "error_label": error_label,
                    "definition": definition,
                    "typical_symptom": symptom,
                    "severity_level": severity,
                    "related_dimension": dimension,
                    "suggested_data_action": suggested,
                    "validation_metric": metric,
                }
            )
        except Exception as exc:  # noqa: BLE001 - 校验失败如实反馈
            st.error(str(exc))
        else:
            st.success(f"已新增错误标签 {error_label.strip()}。")
            _mark_data_changed()
            st.rerun()


def _render_label_edit_form(records: list[dict]) -> None:
    if not records:
        return
    render_section_title("编辑 / 停用错误标签", "修改标签字段，或将标签停用（保留历史，不物理删除）。")
    labels = [str(r.get("error_label")) for r in records]
    selected = st.selectbox("选择错误标签", labels, key="admin_label_edit_select")
    row = next((r for r in records if str(r.get("error_label")) == selected), None)
    if not row:
        return

    dimensions = _dimension_options()
    severities = ["", "高", "中", "低"]
    with st.form("admin_label_edit"):
        definition = st.text_area("定义 definition", value=_text(row.get("definition"), ""), height=70)
        symptom = st.text_area("典型表现 typical_symptom", value=_text(row.get("typical_symptom"), ""), height=70)
        col1, col2 = st.columns(2)
        severity = col1.selectbox(
            "严重度 severity_level", severities,
            index=_index_of(severities, row.get("severity_level")),
            format_func=lambda v: v or "未标注",
        )
        dimension = col2.selectbox(
            "关联维度 related_dimension", dimensions,
            index=_index_of(dimensions, row.get("related_dimension")),
            format_func=lambda v: v or "未关联",
        )
        suggested = st.text_area("建议补强方向 suggested_data_action", value=_text(row.get("suggested_data_action"), ""), height=70)
        metric = st.text_input("验证指标 validation_metric", value=_text(row.get("validation_metric"), ""))
        save = st.form_submit_button("保存修改", type="primary")

    if save:
        ds.update_error_label(
            selected,
            {
                "definition": definition,
                "typical_symptom": symptom,
                "severity_level": severity,
                "related_dimension": dimension,
                "suggested_data_action": suggested,
                "validation_metric": metric,
            },
        )
        st.success(f"已保存错误标签 {selected}。")
        _mark_data_changed()
        st.rerun()

    status = str(row.get("status") or "active").strip().lower()
    if status == ds.INACTIVE_STATUS:
        if st.button("启用标签", key="admin_label_activate"):
            ds.set_error_label_status(selected, ds.ACTIVE_STATUS)
            st.success(f"已启用错误标签 {selected}。")
            _mark_data_changed()
            st.rerun()
    else:
        if st.button("停用标签（软删除）", key="admin_label_deactivate"):
            ds.set_error_label_status(selected, ds.INACTIVE_STATUS)
            st.success(f"已停用错误标签 {selected}，记录保留为 inactive。")
            _mark_data_changed()
            st.rerun()


def _render_config_check() -> None:
    render_section_title("配置校验", "识别无效标签、缺少补强动作的高频错误，以及关联不存在标签的补强动作。")
    issues = ds.evaluate_error_configuration()
    if not issues:
        render_html('<div class="empty-state">当前错误标签与补强动作配置一致，无待处理问题。</div>')
        return
    body = ""
    for issue in issues:
        level = _ISSUE_BADGE.get(issue.severity, "neutral")
        label = "错误" if issue.severity == "error" else "提示"
        body += (
            f'<tr><td><span class="status-badge status-{level}">{escape(label)}</span></td>'
            f'<td class="check-key">{escape(str(issue.target))}</td>'
            f'<td class="check-note">{escape(issue.message)}</td></tr>'
        )
    render_html(
        '<table class="check-table"><thead><tr><th>级别</th><th>对象</th><th>说明</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


# --------------------------------------------------------------------------- #
# 数据补强动作管理
# --------------------------------------------------------------------------- #
def _render_action_admin() -> None:
    actions = ds.list_improvement_actions().to_dict(orient="records")
    render_section_title("补强动作清单", "每条补强动作关联到一个错误标签，写入即被错误归因页读取。")
    if actions:
        _render_action_table(actions)
    else:
        render_empty_state("暂无数据补强动作记录。")

    _render_action_create_form()
    _render_action_edit_form(actions)


def _render_action_table(records: list[dict]) -> None:
    header = "".join(
        f"<th>{escape(name)}</th>"
        for name in ["动作编号", "关联错误标签", "动作类型", "动作说明", "优先级", "状态"]
    )
    body = ""
    for row in records:
        status = str(row.get("status") or "active").strip().lower()
        s_label, s_level = _STATUS_BADGE.get(status, (status or "未知", "neutral"))
        priority = _text(row.get("priority"), "未标注")
        p_badge = f'<span class="status-badge status-{_PRIORITY_BADGE.get(priority, "neutral")}">{escape(priority)}</span>'
        body += (
            f'<tr><td class="check-key">{escape(_text(row.get("action_id"), str(row.get("id", ""))))}</td>'
            f'<td>{escape(_text(row.get("frequent_error"), "未关联"))}</td>'
            f'<td>{escape(_text(row.get("action_type"), "未标注"))}</td>'
            f'<td class="check-note">{escape(_text(row.get("optimization_action"), "待补充"))}</td>'
            f"<td>{p_badge}</td>"
            f'<td><span class="status-badge status-{s_level}">{escape(s_label)}</span></td></tr>'
        )
    render_html(
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
    )


def _render_action_create_form() -> None:
    render_section_title("新增补强动作", "补强动作必须关联到一个已登记的错误标签。")
    labels = sorted(ds.active_error_labels())
    if not labels:
        render_empty_state("请先在「错误标签管理」中登记错误标签，再新增补强动作。")
        return
    with st.form("admin_action_create", clear_on_submit=True):
        related = st.selectbox("关联错误标签 related_error_label", labels)
        col1, col2 = st.columns(2)
        action_type = col1.text_input("动作类型 action_type")
        priority = col2.selectbox("优先级 priority", ["", "高", "中", "低"], format_func=lambda v: v or "未标注")
        description = st.text_area("动作说明 action_description", height=80)
        expected = st.text_area("预期效果 expected_effect", height=70)
        method = st.text_input("验证方式 validation_method")
        submitted = st.form_submit_button("新增补强动作", type="primary")

    if submitted:
        try:
            ds.create_improvement_action(
                {
                    "related_error_label": related,
                    "action_type": action_type,
                    "action_description": description,
                    "expected_effect": expected,
                    "validation_method": method,
                    "priority": priority,
                }
            )
        except Exception as exc:  # noqa: BLE001 - 校验失败如实反馈
            st.error(str(exc))
        else:
            st.success(f"已新增补强动作，关联标签 {related}。")
            _mark_data_changed()
            st.rerun()


def _render_action_edit_form(records: list[dict]) -> None:
    if not records:
        return
    render_section_title("编辑 / 停用补强动作", "修改动作字段、改换关联标签，或将动作停用（软删除）。")
    labels = sorted(ds.active_error_labels())
    options = [int(r.get("id")) for r in records if r.get("id") is not None]
    id_to_row = {int(r.get("id")): r for r in records if r.get("id") is not None}
    selected = st.selectbox(
        "选择补强动作", options,
        format_func=lambda i: f'{_text(id_to_row[i].get("action_id"), str(i))} · {_text(id_to_row[i].get("frequent_error"), "未关联")}',
        key="admin_action_edit_select",
    )
    row = id_to_row.get(selected)
    if not row:
        return

    related_options = labels.copy()
    current_related = _text(row.get("frequent_error"), "")
    if current_related and current_related not in related_options:
        related_options = [current_related] + related_options
    priorities = ["", "高", "中", "低"]
    with st.form("admin_action_edit"):
        related = st.selectbox(
            "关联错误标签 related_error_label", related_options,
            index=_index_of(related_options, current_related) if current_related in related_options else 0,
        )
        col1, col2 = st.columns(2)
        action_type = col1.text_input("动作类型 action_type", value=_text(row.get("action_type"), ""))
        priority = col2.selectbox(
            "优先级 priority", priorities, index=_index_of(priorities, row.get("priority")),
            format_func=lambda v: v or "未标注",
        )
        description = st.text_area("动作说明 action_description", value=_text(row.get("optimization_action"), ""), height=80)
        expected = st.text_area("预期效果 expected_effect", value=_text(row.get("expected_effect"), ""), height=70)
        method = st.text_input("验证方式 validation_method", value=_text(row.get("validation_method"), ""))
        save = st.form_submit_button("保存修改", type="primary")

    if save:
        try:
            ds.update_improvement_action(
                selected,
                {
                    "related_error_label": related,
                    "action_type": action_type,
                    "action_description": description,
                    "expected_effect": expected,
                    "validation_method": method,
                    "priority": priority,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 校验失败如实反馈
            st.error(str(exc))
        else:
            st.success("已保存补强动作。")
            _mark_data_changed()
            st.rerun()

    status = str(row.get("status") or "active").strip().lower()
    if status == ds.INACTIVE_STATUS:
        if st.button("启用动作", key="admin_action_activate"):
            ds.set_improvement_action_status(selected, ds.ACTIVE_STATUS)
            st.success("已启用补强动作。")
            _mark_data_changed()
            st.rerun()
    else:
        if st.button("停用动作（软删除）", key="admin_action_deactivate"):
            ds.set_improvement_action_status(selected, ds.INACTIVE_STATUS)
            st.success("已停用补强动作，记录保留为 inactive。")
            _mark_data_changed()
            st.rerun()


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _text(value: object, fallback: str = "暂无记录") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def _index_of(options: list, value: object) -> int:
    text = "" if value is None else str(value).strip()
    return options.index(text) if text in options else 0



def _mark_data_changed() -> None:
    """数据集发生变更后设置标记，提醒用户重新运行评测以查看最新结论。"""
    import streamlit as st

    st.session_state["admin_data_changed"] = True


def _render_rerun_prompt() -> None:
    """当数据集最近被修改且尚未重新运行时，在页面顶部提示重跑。"""
    import streamlit as st

    if not st.session_state.get("admin_data_changed"):
        return
    render_info_panel(
        "数据已更新",
        "当前分析页仍基于上次运行结果；建议重新运行评测以查看最新结论。",
    )
    if st.button("重新运行评测 →", key="admin_rerun_eval", type="primary"):
        st.session_state.current_page = "eval_run"
        st.session_state.pop("admin_data_changed", None)
        st.rerun()