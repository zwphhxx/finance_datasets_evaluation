"""样本库页面。

基于 app.services.sample_repository 的轻量样本管理：
- 支持按状态、场景、难度、错误标签筛选与关键词搜索；
- 紧凑表格展示样本；
- 新增、编辑、状态流转、归档（软删除）。
"""

from __future__ import annotations

import json
import re
from html import escape

import streamlit as st

from app.services import dataset_service as ds
from app.services import sample_repository as sr
from src.gold_quality import field_list, field_text, field_value
from src.ui.components import (
    render_compact_hero,
    render_empty_state,
    render_evidence_panel,
    render_html,
    render_numbered_section,
    render_tag_cloud,
    render_two_column_panel,
)
from src.ui.page_config import get_page_config
from src.ui.tasks import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    TASK_TYPE_LABELS,
    display_label,
)


_TEST_STATUS_LEVEL = {
    "可测试": "success",
    "待补充": "warning",
    "不可测试": "neutral",
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


def _test_status_label(sample: sr.Sample, readiness: ds.SampleReadiness) -> str:
    if sample.status == "已归档" or readiness.label == "已归档":
        return "已归档"
    if readiness.is_testable:
        return "可测试"
    if readiness.missing_items:
        return "待补充"
    return "不可测试"


def _test_status_badge(status: str) -> str:
    level = _TEST_STATUS_LEVEL.get(status, "neutral")
    return f'<span class="status-badge sample-status-badge status-{level}">{escape(status)}</span>'


def _format_date(value) -> str:
    text = _clean_text(value, fallback="")
    if not text:
        return "—"
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return text.replace("T", " ").split()[0] if text.split() else "—"


def _missing_summary(readiness: ds.SampleReadiness, limit: int = 3) -> str:
    if not readiness.missing_items:
        return "—"
    items = readiness.missing_items[:limit]
    suffix = "…" if len(readiness.missing_items) > limit else ""
    return "；".join(items) + suffix


def _as_lines(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(v).strip() for v in value if str(v).strip())
    return str(value) if value else ""


def _parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


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


def _formal_db_path_for_ui():
    return ds.get_db_path() if ds.database_ready() else None


def _page_readiness_inputs(data, samples: list[sr.Sample]) -> tuple[list[dict], dict, list[dict]]:
    if ds.database_ready():
        task_records = ds.list_task_cases().to_dict(orient="records")
        gold_map = {
            sample.sample_id: ds.get_gold_answer_record(sample.sample_id) or {}
            for sample in samples
        }
        rubric_dimensions = ds.get_testable_rubric_dimensions()
        return task_records, gold_map, rubric_dimensions
    return (
        data.tasks.to_dict(orient="records"),
        getattr(data, "gold_answer_map", {}) or {},
        ds.get_testable_rubric_dimensions(),
    )


def build_sample_readiness_map(
    samples: list[sr.Sample],
    task_records: list[dict],
    gold_map: dict,
    rubric_dimensions: list[dict] | None,
) -> dict[str, ds.SampleReadiness]:
    """Build sample readiness display data using the same formal gate as test_run."""
    tasks_by_case = {str(row.get("case_id") or ""): row for row in task_records}
    readiness: dict[str, ds.SampleReadiness] = {}
    for sample in samples:
        case_id = str(sample.sample_id or "").strip()
        readiness[case_id] = ds.assess_sample_readiness(
            tasks_by_case.get(case_id),
            gold_map.get(case_id) or {},
            rubric_dimensions,
        )
    return readiness


def build_sample_table_rows(
    samples: list[sr.Sample],
    readiness_map: dict[str, ds.SampleReadiness],
) -> list[dict[str, str]]:
    """构建样本列表摘要行，避免把长文本资产铺在表格里。"""
    rows: list[dict[str, str]] = []
    for sample in samples:
        readiness = readiness_map.get(sample.sample_id) or ds.assess_sample_readiness(None, None, [])
        test_status = _test_status_label(sample, readiness)
        rows.append({
            "样本编号": sample.sample_id or "待补充",
            "任务标题": _truncate(sample.title, 56),
            "场景": _truncate(sample.scenario, 24),
            "测试状态": test_status,
            "难度": _difficulty_label(sample.difficulty),
            "更新时间": _format_date(sample.updated_at),
        })
    return rows


def parse_gold_answer_for_display(value) -> dict:
    """解析 Gold Answer 为详情页展示结构。JSON 异常时保留原文。"""
    parsed = value if isinstance(value, dict) else None
    fallback_text = ""
    if parsed is None:
        text = str(value or "").strip()
        if text:
            try:
                loaded = json.loads(text)
                parsed = loaded if isinstance(loaded, dict) else None
                if parsed is None:
                    fallback_text = text
            except Exception:
                fallback_text = text

    gold = parsed if isinstance(parsed, dict) else {}
    return {
        "parsed": isinstance(parsed, dict),
        "fields": {
            "核心结论": field_text(gold, "core_conclusion", "待补充"),
            "关键依据": field_text(gold, "key_evidence", "待补充"),
            "边界条件": field_text(gold, "boundary_conditions", "待补充"),
            "人工复核提示": field_text(gold, "manual_review_notes", "待补充"),
        },
        "lists": {
            "必须覆盖点": field_list(gold, "must_have_points"),
            "不可接受错误": field_list(gold, "unacceptable_errors"),
        },
        "fallback_text": fallback_text,
    }


def _rubric_field(item: dict) -> str:
    return str(item.get("field") or item.get("dimension_field") or "").strip()


def _rubric_overrides(value) -> dict[str, dict]:
    parsed = None
    if isinstance(value, dict):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
    elif isinstance(value, list):
        parsed = value

    if isinstance(parsed, dict):
        items = parsed.get("dimensions") if isinstance(parsed.get("dimensions"), list) else [parsed]
    elif isinstance(parsed, list):
        items = parsed
    else:
        items = []
    overrides: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        field = _rubric_field(item)
        if field:
            overrides[field] = item
    return overrides


def build_rubric_rows_for_display(
    rubric_dimensions: list[dict] | None,
    rubric_source=None,
) -> list[dict[str, str]]:
    """构建 Rubric 展示矩阵，维度来自正式数据层或统一配置。"""
    if not rubric_dimensions:
        return []
    overrides = _rubric_overrides(rubric_source)
    rows: list[dict[str, str]] = []
    for dim in rubric_dimensions:
        if not isinstance(dim, dict):
            continue
        field = _rubric_field(dim)
        merged = {**dim, **overrides.get(field, {})}
        rows.append({
            "评分维度": _clean_text(merged.get("name") or merged.get("dimension"), fallback=field or "待补充"),
            "满分": _clean_text(merged.get("full_mark") or merged.get("weight"), fallback="待补充"),
            "满分标准": _clean_text(merged.get("full_mark_standard"), fallback="待补充"),
            "扣分规则": _clean_text(merged.get("deduction_rules"), fallback="待补充"),
            "关联错误类型或说明": _clean_text(
                merged.get("related_error_type")
                or merged.get("related_dimension")
                or merged.get("note")
                or merged.get("description"),
                fallback="—",
            ),
        })
    return rows


def build_sample_asset_sections(
    *,
    sample: sr.Sample,
    readiness: ds.SampleReadiness,
    task_record: dict | None,
    gold_display: dict,
    rubric_rows: list[dict],
) -> list[dict[str, object]]:
    """返回样本详情的评测资产分区定义。"""
    return [
        {
            "title": "样本基础信息",
            "caption": "样本在样本库中的业务状态和基础标识。",
        },
        {
            "title": "任务内容",
            "caption": "被测模型只看到任务题、业务背景和输出要求，不看到理想回复标准、Rubric 或红线错误。",
        },
        {
            "title": "理想回复标准 / Gold Answer",
            "caption": "裁判评分链路使用的评判锚点，包含应答方向、关键依据和红线边界。",
        },
        {
            "title": "Rubric 评分标准",
            "caption": "裁判评分链路使用的维度、满分标准和扣分规则。",
        },
        {
            "title": "错误标签与数据优化建议",
            "caption": "用于解释常见模型问题，并把错误归因转化为后续数据集改进方向。",
        },
        {
            "title": "状态、完整度与复核记录",
            "caption": "说明样本为什么可以或不能进入发起测试，并保留人工复核备注。",
        },
    ]


def _table_html(headers: list[str], rows: list[dict[str, str]]) -> str:
    header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">待补充</td></tr>'
    else:
        body = "".join(
            "<tr>" + "".join(f"<td>{escape(str(row.get(header, '待补充')))}</td>" for header in headers) + "</tr>"
            for row in rows
        )
    return f'<table class="check-table"><thead><tr>{header_html}</tr></thead><tbody>{body}</tbody></table>'


def _kv_html(items: list[tuple[str, str]]) -> str:
    return "<dl class=\"kv-list\">" + "".join(
        f"<dt>{escape(str(label))}</dt><dd>{escape(str(value or '待补充'))}</dd>"
        for label, value in items
    ) + "</dl>"


def _list_html(items: list[str], fallback: str = "待补充") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return f"<p>{escape(fallback)}</p>"
    return "<ul class=\"clean-list\">" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"


def _asset_section_html(title: str, caption: str, body_html: str) -> str:
    return (
        '<div class="asset-section">'
        f'<div class="evidence-title">{escape(title)}</div>'
        f'<p class="check-note">{escape(caption)}</p>'
        f'{body_html}'
        '</div>'
    )


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
        eyebrow="样本维护",
        title=config.title,
        question=config.question,
        stats=hero_stats,
    )

    # 自动初始化 samples.json（从已有 task/gold 生成，幂等）
    samples = sr.load_samples()
    if not samples:
        render_empty_state("暂无可展示的样本。请检查 data/tasks.csv 与 data/gold_answers.json 是否存在。")
        return

    if ds.database_ready():
        st.caption("数据口径：样本库是正式评测样本的维护入口；新增和编辑会同步任务题、理想回复标准 / Gold Answer 与 Rubric 评分标准。")
    else:
        st.warning("当前未初始化 SQLite 数据层。样本库仍可作为本地管理视图运行，但新增或编辑内容不会进入正式测试。")

    task_records, gold_map, rubric_dimensions = _page_readiness_inputs(data, samples)
    readiness_map = build_sample_readiness_map(samples, task_records, gold_map, rubric_dimensions)

    render_numbered_section("01", "筛选与搜索", "按状态、场景、难度、错误标签筛选，或使用关键词搜索。")
    status, scenario, difficulty, error_tag, keyword = _render_filters(samples)

    filtered = sr.filter_samples(status=status, scenario=scenario, difficulty=difficulty, error_tag=error_tag)
    if keyword:
        kw = keyword.lower()
        filtered = [s for s in filtered if kw in _searchable_text(s)]

    render_numbered_section("02", "样本清单", "列表仅保留选择样本所需的摘要信息。")
    if not filtered:
        render_empty_state("没有符合当前筛选条件的样本。")
    else:
        _render_samples_table(filtered, readiness_map)

    render_numbered_section("03", "选中样本详情", "按评测资产结构查看样本内容、标准、评分依据和入库检查。")
    _render_sample_detail(filtered, readiness_map, task_records, gold_map, rubric_dimensions)

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("进入发起测试", key="samples_to_test_run", use_container_width=True):
            st.session_state.current_page = "test_run"
            st.rerun()
    with col2:
        st.caption("发起测试页只展示已入库且通过完整度校验的样本。")

    with st.expander("样本管理", expanded=False):
        _render_sample_management()


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


def _render_samples_table(samples: list[sr.Sample], readiness_map: dict[str, ds.SampleReadiness]) -> None:
    rows = build_sample_table_rows(samples, readiness_map)
    headers = ["样本编号", "任务标题", "场景", "测试状态", "难度", "更新时间"]
    body = "".join(
        (
            f'<tr><td class="sample-id-cell">{escape(row["样本编号"])}</td>'
            f'<td class="sample-title-cell"><span>{escape(row["任务标题"])}</span></td>'
            f'<td class="sample-scenario-cell"><span>{escape(row["场景"])}</span></td>'
            f'<td class="sample-cell-nowrap">{_test_status_badge(row["测试状态"])}</td>'
            f'<td class="sample-cell-nowrap">{escape(row["难度"])}</td>'
            f'<td class="sample-cell-nowrap sample-date-cell">{escape(row["更新时间"])}</td></tr>'
        )
        for row in rows
    )
    header_cells = "".join(f"<th>{escape(name)}</th>" for name in headers)
    colgroup = (
        "<colgroup>"
        '<col class="sample-col-id">'
        '<col class="sample-col-title">'
        '<col class="sample-col-scenario">'
        '<col class="sample-col-status">'
        '<col class="sample-col-difficulty">'
        '<col class="sample-col-date">'
        "</colgroup>"
    )
    table_html = (
        '<div class="sample-index-scroll">'
        f'<table class="check-table sample-index-table">{colgroup}<thead><tr>{header_cells}</tr></thead>'
        f'<tbody>{body}</tbody></table>'
        '</div>'
    )
    render_evidence_panel("样本列表", table_html)


def _render_sample_detail(
    samples: list[sr.Sample],
    readiness_map: dict[str, ds.SampleReadiness],
    task_records: list[dict],
    gold_map: dict,
    rubric_dimensions: list[dict] | None,
) -> None:
    if not samples:
        render_empty_state("没有可查看的样本。")
        return

    sample_ids = [s.sample_id for s in samples]
    selected_id = st.selectbox("选择样本", sample_ids, key="samples_detail_select")
    sample = sr.get_sample(selected_id)
    if sample is None:
        render_empty_state("未找到该样本记录。")
        return
    readiness = readiness_map.get(sample.sample_id) or ds.assess_sample_readiness(None, None, [])
    task_by_case = {str(row.get("case_id") or ""): row for row in task_records}
    task_record = task_by_case.get(sample.sample_id) or {}
    gold_record = gold_map.get(sample.sample_id) or sample.gold_answer
    gold_display = parse_gold_answer_for_display(gold_record)
    rubric_rows = build_rubric_rows_for_display(rubric_dimensions, sample.rubric)
    sections = build_sample_asset_sections(
        sample=sample,
        readiness=readiness,
        task_record=task_record,
        gold_display=gold_display,
        rubric_rows=rubric_rows,
    )

    _render_asset_overview(sample, readiness, sections[0])
    left = _task_section_html(sample, task_record, sections[1])
    right = _gold_section_html(gold_display, sections[2])
    render_two_column_panel(left, right)
    _render_rubric_section(rubric_rows, sections[3])
    left = _error_optimization_section_html(sample, sections[4])
    right = _readiness_section_html(readiness, sample, sections[5])
    render_two_column_panel(left, right)


def _render_asset_overview(sample: sr.Sample, readiness: ds.SampleReadiness, section: dict) -> None:
    rows = [
        ("样本编号", sample.sample_id or "待补充"),
        ("标题", sample.title or "待补充"),
        ("场景", sample.scenario or "待补充"),
        ("难度", _difficulty_label(sample.difficulty)),
        ("状态", sample.status or "待复核"),
        ("完整度", readiness.label),
        ("更新时间", sample.updated_at or "未标注"),
    ]
    render_evidence_panel(
        section["title"],
        f'<p class="check-note">{escape(str(section["caption"]))}</p>{_kv_html(rows)}',
    )


def _task_section_html(sample: sr.Sample, task_record: dict, section: dict) -> str:
    task_prompt = task_record.get("question") or sample.task_prompt or "待补充"
    context = task_record.get("context") or sample.business_context or "待补充"
    output_requirement = (
        task_record.get("expected_capability")
        or task_record.get("task_type")
        or "按任务题和业务背景输出尽调判断、依据与需进一步核查事项。"
    )
    body = (
        _kv_html([
            ("任务题", str(task_prompt)),
            ("业务背景", str(context)),
            ("输出要求 / 考察能力", str(output_requirement)),
        ])
    )
    return _asset_section_html(str(section["title"]), str(section["caption"]), body)


def _gold_section_html(gold_display: dict, section: dict) -> str:
    fields = gold_display.get("fields", {})
    lists = gold_display.get("lists", {})
    fallback = str(gold_display.get("fallback_text") or "").strip()
    body = _kv_html([
        ("核心结论", fields.get("核心结论", "待补充")),
        ("关键依据", fields.get("关键依据", "待补充")),
        ("边界条件", fields.get("边界条件", "待补充")),
        ("人工复核提示", fields.get("人工复核提示", "待补充")),
    ])
    body += '<div class="text-block-label">必须覆盖点</div>' + _list_html(lists.get("必须覆盖点", []))
    body += '<div class="text-block-label">不可接受错误</div>' + _list_html(lists.get("不可接受错误", []))
    if fallback:
        body += f'<p class="check-note">未识别为结构化 JSON，以下按原文展示：{escape(fallback)}</p>'
    return _asset_section_html(str(section["title"]), str(section["caption"]), body)


def _render_rubric_section(rubric_rows: list[dict[str, str]], section: dict) -> None:
    table = _table_html(
        ["评分维度", "满分", "满分标准", "扣分规则", "关联错误类型或说明"],
        rubric_rows,
    )
    render_evidence_panel(
        str(section["title"]),
        f'<p class="check-note">{escape(str(section["caption"]))}</p>{table}',
    )


def _error_optimization_section_html(sample: sr.Sample, section: dict) -> str:
    body = '<div class="text-block-label">错误标签</div>'
    body += _list_html(sample.error_tags, fallback="暂无关联错误标签")
    body += '<div class="text-block-label">常见模型问题</div>'
    body += _list_html(sample.model_answers, fallback="暂无历史模型回答记录")
    body += '<div class="text-block-label">数据优化建议</div>'
    body += _list_html(sample.improvement_suggestions, fallback="暂无优化建议")
    return _asset_section_html(str(section["title"]), str(section["caption"]), body)


def _readiness_section_html(readiness: ds.SampleReadiness, sample: sr.Sample, section: dict) -> str:
    rows = [
        ("是否可进入测试", "是" if readiness.is_testable else "否"),
        ("检查结果", readiness.label),
        ("缺失项", "；".join(readiness.missing_items) if readiness.missing_items else "—"),
        ("复核备注", sample.reviewer_note or "未填写"),
        ("创建时间", sample.created_at or "未标注"),
        ("更新时间", sample.updated_at or "未标注"),
    ]
    body = _kv_html(rows)
    body += '<div class="text-block-label">已满足项</div>' + _list_html(readiness.satisfied_items, fallback="待补充")
    return _asset_section_html(str(section["title"]), str(section["caption"]), body)


def _render_readiness_panel(readiness: ds.SampleReadiness) -> None:
    rows = [
        ("是否可进入测试", "是" if readiness.is_testable else "否"),
        ("检查结果", readiness.label),
        ("已满足项", "；".join(readiness.satisfied_items) if readiness.satisfied_items else "—"),
        ("缺失项", "；".join(readiness.missing_items) if readiness.missing_items else "—"),
        ("原因", "；".join(readiness.reasons) if readiness.reasons else "已满足测试准入条件"),
    ]
    body = "".join(
        f"<tr><td>{escape(key)}</td><td>{escape(value)}</td></tr>"
        for key, value in rows
    )
    render_evidence_panel(
        "样本完整度 / 入库检查",
        f'<table class="check-table"><tbody>{body}</tbody></table>',
    )


def _render_sample_management() -> None:
    if ds.database_ready():
        st.caption("管理区维护正式评测资产，并保留 samples.json 作为轻量视图、导入导出和兼容备份。")
    else:
        st.warning("SQLite 未初始化，管理区只能写入本地样本视图；这些记录不能进入发起测试。")
    tab_create, tab_edit, tab_status, tab_backup = st.tabs(["新增样本", "编辑样本", "状态管理", "导入导出"])
    with tab_create:
        _render_create_form()
    with tab_edit:
        _render_edit_form()
    with tab_status:
        _render_status_transition()
        _render_archive_form()
    with tab_backup:
        _render_backup_controls()
        st.caption(
            "样本管理记录保存在本地样本文件；部署到无持久化卷的环境时，新增、编辑、归档内容可能随会话结束而丢失。"
        )


def _render_backup_controls() -> None:
    st.markdown("**备份与恢复**")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="导出样本库 JSON",
            data=sr.export_samples_json(),
            file_name="samples.json",
            mime="application/json",
            key="samples_export",
        )
    with col2:
        uploaded = st.file_uploader("导入样本库 JSON", type=["json"], key="samples_import")
        if uploaded is not None:
            if st.button("确认导入并合并", key="samples_import_confirm"):
                try:
                    raw = json.loads(uploaded.getvalue().decode("utf-8"))
                    sr.import_samples(raw, db_path=_formal_db_path_for_ui())
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success("导入成功，样本已合并到当前库。")
                    st.rerun()


def _render_create_form() -> None:
    with st.form("samples_create", clear_on_submit=True):
        sample_id = st.text_input("样本编号", help="唯一编号。")
        title = st.text_input("标题")
        col1, col2 = st.columns(2)
        scenario = col1.text_input("场景")
        difficulty = col2.selectbox(
            "难度",
            _DIFFICULTY_OPTIONS,
            format_func=lambda v: DIFFICULTY_LABELS.get(v, v) if v else "未标注",
            key="samples_create_difficulty",
        )
        task_prompt = st.text_area("任务描述", height=110)
        business_context = st.text_area("业务背景", height=80)
        gold_answer = st.text_area("理想回复标准 / Gold Answer *", height=120, help="可填写文本或 JSON。")
        rubric = st.text_area("Rubric 评分标准 *", height=80, help="可填写文本或 JSON。")
        col3, col4 = st.columns(2)
        model_answers = col3.text_area("模型回答（每行一条）", height=80)
        error_tags = col4.text_area("错误标签（每行一条）", height=80)
        improvement_suggestions = st.text_area("优化建议（每行一条）", height=80)
        reviewer_note = st.text_area("复核备注", height=60)
        status = st.selectbox("状态 *", sr.SAMPLE_STATUSES, key="samples_create_status")
        submitted = st.form_submit_button("新增样本")

    if submitted:
        try:
            sr.create_sample(
                {
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
                },
                db_path=_formal_db_path_for_ui(),
            )
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
        title = st.text_input("标题", value=sample.title)
        col1, col2 = st.columns(2)
        scenario = col1.text_input("场景", value=sample.scenario)
        difficulty = col2.selectbox(
            "难度",
            _DIFFICULTY_OPTIONS,
            index=_index_of(_DIFFICULTY_OPTIONS, sample.difficulty),
            format_func=lambda v: DIFFICULTY_LABELS.get(v, v) if v else "未标注",
            key="samples_edit_difficulty",
        )
        task_prompt = st.text_area("任务描述", value=sample.task_prompt, height=110)
        business_context = st.text_area("业务背景", value=sample.business_context, height=80)
        gold_answer = st.text_area("理想回复标准 / Gold Answer *", value=sample.gold_answer, height=120)
        rubric = st.text_area("Rubric 评分标准 *", value=sample.rubric, height=80)
        col3, col4 = st.columns(2)
        model_answers = col3.text_area("模型回答（每行一条）", value=_as_lines(sample.model_answers), height=80)
        error_tags = col4.text_area("错误标签（每行一条）", value=_as_lines(sample.error_tags), height=80)
        improvement_suggestions = st.text_area(
            "优化建议（每行一条）", value=_as_lines(sample.improvement_suggestions), height=80
        )
        reviewer_note = st.text_area("复核备注", value=sample.reviewer_note, height=60)
        status = st.selectbox(
            "状态 *",
            sr.SAMPLE_STATUSES,
            index=sr.SAMPLE_STATUSES.index(sample.status),
            key="samples_edit_status",
        )
        save = st.form_submit_button("保存修改")

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
                db_path=_formal_db_path_for_ui(),
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
            disabled = False
            projected = None
            if new_status == "已入库" and ds.database_ready():
                projected = _entry_readiness_for_sample(sample)
                disabled = not projected.is_testable
                if disabled:
                    st.caption("暂不能设为已入库：" + _missing_summary(projected, limit=5))
            if st.button(
                f"设为「{new_status}」",
                key=f"samples_status_{selected_id}_{new_status}",
                disabled=disabled,
            ):
                try:
                    sr.set_sample_status(selected_id, new_status, db_path=_formal_db_path_for_ui())
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success(f"样本 {selected_id} 已变更为 {new_status}。")
                    st.rerun()


def _entry_readiness_for_sample(sample: sr.Sample) -> ds.SampleReadiness:
    task = ds.get_task_case(sample.sample_id) or {
        "case_id": sample.sample_id,
        "question": sample.task_prompt,
        "context": sample.business_context,
        "scenario": sample.scenario,
    }
    task = {**task, "status": ds.ACTIVE_STATUS}
    gold = ds.get_gold_answer_record(sample.sample_id) or _parse_gold_for_local_check(sample)
    return ds.assess_sample_readiness(task, gold, ds.get_testable_rubric_dimensions())


def _parse_gold_for_local_check(sample: sr.Sample) -> dict:
    try:
        parsed = json.loads(sample.gold_answer)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        text = str(sample.gold_answer or "").strip()
        return {"core_conclusion": text} if text else {}


def _render_archive_form() -> None:
    samples = [s for s in sr.load_samples() if s.status != "已归档"]
    if not samples:
        render_empty_state("没有可归档的样本。")
        return

    sample_ids = [s.sample_id for s in samples]
    selected_id = st.selectbox("选择样本归档", sample_ids, key="samples_archive_select")
    if st.button("归档样本", key="samples_archive_btn"):
        try:
            sr.archive_sample(selected_id, db_path=_formal_db_path_for_ui())
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"样本 {selected_id} 已归档。可在高级管理中重新激活。")
            st.rerun()


def _index_of(options: list, value: object) -> int:
    text = "" if value is None else str(value).strip()
    return options.index(text) if text in options else 0
