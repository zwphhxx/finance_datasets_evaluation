"""评分确认页的评分依据、建议处理与兼容计算函数。"""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from src.gold_quality import field_list
from src.metrics import ERROR_TYPE_TO_DIMENSION, SCORE_DIMENSIONS, get_errors_for_output
from src.ui.components import render_empty_state
from src.ui.labels import summarize_text


_DEFAULT_DIMENSION_BASIS = {
    "accuracy_score": "结论与关键计算是否准确，并对照判断依据。",
    "reasoning_score": "分析逻辑是否完整，是否贴合任务场景。",
    "coverage_score": "是否覆盖必须关注的风险点与核查事项。",
    "evidence_score": "是否提供法规、数据等可靠依据支撑结论。",
    "expression_score": "表达是否清晰、审慎，符合专业报告风格。",
}

RECOMMEND_CONFIRM_FLOOR = 85.0
RECOMMEND_REVIEW_FLOOR = 60.0
RECOMMEND_LOW_DIM_RATIO = 0.60
RECOMMEND_SEVERE_DIM_RATIO = 0.35
RECOMMEND_RATIONALE_MIN_CHARS = 12

VERDICT_DIRECT_FLOOR = 85.0
VERDICT_PASS_FLOOR = 60.0
VERDICT_WEAK_RATIO = 0.6

_VERDICT_TIERS = {
    "direct": ("可作为初稿参考", "success"),
    "review": ("必须人工复核", "warning"),
    "not_direct": ("不可作为依据", "danger"),
    "none": ("暂无裁判结论", "neutral"),
}


def has_value(value) -> bool:
    if value is None:
        return False
    try:
        return not pd.isna(value)
    except TypeError:
        return True


def get_rubric_dimensions() -> list[dict]:
    """返回当前生效的评分维度，优先使用 DB / manifest 维护的值。"""
    return ds.get_rubric_dimensions()


def build_rubric_rows(score_row: pd.Series) -> list[dict]:
    rows = []
    for dim in get_rubric_dimensions():
        column = dim["field"]
        label = dim["name"]
        full = int(dim.get("full_mark") or 0)
        if not full or not has_value(score_row.get(column)):
            continue
        score = float(score_row.get(column))
        ratio = score / full if full else 0.0
        if ratio >= 0.85:
            level_text, level_class = "达标", "success"
        elif ratio >= 0.6:
            level_text, level_class = "部分达标", "warning"
        else:
            level_text, level_class = "需改进", "danger"
        basis = dim.get("full_mark_standard") or _DEFAULT_DIMENSION_BASIS.get(column, "")
        rows.append(
            {
                "field": column,
                "dimension": label,
                "score": score,
                "full": full,
                "gap": full - score,
                "level_text": level_text,
                "level_class": level_class,
                "basis": basis,
            }
        )
    return rows


def build_review_scoring_matrix_rows(
    score_row: pd.Series | dict | None,
    errors_df: pd.DataFrame | None,
    rubric_dimensions: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Build the legacy review matrix rows from dynamic scoring dimensions."""
    row = score_row if isinstance(score_row, pd.Series) else pd.Series(score_row or {})
    dimensions = rubric_dimensions if rubric_dimensions is not None else get_rubric_dimensions()
    output_id = row.get("output_id")
    errors_by_field = errors_by_dimension_field(errors_df, output_id, dimensions)
    rows: list[dict[str, str]] = []
    for dim in dimensions or []:
        field = str(dim.get("field") or dim.get("dimension_field") or "").strip()
        if not field:
            continue
        name = text(dim.get("name") or dim.get("dimension"), field)
        full = dim.get("full_mark")
        score = row.get(field)
        full_text = number_text(full, "待补充")
        score_text = "待补充"
        if has_value(score):
            score_text = f"{number_text(score)} / {full_text}"

        rows.append({
            "评分维度": name,
            "满分": full_text,
            "理想回复要求 / Gold 要求": rubric_requirement(field, dim),
            "模型得分": score_text,
            "评分依据": rationale_for_field(row, field),
            "扣分原因": text(dim.get("deduction_rules"), "暂无规则"),
            "对应错误标签": "；".join(errors_by_field.get(field, [])) or "暂无错误标签",
        })
    return rows


def build_review_basis_rows(
    score_row: pd.Series | dict | None,
    errors_df: pd.DataFrame | None,
    rubric_dimensions: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Build the compact score-basis table used on the review main page."""
    row = score_row if isinstance(score_row, pd.Series) else pd.Series(score_row or {})
    dimensions = rubric_dimensions if rubric_dimensions is not None else get_rubric_dimensions()
    output_id = row.get("output_id")
    errors_by_field = errors_by_dimension_field(errors_df, output_id, dimensions)
    rows: list[dict[str, str]] = []
    for dim in dimensions or []:
        field = str(dim.get("field") or dim.get("dimension_field") or "").strip()
        if not field:
            continue
        name = text(dim.get("name") or dim.get("dimension"), field)
        full = as_float(dim.get("full_mark"))
        score = as_float(row.get(field))
        if full:
            score_text = f"{number_text(score)} / {number_text(full)}" if score is not None else f"待补充 / {number_text(full)}"
        else:
            score_text = "待补充"
        rows.append(
            {
                "维度": name,
                "得分": score_text,
                "评分依据": rationale_for_field(row, field),
                "需关注点": dimension_attention(field, score, full, dim, errors_by_field.get(field, [])),
            }
        )
    return rows


def build_review_recommendation(
    score_row: pd.Series | dict | None,
    errors_df: pd.DataFrame | None,
    gold,
    task_info: pd.Series | dict | None,
    rubric_rows: list[dict] | None,
) -> dict:
    """Return the suggested review handling for one score draft."""
    row = score_row if isinstance(score_row, pd.Series) else pd.Series(score_row or {})
    reasons: list[str] = []
    danger = False
    warning = False

    judge_status = clean(row.get("judge_status"))
    if judge_status and judge_status != "success":
        danger = True
        reasons.append("裁判评分未成功")

    answer_text = clean(row.get("answer_text"))
    if not answer_text:
        danger = True
        reasons.append("模型回答为空或不可用")

    total = as_float(row.get("total_score"))
    if total is None:
        danger = True
        reasons.append("未产生总分")
    elif total < RECOMMEND_REVIEW_FLOOR:
        danger = True
        reasons.append(f"总分低于及格线（{total:.0f}）")
    elif total < RECOMMEND_CONFIRM_FLOOR:
        warning = True
        reasons.append(f"总分处于中间区间（{total:.0f}）")

    output_id = row.get("output_id")
    errors = get_errors_for_output(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), output_id)
    if not errors.empty:
        severities = (
            [text(value, "") for value in errors["severity"].tolist()]
            if "severity" in errors.columns
            else []
        )
        if any(value == "高" for value in severities):
            danger = True
            reasons.append("存在高严重度错误")
        elif any(value in {"中", "低"} for value in severities):
            warning = True
            reasons.append("存在中低严重度错误标签")

    redline_hits = detect_redline_hits(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), output_id, gold)
    if redline_hits:
        danger = True
        reasons.append("命中专业标准答案红线")

    severe_dims: list[str] = []
    weak_dims: list[str] = []
    for item in rubric_rows or []:
        full = as_float(item.get("full"))
        score = as_float(item.get("score"))
        if not full or score is None:
            continue
        ratio = score / full
        label = str(item.get("dimension") or item.get("field") or "未标注维度")
        if ratio < RECOMMEND_SEVERE_DIM_RATIO:
            severe_dims.append(label)
        elif ratio < RECOMMEND_LOW_DIM_RATIO:
            weak_dims.append(label)
    if severe_dims:
        danger = True
        reasons.append("关键维度严重低分：" + "、".join(severe_dims[:2]))
    elif weak_dims:
        warning = True
        reasons.append("存在低分维度：" + "、".join(weak_dims[:2]))

    risk = text(task_info.get("risk_level"), "") if task_info is not None else ""
    if risk == "高":
        warning = True
        reasons.append("任务风险等级较高")

    rationale_blob = " ".join(str(value) for value in rationale_map(row).values())
    review_note = clean(row.get("review_note"))
    if len(rationale_blob.strip()) < RECOMMEND_RATIONALE_MIN_CHARS or not review_note:
        warning = True
        reasons.append("评分依据或复核提示不足")

    if danger:
        recommendation, level = "不建议采用", "danger"
    elif warning:
        recommendation, level = "建议复核", "warning"
    else:
        recommendation, level = "建议确认", "success"
        reasons.append("分数较高且未发现红线或明显低分维度")

    return {
        "recommendation": recommendation,
        "level": level,
        "reasons": dedupe_texts(reasons),
    }


def build_point_coverage(points, answer_text) -> tuple[list[str], list[str]]:
    """Approximate which must-have points the answer covers, by keyword match."""
    answer = normalize_text(answer_text)
    covered: list[str] = []
    missed: list[str] = []
    for point in points:
        text_value = str(point).strip()
        if not text_value:
            continue
        keywords = [token for token in re.split(r"[，。、；：（）()/\s,.;:]+", text_value) if len(token) >= 3]
        hit = any(normalize_text(token) in answer for token in keywords) if keywords else normalize_text(text_value) in answer
        (covered if hit else missed).append(text_value)
    return covered, missed


def normalize_text(value) -> str:
    return re.sub(r"\s+", "", str(value))


def detect_redline_hits(errors_df, output_id, gold) -> list[str]:
    errors = get_errors_for_output(errors_df, output_id)
    hits: list[str] = []
    if not errors.empty:
        for _, error in errors.iterrows():
            if text(error.get("severity")) == "高":
                hits.append(f'高严重度错误：{text(error.get("error_type"), "未分类错误")}')

        unacceptable = field_list(gold, "unacceptable_errors") if isinstance(gold, dict) else []
        if unacceptable:
            blob = normalize_text(
                " ".join(
                    f'{text(e.get("error_type"), "")}{text(e.get("error_description"), "")}'
                    for _, e in errors.iterrows()
                )
            )
            for item in unacceptable:
                item_text = str(item).strip()
                if not item_text:
                    continue
                keywords = [token for token in re.split(r"[，。、；：（）()/\s,.;:]+", item_text) if len(token) >= 3]
                matched = (
                    any(normalize_text(token) in blob for token in keywords)
                    if keywords
                    else normalize_text(item_text) in blob
                )
                if matched:
                    hits.append(f"疑似触及红线：{summarize_text(item_text, 40)}")

    return dedupe_texts(hits)


def build_redline_blocks(
    verdict: dict,
    gold,
    output_row: pd.Series | dict | None,
    errors_df: pd.DataFrame | None,
    task_info: pd.Series | dict | None,
) -> list[dict[str, list[str]]]:
    """Build restrained redline notes from Gold, severe errors, weak dimensions and risk."""
    row = output_row if isinstance(output_row, pd.Series) else pd.Series(output_row or {})
    errors = get_errors_for_output(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), row.get("output_id"))
    blocks: list[dict[str, list[str]]] = []

    hits = [str(item) for item in (verdict.get("redline_hits") or []) if str(item).strip()]
    if hits:
        blocks.append({"title": "命中红线", "items": dedupe_texts(hits)})

    high_errors = [
        f"{text(error.get('error_type'), '未分类错误')}：{text(error.get('error_description'), '暂无错误表现')}"
        for _, error in errors.iterrows()
        if text(error.get("severity"), "") == "高"
    ] if not errors.empty else []
    if high_errors:
        blocks.append({"title": "高严重度错误", "items": dedupe_texts(high_errors)})

    weak_dims = [
        f"{r['dimension']}（{r['score']:.0f}/{r['full']}）"
        for r in build_rubric_rows(row)
        if r["full"] and r["score"] / r["full"] < VERDICT_WEAK_RATIO
    ]
    if weak_dims:
        blocks.append({"title": "关键维度低分", "items": weak_dims})

    risk = text(task_info.get("risk_level"), "") if task_info is not None else ""
    if risk == "高":
        blocks.append({"title": "任务风险等级", "items": ["当前任务标记为高风险，结论必须人工复核，不可作为依据。"]})

    red_lines = field_list(gold, "unacceptable_errors") if isinstance(gold, dict) else []
    if red_lines:
        blocks.append({"title": "专业标准答案中的不可接受错误", "items": [str(item) for item in red_lines]})
    return blocks


def weakest_rubric(rubric_rows: list[dict]) -> tuple[str, bool]:
    if not rubric_rows:
        return "暂无分项评分", False
    weakest = min(rubric_rows, key=lambda row: (row["score"] / row["full"] if row["full"] else 0.0))
    weak_text = f'{weakest["dimension"]}（{weakest["score"]:.0f}/{weakest["full"]}）'
    has_weak = any(
        (row["full"] and row["score"] / row["full"] < VERDICT_WEAK_RATIO) for row in rubric_rows
    )
    return weak_text, has_weak


def build_case_verdict(output_row, errors_df, gold, task_info) -> dict:
    if output_row is None:
        title, level = _VERDICT_TIERS["none"]
        return {
            "tier": "none",
            "title": title,
            "level": level,
            "reason": "该任务暂无模型回答记录，运行评测后生成裁判结论。",
            "redline_hits": [],
            "weakest": "暂无分项评分",
            "score_text": "未评分",
        }

    output_id = output_row.get("output_id")
    total = output_row.get("total_score")
    score = score_text(total) if has_value(total) else "未评分"
    weakest, has_weak = weakest_rubric(build_rubric_rows(output_row))
    redline_hits = detect_redline_hits(errors_df, output_id, gold)
    risk = text(task_info.get("risk_level"), "") if task_info is not None else ""

    reasons: list[str] = []
    if redline_hits:
        tier = "not_direct"
        reasons.append(f"命中红线 {len(redline_hits)} 项，红线错误一票否决")
    elif risk == "高":
        tier = "not_direct"
        reasons.append("高风险任务，结论须人工与合规终审")
    elif not has_value(total):
        tier = "review"
        reasons.append("尚未产生评分，需人工评测复核")
    elif float(total) >= VERDICT_DIRECT_FLOOR and not has_weak:
        tier = "direct"
        reasons.append(f"总分 {score} 且无显著维度短板")
    elif float(total) >= VERDICT_PASS_FLOOR:
        tier = "review"
        reasons.append(f"总分 {score}，存在维度短板，需人工复核")
    else:
        tier = "not_direct"
        reasons.append(f"总分 {score} 低于及格线")

    if has_weak and tier != "direct" and weakest != "暂无分项评分":
        reasons.append(f"最弱维度 {weakest}")

    title, level = _VERDICT_TIERS[tier]
    return {
        "tier": tier,
        "title": title,
        "level": level,
        "reason": "；".join(reasons) + "。",
        "redline_hits": redline_hits,
        "weakest": weakest,
        "score_text": score,
    }


def render_scoring_basis(output_row: pd.Series | None, errors_df) -> None:
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    rows = build_review_basis_rows(output_row, errors_df)
    if not rows:
        render_empty_state("当前模型回答尚未配置评分标准。")
        return
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "维度": st.column_config.TextColumn("维度", width="small"),
            "得分": st.column_config.TextColumn("得分", width="small"),
            "评分依据": st.column_config.TextColumn("评分依据", width="large"),
            "需关注点": st.column_config.TextColumn("需关注点", width="large"),
        },
    )


def errors_by_dimension(errors_df, output_id):
    errors = get_errors_for_output(errors_df, output_id)
    by_dimension: dict[str, list[tuple[str, str]]] = {}
    unmapped: list[tuple[str, str]] = []
    if errors.empty:
        return by_dimension, unmapped
    for _, error in errors.iterrows():
        error_type = text(error.get("error_type"), "未分类错误")
        severity = text(error.get("severity"), "")
        dimension = ERROR_TYPE_TO_DIMENSION.get(error_type)
        if dimension:
            by_dimension.setdefault(dimension, []).append((error_type, severity))
        else:
            unmapped.append((error_type, severity))
    return by_dimension, unmapped


def errors_by_dimension_field(errors_df, output_id, dimensions: list[dict] | None) -> dict[str, list[str]]:
    errors = get_errors_for_output(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), output_id)
    if errors.empty:
        return {}
    default_label_to_field = {label: field for field, label in SCORE_DIMENSIONS}
    current_label_to_field = {
        str(dim.get("name") or dim.get("dimension") or ""): str(dim.get("field") or dim.get("dimension_field") or "")
        for dim in (dimensions or [])
    }
    by_field: dict[str, list[str]] = {}
    for _, error in errors.iterrows():
        error_type = text(error.get("error_type"), "未分类错误")
        dimension_label = ERROR_TYPE_TO_DIMENSION.get(error_type)
        field = default_label_to_field.get(dimension_label or "") or current_label_to_field.get(dimension_label or "")
        if not field:
            continue
        by_field.setdefault(field, []).append(error_type)
    return {field: dedupe_texts(labels) for field, labels in by_field.items()}


def dimension_attention(field: str, score: float | None, full: float | None, dim: dict, labels: list[str]) -> str:
    notes: list[str] = []
    if full and score is not None and score / full < RECOMMEND_LOW_DIM_RATIO:
        notes.append("低分维度")
    if labels:
        notes.append("错误标签：" + "、".join(labels[:2]))
    deduction = clean(dim.get("deduction_rules"))
    if deduction:
        notes.append("扣分规则：" + summarize_text(deduction, 48))
    return "；".join(dedupe_texts(notes)) or "暂无特别关注点"


def attention_items(
    row: pd.Series,
    errors_df: pd.DataFrame,
    gold,
    task_info,
    rubric_rows: list[dict],
) -> list[str]:
    items: list[str] = []
    for rubric in rubric_rows or []:
        full = as_float(rubric.get("full"))
        score = as_float(rubric.get("score"))
        if full and score is not None and score / full < RECOMMEND_LOW_DIM_RATIO:
            items.append(f"{rubric.get('dimension')}：{score:.0f} / {full:.0f}")
    for hit in detect_redline_hits(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), row.get("output_id"), gold):
        items.append(hit)
    risk = text(task_info.get("risk_level"), "") if task_info is not None else ""
    if risk == "高":
        items.append("任务风险等级较高，确认前需复核评分依据。")
    return dedupe_texts(items)[:5]


def rubric_material_rows(dimensions: list[dict]) -> list[dict[str, str]]:
    return list(build_rubric_material_display(dimensions)["rows"])


def build_rubric_material_display(dimensions: list[dict]) -> dict[str, object]:
    """Build dynamic scoring-standard display metadata for complete/incomplete standards."""
    rows: list[dict[str, str]] = []
    complete = bool(dimensions)
    for dim in dimensions or []:
        field = clean(dim.get("field") or dim.get("dimension_field"))
        normalized = {
            "field": field,
            "name": clean(dim.get("name") or dim.get("dimension")),
            "full_mark": dim.get("full_mark") or dim.get("weight"),
            "full_mark_standard": clean(dim.get("full_mark_standard")),
            "deduction_rules": clean(dim.get("deduction_rules")),
        }
        missing = ds.rubric_dimension_missing_items(normalized)
        if missing:
            complete = False
            rows.append({
                "维度": normalized["name"] or field or "未标注维度",
                "满分": number_text(normalized["full_mark"], "待补充"),
                "缺失项": "；".join(missing),
            })
            continue
        rows.append({
            "维度": normalized["name"] or field or "未标注维度",
            "满分": number_text(normalized["full_mark"], "待补充"),
            "满分标准": normalized["full_mark_standard"] or "",
            "扣分规则": normalized["deduction_rules"] or "",
        })
    if complete:
        return {
            "complete": True,
            "title": "评分标准",
            "note": "",
            "rows": rows,
        }
    return {
        "complete": False,
        "title": "评分维度配置",
        "note": "当前评分标准仅维护评分维度和满分，尚未完整维护满分标准与扣分规则。该样本不应作为完整可测样本进入正式评测。",
        "rows": rows,
    }


def rubric_requirement(field: str, dim: dict) -> str:
    explicit = clean(dim.get("full_mark_standard"))
    if explicit:
        return explicit
    if has_value(dim.get("full_mark")):
        return _DEFAULT_DIMENSION_BASIS.get(field, "待补充")
    return "待补充"


def rationale_for_field(row: pd.Series | dict, field: str) -> str:
    mapping = rationale_map(row)
    value = clean(mapping.get(field))
    return value or "未返回明确依据"


def rationale_map(row: pd.Series | dict | None) -> dict[str, str]:
    if row is None:
        return {}
    getter = row.get if hasattr(row, "get") else lambda key, default=None: default
    raw = getter("rationale", "")
    if isinstance(raw, dict):
        return {str(key): clean(value) for key, value in raw.items()}
    value = clean(raw)
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): clean(value) for key, value in payload.items()}


def number_text(value, fallback: str = "—") -> str:
    if not has_value(value):
        return fallback
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def as_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def as_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_datetime(value) -> str:
    value_text = clean(value)
    if not value_text:
        return "—"
    parsed = pd.to_datetime(value_text, errors="coerce")
    if pd.isna(parsed):
        return value_text[:19]
    return parsed.strftime("%Y-%m-%d %H:%M")


def clean(value) -> str:
    if value is None:
        return ""
    value_text = str(value).strip()
    return "" if not value_text or value_text.lower() in {"nan", "none", "null"} else value_text


def dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def score_text(value) -> str:
    number = as_float(value)
    return "未评分" if number is None else f"{number:.0f}"


def safe_key(value) -> str:
    value_text = "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))
    return value_text[:80] or "item"


def text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    value_text = str(value).strip()
    if not value_text or value_text.lower() in {"nan", "none", "null"}:
        return fallback
    return value_text
