"""评分确认页面。

- 只处理真实运行生成并写入 SQLite 的评分草稿。
- 确认生效后才纳入正式结论；未确认结果仅作为机器建议。
"""

from __future__ import annotations

import json
import re
import pandas as pd
import streamlit as st

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services import model_display as md
from app.services import scorer as sc
from src.gold_quality import field_list, field_text
from src.metrics import (
    ERROR_TYPE_TO_DIMENSION,
    SCORE_DIMENSIONS,
    get_case_ids,
    get_errors_for_output,
    get_task_by_case_id,
    normalize_optimization_plan,
)
from src.ui.common import has_value
from src.ui.components import (
    render_clean_list,
    render_compact_hero,
    render_empty_state,
    render_inline_status,
    render_numbered_section,
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


# 当评分量表未维护满分标准时，用作参考答案要求展示的默认依据文案。
_DEFAULT_DIMENSION_BASIS = {
    "accuracy_score": "结论与关键计算是否准确，并对照判断依据。",
    "reasoning_score": "分析逻辑是否完整，是否贴合任务场景。",
    "coverage_score": "是否覆盖必须关注的风险点与核查事项。",
    "evidence_score": "是否提供法规、数据等可靠依据支撑结论。",
    "expression_score": "表达是否清晰、审慎，符合专业报告风格。",
}

SEVERITY_BADGE = {"高": "danger", "中": "warning", "低": "neutral"}
REVIEW_SECTIONS = [
    "待确认评分",
    "当前评分摘要",
    "评分依据",
    "确认处理",
]
REVIEW_FILTER_OPTIONS = ["待确认", "建议确认", "建议复核", "不建议采用", "已确认", "全部"]
BULK_REVIEW_NOTE = "低风险评分草稿，经人工批量确认生效。"
REVIEW_BULK_RESULT_KEY = "review_bulk_result"
REVIEW_QUEUE_VERSION_KEY = "review_queue_version"

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


def get_review_sections() -> list[str]:
    """Return the review page sections in reader-facing order."""
    return REVIEW_SECTIONS[:]


def _get_rubric() -> list[dict]:
    """返回当前生效的评分维度，优先使用 DB / manifest 维护的值。"""
    return ds.get_rubric_dimensions()


def build_rubric_rows(score_row: pd.Series) -> list[dict]:
    rows = []
    for dim in _get_rubric():
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
    """Build the review matrix from dynamic Rubric dimensions and error labels."""
    row = score_row if isinstance(score_row, pd.Series) else pd.Series(score_row or {})
    dimensions = rubric_dimensions if rubric_dimensions is not None else _get_rubric()
    output_id = row.get("output_id")
    errors_by_field = _errors_by_dimension_field(errors_df, output_id, dimensions)
    rows: list[dict[str, str]] = []
    for dim in dimensions or []:
        field = str(dim.get("field") or dim.get("dimension_field") or "").strip()
        if not field:
            continue
        name = _text(dim.get("name") or dim.get("dimension"), field)
        full = dim.get("full_mark")
        score = row.get(field)
        full_text = _number_text(full, "待补充")
        score_text = "待补充"
        if has_value(score):
            score_text = f"{_number_text(score)} / {full_text}"

        requirement = _rubric_requirement(field, dim)
        deduction = _text(dim.get("deduction_rules"), "暂无规则")
        rationale = _rationale_for_field(row, field)
        labels = "；".join(errors_by_field.get(field, [])) or "暂无错误标签"
        rows.append({
            "评分维度": name,
            "满分": full_text,
            "理想回复要求 / Gold 要求": requirement,
            "模型得分": score_text,
            "评分依据": rationale,
            "扣分原因": deduction,
            "对应错误标签": labels,
        })
    return rows


def build_review_basis_rows(
    score_row: pd.Series | dict | None,
    errors_df: pd.DataFrame | None,
    rubric_dimensions: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Build the compact score-basis table used on the review main page."""
    row = score_row if isinstance(score_row, pd.Series) else pd.Series(score_row or {})
    dimensions = rubric_dimensions if rubric_dimensions is not None else _get_rubric()
    output_id = row.get("output_id")
    errors_by_field = _errors_by_dimension_field(errors_df, output_id, dimensions)
    rows: list[dict[str, str]] = []
    for dim in dimensions or []:
        field = str(dim.get("field") or dim.get("dimension_field") or "").strip()
        if not field:
            continue
        name = _text(dim.get("name") or dim.get("dimension"), field)
        full = _as_float(dim.get("full_mark"))
        score = _as_float(row.get(field))
        if full:
            score_text = f"{_number_text(score)} / {_number_text(full)}" if score is not None else f"待补充 / {_number_text(full)}"
        else:
            score_text = "待补充"
        attention = _dimension_attention(field, score, full, dim, errors_by_field.get(field, []))
        rows.append(
            {
                "维度": name,
                "得分": score_text,
                "评分依据": _rationale_for_field(row, field),
                "需关注点": attention,
            }
        )
    return rows


def build_error_attribution_rows(
    errors_df: pd.DataFrame | None,
    optimization_df: pd.DataFrame | None,
    output_id,
) -> list[dict[str, str]]:
    """Build error-attribution rows for the selected answer."""
    errors = get_errors_for_output(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), output_id)
    if errors.empty:
        return []
    optimization_lookup = _optimization_lookup(optimization_df)
    rows: list[dict[str, str]] = []
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        plan = optimization_lookup.get(error_type, {})
        data_action = (
            _clean(plan.get("data_action"))
            or _clean(error.get("optimization_action"))
            or "暂无优化建议"
        )
        rows.append({
            "错误类型": error_type,
            "严重程度": _text(error.get("severity"), "未标注"),
            "错误表现": _text(error.get("error_description"), "暂无错误表现"),
            "修正方向": _text(error.get("correction"), "待补充修正方向"),
            "数据优化建议": data_action,
            "可能原因": _text(plan.get("root_cause"), "待补充错误原因"),
        })
    return rows


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
        blocks.append({"title": "命中红线", "items": _dedupe_texts(hits)})

    high_errors = [
        f"{_text(error.get('error_type'), '未分类错误')}：{_text(error.get('error_description'), '暂无错误表现')}"
        for _, error in errors.iterrows()
        if _text(error.get("severity"), "") == "高"
    ] if not errors.empty else []
    if high_errors:
        blocks.append({"title": "高严重度错误", "items": _dedupe_texts(high_errors)})

    weak_dims = [
        f"{r['dimension']}（{r['score']:.0f}/{r['full']}）"
        for r in build_rubric_rows(row)
        if r["full"] and r["score"] / r["full"] < VERDICT_WEAK_RATIO
    ]
    if weak_dims:
        blocks.append({"title": "关键维度低分", "items": weak_dims})

    risk = _text(task_info.get("risk_level"), "") if task_info is not None else ""
    if risk == "高":
        blocks.append({"title": "任务风险等级", "items": ["当前任务标记为高风险，结论必须人工复核，不可作为依据。"]})

    red_lines = field_list(gold, "unacceptable_errors") if isinstance(gold, dict) else []
    if red_lines:
        blocks.append({"title": "Gold Answer 中的不可接受错误", "items": [str(item) for item in red_lines]})
    return blocks


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

    judge_status = _clean(row.get("judge_status"))
    if judge_status and judge_status != "success":
        danger = True
        reasons.append("裁判评分未成功")

    answer_text = _clean(row.get("answer_text"))
    if not answer_text:
        danger = True
        reasons.append("模型回答为空或不可用")

    total = _as_float(row.get("total_score"))
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
            [_text(value, "") for value in errors["severity"].tolist()]
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
        reasons.append("命中 Gold Answer 红线")

    severe_dims: list[str] = []
    weak_dims: list[str] = []
    for item in rubric_rows or []:
        full = _as_float(item.get("full"))
        score = _as_float(item.get("score"))
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

    risk = _text(task_info.get("risk_level"), "") if task_info is not None else ""
    if risk == "高":
        warning = True
        reasons.append("任务风险等级较高")

    rationale_blob = " ".join(str(value) for value in _rationale_map(row).values())
    review_note = _clean(row.get("review_note"))
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
        "reasons": _dedupe_texts(reasons),
    }


def build_point_coverage(points, answer_text) -> tuple[list[str], list[str]]:
    """Approximate which must-have points the answer covers, by keyword match."""
    answer = _normalize_text(answer_text)
    covered: list[str] = []
    missed: list[str] = []
    for point in points:
        text = str(point).strip()
        if not text:
            continue
        keywords = [token for token in re.split(r"[，。、；：（）()/s,.;:]+", text) if len(token) >= 3]
        if keywords:
            hit = any(_normalize_text(token) in answer for token in keywords)
        else:
            hit = _normalize_text(text) in answer
        (covered if hit else missed).append(text)
    return covered, missed


def _normalize_text(value) -> str:
    return re.sub(r"\s+", "", str(value))


def detect_redline_hits(errors_df, output_id, gold) -> list[str]:
    errors = get_errors_for_output(errors_df, output_id)
    hits: list[str] = []
    if not errors.empty:
        for _, error in errors.iterrows():
            if _text(error.get("severity")) == "高":
                hits.append(f'高严重度错误：{_text(error.get("error_type"), "未分类错误")}')

        unacceptable = field_list(gold, "unacceptable_errors") if isinstance(gold, dict) else []
        if unacceptable:
            blob = _normalize_text(
                " ".join(
                    f'{_text(e.get("error_type"), "")}{_text(e.get("error_description"), "")}'
                    for _, e in errors.iterrows()
                )
            )
            for item in unacceptable:
                text = str(item).strip()
                if not text:
                    continue
                keywords = [token for token in re.split(r"[，。、；：（）()/s,.;:]+", text) if len(token) >= 3]
                matched = (
                    any(_normalize_text(token) in blob for token in keywords)
                    if keywords
                    else _normalize_text(text) in blob
                )
                if matched:
                    hits.append(f"疑似触及红线：{summarize_text(text, 40)}")

    seen: set[str] = set()
    ordered: list[str] = []
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            ordered.append(hit)
    return ordered


def _weakest_rubric(rubric_rows: list[dict]) -> tuple[str, bool]:
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
    score_text = f"{float(total):.0f}" if has_value(total) else "未评分"
    weakest, has_weak = _weakest_rubric(build_rubric_rows(output_row))
    redline_hits = detect_redline_hits(errors_df, output_id, gold)
    risk = _text(task_info.get("risk_level"), "") if task_info is not None else ""

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
        reasons.append(f"总分 {score_text} 且无显著维度短板")
    elif float(total) >= VERDICT_PASS_FLOOR:
        tier = "review"
        reasons.append(f"总分 {score_text}，存在维度短板，需人工复核")
    else:
        tier = "not_direct"
        reasons.append(f"总分 {score_text} 低于及格线")

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
        "score_text": score_text,
    }


def get_case_models(merged_outputs: pd.DataFrame) -> list[str]:
    if merged_outputs.empty or "model_name" not in merged_outputs:
        return []
    return sorted(merged_outputs["model_name"].dropna().astype(str).unique().tolist())


def get_output_row(merged_outputs: pd.DataFrame, model_name: str) -> pd.Series | None:
    if merged_outputs.empty or "model_name" not in merged_outputs:
        return None
    rows = merged_outputs[merged_outputs["model_name"].astype(str) == str(model_name)]
    if rows.empty:
        return None
    return rows.iloc[0]


def render_review_page(data_bundle: dict) -> None:
    base = data_bundle.get("base") or data_bundle["data"]
    eval_status = data_bundle.get("eval_status") or {}
    errors_df = getattr(base, "errors", pd.DataFrame())
    optimizations_df = getattr(base, "optimizations", pd.DataFrame())

    config = get_page_config("review")
    render_compact_hero(
        eyebrow="评分确认",
        title=config.title,
        question=config.question,
    )
    st.caption(
        "本页用于确认评分草稿。确认后的结果才进入正式结论；未确认结果仅作为机器建议。"
    )

    items, selected_score_run_id = _load_live_review_items(base, eval_status)
    if not items:
        render_empty_state("暂无待确认评分草稿。请先在发起评测页运行模型回答并生成评分草稿。")
        return

    render_numbered_section("01", REVIEW_SECTIONS[0], "低风险评分可批量确认，高风险评分需逐条查看。")
    visible_items = _render_review_queue(items, selected_score_run_id)
    if not visible_items:
        render_empty_state("当前筛选条件下暂无评分记录。")
        return
    selected_index = st.selectbox(
        "当前评分",
        list(range(len(visible_items))),
        format_func=lambda index: _review_item_label(visible_items[index]),
        key="review_score_select",
    )
    item = visible_items[int(selected_index)]
    output_row = item["output_row"]
    task_info = item["task_info"]
    gold = item["gold"]
    recommendation = item["recommendation"]
    verdict = build_case_verdict(output_row, errors_df, gold, task_info)

    render_numbered_section("02", REVIEW_SECTIONS[1], "确认这条评分对应的样本、模型、总分和建议处理。")
    _render_score_summary(item, verdict, errors_df, optimizations_df)

    render_numbered_section("03", REVIEW_SECTIONS[2], "按 Rubric 维度查看得分、评分依据和需关注点。")
    _render_scoring_basis(output_row, errors_df)

    render_numbered_section("04", REVIEW_SECTIONS[3], "人工确认生效、修订后确认，或暂不采用。")
    _render_confirmation_actions(item)


def _load_live_review_items(base, eval_status: dict) -> tuple[list[dict], str | None]:
    scores = _filter_live_score_frame(cc.load_live_scores())
    if scores.empty:
        return [], None
    selected_score_run_id = _select_score_run_id(scores, eval_status)
    if selected_score_run_id:
        scores = scores[scores["score_run_id"].astype(str) == str(selected_score_run_id)]
    responses = cc.load_live_responses()
    items = _build_live_review_items(base, scores, responses)
    return items, selected_score_run_id


def _filter_live_score_frame(scores: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(scores, pd.DataFrame) or scores.empty:
        return pd.DataFrame()
    frame = scores.copy()
    if "judge_status" in frame:
        frame = frame[frame["judge_status"].astype(str).str.strip().str.lower() == "success"]
    if "status" in frame:
        frame = frame[frame["status"].astype(str).str.strip().str.lower() != "inactive"]
    if "eval_model" in frame:
        frame = frame[~frame["eval_model"].apply(md.is_seed_model)]
    if "score_run_id" not in frame:
        frame["score_run_id"] = ""
    if "id" in frame:
        frame = frame.sort_values("id", ascending=False)
    return frame.reset_index(drop=True)


def _select_score_run_id(scores: pd.DataFrame, eval_status: dict) -> str | None:
    run_ids = [str(value) for value in scores.get("score_run_id", pd.Series(dtype=str)).dropna().unique().tolist()]
    run_ids = [value for value in run_ids if value]
    if not run_ids:
        return None

    latest = _latest_score_run_id(scores)
    preferred = str(eval_status.get("score_run_id") or "")
    default = preferred if preferred in run_ids else latest
    index = run_ids.index(default) if default in run_ids else 0
    if len(run_ids) == 1:
        st.caption(f"评分批次：{_score_run_label(scores, run_ids[0])}")
        return run_ids[0]
    selected = st.selectbox(
        "评分批次",
        run_ids,
        index=index,
        format_func=lambda run_id: _score_run_label(scores, run_id),
        key="review_score_run_select",
    )
    return str(selected)


def _latest_score_run_id(scores: pd.DataFrame) -> str:
    if scores.empty:
        return ""
    if "id" in scores:
        row = scores.sort_values("id", ascending=False).iloc[0]
    elif "created_at" in scores:
        row = scores.sort_values("created_at", ascending=False).iloc[0]
    else:
        row = scores.iloc[0]
    return str(row.get("score_run_id") or "")


def _score_run_label(scores: pd.DataFrame, score_run_id: str) -> str:
    rows = scores[scores["score_run_id"].astype(str) == str(score_run_id)]
    created = _format_datetime(rows.get("created_at", pd.Series(dtype=str)).dropna().astype(str).max())
    pending = int((rows.get("review_status", pd.Series(dtype=str)).astype(str).str.lower() == "pending").sum())
    total = len(rows)
    suffix = f" · {created}" if created != "—" else ""
    return f"{score_run_id} · 待确认 {pending}/{total}{suffix}"


def _build_live_review_items(base, score_rows: pd.DataFrame, responses: pd.DataFrame) -> list[dict]:
    items: list[dict] = []
    answer_lookup = _live_answer_lookup(responses)
    for _, score_row in score_rows.iterrows():
        case_id = _clean(score_row.get("case_id"))
        model_name = _clean(score_row.get("eval_model"))
        if not case_id or not model_name:
            continue
        task_rows = get_task_by_case_id(base.tasks, case_id)
        if task_rows.empty:
            continue
        task_info = task_rows.iloc[0]
        gold = base.gold_answer_map.get(case_id)
        run_id = _clean(score_row.get("run_id"))
        output_data = dict(score_row)
        output_data["model_name"] = model_name
        output_data["answer_text"] = answer_lookup.get((run_id, case_id, model_name), "")
        output_data["output_id"] = f"{run_id}::{model_name}::{case_id}"
        output_row = pd.Series(output_data)
        rubric_rows = build_rubric_rows(output_row)
        recommendation = build_review_recommendation(
            output_row,
            pd.DataFrame(),
            gold,
            task_info,
            rubric_rows,
        )
        items.append({
            "case_id": case_id,
            "model_name": model_name,
            "display_model": md.display_model_name(model_name, source="live"),
            "source": "live",
            "source_label": "真实评分草稿",
            "score_row_id": _as_int(score_row.get("id")),
            "score_run_id": _clean(score_row.get("score_run_id")),
            "created_at": _clean(score_row.get("created_at")),
            "task_info": task_info,
            "gold": gold,
            "output_row": output_row,
            "score_row": dict(score_row),
            "rubric_rows": rubric_rows,
            "recommendation": recommendation,
        })
    items.sort(key=lambda item: (
        _review_status_rank(item["output_row"].get("review_status"), item["source"]),
        _recommendation_rank(item["recommendation"]),
        item["case_id"],
        item["display_model"],
    ))
    return items


def _live_answer_lookup(responses: pd.DataFrame) -> dict[tuple[str, str, str], str]:
    if not isinstance(responses, pd.DataFrame) or responses.empty:
        return {}
    lookup: dict[tuple[str, str, str], str] = {}
    for _, row in responses.iterrows():
        key = (
            _clean(row.get("run_id")),
            _clean(row.get("case_id")),
            _clean(row.get("model_name")),
        )
        lookup[key] = _clean(row.get("answer_text"))
    return lookup


def _render_review_queue(items: list[dict], selected_score_run_id: str | None) -> list[dict]:
    stats = build_review_queue_stats(items)
    _render_bulk_review_feedback()
    render_inline_status(
        [
            ("待确认", str(stats["pending"])),
            ("建议确认", str(stats["confirm"])),
            ("建议复核", str(stats["review"])),
            ("不建议采用", str(stats["reject"])),
            ("已确认", str(stats["confirmed"])),
        ]
    )

    if st.session_state.get("review_queue_filter") not in REVIEW_FILTER_OPTIONS:
        st.session_state["review_queue_filter"] = REVIEW_FILTER_OPTIONS[0]
    filter_value = st.selectbox(
        "筛选",
        REVIEW_FILTER_OPTIONS,
        key="review_queue_filter",
        help="按建议处理或确认状态筛选待确认队列。",
    )
    visible_items = filter_review_queue_items(items, filter_value)
    if not visible_items:
        return []

    table_rows = [review_queue_row(item) for item in visible_items]
    frame = pd.DataFrame(table_rows)
    version = int(st.session_state.get(REVIEW_QUEUE_VERSION_KEY, 0) or 0)
    edited = st.data_editor(
        frame,
        hide_index=True,
        use_container_width=True,
        disabled=["样本编号", "模型", "总分", "建议处理", "主要原因", "复核状态", "可批量确认", "生成时间"],
        column_order=["选择", "样本编号", "模型", "总分", "建议处理", "主要原因", "复核状态", "可批量确认", "生成时间"],
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", help="仅建议确认且待确认的评分可批量确认。"),
            "样本编号": st.column_config.TextColumn("样本编号", width="small"),
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "总分": st.column_config.TextColumn("总分", width="small"),
            "建议处理": st.column_config.TextColumn("建议处理", width="small"),
            "主要原因": st.column_config.TextColumn("主要原因", width="large"),
            "复核状态": st.column_config.TextColumn("复核状态", width="small"),
            "可批量确认": st.column_config.TextColumn("可批量确认", width="small"),
            "生成时间": st.column_config.TextColumn("生成时间", width="medium"),
        },
        key=f"review_queue_editor::{selected_score_run_id or 'latest'}::{filter_value}::{version}",
    )
    selected_positions: list[int] = []
    if isinstance(edited, pd.DataFrame) and "选择" in edited:
        for index, row in edited.iterrows():
            if not bool(row.get("选择")):
                continue
            try:
                selected_positions.append(int(index))
            except (TypeError, ValueError):
                continue
    selected_items = [
        visible_items[index]
        for index in selected_positions
        if 0 <= index < len(visible_items)
    ]
    eligible_items = [item for item in selected_items if is_bulk_confirm_eligible(item)]
    blocked_items = [item for item in selected_items if not is_bulk_confirm_eligible(item)]
    _render_bulk_confirmation(eligible_items, blocked_items)
    st.caption("队列只包含真实运行生成的评分草稿；未确认评分不会纳入正式结论。")
    return visible_items


def build_review_queue_stats(items: list[dict]) -> dict[str, int]:
    """统计评分确认队列；只统计真实运行评分。"""
    stats = {"pending": 0, "confirm": 0, "review": 0, "reject": 0, "confirmed": 0}
    for item in items:
        if item.get("source") == "seed":
            continue
        status = str(item["output_row"].get("review_status") or "pending").strip().lower()
        if status == "confirmed":
            stats["confirmed"] += 1
            continue
        if status == "skipped":
            continue
        stats["pending"] += 1
        recommendation = str(item["recommendation"].get("recommendation") or "")
        if recommendation == "建议确认":
            stats["confirm"] += 1
        elif recommendation == "不建议采用":
            stats["reject"] += 1
        else:
            stats["review"] += 1
    return stats


def filter_review_queue_items(items: list[dict], filter_value: str) -> list[dict]:
    live_items = [item for item in items if item.get("source") != "seed"]
    if filter_value == "全部":
        return live_items
    if filter_value == "待确认":
        return [
            item for item in live_items
            if _review_status_value(item) == "pending"
        ]
    if filter_value == "已确认":
        return [item for item in live_items if _review_status_value(item) == "confirmed"]
    return [
        item for item in live_items
        if _review_status_value(item) not in {"confirmed", "skipped"}
        and str(item["recommendation"].get("recommendation") or "") == filter_value
    ]


def is_bulk_confirm_eligible(item: dict) -> bool:
    return (
        item.get("source") != "seed"
        and _review_status_value(item) == "pending"
        and str(item["recommendation"].get("recommendation") or "") == "建议确认"
    )


def review_queue_row(item: dict) -> dict[str, object]:
    row = item["output_row"]
    recommendation = item["recommendation"]
    reasons = "；".join(recommendation.get("reasons") or []) or "暂无原因"
    return {
        "选择": False,
        "样本编号": item["case_id"],
        "模型": item["display_model"],
        "总分": _score_text(row.get("total_score")),
        "建议处理": str(recommendation.get("recommendation") or "待判断"),
        "主要原因": summarize_text(reasons, 64),
        "复核状态": _display_review_status(row.get("review_status"), item["source"]),
        "可批量确认": "是" if is_bulk_confirm_eligible(item) else "否",
        "生成时间": _format_datetime(item.get("created_at")),
    }


def _render_bulk_confirmation(
    eligible_items: list[dict],
    blocked_items: list[dict],
) -> None:
    if blocked_items:
        st.caption("建议复核、不建议采用或已确认的评分不能批量确认，请进入当前评分摘要逐条处理。")

    count = len(eligible_items)
    prompt = f"将确认 {count} 条低风险评分草稿，确认后纳入正式结论。" if count else ""
    st.caption(f"已选择 {count} 条可批量确认评分。" + (f" {prompt}" if prompt else ""))
    if st.button(
        "批量确认生效",
        type="primary",
        disabled=count == 0,
        key="review_bulk_confirm",
        use_container_width=False,
    ):
        _render_bulk_confirm_dialog(eligible_items, len(blocked_items))


@st.dialog("批量确认生效", width="medium")
def _render_bulk_confirm_dialog(eligible_items: list[dict], blocked_count: int = 0) -> None:
    count = len(eligible_items)
    st.markdown(f"将确认 **{count}** 条低风险评分草稿。确认后，这些评分将纳入正式结论。")
    if blocked_count:
        st.caption(f"{blocked_count} 条已勾选评分不符合批量确认条件，本次不会处理。")
    st.markdown("**本次不会处理**")
    _render_markdown_bullets(["建议复核", "不建议采用", "已确认", "暂不采用"])
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认生效", type="primary", key="review_bulk_dialog_submit", use_container_width=True):
            result = _confirm_low_risk_items(eligible_items, blocked_count)
            st.session_state[REVIEW_BULK_RESULT_KEY] = result
            st.session_state[REVIEW_QUEUE_VERSION_KEY] = int(
                st.session_state.get(REVIEW_QUEUE_VERSION_KEY, 0) or 0
            ) + 1
            st.session_state["review_queue_filter"] = "待确认"
            st.rerun()
    with col2:
        if st.button("取消", type="tertiary", key="review_bulk_dialog_cancel", use_container_width=True):
            st.rerun()


def _confirm_low_risk_items(items: list[dict], blocked_count: int = 0) -> dict[str, object]:
    row_ids: list[int] = []
    for item in items:
        row_id = _as_int(item.get("score_row_id"))
        if row_id is not None and _review_status_value(item) == "pending":
            row_ids.append(row_id)
    result = sc.confirm_score_reviews_bulk(row_ids, BULK_REVIEW_NOTE)
    summary = summarize_bulk_confirm_result(row_ids, result, blocked_count=blocked_count)
    message = build_bulk_review_message(
        confirmed_count=int(summary["confirmed_count"]),
        failed_count=int(summary["failed_count"]),
        blocked_count=blocked_count,
    )
    return {**summary, **message}


def summarize_bulk_confirm_result(
    requested_ids: list[int],
    result: dict,
    *,
    blocked_count: int = 0,
) -> dict[str, object]:
    confirmed_ids = [int(value) for value in result.get("confirmed_ids") or []]
    failed_ids = [int(value) for value in result.get("failed_ids") or result.get("failed") or []]
    if not confirmed_ids and result.get("confirmed"):
        confirmed_count = int(result.get("confirmed") or 0)
        confirmed_ids = requested_ids[:confirmed_count]
    if not failed_ids:
        failed_ids = [row_id for row_id in requested_ids if row_id not in set(confirmed_ids)]
    confirmed_count = int(result.get("confirmed_count", len(confirmed_ids)) or 0)
    failed_count = int(result.get("failed_count", len(failed_ids)) or 0)
    return {
        "confirmed_count": confirmed_count,
        "confirmed_ids": confirmed_ids,
        "failed_count": failed_count,
        "failed_ids": failed_ids,
        "blocked_count": int(blocked_count or 0),
        "reason": str(result.get("reason") or ""),
        "summary": str(result.get("summary") or ""),
    }


def build_bulk_review_message(
    *,
    confirmed_count: int,
    failed_count: int,
    blocked_count: int = 0,
) -> dict[str, str]:
    success = ""
    warning_parts: list[str] = []
    if confirmed_count:
        success = f"已确认 {confirmed_count} 条评分，已纳入正式结论。"
    if failed_count:
        warning_parts.append(
            f"{failed_count} 条评分未确认，仅“建议确认”且状态为“待确认”的评分支持批量确认。"
        )
    if blocked_count:
        warning_parts.append(f"{blocked_count} 条已勾选评分不符合批量确认条件。")
    if warning_parts:
        warning_parts.append("建议复核、不建议采用或已确认的评分请逐条处理。")
    return {"success": success, "warning": " ".join(warning_parts)}


def _render_bulk_review_feedback() -> None:
    result = st.session_state.get(REVIEW_BULK_RESULT_KEY)
    if not isinstance(result, dict):
        return
    success = str(result.get("success") or "")
    warning = str(result.get("warning") or "")
    if success:
        st.success(success)
    if warning:
        st.warning(warning)
    if success and st.button("查看评测结论", type="secondary", key="review_bulk_go_conclusions"):
        st.session_state.current_page = "conclusions"
        st.rerun()


def _review_status_value(item: dict) -> str:
    return str(item["output_row"].get("review_status") or "pending").strip().lower()


def _review_item_label(item: dict) -> str:
    row = item["output_row"]
    return (
        f"{item['case_id']}｜{item['display_model']}｜"
        f"{_score_text(row.get('total_score'))}｜{_display_review_status(row.get('review_status'), item['source'])}"
    )


def _render_score_summary(item: dict, verdict: dict, errors_df: pd.DataFrame, optimization_df: pd.DataFrame) -> None:
    row = item["output_row"]
    recommendation = item["recommendation"]
    reasons = recommendation.get("reasons") or ["暂无原因"]
    model_id = item["model_name"]
    summary_rows = [
        ("样本", item["case_id"]),
        ("模型", item["display_model"]),
        ("完整模型 ID", model_id),
        ("总分", f"{_score_text(row.get('total_score'))} / 100"),
        ("建议处理", str(recommendation.get("recommendation") or "待判断")),
        ("主要原因", summarize_text("；".join(reasons[:3]), 96)),
    ]
    render_inline_status(summary_rows)

    attention = _attention_items(row, errors_df, item["gold"], item["task_info"], item.get("rubric_rows") or [])
    if attention:
        st.markdown("**需要关注**")
        _render_markdown_bullets(attention)
    else:
        st.caption("当前摘要未发现需额外关注的低分维度或红线提示。")

    if st.button(
        "查看评分材料",
        type="tertiary",
        key=f"review_materials::{item['case_id']}::{_safe_key(model_id)}",
    ):
        _render_score_materials_dialog(item, verdict, errors_df, optimization_df)


@st.dialog("评分材料", width="large")
def _render_score_materials_dialog(
    item: dict,
    verdict: dict,
    errors_df: pd.DataFrame,
    optimization_df: pd.DataFrame,
) -> None:
    row = item["output_row"]
    task_info = item["task_info"]
    gold = item["gold"]
    st.caption(f"样本：{item['case_id']} · 模型：{item['display_model']}")

    st.markdown("**任务背景**")
    render_inline_status([
        ("领域", display_label(task_info.get("domain"), DOMAIN_LABELS)),
        ("类型", display_label(task_info.get("task_type"), TASK_TYPE_LABELS)),
        ("难度", DIFFICULTY_LABELS.get(_text(task_info.get("difficulty")), _text(task_info.get("difficulty")))),
        ("风险", RISK_LABELS.get(_text(task_info.get("risk_level")), _text(task_info.get("risk_level")))),
    ])
    st.markdown(_text(task_info.get("context"), "暂无背景材料"))
    st.markdown("**任务题**")
    st.markdown(_text(task_info.get("question"), _text(task_info.get("scenario"), "暂无任务题")))

    st.markdown("**理想回复标准 / Gold Answer**")
    if isinstance(gold, dict):
        render_inline_status([
            ("核心结论", field_text(gold, "core_conclusion", "待补充")),
            ("关键依据", field_text(gold, "key_evidence", "待补充")),
            ("边界条件", field_text(gold, "boundary_conditions", "待补充")),
        ])
        must_points = field_list(gold, "must_have_points")
        red_lines = field_list(gold, "unacceptable_errors")
        if must_points:
            st.markdown("**必须覆盖点**")
            render_clean_list(must_points)
        if red_lines:
            st.markdown("**不可接受错误**")
            render_clean_list(red_lines)
    else:
        st.caption("该任务暂无理想回复标准 / Gold Answer。")

    st.markdown("**模型回答**")
    st.markdown(_text(row.get("answer_text"), "暂无回答内容。"))

    st.markdown("**Rubric 原始要求**")
    rubric_rows = _rubric_material_rows(ds.get_rubric_dimensions())
    if rubric_rows:
        st.dataframe(pd.DataFrame(rubric_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("暂无 Rubric 评分标准。")

    st.markdown("**错误标签**")
    error_rows = build_error_attribution_rows(errors_df, optimization_df, row.get("output_id"))
    if error_rows:
        st.dataframe(pd.DataFrame(error_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("暂无错误标签。")

    st.markdown("**技术明细**")
    render_inline_status([
        ("评分批次", _text(row.get("score_run_id"), "—")),
        ("运行批次", _text(row.get("run_id"), "—")),
        ("裁判模型", md.display_model_name(row.get("judge_model") or sc.DEFAULT_JUDGE_MODEL)),
        ("裁判状态", _text(row.get("judge_status"), "—")),
        ("耗时", f"{_number_text(row.get('latency_ms'))} ms" if has_value(row.get("latency_ms")) else "—"),
        ("使用边界", verdict.get("title") or "待判断"),
    ])


def _render_scoring_basis(output_row: pd.Series | None, errors_df) -> None:
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    rows = build_review_basis_rows(output_row, errors_df)
    if not rows:
        render_empty_state("当前模型回答尚未配置 Rubric 评分标准。")
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


def _errors_by_dimension(errors_df, output_id):
    errors = get_errors_for_output(errors_df, output_id)
    by_dimension: dict[str, list[tuple[str, str]]] = {}
    unmapped: list[tuple[str, str]] = []
    if errors.empty:
        return by_dimension, unmapped
    from src.metrics import ERROR_TYPE_TO_DIMENSION
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        severity = _text(error.get("severity"), "")
        dimension = ERROR_TYPE_TO_DIMENSION.get(error_type)
        if dimension:
            by_dimension.setdefault(dimension, []).append((error_type, severity))
        else:
            unmapped.append((error_type, severity))
    return by_dimension, unmapped


def _errors_by_dimension_field(errors_df, output_id, dimensions: list[dict] | None) -> dict[str, list[str]]:
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
        error_type = _text(error.get("error_type"), "未分类错误")
        severity = _text(error.get("severity"), "未标注")
        dimension_label = ERROR_TYPE_TO_DIMENSION.get(error_type)
        field = default_label_to_field.get(dimension_label or "") or current_label_to_field.get(dimension_label or "")
        if not field:
            continue
        by_field.setdefault(field, []).append(error_type)
    return {field: _dedupe_texts(labels) for field, labels in by_field.items()}


def _dimension_attention(field: str, score: float | None, full: float | None, dim: dict, labels: list[str]) -> str:
    notes: list[str] = []
    if full and score is not None and score / full < RECOMMEND_LOW_DIM_RATIO:
        notes.append("低分维度")
    if labels:
        notes.append("错误标签：" + "、".join(labels[:2]))
    deduction = _clean(dim.get("deduction_rules"))
    if deduction:
        notes.append("扣分规则：" + summarize_text(deduction, 48))
    return "；".join(_dedupe_texts(notes)) or "暂无特别关注点"


def _attention_items(
    row: pd.Series,
    errors_df: pd.DataFrame,
    gold,
    task_info,
    rubric_rows: list[dict],
) -> list[str]:
    items: list[str] = []
    for rubric in rubric_rows or []:
        full = _as_float(rubric.get("full"))
        score = _as_float(rubric.get("score"))
        if full and score is not None and score / full < RECOMMEND_LOW_DIM_RATIO:
            items.append(f"{rubric.get('dimension')}：{score:.0f} / {full:.0f}")
    for hit in detect_redline_hits(errors_df if isinstance(errors_df, pd.DataFrame) else pd.DataFrame(), row.get("output_id"), gold):
        items.append(hit)
    risk = _text(task_info.get("risk_level"), "") if task_info is not None else ""
    if risk == "高":
        items.append("任务风险等级较高，确认前需复核评分依据。")
    return _dedupe_texts(items)[:5]


def _rubric_material_rows(dimensions: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for dim in dimensions or []:
        rows.append(
            {
                "维度": _text(dim.get("name") or dim.get("dimension"), "未标注维度"),
                "满分": _number_text(dim.get("full_mark"), "待补充"),
                "满分标准": _text(dim.get("full_mark_standard"), "待补充"),
                "扣分规则": _text(dim.get("deduction_rules"), "暂无规则"),
            }
        )
    return rows


def _rubric_requirement(field: str, dim: dict) -> str:
    explicit = _clean(dim.get("full_mark_standard"))
    if explicit:
        return explicit
    if has_value(dim.get("full_mark")):
        return _DEFAULT_DIMENSION_BASIS.get(field, "待补充")
    return "待补充"


def _rationale_for_field(row: pd.Series | dict, field: str) -> str:
    mapping = _rationale_map(row)
    text = _clean(mapping.get(field))
    return text or "未返回明确依据"


def _rationale_map(row: pd.Series | dict | None) -> dict[str, str]:
    if row is None:
        return {}
    getter = row.get if hasattr(row, "get") else lambda key, default=None: default
    raw = getter("rationale", "")
    if isinstance(raw, dict):
        return {str(key): _clean(value) for key, value in raw.items()}
    text = _clean(raw)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): _clean(value) for key, value in payload.items()}


def _optimization_lookup(optimization_df: pd.DataFrame | None) -> dict[str, dict]:
    if not isinstance(optimization_df, pd.DataFrame) or optimization_df.empty:
        return {}
    normalized = normalize_optimization_plan(optimization_df)
    lookup: dict[str, dict] = {}
    for _, row in normalized.iterrows():
        error_type = _clean(row.get("error_type"))
        if error_type:
            lookup[error_type] = row.to_dict()
    return lookup


def _number_text(value, fallback: str = "—") -> str:
    if not has_value(value):
        return fallback
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _as_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def _as_int(value) -> int | None:
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


def _format_datetime(value) -> str:
    text = _clean(value)
    if not text:
        return "—"
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text[:19]
    return parsed.strftime("%Y-%m-%d %H:%M")


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if not text or text.lower() in {"nan", "none", "null"} else text


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _render_markdown_bullets(items: list[str]) -> None:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        st.caption("暂无")
        return
    st.markdown("\n".join(f"- {item}" for item in cleaned))


def _render_confirmation_actions(item: dict) -> None:
    row = item.get("score_row") or {}
    row_id = _as_int(item.get("score_row_id"))
    if not row or row_id is None:
        st.caption("未找到可确认的评分草稿。")
        return

    review_status = str(row.get("review_status") or "pending")
    if review_status == "confirmed":
        st.caption("本条评分已确认，已纳入正式结论。")
        return
    if review_status == "skipped":
        st.caption("本条评分已暂不采用，未纳入正式结论。")
        return
    if review_status != "pending":
        st.caption(f"本条评分状态为 {_review_status_label(review_status)}，仅待确认草稿可在此确认。")
        return

    st.caption("确认后才纳入正式结论；暂不采用的评分会保留记录，但不会进入正式结论。")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("确认生效", type="primary", key=f"review_confirm::{row_id}", use_container_width=True):
            _render_confirm_dialog(item)
    with col2:
        if st.button("修订后确认", type="secondary", key=f"review_confirm_edit::{row_id}", use_container_width=True):
            _render_revision_dialog(item)
    with col3:
        if st.button("暂不采用", type="tertiary", key=f"review_skip::{row_id}", use_container_width=True):
            _render_skip_dialog(item)


@st.dialog("确认生效", width="medium")
def _render_confirm_dialog(item: dict) -> None:
    row = item.get("score_row") or {}
    row_id = _as_int(item.get("score_row_id"))
    if row_id is None:
        render_empty_state("未找到可确认的评分草稿。")
        return
    recommendation = item.get("recommendation") or {}
    required = _review_note_required(recommendation)

    st.markdown("你将确认当前评分草稿。确认后，该评分将纳入正式结论。")
    _render_dialog_score_summary(item)
    note = st.text_area("复核说明", value=str(row.get("review_note") or ""), key=f"review_confirm_note::{row_id}")
    if required:
        st.caption("建议复核或不建议采用的评分，需要填写复核说明。")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认生效", type="primary", key=f"review_confirm_dialog_submit::{row_id}", use_container_width=True):
            _confirm_review(row_id, _scores_from_row(row, ds.get_rubric_dimensions()), note, required)
    with col2:
        if st.button("取消", type="tertiary", key=f"review_confirm_dialog_cancel::{row_id}", use_container_width=True):
            st.rerun()


@st.dialog("修订后确认", width="large")
def _render_revision_dialog(item: dict) -> None:
    row = item.get("score_row") or {}
    row_id = _as_int(item.get("score_row_id"))
    if row_id is None:
        render_empty_state("未找到可确认的评分草稿。")
        return
    st.markdown("请修订维度分数，并填写复核说明。保存后，该评分将纳入正式结论。")
    _render_dialog_score_summary(item)
    dimensions = ds.get_rubric_dimensions()
    edited: dict[str, int] = {}
    for dim in dimensions:
        field_name = dim["field"]
        full_mark = int(dim.get("full_mark") or 0)
        current = row.get(field_name)
        value = int(current) if current is not None and str(current) != "nan" else 0
        edited[field_name] = st.number_input(
            dim["name"],
            min_value=0,
            max_value=full_mark,
            value=min(value, full_mark),
            step=1,
            key=f"review_revision_score::{row_id}::{field_name}",
        )
    note = st.text_area("复核说明", value=str(row.get("review_note") or ""), key=f"review_revision_note::{row_id}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("保存并确认", type="primary", key=f"review_revision_submit::{row_id}", use_container_width=True):
            _confirm_review(row_id, edited, note, True)
    with col2:
        if st.button("取消", type="tertiary", key=f"review_revision_cancel::{row_id}", use_container_width=True):
            st.rerun()


@st.dialog("暂不采用", width="medium")
def _render_skip_dialog(item: dict) -> None:
    row_id = _as_int(item.get("score_row_id"))
    if row_id is None:
        render_empty_state("未找到可处理的评分草稿。")
        return
    st.markdown("该评分草稿不会纳入正式结论，但会保留记录，便于后续追溯。")
    _render_dialog_score_summary(item)
    reason = st.text_area("原因", key=f"review_skip_reason::{row_id}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("确认暂不采用", type="primary", key=f"review_skip_submit::{row_id}", use_container_width=True):
            cleaned = _clean(reason)
            if not cleaned:
                st.warning("请填写暂不采用原因。")
                return
            if sc.skip_score_review(row_id, f"暂不采用：{cleaned}"):
                st.info("已暂不采用。该评分草稿仍保留，未纳入正式结论。")
                st.rerun()
            else:
                st.warning("暂不采用操作失败：请确认 SQLite 数据层已初始化。")
    with col2:
        if st.button("取消", type="tertiary", key=f"review_skip_cancel::{row_id}", use_container_width=True):
            st.rerun()


def _render_dialog_score_summary(item: dict) -> None:
    row = item["output_row"]
    recommendation = item.get("recommendation") or {}
    st.markdown(f"**样本：** {item['case_id']}")
    st.markdown(f"**模型：** {item['display_model']}")
    st.markdown(f"**总分：** {_score_text(row.get('total_score'))} / 100")
    st.markdown(f"**建议处理：** {recommendation.get('recommendation') or '待判断'}")


def _review_note_required(recommendation: dict) -> bool:
    return str(recommendation.get("recommendation") or "") != "建议确认"


def _scores_from_row(row: dict | pd.Series, dimensions: list[dict]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for dim in dimensions:
        field_name = str(dim.get("field") or "")
        if not field_name:
            continue
        full_mark = int(dim.get("full_mark") or 0)
        value = row.get(field_name) if hasattr(row, "get") else None
        number = _as_float(value)
        score = 0 if number is None else int(round(number))
        scores[field_name] = max(0, min(full_mark, score))
    return scores


def _confirm_review(row_id: int, edited: dict[str, int], note: str, requires_note: bool) -> None:
    if requires_note and not _clean(note):
        st.warning("建议复核或不建议采用的评分，需要填写复核说明后再确认。")
        return
    if sc.confirm_score_review(row_id, edited, note):
        st.success("已确认生效；该评分将纳入正式结论。")
        st.rerun()
    else:
        st.warning("确认失败：请确认 SQLite 数据层已初始化。")


def _review_status_label(status: str) -> str:
    return {
        "pending": "待确认",
        "confirmed": "已确认",
        "skipped": "暂不采用",
    }.get(str(status).strip().lower(), "待确认")


def _display_review_status(status, source: str) -> str:
    return _review_status_label(str(status or "pending"))


def _review_status_rank(status, source: str) -> int:
    value = str(status or "pending").strip().lower()
    if value == "pending":
        return 0
    if value == "skipped":
        return 1
    if value == "confirmed":
        return 2
    return 3


def _recommendation_rank(recommendation: dict) -> int:
    order = {"不建议采用": 0, "建议复核": 1, "建议确认": 2}
    return order.get(str(recommendation.get("recommendation") or ""), 3)


def _score_text(value) -> str:
    number = _as_float(value)
    return "未评分" if number is None else f"{number:.0f}"


def _safe_key(value) -> str:
    text = "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))
    return text[:80] or "item"


def _text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text
