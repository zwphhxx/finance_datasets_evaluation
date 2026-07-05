"""评分确认页面。

- 对裁判模型生成的评分草稿进行人工确认、必要修订和归档。
- 确认归档后才进入正式结论；未确认结果仅作为机器建议。
"""

from __future__ import annotations

import json
import re
from html import escape

import pandas as pd
import streamlit as st

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
    merge_case_outputs_with_scores,
    normalize_optimization_plan,
)
from src.ui.common import has_value
from src.ui.components import (
    render_clean_list,
    render_compact_hero,
    render_empty_state,
    render_evidence_panel,
    render_html,
    render_inline_status,
    render_numbered_section,
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
    "当前评分详情",
    "评分依据",
    "风险与红线",
    "确认处理",
]
REVIEW_FILTER_OPTIONS = ["全部", "建议确认", "建议复核", "不建议归档", "已确认"]
BULK_REVIEW_NOTE = "低风险评分草稿，经人工批量确认归档。"

ANSWER_SUMMARY_LIMIT = 220

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
        recommendation, level = "不建议归档", "danger"
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


def _has_red_line(errors_df, output_id) -> bool:
    errors = get_errors_for_output(errors_df, output_id)
    if errors.empty or "severity" not in errors.columns:
        return False
    return any(_text(value) == "高" for value in errors["severity"].tolist())


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
    seed_data = data_bundle.get("base") or data_bundle["data"]
    live_data = data_bundle["data"]
    eval_status = data_bundle.get("eval_status") or {}

    config = get_page_config("review")
    render_compact_hero(
        eyebrow="评分确认",
        title=config.title,
        question=config.question,
    )
    st.caption(
        "本页用于确认评分草稿。确认后的结果才进入正式结论；未确认结果仅作为机器建议。"
    )

    data, result_source = _resolve_source(seed_data, live_data, eval_status)
    items = _build_review_items(data, result_source)
    if not items:
        render_empty_state("暂无可确认的评分记录。请先在发起测试页生成评分草稿。")
        return

    render_numbered_section("01", REVIEW_SECTIONS[0], "低风险评分可批量确认，高风险评分需逐条查看。")
    visible_items = _render_review_queue(items, eval_status, result_source)
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
    verdict = build_case_verdict(output_row, data.errors, gold, task_info)

    render_numbered_section("02", REVIEW_SECTIONS[1], "确认这条评分对应的样本、模型、总分和建议处理。")
    _render_score_detail(item, verdict)

    render_numbered_section("03", REVIEW_SECTIONS[2], "按 Rubric 维度查看得分、评分依据、Gold 要求和错误标签。")
    _render_scoring_matrix(output_row, data.errors)

    render_numbered_section("04", REVIEW_SECTIONS[3], "查看高严重度错误、红线、低分维度和任务风险等级。")
    _render_redline_panel(verdict, gold, output_row, data.errors, task_info)
    _render_error_attribution(output_row, data.errors, getattr(data, "optimizations", pd.DataFrame()))

    render_numbered_section("05", REVIEW_SECTIONS[4], "人工确认、修订后归档，或暂不归档。")
    _render_confirmation_actions(item, eval_status, result_source)


def _resolve_source(seed_data, live_data, eval_status: dict):
    has_score_draft = bool(
        int(eval_status.get("scored", 0) or 0)
        or int(eval_status.get("pending", 0) or 0)
        or int(eval_status.get("confirmed", 0) or 0)
    )
    if not has_score_draft:
        st.caption("当前尚无本次评分草稿，展示示例历史评价。")
        return seed_data, "seed"
    choice = st.radio(
        "数据来源",
        ["本次运行结果", "示例历史评价"],
        horizontal=True,
        help="默认展示本次运行结果；示例历史评价仅用于对照数据方法。",
    )
    if choice == "本次运行结果":
        st.caption("正在查看本次运行结果；待复核评分不会直接进入正式结论。")
        return live_data, "live"
    st.caption("正在查看示例历史评价；这些结果不是当前选择模型生成。")
    return seed_data, "seed"


def _build_review_items(data, result_source: str) -> list[dict]:
    items: list[dict] = []
    for case_id in get_case_ids(data.tasks):
        task_rows = get_task_by_case_id(data.tasks, case_id)
        if task_rows.empty:
            continue
        task_info = task_rows.iloc[0]
        gold = data.gold_answer_map.get(case_id)
        merged = merge_case_outputs_with_scores(data.model_outputs, data.scores, case_id)
        if merged.empty or "model_name" not in merged.columns:
            continue
        for _, row in merged.iterrows():
            model_name = _clean(row.get("model_name"))
            if not model_name:
                continue
            output_row = pd.Series(row)
            if not has_value(output_row.get("total_score")) and result_source != "seed":
                continue
            rubric_rows = build_rubric_rows(output_row)
            recommendation = build_review_recommendation(
                output_row,
                data.errors,
                gold,
                task_info,
                rubric_rows,
            )
            items.append({
                "case_id": case_id,
                "model_name": model_name,
                "display_model": md.display_model_name(model_name, source=result_source),
                "source": result_source,
                "source_label": md.source_label(result_source),
                "task_info": task_info,
                "gold": gold,
                "output_row": output_row,
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


def _render_review_queue(items: list[dict], eval_status: dict, result_source: str) -> list[dict]:
    stats = build_review_queue_stats(items)
    render_inline_status(
        [
            ("待确认", str(stats["pending"])),
            ("建议确认", str(stats["confirm"])),
            ("建议复核", str(stats["review"])),
            ("不建议归档", str(stats["reject"])),
            ("已确认", str(stats["confirmed"])),
        ]
    )

    filter_value = st.selectbox(
        "筛选",
        REVIEW_FILTER_OPTIONS,
        key="review_queue_filter",
        help="按建议处理或确认状态筛选待确认队列。",
    )
    visible_items = filter_review_queue_items(items, filter_value)
    if not visible_items:
        return []

    table_rows = [_review_queue_row(item) for item in visible_items]
    frame = pd.DataFrame(table_rows)
    edited = st.data_editor(
        frame,
        hide_index=True,
        use_container_width=True,
        disabled=["样本编号", "模型", "总分", "建议处理", "主要原因", "复核状态"],
        column_order=["选择", "样本编号", "模型", "总分", "建议处理", "主要原因", "复核状态"],
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", help="仅建议确认且待人工复核的评分可批量确认。"),
            "样本编号": st.column_config.TextColumn("样本编号", width="small"),
            "模型": st.column_config.TextColumn("模型", width="medium"),
            "总分": st.column_config.TextColumn("总分", width="small"),
            "建议处理": st.column_config.TextColumn("建议处理", width="small"),
            "主要原因": st.column_config.TextColumn("主要原因", width="large"),
            "复核状态": st.column_config.TextColumn("复核状态", width="small"),
        },
        key=f"review_queue_editor::{result_source}::{filter_value}",
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
    _render_bulk_confirmation(eligible_items, blocked_items, eval_status, result_source)
    st.caption("队列用于确认评分草稿；示例历史评价只用于对照方法，不进入当前批量确认。")
    return visible_items


def build_review_queue_stats(items: list[dict]) -> dict[str, int]:
    """统计评分确认队列；示例历史评价不计入待确认与已确认口径。"""
    stats = {"pending": 0, "confirm": 0, "review": 0, "reject": 0, "confirmed": 0}
    for item in items:
        if item.get("source") == "seed":
            continue
        status = str(item["output_row"].get("review_status") or "pending").strip().lower()
        if status == "confirmed":
            stats["confirmed"] += 1
            continue
        stats["pending"] += 1
        recommendation = str(item["recommendation"].get("recommendation") or "")
        if recommendation == "建议确认":
            stats["confirm"] += 1
        elif recommendation == "不建议归档":
            stats["reject"] += 1
        else:
            stats["review"] += 1
    return stats


def filter_review_queue_items(items: list[dict], filter_value: str) -> list[dict]:
    if filter_value == "全部":
        return items
    if filter_value == "已确认":
        return [item for item in items if _review_status_value(item) == "confirmed" and item.get("source") != "seed"]
    return [
        item for item in items
        if _review_status_value(item) != "confirmed"
        and str(item["recommendation"].get("recommendation") or "") == filter_value
    ]


def is_bulk_confirm_eligible(item: dict) -> bool:
    return (
        item.get("source") != "seed"
        and _review_status_value(item) == "pending"
        and str(item["recommendation"].get("recommendation") or "") == "建议确认"
    )


def _review_queue_row(item: dict) -> dict[str, object]:
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
    }


def _render_bulk_confirmation(
    eligible_items: list[dict],
    blocked_items: list[dict],
    eval_status: dict,
    result_source: str,
) -> None:
    if result_source == "seed":
        st.caption("当前为示例历史评价，不提供批量确认。")
        return
    if blocked_items:
        st.caption("建议复核、不建议归档或已确认的评分不能批量确认，请进入当前评分详情逐条处理。")

    count = len(eligible_items)
    prompt = f"将确认 {count} 条低风险评分草稿，确认后进入正式结论。" if count else ""
    st.caption(f"已选择 {count} 条可批量确认评分。" + (f" {prompt}" if prompt else ""))
    if st.button(
        "批量确认归档",
        type="primary",
        disabled=count == 0,
        key="review_bulk_confirm",
        use_container_width=False,
    ):
        confirmed, failed = _confirm_low_risk_items(eligible_items, eval_status)
        if confirmed:
            st.success(f"已批量确认 {confirmed} 条评分草稿。")
        if failed:
            st.warning(f"{failed} 条评分未能确认，请进入当前评分详情逐条处理。")
        if confirmed:
            st.rerun()


def _confirm_low_risk_items(items: list[dict], eval_status: dict) -> tuple[int, int]:
    score_run_id = eval_status.get("score_run_id")
    if not score_run_id:
        return 0, len(items)

    row_ids: list[int] = []
    for item in items:
        row = sc.load_score_row_for_case(
            str(score_run_id),
            str(item["case_id"]),
            str(item["model_name"]),
        )
        if row is not None and str(row.get("review_status") or "pending").lower() == "pending":
            row_ids.append(int(row["id"]))
    result = sc.confirm_score_reviews_bulk(row_ids, BULK_REVIEW_NOTE)
    confirmed = int(result.get("confirmed", 0) or 0)
    failed = len(items) - confirmed
    return confirmed, max(0, failed)


def _review_status_value(item: dict) -> str:
    return str(item["output_row"].get("review_status") or "pending").strip().lower()


def _review_item_label(item: dict) -> str:
    row = item["output_row"]
    return (
        f"{item['case_id']}｜{item['display_model']}｜"
        f"{_score_text(row.get('total_score'))}｜{_display_review_status(row.get('review_status'), item['source'])}"
    )


def _render_score_detail(item: dict, verdict: dict) -> None:
    row = item["output_row"]
    task_info = item["task_info"]
    recommendation = item["recommendation"]
    reasons = recommendation.get("reasons") or ["暂无原因"]
    model_id = item["model_name"]
    summary_rows = [
        ("样本", f"{item['case_id']}｜{summarize_text(task_info.get('question'), 24)}"),
        ("模型", item["display_model"]),
        ("总分", _score_text(row.get("total_score"))),
        ("裁判模型", md.display_model_name(row.get("judge_model") or sc.DEFAULT_JUDGE_MODEL)),
        ("评分状态", _display_review_status(row.get("review_status"), item["source"])),
        ("数据来源", item["source_label"]),
    ]
    if item["source"] != "seed" and item["display_model"] != model_id:
        summary_rows.append(("模型 ID", model_id))
    render_inline_status(summary_rows)
    _render_recommendation_note(recommendation)
    st.caption("主要原因：" + "；".join(reasons[:4]))

    answer = _text(row.get("answer_text"), "暂无回答内容。")
    render_text_block("任务摘要", summarize_text(task_info.get("question"), 180))
    render_text_block("模型回答摘要", summarize_text(answer, ANSWER_SUMMARY_LIMIT))
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("查看任务与标准详情", type="tertiary", key=f"review_task_detail::{item['case_id']}"):
            _render_task_and_gold_dialog(task_info, item["gold"])
    with col2:
        if st.button(
            "查看完整模型回答",
            type="tertiary",
            key=f"review_answer_detail::{item['case_id']}::{_safe_key(model_id)}",
            disabled=not bool(answer.strip()),
        ):
            _render_full_answer_dialog(item["display_model"], item["case_id"], answer)
    _render_inline_verdict(verdict)


def _render_recommendation_note(recommendation: dict) -> None:
    level = str(recommendation.get("level") or "neutral")
    title = str(recommendation.get("recommendation") or "待判断")
    render_html(
        f"""
        <div class="review-risk-note review-risk-note-{escape(level)}">
            <strong>{escape(title)}</strong>
            <span>该建议只辅助人工判断，不会自动归档。</span>
        </div>
        """
    )


@st.dialog("任务与标准详情", width="large")
def _render_task_and_gold_dialog(task_info, gold) -> None:
    st.markdown("#### 任务内容")
    _render_task_context(task_info)
    _render_task_brief(task_info)
    st.markdown("#### 理想回复标准 / Gold Answer")
    _render_gold_standard(gold)


@st.dialog("模型回答详情", width="large")
def _render_full_answer_dialog(model_name: str, case_id: str, answer: str) -> None:
    st.caption(f"样本：{case_id} · 模型：{model_name}")
    st.markdown(answer or "暂无回答内容。")


def _render_task_context(task_info: pd.Series) -> None:
    domain = display_label(task_info.get("domain"), DOMAIN_LABELS)
    task_type = display_label(task_info.get("task_type"), TASK_TYPE_LABELS)
    difficulty = DIFFICULTY_LABELS.get(_text(task_info.get("difficulty")), _text(task_info.get("difficulty")))
    risk = RISK_LABELS.get(_text(task_info.get("risk_level")), _text(task_info.get("risk_level")))
    requirement = _text(task_info.get("question"), _text(task_info.get("scenario"), "暂无任务要求"))
    capability = _text(task_info.get("expected_capability"), "暂无考察能力说明")

    render_text_block("任务要求", requirement)
    render_inline_status([
        ("领域", domain),
        ("类型", task_type),
        ("难度", difficulty),
        ("风险", risk),
        ("考察能力", capability),
    ])


def _render_task_brief(task_info: pd.Series) -> None:
    background = _text(task_info.get("context"), "暂无背景材料")
    requirement = _text(task_info.get("question"), _text(task_info.get("scenario"), "暂无任务要求"))
    capability = _text(task_info.get("expected_capability"), "暂无考察能力说明")

    left = (
        f'<div class="text-block"><div class="text-block-label">任务背景</div>'
        f'<div class="text-block-body">{escape(background)}</div></div>'
        f'<div class="text-block"><div class="text-block-label">考察能力</div>'
        f'<div class="text-block-body">{escape(capability)}</div></div>'
    )
    right = (
        f'<div class="text-block"><div class="text-block-label">任务要求</div>'
        f'<div class="text-block-body">{escape(requirement)}</div></div>'
    )
    render_two_column_panel(left, right)


def _render_gold_standard(gold: dict | None) -> None:
    if not isinstance(gold, dict):
        render_empty_state("该任务暂无理想回复标准 / Gold Answer 记录。")
        return

    from src.gold_quality import evaluate_gold_quality
    quality = evaluate_gold_quality(gold)
    st.markdown(f"**Gold Answer 状态：** {quality['status']}")

    core = field_text(gold, "core_conclusion", "需进一步补充")
    evidence = field_text(gold, "key_evidence", "待补充依据")
    boundary = field_text(gold, "boundary_conditions", "待补充边界")

    left = (
        f'<div class="text-block"><div class="text-block-label">标准结论</div>'
        f'<div class="text-block-body">{escape(core)}</div></div>'
        f'<div class="text-block"><div class="text-block-label">关键依据</div>'
        f'<div class="text-block-body">{escape(evidence)}</div></div>'
    )
    right = (
        f'<div class="text-block"><div class="text-block-label">边界条件</div>'
        f'<div class="text-block-body">{escape(boundary)}</div></div>'
    )
    render_two_column_panel(left, right)

    must_points = field_list(gold, "must_have_points")
    red_lines = field_list(gold, "unacceptable_errors")

    col_left, col_right = st.columns(2)
    with col_left:
        render_text_block("必须覆盖点", "")
        if must_points:
            render_clean_list(must_points)
        else:
            st.caption("暂无")
    with col_right:
        render_text_block("不可接受错误（红线）", "")
        if red_lines:
            render_clean_list(red_lines)
        else:
            st.caption("暂无")

    review = quality["manual_review"]
    if review:
        st.caption(f"人工复核提示：{review}")


def _render_inline_verdict(verdict: dict) -> None:
    redline_count = len(verdict.get("redline_hits") or [])
    redline_text = f"红线命中 {redline_count} 项" if redline_count else "未命中红线"
    render_html(
        f"""
        <div class="review-risk-note review-risk-note-{escape(str(verdict.get("level", "neutral")))}">
            <strong>{escape(str(verdict["title"]))}</strong>
            <span>总分 {escape(str(verdict["score_text"]))} · {escape(redline_text)}</span>
            <p>{escape(str(verdict["reason"]))}</p>
        </div>
        """
    )


def _render_model_answer(output_row: pd.Series | None, gold) -> None:
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录。")
        return

    answer = _text(output_row.get("answer_text"), "暂无回答内容。")
    render_text_block("回答摘要", summarize_text(answer, ANSWER_SUMMARY_LIMIT))
    if len(answer) > ANSWER_SUMMARY_LIMIT:
        with st.expander("查看完整模型回答"):
            st.write(answer)

    must_points = field_list(gold, "must_have_points") if isinstance(gold, dict) else []
    if must_points:
        covered, missed = build_point_coverage(must_points, answer)
        with st.expander("要点覆盖", expanded=False):
            st.caption("基于关键词近似匹配，仅供对照参考。")
            col1, col2 = st.columns(2)
            with col1:
                render_text_block("已覆盖要点", "")
                render_clean_list(covered if covered else ["未识别到明确覆盖"])
            with col2:
                render_text_block("遗漏要点", "")
                render_clean_list(missed if missed else ["未识别到明显遗漏"])


def _render_scoring_matrix(output_row: pd.Series | None, errors_df) -> None:
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    rows = build_review_scoring_matrix_rows(output_row, errors_df)
    if not rows:
        render_empty_state("当前模型回答尚未配置 Rubric 评分标准。")
        return

    header = (
        "<th>评分维度</th><th>满分</th><th>理想回复要求 / Gold 要求</th>"
        "<th>模型得分</th><th>评分依据</th><th>扣分原因</th><th>对应错误标签</th>"
    )
    body = ""
    for row in rows:
        labels = _labels_html(row["对应错误标签"])
        body += (
            f'<tr><td><span class="rubric-dim">{escape(row["评分维度"])}</span></td>'
            f'<td><span class="rubric-gap">{escape(row["满分"])}</span></td>'
            f'<td><span class="rubric-evidence">{escape(row["理想回复要求 / Gold 要求"])}</span></td>'
            f'<td><span class="rubric-score">{escape(row["模型得分"])}</span></td>'
            f'<td><span class="rubric-evidence">{escape(row["评分依据"])}</span></td>'
            f'<td><span class="rubric-gap">{escape(row["扣分原因"])}</span></td>'
            f"<td>{labels}</td></tr>"
        )
    table_html = (
        '<table class="rubric-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    render_evidence_panel("维度评分详情", table_html)


def _render_error_attribution(output_row: pd.Series | None, errors_df, optimization_df) -> None:
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录，暂无错误归因。")
        return
    rows = build_error_attribution_rows(errors_df, optimization_df, output_row.get("output_id"))
    if not rows:
        render_empty_state("暂无错误标签。")
        return
    headers = ["错误类型", "严重程度", "错误表现", "修正方向", "数据优化建议"]
    header = "".join(f"<th>{escape(name)}</th>" for name in headers)
    body = ""
    for row in rows:
        body += (
            f'<tr><td class="check-key">{escape(row["错误类型"])}</td>'
            f'<td>{escape(row["严重程度"])}</td>'
            f'<td>{escape(row["错误表现"])}</td>'
            f'<td>{escape(row["修正方向"])}</td>'
            f'<td>{escape(row["数据优化建议"])}</td></tr>'
        )
    render_evidence_panel(
        "错误归因明细",
        f'<table class="check-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>',
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


def _labels_html(value: str) -> str:
    if not value or value == "暂无错误标签":
        return '<span class="status-badge status-muted">暂无错误标签</span>'
    return "".join(
        f'<span class="status-badge status-neutral">{escape(label)}</span>'
        for label in [item.strip() for item in value.split("；") if item.strip()]
    )


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


def _render_redline_panel(verdict: dict, gold, output_row: pd.Series | None, errors_df, task_info) -> None:
    blocks = build_redline_blocks(verdict, gold, output_row, errors_df, task_info)
    if not blocks:
        render_html(
            '<div class="review-risk-note review-risk-note-neutral">'
            '<strong>当前未发现红线提示</strong>'
            '<span>无高严重度错误、无关键维度低分，当前 Gold Answer 未标定不可接受错误。</span>'
            '</div>'
        )
        return
    html = ""
    for block in blocks:
        items = "".join(f"<li>{escape(str(item))}</li>" for item in block["items"])
        html += (
            '<div class="review-risk-note review-risk-note-danger">'
            f'<strong>{escape(str(block["title"]))}</strong>'
            f'<ul class="clean-list">{items}</ul>'
            '</div>'
        )
    render_html(html)


def _render_confirmation_actions(item: dict, eval_status: dict, result_source: str) -> None:
    output_row = item["output_row"]
    recommendation = item["recommendation"]
    if result_source == "seed":
        st.caption("当前为示例历史评价，不提供归档操作。请在发起测试页生成本次评分草稿后再确认。")
        return

    score_run_id = eval_status.get("score_run_id")
    if not score_run_id:
        st.caption("当前评分草稿尚未落库，暂不能确认归档。SQLite 可用后可在此确认。")
        return

    case_id = str(output_row.get("case_id") or "")
    model_name = str(output_row.get("model_name") or "")
    row = sc.load_score_row_for_case(score_run_id, case_id, model_name)
    if row is None:
        st.caption("未找到可归档的评分草稿。")
        return

    review_status = str(row.get("review_status") or "pending")
    if review_status == "confirmed":
        st.caption("本条评分已确认归档，已可进入正式结论。")
        return
    if review_status != "pending":
        st.caption(f"本条评分状态为 {_review_status_label(review_status)}，仅待复核草稿可在此归档。")
        return

    row_id = int(row["id"])
    skip_key = f"review_not_archive::{row_id}"
    if st.session_state.get(skip_key):
        render_html(
            '<div class="review-risk-note review-risk-note-muted">'
            '<strong>已暂不归档</strong>'
            '<span>该操作不改变数据库状态；评分草稿仍保留，未进入正式结论。</span>'
            '</div>'
        )

    dimensions = ds.get_rubric_dimensions()
    st.caption("可直接确认，也可修订维度分与复核说明后归档。确认后才进入正式结论。")
    cols = st.columns(len(dimensions))
    edited: dict[str, int] = {}
    original: dict[str, int] = {}
    for i, dim in enumerate(dimensions):
        field_name = dim["field"]
        full_mark = int(dim.get("full_mark") or 0)
        current = row.get(field_name)
        value = int(current) if current is not None and str(current) != "nan" else 0
        original[field_name] = min(value, full_mark)
        edited[field_name] = cols[i].number_input(
            dim["name"], min_value=0, max_value=full_mark, value=min(value, full_mark),
            step=1, key=f"review_score::{row_id}::{field_name}",
        )
    note = st.text_area(
        "复核说明", value=str(row.get("review_note") or ""), key=f"review_note::{row_id}"
    )
    changed = any(edited.get(key) != original.get(key) for key in edited)
    requires_note = recommendation.get("recommendation") != "建议确认" or changed
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("确认归档", type="primary", key=f"review_confirm::{row_id}", use_container_width=True):
            _confirm_review(row_id, edited, note, requires_note)
    with col2:
        if st.button("修订后归档", type="secondary", key=f"review_confirm_edit::{row_id}", use_container_width=True):
            _confirm_review(row_id, edited, note, True)
    with col3:
        if st.button("暂不归档", type="tertiary", key=f"review_skip::{row_id}", use_container_width=True):
            st.session_state[skip_key] = True
            st.info("已暂不归档。该评分草稿仍保留，未进入正式结论。")


def _confirm_review(row_id: int, edited: dict[str, int], note: str, requires_note: bool) -> None:
    if requires_note and not _clean(note):
        st.warning("建议复核或不建议归档的评分，需要填写复核说明后再归档。")
        return
    if sc.confirm_score_review(row_id, edited, note):
        st.success("已确认归档；该评分可进入正式结论。")
        st.rerun()
    else:
        st.warning("归档失败：请确认 SQLite 数据层已初始化。")


def _render_case_review(output_row: pd.Series | None, eval_status: dict) -> None:
    """在当前 (case, model) 评分处于待复核草稿时，提供就地复核表单。"""
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录，不能进行人工复核。")
        return
    score_run_id = eval_status.get("score_run_id")
    if not score_run_id:
        st.caption("当前展示的是已沉淀评价或会话内结果；只有待人工复核的评分草稿可在此确认归档。")
        return
    case_id = str(output_row.get("case_id") or "")
    model_name = str(output_row.get("model_name") or "")
    row = sc.load_score_row_for_case(score_run_id, case_id, model_name)
    if row is None:
        st.caption("未找到可归档的评分草稿。")
        return
    review_status = str(row.get("review_status") or "pending")
    if review_status == "confirmed":
        st.caption("本条评分已确认归档。")
        return
    if review_status != "pending":
        st.caption(f"本条评分状态为 {_review_status_label(review_status)}，仅待复核草稿可在此归档。")
        return

    dimensions = ds.get_rubric_dimensions()
    st.caption("请对照理想回复标准 / Gold Answer、模型回答和评分矩阵确认建议分；确认后才进入正式结论。")
    cols = st.columns(len(dimensions))
    edited: dict[str, int] = {}
    for i, dim in enumerate(dimensions):
        field_name = dim["field"]
        full_mark = int(dim.get("full_mark") or 0)
        current = row.get(field_name)
        value = int(current) if current is not None and str(current) != "nan" else 0
        edited[field_name] = cols[i].number_input(
            dim["name"], min_value=0, max_value=full_mark, value=min(value, full_mark),
            step=1, key=f"review_score::{row['id']}::{field_name}",
        )
    note = st.text_area(
        "复核说明", value=str(row.get("review_note") or ""), key=f"review_note::{row['id']}"
    )
    if st.button("确认并归档", type="primary", key=f"review_confirm::{row['id']}"):
        if sc.confirm_score_review(int(row["id"]), edited, note):
            st.success("已确认归档；该评分可进入正式结论。")
            st.rerun()
        else:
            st.warning("归档失败：请确认 SQLite 数据层已初始化。")


def _domain_by_case(tasks_df: pd.DataFrame) -> dict[str, str]:
    if tasks_df.empty or "case_id" not in tasks_df:
        return {}
    return {
        str(row.get("case_id")): display_label(row.get("domain"), DOMAIN_LABELS)
        for _, row in tasks_df.iterrows()
    }


def _review_status_label(status: str) -> str:
    return {"pending": "待人工复核", "confirmed": "已复核"}.get(str(status).strip().lower(), "待人工复核")


def _display_review_status(status, source: str) -> str:
    if source == "seed":
        return "示例历史评价"
    return _review_status_label(str(status or "pending"))


def _review_status_rank(status, source: str) -> int:
    if source == "seed":
        return 9
    value = str(status or "pending").strip().lower()
    if value == "pending":
        return 0
    if value == "confirmed":
        return 2
    return 1


def _recommendation_rank(recommendation: dict) -> int:
    order = {"不建议归档": 0, "建议复核": 1, "建议确认": 2}
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
