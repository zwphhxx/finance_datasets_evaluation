"""评测复核页面。

Replaces case_detail review function.
- 展示评判标准、模型回答、建议分、扣分理由、红线和使用边界。
- 人工可修订维度分和复核说明，确认后归档。
"""

from __future__ import annotations

import re
from html import escape

import pandas as pd
import streamlit as st

from app.services import dataset_service as ds
from app.services import scorer as sc
from src.gold_quality import field_list, field_text
from src.metrics import (
    get_case_ids,
    get_errors_for_output,
    get_task_by_case_id,
    merge_case_outputs_with_scores,
)
from src.ui.common import has_value
from src.ui.components import (
    render_clean_list,
    render_compact_hero,
    render_empty_state,
    render_evidence_panel,
    render_inline_status,
    render_key_value_list,
    render_numbered_section,
    render_section_title,
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

ANSWER_SUMMARY_LIMIT = 220

VERDICT_DIRECT_FLOOR = 85.0
VERDICT_PASS_FLOOR = 60.0
VERDICT_WEAK_RATIO = 0.6

_VERDICT_TIERS = {
    "direct": ("可直接使用", "success"),
    "review": ("必须人工复核", "warning"),
    "not_direct": ("不可直接使用", "danger"),
    "none": ("暂无裁判结论", "neutral"),
}


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
    live = bool(eval_status.get("live"))

    config = get_page_config("review")
    render_compact_hero(
        eyebrow="FinDueEval",
        title=config.title,
        question=config.question,
    )
    st.caption(
        "逐条查看评判标准、模型回复、各维度建议分与扣分理由，人工复核后确认归档。"
        "重点是'这道题为什么能测出模型能力'，而不只是分数。"
    )

    # 始终以正式题库决定可选样本
    case_ids = get_case_ids(seed_data.tasks)
    if not case_ids:
        render_empty_state("暂无可展示的任务样本。")
        return

    # 数据来源：默认已沉淀评价；有真实运行时可切换查看本次结果
    data = _resolve_source(seed_data, live_data, live)

    # 选择样本
    domain_by_case = _domain_by_case(seed_data.tasks)
    selected_case = st.selectbox(
        "选择任务",
        case_ids,
        format_func=lambda case_id: f"{case_id} · {domain_by_case.get(case_id, '未标注领域')}",
        key="review_case_select",
    )

    task_rows = get_task_by_case_id(data.tasks, selected_case)
    if task_rows.empty:
        render_empty_state("未找到该任务的记录。")
        return
    task_info = task_rows.iloc[0]
    gold = data.gold_answer_map.get(selected_case)
    merged = merge_case_outputs_with_scores(data.model_outputs, data.scores, selected_case)

    # 01 任务背景与考察能力
    render_numbered_section("01", "任务", "当前评测任务的业务场景、考察能力与数据边界。")
    _render_task_context(task_info)
    _render_task_brief(task_info)

    # 02 参考答案（评测锚点 / 评判标准）
    render_numbered_section("02", "评判标准", "优秀回答的锚点：核心结论、关键依据、边界条件、必须覆盖点与红线。")
    _render_gold_standard(gold)

    # 03 模型回答选择
    render_numbered_section("03", "模型回答", "选择模型查看回答、评分与红线提示。")
    models = get_case_models(merged)
    if models:
        model_totals = []
        for model in models:
            output_row = get_output_row(merged, model)
            total = output_row.get("total_score") if output_row is not None else None
            model_totals.append((model, float(total) if has_value(total) else None))
        model_totals.sort(key=lambda x: (x[1] is None, -(x[1] or 0.0), x[0]))
        selected_model = st.selectbox(
            "选择模型", [m for m, _ in model_totals], key="review_model_select"
        )
        output_row = get_output_row(merged, selected_model)
    else:
        st.selectbox("选择模型", ["暂无模型回答"], disabled=True, key="review_model_select")
        output_row = None
        render_empty_state("该任务暂无模型回答记录。")

    # 04 模型回答详情
    if output_row is not None:
        verdict = build_case_verdict(output_row, data.errors, gold, task_info)
        _render_inline_verdict(verdict)
        _render_model_answer(output_row, gold)

        with st.expander("评分矩阵", expanded=False):
            _render_scoring_matrix(output_row, data.errors)

        # 05 人工点评
        _render_human_review_note(output_row)

        # 06 红线提示
        _render_redline_panel(verdict, gold, output_row, data.errors)

        # 07 人工复核（仅 pending 现场评分）
        _render_case_review(output_row, eval_status)


def _resolve_source(seed_data, live_data, live: bool):
    if not live:
        st.caption("当前展示已沉淀评价。运行评测后可在此切换查看本次结果。")
        return seed_data
    choice = st.radio(
        "样本来源",
        ["已沉淀评价", "本次运行结果"],
        horizontal=True,
        help="默认展示已沉淀评价；本次运行结果仅供对照，不会覆盖正式结论。",
    )
    if choice == "本次运行结果":
        st.caption("正在查看本次运行结果；已沉淀评价不受影响。")
        return live_data
    st.caption("正在查看已沉淀评价。")
    return seed_data


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
        render_empty_state("该任务暂无参考答案记录。")
        return

    from src.gold_quality import evaluate_gold_quality
    quality = evaluate_gold_quality(gold)
    st.markdown(f"**参考答案状态：** {quality['status']}")

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
    st.markdown(
        f"**{verdict['title']}** · 总分 {verdict['score_text']} · {redline_text}"
    )
    st.caption(verdict["reason"])


def _render_model_answer(output_row: pd.Series | None, gold) -> None:
    render_section_title("模型回答")
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
    render_numbered_section("04", "评分矩阵", "维度、权重、Gold 要求、模型得分、扣分与对应错误标签。")
    if output_row is None:
        render_empty_state("暂无可展示数据")
        return
    rubric_rows = build_rubric_rows(output_row)
    if not rubric_rows:
        render_empty_state("当前模型回答尚未配置分项评分。")
        return

    by_dimension, unmapped = _errors_by_dimension(errors_df, output_row.get("output_id"))
    header = (
        "<th>评分维度</th><th>权重</th><th>Gold 要求</th>"
        "<th>模型得分</th><th>扣分原因</th><th>对应错误标签</th>"
    )
    body = ""
    for row in rubric_rows:
        reason = "未扣分" if row["gap"] <= 0 else f'扣 {row["gap"]:.0f} 分（{row["level_text"]}）'
        dimension_errors = by_dimension.get(row["dimension"], [])
        if dimension_errors:
            labels = "".join(
                f'<span class="status-badge status-{SEVERITY_BADGE.get(severity, "neutral")}">{escape(error_type)}</span>'
                for error_type, severity in dimension_errors
            )
        else:
            labels = '<span class="rubric-gap">—</span>'
        body += (
            f'<tr><td><span class="rubric-dim">{escape(row["dimension"])}</span></td>'
            f'<td><span class="rubric-gap">{row["full"]}</span></td>'
            f'<td><span class="rubric-evidence">{escape(row["basis"])}</span></td>'
            f'<td><span class="rubric-score">{row["score"]:.0f} / {row["full"]}</span></td>'
            f'<td><span class="rubric-gap">{escape(reason)}</span></td>'
            f"<td>{labels}</td></tr>"
        )
    table_html = (
        '<table class="rubric-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    render_evidence_panel("维度评分详情", table_html)
    if unmapped:
        extra = "、".join(f"{error_type}（{severity}）" for error_type, severity in unmapped)
        st.caption(f"其他错误标签：{extra}")


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


def _render_human_review_note(output_row: pd.Series | None) -> None:
    render_numbered_section("05", "人工点评", "复核人对该回答的点评，动态读取自评分记录的 review_note。")
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录，暂无人工点评。")
        return
    note = _text(output_row.get("review_note"), "")
    if note:
        render_text_block("复核点评", note)
    else:
        st.caption("该回答暂无人工点评（review_note 为空）。")


def _render_redline_panel(verdict: dict, gold, output_row: pd.Series | None, errors_df) -> None:
    render_numbered_section("06", "红线提示", "结合 Gold 不可接受错误、低分维度与错误标签动态生成。")

    blocks: list[tuple[str, list[str]]] = []

    hits = verdict.get("redline_hits") or []
    if hits:
        blocks.append(("命中红线", hits))

    rubric_rows = build_rubric_rows(output_row) if output_row is not None else []
    weak_dims = [f"{r['dimension']}（{r['score']:.0f}/{r['full']}）" for r in rubric_rows if r["full"] and r["score"] / r["full"] < VERDICT_WEAK_RATIO]
    if weak_dims:
        blocks.append(("低分维度预警", weak_dims))

    errors = (
        get_errors_for_output(errors_df, output_row.get("output_id"))
        if output_row is not None
        else pd.DataFrame()
    )
    if not errors.empty:
        error_items = [
            f"{_text(error.get('error_type'), '未分类错误')}（严重度 {_text(error.get('severity'), '未标注')}）"
            for _, error in errors.iterrows()
        ]
        blocks.append(("错误标签", error_items))

    red_lines = field_list(gold, "unacceptable_errors") if isinstance(gold, dict) else []
    if red_lines:
        blocks.append(("本题标定的不可接受错误（Gold 红线）", red_lines))

    if not blocks:
        render_empty_state("本题未触发红线提示：无高严重度错误、无明显低分维度，且 Gold 未标定红线。")
        return

    col1, col2 = st.columns(2)
    for i, (title, items) in enumerate(blocks):
        with (col1 if i % 2 == 0 else col2):
            render_text_block(title, "")
            render_clean_list(items)


def _render_case_review(output_row: pd.Series | None, eval_status: dict) -> None:
    """在当前 (case, model) 评分处于待复核草稿时，提供就地复核表单。"""
    if output_row is None:
        return
    score_run_id = eval_status.get("score_run_id")
    if not score_run_id:
        return
    case_id = str(output_row.get("case_id") or "")
    model_name = str(output_row.get("model_name") or "")
    row = sc.load_score_row_for_case(score_run_id, case_id, model_name)
    if row is None:
        return
    review_status = str(row.get("review_status") or "pending")
    if review_status == "confirmed":
        st.caption("本条评分已复核归档。")
        return
    if review_status != "pending":
        st.caption(f"本条评分状态为 {_review_status_label(review_status)}，仅待复核草稿可在此归档。")
        return

    dimensions = ds.get_rubric_dimensions()
    render_numbered_section("07", "人工复核", "对照参考答案与模型回答，确认或修订各维度分。")
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
            st.success("已归档为已复核。")
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
    return {"pending": "待复核", "confirmed": "已复核"}.get(str(status).strip().lower(), "待复核")


def _text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text
