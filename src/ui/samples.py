"""样本库页面。

基于 app.services.sample_repository 的样本库数据维护：
- 支持按关键词、专业场景、测试状态和完整度筛选；
- 紧凑样本索引只展示当前查询结果；
- 当前样本区用于查看、编辑和移出测试。
"""

from __future__ import annotations

import json
import re
from html import escape

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from app.services import sample_repository as sr
from src.gold_quality import field_list, field_text, field_value
from src.ui.components import (
    document_section_html,
    render_detail_panel,
    render_empty_state,
    render_field_section,
    render_html,
    render_long_text_section,
    render_numbered_section,
    render_page_heading,
)
from src.ui.page_config import get_page_config
from src.ui.labels import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    TASK_TYPE_LABELS,
    display_label,
)


_TEST_STATUS_OPTIONS = ["全部", "可测试", "待补充", "不可测试", "已移出测试"]
_COMPLETENESS_OPTIONS = ["全部", "通过", "待补充", "已移出测试"]
PROFESSIONAL_SCENE_OPTIONS = ["财务场景", "法律场景", "投行场景"]
_PROFESSIONAL_SCENE_TO_DOMAIN = {
    "财务场景": "Financial",
    "法律场景": "Legal",
    "投行场景": "Capital Markets",
}
_DOMAIN_TO_PROFESSIONAL_SCENE = {
    "finance": "财务场景",
    "financial": "财务场景",
    "财务": "财务场景",
    "财务尽调": "财务场景",
    "财务场景": "财务场景",
    "legal": "法律场景",
    "法律": "法律场景",
    "法律审阅": "法律场景",
    "法律审核": "法律场景",
    "法律场景": "法律场景",
    "ib": "投行场景",
    "investment_banking": "投行场景",
    "investment banking": "投行场景",
    "capital markets": "投行场景",
    "资本市场": "投行场景",
    "投行": "投行场景",
    "投行场景": "投行场景",
}
OUTPUT_REQUIREMENT_OPTIONS = [
    "结论 + 主要依据 + 需核查事项",
    "问题判断 + 风险说明 + 整改建议",
    "条款判断 + 依据 + 修改建议",
    "财务影响判断 + 核查路径 + 风险边界",
    "自定义",
]
DIFFICULTY_FORM_OPTIONS = ["基础", "中等", "复杂"]
RISK_LEVEL_OPTIONS = ["低", "中", "高"]
_SAMPLE_TABLE_COLUMNS = ["样本编号", "任务标题", "专业场景", "测试状态", "完整度", "更新时间", "操作"]
_CSV_TEMPLATE_COLUMNS = [
    "case_id",
    "title",
    "professional_scene",
    "status",
    "question",
    "context",
    "output_requirement",
    "standard_conclusion",
    "key_evidence",
    "must_have_points",
    "unacceptable_errors",
    "boundary_and_check_items",
    "difficulty",
    "risk_level",
    "manual_review_notes",
    "reviewer_note",
    "scoring_focus",
]
_SIMPLIFIED_REQUIRED_CSV_COLUMNS = [
    "case_id",
    "title",
    "professional_scene",
    "status",
    "question",
    "context",
    "standard_conclusion",
    "must_have_points",
    "unacceptable_errors",
]
_LEGACY_REQUIRED_CSV_COLUMNS = [
    "case_id",
    "title",
    "scenario",
    "question",
    "gold_core_conclusion",
    "gold_must_have_points",
    "gold_unacceptable_errors",
    "rubric_dimension_name",
    "rubric_full_mark",
    "rubric_full_mark_standard",
    "rubric_deduction_rules",
    "status",
]

_DIFFICULTY_OPTIONS = list(DIFFICULTY_LABELS.keys())


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
    text = str(value or "").strip()
    mapped = {
        "Easy": "基础",
        "Medium": "中等",
        "Hard": "复杂",
        "低": "基础",
        "中": "中等",
        "高": "复杂",
    }
    return mapped.get(text) or DIFFICULTY_LABELS.get(text, text or "未标注")


def _professional_scene_from_value(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    direct = _DOMAIN_TO_PROFESSIONAL_SCENE.get(text)
    if direct:
        return direct
    lower = text.lower().replace("-", "_")
    return _DOMAIN_TO_PROFESSIONAL_SCENE.get(lower, "")


def _domain_from_professional_scene(value) -> str:
    scene = _professional_scene_from_value(value) or str(value or "").strip()
    return _PROFESSIONAL_SCENE_TO_DOMAIN.get(scene, "")


def _professional_scene_label(task_record: dict | None, sample: sr.Sample | None = None) -> str:
    task_record = task_record or {}
    scene = _professional_scene_from_value(task_record.get("domain"))
    if scene:
        return scene
    if sample is not None:
        scene = _professional_scene_from_value(getattr(sample, "domain", ""))
        if scene:
            return scene
    return "待补充"


def _difficulty_form_value(value) -> str:
    label = _difficulty_label(value)
    return label if label in DIFFICULTY_FORM_OPTIONS else "中等"


def _risk_level_form_value(value) -> str:
    text = str(value or "").strip()
    mapping = {
        "Low": "低",
        "Medium": "中",
        "High": "高",
        "低风险": "低",
        "中风险": "中",
        "高风险": "高",
    }
    normalized = mapping.get(text, text)
    return normalized if normalized in RISK_LEVEL_OPTIONS else "中"


def _output_requirement_for_form(value) -> tuple[str, str]:
    text = str(value or "").strip()
    if text in OUTPUT_REQUIREMENT_OPTIONS[:-1]:
        return text, ""
    return "自定义", text


def _test_status_label(sample: sr.Sample, readiness: ds.SampleReadiness) -> str:
    if sample.status == sr.REMOVED_FROM_TEST_STATUS or readiness.label == "已移出测试":
        return "已移出测试"
    if readiness.is_testable:
        return "可测试"
    if readiness.missing_items:
        return "待补充"
    return "不可测试"


def _sample_status_label(sample: sr.Sample) -> str:
    return sample.status or "待复核"


def _domain_label(task_record: dict, sample: sr.Sample | None = None) -> str:
    return _professional_scene_label(task_record, sample)


def _completeness_label(sample: sr.Sample, readiness: ds.SampleReadiness) -> str:
    if sample.status == sr.REMOVED_FROM_TEST_STATUS or readiness.label == "已移出测试":
        return "已移出测试"
    return "通过" if readiness.is_testable else "待补充"


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
    task_records: list[dict] | None = None,
) -> list[dict[str, str]]:
    """构建样本列表摘要行，避免把长文本资产铺在表格里。"""
    task_by_case = {str(row.get("case_id") or ""): row for row in (task_records or [])}
    rows: list[dict[str, str]] = []
    for sample in samples:
        readiness = readiness_map.get(sample.sample_id) or ds.assess_sample_readiness(None, None, [])
        test_status = _test_status_label(sample, readiness)
        task_record = task_by_case.get(sample.sample_id) or {}
        rows.append({
            "样本编号": sample.sample_id or "待补充",
            "任务标题": _truncate(sample.title, 44),
            "专业场景": _professional_scene_label(task_record, sample),
            "测试状态": test_status,
            "完整度": _completeness_label(sample, readiness),
            "更新时间": _format_date(sample.updated_at),
            "操作": "查看",
        })
    return rows


def _filter_samples_for_index(
    samples: list[sr.Sample],
    readiness_map: dict[str, ds.SampleReadiness],
    task_records: list[dict] | None = None,
    *,
    keyword: str,
    domain: str,
    test_status: str,
    completeness: str,
) -> list[sr.Sample]:
    """Apply the sample-index filters without exposing long-form fields in the table."""
    task_by_case = {str(row.get("case_id") or ""): row for row in (task_records or [])}
    filtered = samples
    if domain != "全部":
        filtered = [
            sample for sample in filtered
            if _professional_scene_label(task_by_case.get(sample.sample_id) or {}, sample) == domain
        ]
    if test_status != "全部":
        filtered = [
            sample
            for sample in filtered
            if _test_status_label(
                sample,
                readiness_map.get(sample.sample_id)
                or ds.assess_sample_readiness(None, None, []),
            ) == test_status
        ]
    if completeness != "全部":
        filtered = [
            sample
            for sample in filtered
            if _completeness_label(
                sample,
                readiness_map.get(sample.sample_id)
                or ds.assess_sample_readiness(None, None, []),
            ) == completeness
        ]
    kw = str(keyword or "").strip().lower()
    if kw:
        filtered = [sample for sample in filtered if kw in _searchable_text(sample)]
    return filtered


def parse_gold_answer_for_display(value) -> dict:
    """解析专业标准答案为详情页展示结构。JSON 异常时保留原文。"""
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
            "标准结论": field_text(gold, "core_conclusion", "待补充"),
            "关键依据": field_text(gold, "key_evidence", "待补充"),
            "边界与需核查事项": (
                field_text(gold, "boundary_conditions", "")
                or field_text(gold, "materials_to_check", "待补充")
            ),
            "人工复核提示": field_text(gold, "manual_review_notes", "待补充"),
            "本题评分关注点": field_text(gold, "scoring_focus", "待补充"),
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
    """构建评分标准展示矩阵，维度来自正式数据层或统一配置。"""
    if not rubric_dimensions:
        return []
    overrides = _rubric_overrides(rubric_source)
    rows: list[dict[str, str]] = []
    for dim in rubric_dimensions:
        if not isinstance(dim, dict):
            continue
        field = _rubric_field(dim)
        merged = {**dim, **overrides.get(field, {})}
        normalized = {
            "field": field,
            "name": _clean_text(merged.get("name") or merged.get("dimension"), fallback=""),
            "full_mark": merged.get("full_mark") or merged.get("weight"),
            "full_mark_standard": _clean_text(merged.get("full_mark_standard"), fallback=""),
            "deduction_rules": _clean_text(merged.get("deduction_rules"), fallback=""),
        }
        missing = ds.rubric_dimension_missing_items(normalized)
        if missing:
            rows.append({
                "评分维度": normalized["name"] or field or "待补充",
                "满分": _clean_text(normalized["full_mark"], fallback="待补充"),
                "缺失项": "；".join(missing),
            })
            continue
        rows.append({
            "评分维度": normalized["name"],
            "满分": _clean_text(normalized["full_mark"], fallback="待补充"),
            "满分标准": normalized["full_mark_standard"],
            "扣分规则": normalized["deduction_rules"],
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
    rubric_title = "评分标准" if _rubric_rows_are_complete(rubric_rows) else "评分维度配置"
    rubric_caption = (
        "裁判评分链路使用的维度、满分标准和扣分规则。"
        if rubric_title == "评分标准"
        else "当前仅展示评分维度和满分，缺失项需补齐后才可作为完整评分标准。"
    )
    return [
        {
            "title": "基础信息",
            "caption": "样本在样本库中的业务状态和基础标识。",
        },
        {
            "title": "任务内容",
            "caption": "被测模型只看到任务题、业务背景和输出要求，不看到专业标准答案、评分标准或红线错误。",
        },
        {
            "title": "专业标准答案",
            "caption": "裁判评分链路使用的评判锚点，包含应答方向、关键依据和红线边界。",
        },
        {
            "title": rubric_title,
            "caption": rubric_caption,
        },
        {
            "title": "历史运行与优化",
            "caption": "只读展示历史模型回答、错误标签和数据优化建议，不在新增或编辑时填写。",
        },
        {
            "title": "准入检查",
            "caption": "说明样本为什么可以或不能进入发起评测，并保留人工复核备注。",
        },
    ]


# --------------------------------------------------------------------------- #
# Backward-compatible helpers (kept for existing tests)
# --------------------------------------------------------------------------- #
def build_case_overview_rows(data) -> list[dict]:
    """One compact row per task, with answer-standard / model-answer / error-label
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
        ("专业标准答案覆盖", f"{with_gold}/{total}"),
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


def _empty_if_pending(value: str) -> str:
    text = str(value or "").strip()
    return "" if text in {"待补充", "暂无记录", "未标注", "—"} else text


def _safe_json_load(value):
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _gold_defaults(value) -> dict[str, str]:
    display = parse_gold_answer_for_display(value)
    fields = display.get("fields", {})
    lists = display.get("lists", {})
    fallback = str(display.get("fallback_text") or "").strip()
    return {
        "core_conclusion": _empty_if_pending(fields.get("标准结论", "")) or fallback,
        "key_evidence": _empty_if_pending(fields.get("关键依据", "")),
        "boundary_conditions": _empty_if_pending(fields.get("边界与需核查事项", "")),
        "manual_review_notes": _empty_if_pending(fields.get("人工复核提示", "")),
        "scoring_focus": _empty_if_pending(fields.get("本题评分关注点", "")),
        "must_have_points": _as_lines(lists.get("必须覆盖点", [])),
        "unacceptable_errors": _as_lines(lists.get("不可接受错误", [])),
    }


def _build_gold_answer_json(
    *,
    sample_id: str,
    core_conclusion: str,
    key_evidence: str,
    must_have_points: str,
    unacceptable_errors: str,
    boundary_conditions: str,
    manual_review_notes: str,
    scoring_focus: str = "",
) -> str:
    payload = {
        "case_id": str(sample_id or "").strip(),
        "core_conclusion": str(core_conclusion or "").strip(),
        "key_evidence": str(key_evidence or "").strip(),
        "must_have_points": _parse_lines(must_have_points),
        "unacceptable_errors": _parse_lines(unacceptable_errors),
        "boundary_conditions": str(boundary_conditions or "").strip(),
        "materials_to_check": str(boundary_conditions or "").strip(),
        "manual_review_notes": str(manual_review_notes or "").strip(),
        "scoring_focus": str(scoring_focus or "").strip(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _rubric_items(value) -> list[dict]:
    parsed = _safe_json_load(value)
    if isinstance(parsed, dict):
        if isinstance(parsed.get("dimensions"), list):
            raw_items = parsed["dimensions"]
        elif isinstance(parsed.get("rubric"), dict) and isinstance(parsed["rubric"].get("dimensions"), list):
            raw_items = parsed["rubric"]["dimensions"]
        else:
            raw_items = [parsed]
    elif isinstance(parsed, list):
        raw_items = parsed
    else:
        raw_items = []
    return [dict(item) for item in raw_items if isinstance(item, dict)]


def _to_int(value, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _rubric_defaults(value, rubric_dimensions: list[dict] | None) -> dict[str, object]:
    items = _rubric_items(value)
    overrides = {field: item for item in items if (field := _rubric_field(item))}
    global_by_field = {
        _rubric_field(item): item
        for item in (rubric_dimensions or [])
        if isinstance(item, dict) and _rubric_field(item)
    }
    selected_field = next(iter(overrides), "") or next(iter(global_by_field), "")
    raw_item = overrides.get(selected_field) or (items[0] if items else {})
    base = global_by_field.get(selected_field, {})
    merged = {**base, **raw_item}
    return {
        "field": selected_field or _rubric_field(merged),
        "name": _clean_text(merged.get("name") or merged.get("dimension"), fallback=""),
        "full_mark": _to_int(merged.get("full_mark") or merged.get("weight"), fallback=10),
        "full_mark_standard": _clean_text(merged.get("full_mark_standard"), fallback=""),
        "deduction_rules": _clean_text(merged.get("deduction_rules"), fallback=""),
        "items": items,
    }


def _build_rubric_json(
    *,
    existing_rubric,
    dimension_field: str,
    dimension_name: str,
    full_mark: int,
    full_mark_standard: str,
    deduction_rules: str,
) -> str:
    field = str(dimension_field or dimension_name or "").strip()
    name = str(dimension_name or field).strip()
    items = _rubric_items(existing_rubric)
    updated = {
        "dimension_field": field,
        "field": field,
        "name": name,
        "full_mark": int(full_mark or 0),
        "full_mark_standard": str(full_mark_standard or "").strip(),
        "deduction_rules": str(deduction_rules or "").strip(),
        "status": ds.ACTIVE_STATUS,
    }

    replaced = False
    next_items: list[dict] = []
    for item in items:
        if _rubric_field(item) == field:
            next_items.append({**item, **updated})
            replaced = True
        else:
            next_items.append(item)
    if field and not replaced:
        next_items.append(updated)
    return json.dumps(next_items, ensure_ascii=False, indent=2)


def _default_scoring_standard_json(rubric_dimensions: list[dict] | None) -> str:
    items: list[dict] = []
    for dimension in rubric_dimensions or []:
        if not isinstance(dimension, dict):
            continue
        field = _rubric_field(dimension)
        name = str(dimension.get("name") or dimension.get("dimension") or field).strip()
        if not field and not name:
            continue
        items.append({
            "dimension_field": field or name,
            "field": field or name,
            "name": name or field,
            "full_mark": _to_int(dimension.get("full_mark") or dimension.get("weight"), fallback=0),
            "full_mark_standard": str(dimension.get("full_mark_standard") or "").strip(),
            "deduction_rules": str(dimension.get("deduction_rules") or "").strip(),
            "status": dimension.get("status") or ds.ACTIVE_STATUS,
        })
    return json.dumps(items, ensure_ascii=False, indent=2) if items else ""


def _rubric_dimensions_for_check(
    rubric_json: str,
    fallback_dimensions: list[dict] | None,
) -> list[dict]:
    fallback = fallback_dimensions or []
    if ds.has_rubric_criteria(fallback):
        return fallback
    dimensions: list[dict] = []
    for item in _rubric_items(rubric_json):
        field = _rubric_field(item)
        if not field:
            continue
        dimensions.append({
            "field": field,
            "name": _clean_text(item.get("name") or item.get("dimension"), fallback=field),
            "full_mark": _to_int(item.get("full_mark") or item.get("weight"), fallback=0),
            "full_mark_standard": _clean_text(item.get("full_mark_standard"), fallback=""),
            "deduction_rules": _clean_text(item.get("deduction_rules"), fallback=""),
        })
    return dimensions


def _readiness_for_dialog_values(
    values: dict,
    rubric_dimensions: list[dict] | None,
) -> ds.SampleReadiness:
    gold = _safe_json_load(values.get("gold_answer")) or {}
    task = {
        "case_id": str(values.get("sample_id") or "").strip(),
        "question": str(values.get("task_prompt") or "").strip(),
        "context": str(values.get("business_context") or "").strip(),
        "scenario": str(values.get("scenario") or "").strip(),
        "status": sr.formal_status_for_sample_status(str(values.get("status") or "待复核")),
    }
    return ds.assess_sample_readiness(
        task,
        gold if isinstance(gold, dict) else {},
        _rubric_dimensions_for_check(str(values.get("rubric") or ""), rubric_dimensions),
    )


def _validate_active_dialog_values(values: dict, rubric_dimensions: list[dict] | None) -> bool:
    if values.get("status") != "已入库":
        return True
    readiness = _readiness_for_dialog_values(values, rubric_dimensions)
    if readiness.is_testable:
        return True
    st.error("暂不能设为已入库：" + _missing_summary(readiness, limit=8))
    return False


def _clear_dialog_state() -> None:
    for key in ("samples_dialog_mode", "samples_edit_id", "samples_archive_confirm_id"):
        st.session_state.pop(key, None)


def _open_create_dialog() -> None:
    st.session_state["samples_dialog_mode"] = "create"
    st.session_state.pop("samples_edit_id", None)
    st.session_state.pop("samples_archive_confirm_id", None)


def _open_edit_dialog(sample_id: str) -> None:
    st.session_state["samples_dialog_mode"] = "edit"
    st.session_state["samples_edit_id"] = sample_id
    st.session_state.pop("samples_archive_confirm_id", None)


def _open_import_csv_dialog() -> None:
    st.session_state["samples_dialog_mode"] = "import_csv"
    st.session_state.pop("samples_edit_id", None)
    st.session_state.pop("samples_archive_confirm_id", None)


def _open_archive_dialog(sample_id: str) -> None:
    st.session_state["samples_archive_confirm_id"] = sample_id
    st.session_state.pop("samples_dialog_mode", None)
    st.session_state.pop("samples_edit_id", None)


def _select_sample(sample_id: str) -> None:
    st.session_state["samples_selected_id"] = sample_id


def _format_source_status_caption(status: dict) -> str:
    return f"当前数据源：{status.get('source', '未知')}。{status.get('message', '')}"


def _render_sample_source_status() -> None:
    status = sr.sample_data_source_status()
    st.caption(_format_source_status_caption(status))
    if not status.get("sqlite_ready"):
        st.caption("seed 文件只用于初始化；samples.json 是样本库管理视图，不是发起评测的唯一正式源。")


def _store_sample_operation_message(message: str, level: str = "success") -> None:
    st.session_state["samples_operation_message"] = {"message": message, "level": level}


def _render_sample_operation_message() -> None:
    payload = st.session_state.get("samples_operation_message")
    if isinstance(payload, dict):
        message = str(payload.get("message") or "")
        level = str(payload.get("level") or "success")
    elif payload:
        message = str(payload)
        level = "success"
    else:
        return
    if level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    elif level == "info":
        st.info(message)
    else:
        st.success(message)


def _sync_samples_to_formal_assets() -> None:
    result = sr.sync_all_samples_to_formal_assets(db_path=_formal_db_path_for_ui())
    failures = result.get("failures") or []
    level = "success" if result.get("sqlite_ready") and not result.get("failed_count") else "warning"
    message = str(result.get("message") or "同步完成。")
    if failures:
        first = failures[0]
        message += f" 首条失败：{first.get('case_id', '未知样本')}：{first.get('reason', '未知原因')}"
    _store_sample_operation_message(message, level=level)


def _formal_sync_feedback_suffix() -> tuple[str, str]:
    status = sr.sample_data_source_status()
    if status.get("sqlite_ready"):
        return "已同步正式评测资产。", "success"
    return "已写入样本库视图，但当前 SQLite 不可用，尚未写入正式评测资产。", "warning"


# --------------------------------------------------------------------------- #
# New sample-library UI
# --------------------------------------------------------------------------- #
def _render_samples_title_bar(config) -> None:
    col1, col2, col3, col4 = st.columns([3.7, 0.9, 0.9, 1.35], gap="small")
    with col1:
        render_page_heading(config.title, config.question)
    with col2:
        st.write("")
        if st.button("新增样本", key="samples_create_open", type="secondary", use_container_width=True):
            _open_create_dialog()
    with col3:
        st.write("")
        if st.button("导入 CSV", key="samples_import_csv_open", type="secondary", use_container_width=True):
            _open_import_csv_dialog()
    with col4:
        st.write("")
        if st.button("同步样本库", key="samples_sync_assets", type="tertiary", use_container_width=True):
            _sync_samples_to_formal_assets()
            st.rerun()
    _render_sample_operation_message()
    _render_sample_source_status()


def render_samples_page(data_bundle: dict) -> None:
    data = data_bundle["data"]
    config = get_page_config("samples")

    _render_samples_title_bar(config)

    # 自动初始化 samples.json（从已有 task/gold 生成，幂等）
    samples = sr.load_samples()
    if not samples:
        render_empty_state("暂无可展示的样本。请检查 data/tasks.csv 与 data/gold_answers.json 是否存在。")
        return

    task_records, gold_map, rubric_dimensions = _page_readiness_inputs(data, samples)
    readiness_map = build_sample_readiness_map(samples, task_records, gold_map, rubric_dimensions)

    render_numbered_section("01", "查询与筛选")
    keyword, domain, test_status, completeness = _render_filters(samples, task_records, readiness_map)
    filtered = _filter_samples_for_index(
        samples,
        readiness_map,
        task_records,
        keyword=keyword,
        domain=domain,
        test_status=test_status,
        completeness=completeness,
    )

    render_numbered_section("02", "样本列表", "展示当前查询结果。")
    if not filtered:
        render_empty_state("没有符合当前条件的样本。")
    else:
        _render_samples_table(filtered, readiness_map, task_records)

    render_numbered_section("03", "当前样本", "选择一个样本，查看评测资产结构。")
    _render_sample_detail(filtered, readiness_map, task_records, gold_map, rubric_dimensions)
    _render_test_run_availability_note(samples, readiness_map)

    _render_pending_dialogs(rubric_dimensions)


def _render_filters(
    samples: list[sr.Sample],
    task_records: list[dict],
    readiness_map: dict[str, ds.SampleReadiness],
) -> tuple[str, str, str, str]:
    domain_options = ["全部"] + PROFESSIONAL_SCENE_OPTIONS

    col1, col2, col3, col4 = st.columns(4)
    keyword = col1.text_input(
        "关键词",
        placeholder="编号、标题、任务题、业务背景",
        key="samples_keyword_search",
    )
    domain = col2.selectbox("专业场景", domain_options, key="samples_filter_domain")
    test_status = col3.selectbox("测试状态", _TEST_STATUS_OPTIONS, key="samples_filter_test_status")
    completeness = col4.selectbox("完整度", _COMPLETENESS_OPTIONS, key="samples_filter_completeness")
    return keyword, domain, test_status, completeness


def _render_samples_table(
    samples: list[sr.Sample],
    readiness_map: dict[str, ds.SampleReadiness],
    task_records: list[dict],
) -> None:
    _ensure_selected_sample(samples)
    rows = build_sample_table_rows(samples, readiness_map, task_records)
    frame = pd.DataFrame(rows, columns=_SAMPLE_TABLE_COLUMNS)
    try:
        event = st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            height=_sample_table_height(len(rows)),
            row_height=34,
            column_config=_sample_table_column_config(),
            key="samples_index_table",
            on_select="rerun",
            selection_mode="single-row",
        )
        selected_index = _selected_dataframe_row_index(event)
        if selected_index is not None and 0 <= selected_index < len(samples):
            _select_sample(samples[selected_index].sample_id)
    except TypeError:
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            height=_sample_table_height(len(rows)),
            column_config=_sample_table_column_config(),
        )
        st.caption("当前环境不支持表格行选择，默认展示查询结果中的第一条样本。")


def _sample_table_height(row_count: int) -> int:
    return min(420, max(118, 42 + row_count * 35))


def _sample_table_column_config() -> dict:
    return {
        "样本编号": st.column_config.TextColumn("样本编号", width="small"),
        "任务标题": st.column_config.TextColumn("任务标题", width="large"),
        "专业场景": st.column_config.TextColumn("专业场景", width="medium"),
        "测试状态": st.column_config.TextColumn("测试状态", width="small"),
        "完整度": st.column_config.TextColumn("完整度", width="small"),
        "更新时间": st.column_config.TextColumn("更新时间", width="small"),
        "操作": st.column_config.TextColumn("操作", width="small"),
    }


def _selected_dataframe_row_index(event) -> int | None:
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    if selection is None:
        return None
    rows = getattr(selection, "rows", None)
    if rows is None and isinstance(selection, dict):
        rows = selection.get("rows")
    if not rows:
        return None
    try:
        return int(rows[0])
    except (TypeError, ValueError, IndexError):
        return None


def _ensure_selected_sample(samples: list[sr.Sample]) -> sr.Sample | None:
    if not samples:
        return None
    sample_ids = [sample.sample_id for sample in samples]
    selected_id = st.session_state.get("samples_selected_id")
    if selected_id not in sample_ids:
        selected_id = sample_ids[0]
        st.session_state["samples_selected_id"] = selected_id
    return next((sample for sample in samples if sample.sample_id == selected_id), samples[0])


def _render_sample_detail(
    samples: list[sr.Sample],
    readiness_map: dict[str, ds.SampleReadiness],
    task_records: list[dict],
    gold_map: dict,
    rubric_dimensions: list[dict] | None,
) -> sr.Sample | None:
    if not samples:
        render_empty_state("没有符合当前条件的样本。")
        return None

    selected = _ensure_selected_sample(samples)
    if selected is None:
        render_empty_state("没有符合当前条件的样本。")
        return None

    selected_id = selected.sample_id
    sample = sr.get_sample(str(selected_id))
    if sample is None:
        sample = next((item for item in samples if item.sample_id == selected_id), None)
        if sample is None:
            render_empty_state("未找到该样本记录。")
            return None
    readiness = readiness_map.get(sample.sample_id) or ds.assess_sample_readiness(None, None, [])
    task_by_case = {str(row.get("case_id") or ""): row for row in task_records}
    task_record = task_by_case.get(sample.sample_id) or {}
    gold_record = gold_map.get(sample.sample_id) or sample.gold_answer
    gold_display = parse_gold_answer_for_display(gold_record)
    rubric_rows = build_rubric_rows_for_display(rubric_dimensions, sample.rubric)
    _render_sample_detail_toolbar(sample, readiness)
    render_sample_detail_panel(sample, readiness, task_record, gold_display, rubric_rows)
    return sample


def _render_test_run_availability_note(
    samples: list[sr.Sample],
    readiness_map: dict[str, ds.SampleReadiness],
) -> None:
    has_testable = any(
        _test_status_label(
            sample,
            readiness_map.get(sample.sample_id) or ds.assess_sample_readiness(None, None, []),
        ) == "可测试"
        for sample in samples
    )
    if has_testable:
        st.caption("完整且已入库的样本可在“发起评测”页使用。")
    else:
        st.caption("当前没有可测试样本。请先补充任务内容、专业标准答案和评分标准。")


def _render_sample_detail_toolbar(sample: sr.Sample, readiness: ds.SampleReadiness) -> None:
    test_status = _test_status_label(sample, readiness)
    completeness = _completeness_label(sample, readiness)
    meta = "｜".join([
        _clean_text(test_status),
        _clean_text(_sample_status_label(sample)),
        f"完整度{_clean_text(completeness)}",
        f"更新：{_format_date(sample.updated_at)}",
    ])
    is_archived = sample.status == sr.REMOVED_FROM_TEST_STATUS
    col_title, col_edit, col_remove = st.columns([5.0, 0.9, 0.9], gap="small")
    with col_title:
        render_html(
            f"""
            <div class="sample-detail-toolbar-title">
                <div>{_html_text(sample.sample_id or "待补充")}｜{_html_text(sample.title or "未命名样本")}</div>
                <span>{escape(meta)}</span>
            </div>
            """
        )
    with col_edit:
        if st.button("编辑样本", key=f"samples_toolbar_edit_{sample.sample_id}", type="secondary", use_container_width=True):
            _open_edit_dialog(sample.sample_id)
    with col_remove:
        if st.button(
            "移出测试",
            key=f"samples_toolbar_remove_{sample.sample_id}",
            type="tertiary",
            disabled=is_archived,
            use_container_width=True,
        ):
            _open_archive_dialog(sample.sample_id)


def render_sample_detail_panel(
    sample: sr.Sample,
    readiness: ds.SampleReadiness,
    task_record: dict,
    gold_display: dict,
    rubric_rows: list[dict[str, str]],
) -> None:
    task_prompt, business_context, output_requirement = _task_markdown_values(sample, task_record)
    test_status = _test_status_label(sample, readiness)
    completeness = _completeness_label(sample, readiness)
    scoring_title = "评分标准" if _rubric_rows_are_complete(rubric_rows) else "评分维度配置"
    body = "".join([
        _detail_section_html("基本信息", _basic_info_html(sample, readiness, task_record, test_status, completeness)),
        _detail_section_html("任务内容", _task_detail_html(task_prompt, business_context, output_requirement)),
        _detail_section_html("专业标准答案", _gold_detail_html(gold_display)),
        _detail_section_html(scoring_title, _rubric_detail_html(rubric_rows)),
        _detail_section_html("准入状态", _readiness_detail_html(sample, readiness)),
        _detail_section_html("历史运行与优化", _error_optimization_detail_html(sample)),
    ])
    render_detail_panel(body)


def _detail_section_html(title: str, content_html: str) -> str:
    return document_section_html(title, content_html)


def _basic_info_html(
    sample: sr.Sample,
    readiness: ds.SampleReadiness,
    task_record: dict,
    test_status: str,
    completeness: str,
) -> str:
    risk_level = task_record.get("risk_level") or getattr(sample, "risk_level", "") or "待补充"
    rows = [
        ("专业场景", _professional_scene_label(task_record, sample)),
        ("难度", _difficulty_label(sample.difficulty or task_record.get("difficulty"))),
        ("风险等级", risk_level),
        ("测试状态", test_status),
        ("样本状态", _sample_status_label(sample)),
        ("完整度", completeness or readiness.label),
        ("更新时间", _format_date(sample.updated_at)),
    ]
    return _kv_grid_html(rows)


def _scenario_detail_html(sample: sr.Sample, task_record: dict) -> str:
    return _field_block_html("任务场景", sample.scenario or task_record.get("scenario") or "待补充")


def _task_detail_html(task_prompt: str, business_context: str, output_requirement: str) -> str:
    return "".join([
        _field_block_html("任务题", task_prompt),
        _field_block_html("业务背景", business_context),
        _field_block_html("输出要求", output_requirement),
    ])


def _gold_detail_html(gold_display: dict) -> str:
    fields = gold_display.get("fields", {})
    lists = gold_display.get("lists", {})
    fallback = str(gold_display.get("fallback_text") or "").strip()
    parts = [
        _field_block_html("标准结论", fields.get("标准结论", "待补充")),
        _field_block_html("关键依据", fields.get("关键依据", "待补充")),
        _list_block_html("必须覆盖点", lists.get("必须覆盖点", [])),
        _list_block_html("不可接受错误", lists.get("不可接受错误", []), tone="risk"),
        _field_block_html("边界与需核查事项", fields.get("边界与需核查事项", "待补充")),
        _field_block_html("人工复核提示", fields.get("人工复核提示", "待补充")),
    ]
    scoring_focus = _empty_if_pending(fields.get("本题评分关注点", ""))
    if scoring_focus:
        parts.append(_field_block_html("本题评分关注点", scoring_focus))
    if fallback:
        parts.append(_field_block_html("标准答案原文", fallback))
    return "".join(parts)


def _task_markdown_values(sample: sr.Sample, task_record: dict) -> tuple[str, str, str]:
    task_prompt = task_record.get("question") or sample.task_prompt or "待补充"
    context = task_record.get("context") or sample.business_context or "待补充"
    output_requirement = (
        task_record.get("expected_capability")
        or getattr(sample, "expected_capability", "")
        or task_record.get("task_type")
        or getattr(sample, "task_type", "")
        or "按任务题和业务背景输出尽调判断、依据与需进一步核查事项。"
    )
    return str(task_prompt), str(context), str(output_requirement)


def _rubric_detail_html(rubric_rows: list[dict[str, str]]) -> str:
    if not rubric_rows:
        return '<p class="sample-detail-text">待补充</p>'
    complete = _rubric_rows_are_complete(rubric_rows)
    headers = ["评分维度", "满分", "满分标准", "扣分规则"] if complete else ["评分维度", "满分", "缺失项"]
    note = (
        ""
        if complete
        else (
            '<p class="sample-detail-text">'
            "当前评分标准仅维护评分维度和满分，尚未完整维护满分标准与扣分规则。"
            "该样本不应作为完整可测样本进入正式评测。"
            "</p>"
        )
    )
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    row_html = ""
    for row in rubric_rows:
        row_html += "<tr>" + "".join(
            f"<td>{_html_multiline(row.get(header), fallback='待补充')}</td>"
            for header in headers
        ) + "</tr>"
    return f'{note}<table class="sample-detail-table"><thead><tr>{header_html}</tr></thead><tbody>{row_html}</tbody></table>'


def _rubric_rows_are_complete(rubric_rows: list[dict[str, str]]) -> bool:
    return bool(rubric_rows) and all(
        "满分标准" in row and "扣分规则" in row and "缺失项" not in row
        for row in rubric_rows
    )


def _readiness_detail_html(sample: sr.Sample, readiness: ds.SampleReadiness) -> str:
    missing_items = "无" if not readiness.missing_items else "；".join(readiness.missing_items)
    satisfied = readiness.satisfied_items or ["待补充"]
    visibility_note = "可进入发起评测" if readiness.is_testable else "—"
    if sample.status == "已入库" and not readiness.is_testable:
        visibility_note = "该样本未进入发起评测：专业标准答案或评分标准未同步到正式资产。"
        if readiness.missing_items:
            visibility_note += " " + "；".join(readiness.missing_items[:4])
    rows = [
        ("是否可测试", "是" if readiness.is_testable else "否"),
        ("当前状态", _sample_status_label(sample)),
        ("检查结果", readiness.label),
        ("发起评测可见性", visibility_note),
        ("缺失项", missing_items),
        ("复核备注", sample.reviewer_note or "未填写"),
    ]
    return _kv_grid_html(rows) + _list_block_html("已满足项", satisfied)


def _error_optimization_detail_html(sample: sr.Sample) -> str:
    if not sample.error_tags and not sample.model_answers and not sample.improvement_suggestions:
        return '<p class="sample-detail-text">暂无历史运行信息</p>'
    return "".join([
        _list_block_html("错误标签", sample.error_tags, fallback="暂无关联错误标签"),
        _list_block_html("常见问题", sample.model_answers, fallback="暂无历史模型回答记录"),
        _list_block_html("数据优化建议", sample.improvement_suggestions, fallback="暂无优化建议"),
    ])


def _kv_grid_html(rows: list[tuple[str, object]]) -> str:
    items = "".join(
        f"""
        <div class="sample-detail-kv">
            <span>{escape(str(label))}</span>
            <strong>{_html_multiline(value)}</strong>
        </div>
        """
        for label, value in rows
    )
    return f'<div class="sample-detail-kv-grid">{items}</div>'


def _field_block_html(label: str, value, fallback: str = "待补充") -> str:
    return render_long_text_section(label, value, fallback=fallback)


def _list_block_html(label: str, items, fallback: str = "待补充", *, tone: str | None = None) -> str:
    return render_field_section(label, items, fallback=fallback, tone=tone)


def _html_text(value, fallback: str = "待补充") -> str:
    return escape(_clean_text(value, fallback=fallback))


def _html_multiline(value, fallback: str = "待补充") -> str:
    return _html_text(value, fallback=fallback).replace("\n", "<br>")


def _csv_template_bytes() -> bytes:
    frame = pd.DataFrame(columns=_CSV_TEMPLATE_COLUMNS)
    return frame.to_csv(index=False).encode("utf-8-sig")


def _csv_list(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = re.split(r"[\n；;|]+", text)
    return "\n".join(part.strip() for part in parts if part.strip())


def _csv_dimension_field(name: str, field: str = "") -> str:
    explicit = str(field or "").strip()
    if explicit:
        return explicit
    text = str(name or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"\W+", "_", text).strip("_")
    return normalized or text


def _parse_samples_csv(frame: pd.DataFrame) -> tuple[list[dict], list[str]]:
    if set(_SIMPLIFIED_REQUIRED_CSV_COLUMNS).issubset(set(frame.columns)):
        return _parse_simplified_samples_csv(frame)
    if set(_LEGACY_REQUIRED_CSV_COLUMNS).issubset(set(frame.columns)):
        return _parse_legacy_samples_csv(frame)

    missing_columns = [column for column in _SIMPLIFIED_REQUIRED_CSV_COLUMNS if column not in frame.columns]
    legacy_missing = [column for column in _LEGACY_REQUIRED_CSV_COLUMNS if column not in frame.columns]
    missing_text = "、".join(missing_columns)
    legacy_text = "、".join(legacy_missing)
    return [], [f"缺少必要字段：{missing_text}。如使用旧模板，还缺少：{legacy_text}。"]


def _parse_simplified_samples_csv(frame: pd.DataFrame) -> tuple[list[dict], list[str]]:
    if frame.empty:
        return [], ["CSV 文件没有可导入记录。"]

    rubric = _default_scoring_standard_json(ds.get_testable_rubric_dimensions() or ds.get_rubric_dimensions())
    records: list[dict] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for idx, row in frame.fillna("").iterrows():
        row_no = int(idx) + 2
        sample_id = str(row.get("case_id", "")).strip()
        if not sample_id:
            errors.append(f"第 {row_no} 行缺少 case_id。")
            continue
        if sample_id in seen_ids:
            errors.append(f"第 {row_no} 行 case_id {sample_id} 在文件内重复。")
            continue
        seen_ids.add(sample_id)

        status = sr.normalize_sample_status(row.get("status", "待复核"))
        scene = str(row.get("professional_scene", "")).strip()
        domain = _domain_from_professional_scene(scene)
        if not domain:
            errors.append(f"第 {row_no} 行 professional_scene 只能为：{'、'.join(PROFESSIONAL_SCENE_OPTIONS)}。")
            continue
        gold_answer = _build_gold_answer_json(
            sample_id=sample_id,
            core_conclusion=str(row.get("standard_conclusion", "")).strip(),
            key_evidence=str(row.get("key_evidence", "")).strip(),
            must_have_points=_csv_list(row.get("must_have_points", "")),
            unacceptable_errors=_csv_list(row.get("unacceptable_errors", "")),
            boundary_conditions=str(row.get("boundary_and_check_items", "")).strip(),
            manual_review_notes=str(row.get("manual_review_notes", "")).strip(),
            scoring_focus=str(row.get("scoring_focus", "")).strip(),
        )
        values = {
            "sample_id": sample_id,
            "title": str(row.get("title", "")).strip(),
            "scenario": str(row.get("title", "")).strip(),
            "task_prompt": str(row.get("question", "")).strip(),
            "business_context": str(row.get("context", "")).strip(),
            "domain": domain,
            "task_type": "",
            "risk_level": _risk_level_form_value(row.get("risk_level", "")),
            "expected_capability": str(row.get("output_requirement", "")).strip(),
            "gold_answer": gold_answer,
            "rubric": rubric,
            "model_answers": [],
            "error_tags": [],
            "improvement_suggestions": [],
            "status": status,
            "difficulty": _difficulty_form_value(row.get("difficulty", "")),
            "reviewer_note": str(row.get("reviewer_note", "")).strip(),
        }
        item_errors = sr.validate_sample(values, existing_ids=set())
        if item_errors:
            errors.append(f"第 {row_no} 行（{sample_id}）：{'；'.join(item_errors)}")
            continue
        records.append(values)
    return records, errors


def _parse_legacy_samples_csv(frame: pd.DataFrame) -> tuple[list[dict], list[str]]:
    if frame.empty:
        return [], ["CSV 文件没有可导入记录。"]

    records: list[dict] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for idx, row in frame.fillna("").iterrows():
        row_no = int(idx) + 2
        sample_id = str(row.get("case_id", "")).strip()
        if not sample_id:
            errors.append(f"第 {row_no} 行缺少 case_id。")
            continue
        if sample_id in seen_ids:
            errors.append(f"第 {row_no} 行 case_id {sample_id} 在文件内重复。")
            continue
        seen_ids.add(sample_id)

        status = sr.normalize_sample_status(row.get("status", "待复核"))
        dimension_name = str(row.get("rubric_dimension_name", "")).strip()
        dimension_field = _csv_dimension_field(dimension_name, str(row.get("rubric_dimension_field", "")).strip())
        full_mark = _to_int(row.get("rubric_full_mark"), fallback=10)
        gold_answer = _build_gold_answer_json(
            sample_id=sample_id,
            core_conclusion=str(row.get("gold_core_conclusion", "")).strip(),
            key_evidence=str(row.get("gold_key_evidence", "")).strip(),
            must_have_points=_csv_list(row.get("gold_must_have_points", "")),
            unacceptable_errors=_csv_list(row.get("gold_unacceptable_errors", "")),
            boundary_conditions=str(row.get("gold_boundary_conditions", "")).strip(),
            manual_review_notes=str(row.get("gold_manual_review_notes", "")).strip(),
        )
        rubric = _build_rubric_json(
            existing_rubric="",
            dimension_field=dimension_field,
            dimension_name=dimension_name or dimension_field,
            full_mark=max(1, full_mark),
            full_mark_standard=str(row.get("rubric_full_mark_standard", "")).strip(),
            deduction_rules=str(row.get("rubric_deduction_rules", "")).strip(),
        )
        values = {
            "sample_id": sample_id,
            "title": str(row.get("title", "")).strip(),
            "scenario": str(row.get("scenario", "")).strip(),
            "task_prompt": str(row.get("question", "")).strip(),
            "business_context": str(row.get("context", "")).strip(),
            "domain": str(row.get("domain", "")).strip(),
            "task_type": str(row.get("task_type", "")).strip(),
            "risk_level": str(row.get("risk_level", "")).strip(),
            "expected_capability": str(row.get("expected_capability", "")).strip(),
            "gold_answer": gold_answer,
            "rubric": rubric,
            "model_answers": [],
            "error_tags": [],
            "improvement_suggestions": [],
            "status": status,
            "difficulty": str(row.get("difficulty", "")).strip(),
            "reviewer_note": "",
        }
        item_errors = sr.validate_sample(values, existing_ids=set())
        if item_errors:
            errors.append(f"第 {row_no} 行（{sample_id}）：{'；'.join(item_errors)}")
            continue
        records.append(values)
    return records, errors


def _import_csv_records(records: list[dict], duplicate_policy: str) -> tuple[int, int, int, list[str]]:
    existing_ids = {sample.sample_id for sample in sr.load_samples()}
    imported = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    for values in records:
        sample_id = str(values.get("sample_id") or "").strip()
        try:
            if sample_id in existing_ids:
                if duplicate_policy == "跳过重复样本":
                    skipped += 1
                    continue
                changes = {key: value for key, value in values.items() if key != "sample_id"}
                sr.update_sample(sample_id, changes, db_path=_formal_db_path_for_ui())
                updated += 1
            else:
                sr.create_sample(values, db_path=_formal_db_path_for_ui())
                existing_ids.add(sample_id)
                imported += 1
        except Exception as exc:
            errors.append(f"{sample_id}：{exc}")
    return imported, updated, skipped, errors


def _render_pending_dialogs(rubric_dimensions: list[dict] | None) -> None:
    mode = st.session_state.get("samples_dialog_mode")
    if mode == "create":
        _render_create_sample_dialog(rubric_dimensions)
    elif mode == "edit":
        sample_id = st.session_state.get("samples_edit_id")
        if sample_id:
            _render_edit_sample_dialog(str(sample_id), rubric_dimensions)
    elif mode == "import_csv":
        _render_import_csv_dialog(rubric_dimensions)

    archive_id = st.session_state.get("samples_archive_confirm_id")
    if archive_id:
        _render_archive_dialog(str(archive_id))


@st.dialog("导入 CSV", width="large")
def _render_import_csv_dialog(rubric_dimensions: list[dict] | None) -> None:
    st.caption("CSV 用于批量新增或更新样本库视图；SQLite 可用时会同步正式评测资产。")
    st.download_button(
        "下载 CSV 模板",
        data=_csv_template_bytes(),
        file_name="samples_template.csv",
        mime="text/csv",
        key="samples_csv_template_download",
    )
    st.caption(
        "默认模板只包含专业场景、任务内容、专业标准答案和可选复核信息；"
        "评分标准由正式数据层统一维护。"
    )
    uploaded = st.file_uploader("上传 CSV 文件", type=["csv"], key="samples_csv_upload")
    if uploaded is None:
        if st.button("取消", key="samples_csv_cancel_empty", type="tertiary"):
            _clear_dialog_state()
            st.rerun()
        return

    try:
        frame = pd.read_csv(uploaded, dtype=str).fillna("")
    except Exception as exc:
        st.error(f"CSV 解析失败：{exc}")
        return

    records, errors = _parse_samples_csv(frame)
    st.markdown("**导入前校验**")
    if errors:
        st.error("字段校验未通过。")
        for error in errors[:8]:
            st.caption(error)
        if len(errors) > 8:
            st.caption(f"另有 {len(errors) - 8} 条错误未展示。")
        if st.button("取消", key="samples_csv_cancel_error", type="tertiary"):
            _clear_dialog_state()
            st.rerun()
        return

    existing_ids = {sample.sample_id for sample in sr.load_samples()}
    duplicate_ids = sorted(
        str(record.get("sample_id"))
        for record in records
        if str(record.get("sample_id")) in existing_ids
    )
    if duplicate_ids:
        shown = "、".join(duplicate_ids[:5])
        suffix = f" 等 {len(duplicate_ids)} 条" if len(duplicate_ids) > 5 else ""
        st.warning(f"发现重复样本：{shown}{suffix}。请选择处理方式。")
        duplicate_policy = st.radio(
            "重复样本处理",
            ["跳过重复样本", "更新已有样本", "取消导入"],
            horizontal=True,
            key="samples_csv_duplicate_policy",
        )
    else:
        duplicate_policy = "跳过重复样本"

    st.caption(f"校验通过：{len(records)} 条记录；重复样本：{len(duplicate_ids)} 条。")
    col1, col2 = st.columns(2)
    with col1:
        disabled = duplicate_policy == "取消导入" or not records
        if st.button("确认导入", key="samples_csv_import_confirm", type="primary", disabled=disabled, use_container_width=True):
            imported, updated, skipped, import_errors = _import_csv_records(records, duplicate_policy)
            if import_errors:
                st.error("导入未完全成功。")
                for error in import_errors[:8]:
                    st.caption(error)
                return
            if records:
                for record in records:
                    sample_id = str(record.get("sample_id") or "")
                    if duplicate_policy == "跳过重复样本" and sample_id in existing_ids:
                        continue
                    if sample_id:
                        _select_sample(sample_id)
                        break
            sync_suffix, level = _formal_sync_feedback_suffix()
            _store_sample_operation_message(
                f"已导入 {imported} 条样本，更新 {updated} 条，跳过 {skipped} 条重复记录。{sync_suffix}",
                level=level,
            )
            _clear_dialog_state()
            st.rerun()
    with col2:
        if st.button("取消", key="samples_csv_import_cancel", type="tertiary", use_container_width=True):
            _clear_dialog_state()
            st.rerun()


@st.dialog("新增样本", width="large")
def _render_create_sample_dialog(rubric_dimensions: list[dict] | None) -> None:
    _render_sample_editor_dialog_body("create", None, rubric_dimensions)


@st.dialog("编辑样本", width="large")
def _render_edit_sample_dialog(sample_id: str, rubric_dimensions: list[dict] | None) -> None:
    sample = sr.get_sample(sample_id)
    if sample is None:
        render_empty_state("未找到该样本。")
        if st.button("关闭", key="samples_edit_missing_close", type="tertiary"):
            _clear_dialog_state()
            st.rerun()
        return
    _render_sample_editor_dialog_body("edit", sample, rubric_dimensions)


def _render_sample_editor_dialog_body(
    mode: str,
    sample: sr.Sample | None,
    rubric_dimensions: list[dict] | None,
) -> None:
    is_edit = sample is not None
    prefix = f"samples_{mode}_{sample.sample_id if sample else 'new'}"
    gold_defaults = _gold_defaults(sample.gold_answer if sample else {})
    current_scene = _professional_scene_from_value(sample.domain if sample else "") or PROFESSIONAL_SCENE_OPTIONS[0]
    output_selection, custom_output = _output_requirement_for_form(sample.expected_capability if sample else "")
    difficulty_value = _difficulty_form_value(sample.difficulty if sample else "")
    risk_level_value = _risk_level_form_value(sample.risk_level if sample else "")

    st.caption("样本编号保存后不可修改；如需更换编号，请新建样本。")
    with st.form(f"{prefix}_form", clear_on_submit=not is_edit):
        st.markdown("**基础信息**")
        if is_edit:
            sample_id = st.text_input("样本编号", value=sample.sample_id, disabled=True, key=f"{prefix}_sample_id")
        else:
            sample_id = st.text_input("样本编号", key=f"{prefix}_sample_id")
        title = st.text_input("样本标题", value=sample.title if sample else "", key=f"{prefix}_title")
        col1, col2 = st.columns(2)
        professional_scene = col1.selectbox(
            "专业场景",
            PROFESSIONAL_SCENE_OPTIONS,
            index=_index_of(PROFESSIONAL_SCENE_OPTIONS, current_scene),
            key=f"{prefix}_professional_scene",
        )
        status = col2.selectbox(
            "样本状态",
            sr.SAMPLE_STATUSES,
            index=_index_of(sr.SAMPLE_STATUSES, sample.status if sample else "待复核"),
            key=f"{prefix}_status",
        )

        st.markdown("**任务内容**")
        task_prompt = st.text_area(
            "任务题",
            value=sample.task_prompt if sample else "",
            height=110,
            key=f"{prefix}_task_prompt",
        )
        business_context = st.text_area(
            "业务背景",
            value=sample.business_context if sample else "",
            height=90,
            key=f"{prefix}_business_context",
        )
        output_requirement_choice = st.selectbox(
            "输出要求",
            OUTPUT_REQUIREMENT_OPTIONS,
            index=_index_of(OUTPUT_REQUIREMENT_OPTIONS, output_selection),
            key=f"{prefix}_output_requirement",
        )
        output_requirement_custom = ""
        if output_requirement_choice == "自定义":
            output_requirement_custom = st.text_area(
                "自定义输出要求",
                value=custom_output,
                height=64,
                key=f"{prefix}_output_requirement_custom",
            )

        st.markdown("**专业标准答案**")
        core_conclusion = st.text_area(
            "标准结论",
            value=gold_defaults["core_conclusion"],
            height=72,
            key=f"{prefix}_gold_core",
        )
        key_evidence = st.text_area(
            "关键依据",
            value=gold_defaults["key_evidence"],
            height=72,
            key=f"{prefix}_gold_evidence",
        )
        col4, col5 = st.columns(2)
        must_have_points = col4.text_area(
            "必须覆盖点（每行一条）",
            value=gold_defaults["must_have_points"],
            height=110,
            key=f"{prefix}_gold_must",
        )
        unacceptable_errors = col5.text_area(
            "不可接受错误（每行一条）",
            value=gold_defaults["unacceptable_errors"],
            height=110,
            key=f"{prefix}_gold_unacceptable",
        )
        boundary_conditions = st.text_area(
            "边界与需核查事项",
            value=gold_defaults["boundary_conditions"],
            height=70,
            key=f"{prefix}_gold_boundary",
        )
        manual_review_notes = st.text_area(
            "人工复核提示",
            value=gold_defaults["manual_review_notes"],
            height=70,
            key=f"{prefix}_gold_review",
        )

        st.markdown("**高级信息**")
        col3, col4 = st.columns(2)
        difficulty = col3.selectbox(
            "难度",
            DIFFICULTY_FORM_OPTIONS,
            index=_index_of(DIFFICULTY_FORM_OPTIONS, difficulty_value),
            key=f"{prefix}_difficulty",
        )
        risk_level = col4.selectbox(
            "风险等级",
            RISK_LEVEL_OPTIONS,
            index=_index_of(RISK_LEVEL_OPTIONS, risk_level_value),
            key=f"{prefix}_risk_level",
        )
        reviewer_note = st.text_area(
            "复核备注",
            value=sample.reviewer_note if sample else "",
            height=60,
            key=f"{prefix}_reviewer_note",
        )
        scoring_focus = st.text_area(
            "本题评分关注点",
            value=gold_defaults["scoring_focus"],
            height=60,
            key=f"{prefix}_scoring_focus",
        )
        st.caption("评分标准由正式数据层统一维护；这里只填写本题特有的复核关注点。")

        submitted = st.form_submit_button("保存样本", type="primary", use_container_width=True)

    if st.button("取消", key=f"{prefix}_cancel", type="tertiary"):
        _clear_dialog_state()
        st.rerun()

    if not submitted:
        return

    normalized_sample_id = (sample.sample_id if is_edit else sample_id).strip()
    output_requirement = (
        output_requirement_custom
        if output_requirement_choice == "自定义"
        else output_requirement_choice
    )
    gold_answer = _build_gold_answer_json(
        sample_id=normalized_sample_id,
        core_conclusion=core_conclusion,
        key_evidence=key_evidence,
        must_have_points=must_have_points,
        unacceptable_errors=unacceptable_errors,
        boundary_conditions=boundary_conditions,
        manual_review_notes=manual_review_notes,
        scoring_focus=scoring_focus,
    )
    scoring_standard = (
        sample.rubric
        if sample is not None and str(sample.rubric or "").strip()
        else _default_scoring_standard_json(rubric_dimensions)
    )
    values = {
        "sample_id": normalized_sample_id,
        "title": title,
        "scenario": sample.scenario if sample is not None and sample.scenario else title,
        "task_prompt": task_prompt,
        "business_context": business_context,
        "domain": _domain_from_professional_scene(professional_scene),
        "risk_level": risk_level,
        "expected_capability": output_requirement,
        "gold_answer": gold_answer,
        "rubric": scoring_standard,
        "status": status,
        "difficulty": difficulty,
        "reviewer_note": reviewer_note,
    }
    if not _validate_active_dialog_values(values, rubric_dimensions):
        return

    try:
        if is_edit:
            changes = {key: value for key, value in values.items() if key != "sample_id"}
            sr.update_sample(sample.sample_id, changes, db_path=_formal_db_path_for_ui())
            selected_id = sample.sample_id
        else:
            sr.create_sample(values, db_path=_formal_db_path_for_ui())
            selected_id = normalized_sample_id
    except Exception as exc:
        st.error(str(exc))
        return

    _select_sample(selected_id)
    _clear_dialog_state()
    sync_suffix, level = _formal_sync_feedback_suffix()
    _store_sample_operation_message(f"已保存样本 {selected_id}。{sync_suffix}", level=level)
    st.rerun()


@st.dialog("确认移出测试", width="small")
def _render_archive_dialog(sample_id: str) -> None:
    sample = sr.get_sample(sample_id)
    if sample is None:
        render_empty_state("未找到该样本。")
    else:
        st.write("确认移出测试？移出后，该样本不会进入发起评测，历史记录仍保留。")
        st.caption(f"{sample.sample_id}｜{sample.title or '未命名样本'}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认移出测试", key=f"samples_archive_confirm_{sample_id}", type="primary", use_container_width=True):
            try:
                sr.archive_sample(sample_id, db_path=_formal_db_path_for_ui())
            except Exception as exc:
                st.error(str(exc))
                return
            _select_sample(sample_id)
            _clear_dialog_state()
            sync_suffix, level = _formal_sync_feedback_suffix()
            _store_sample_operation_message(f"样本 {sample_id} 已移出测试。{sync_suffix}", level=level)
            st.rerun()
    with col2:
        if st.button("取消", key=f"samples_archive_cancel_{sample_id}", type="tertiary", use_container_width=True):
            _clear_dialog_state()
            st.rerun()


def _difficulty_options(value: object = "") -> list[str]:
    options = _DIFFICULTY_OPTIONS[:]
    text = str(value or "").strip()
    if text and text not in options:
        options.append(text)
    return options


def _index_of(options: list, value: object) -> int:
    text = "" if value is None else str(value).strip()
    return options.index(text) if text in options else 0


def _rubric_dimension_options(rubric_dimensions: list[dict] | None, current_field: str = "") -> list[str]:
    options = [
        _rubric_field(dimension)
        for dimension in (rubric_dimensions or [])
        if isinstance(dimension, dict) and _rubric_field(dimension)
    ]
    if current_field and current_field not in options:
        options.insert(0, current_field)
    return options


def _rubric_dimension_label(field: str, rubric_dimensions: list[dict] | None) -> str:
    for dimension in rubric_dimensions or []:
        if isinstance(dimension, dict) and _rubric_field(dimension) == field:
            name = str(dimension.get("name") or dimension.get("dimension") or "").strip()
            return name or field
    return field or "未标注"
