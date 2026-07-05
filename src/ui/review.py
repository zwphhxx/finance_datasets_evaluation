"""评测复核页面。

- 展示任务背景、理想回复标准、模型回答、评分矩阵、错误归因和红线提示。
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
    "任务与背景",
    "理想回复标准 / Gold Answer",
    "模型回答摘要",
    "评分矩阵",
    "错误归因",
    "红线提示",
    "人工复核",
]

ANSWER_SUMMARY_LIMIT = 220

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
        labels = "；".join(errors_by_field.get(field, [])) or "暂无错误标签"
        rows.append({
            "评分维度": name,
            "满分": full_text,
            "理想回复要求 / Gold 要求": requirement,
            "模型得分": score_text,
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
        eyebrow="人工复核",
        title=config.title,
        question=config.question,
    )
    st.caption(
        "逐条对照理想回复标准 / Gold Answer、模型回答、评分矩阵、错误归因与红线提示；"
        "评分草稿必须人工复核确认后才进入正式结论。"
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

    render_numbered_section("01", REVIEW_SECTIONS[0], "当前评测任务的业务场景、背景材料、考察能力与使用边界。")
    _render_task_context(task_info)
    _render_task_brief(task_info)

    render_numbered_section("02", REVIEW_SECTIONS[1], "裁判评分链路使用的评判锚点，包含核心结论、必须覆盖点和红线错误。")
    _render_gold_standard(gold)

    render_numbered_section("03", REVIEW_SECTIONS[2], "选择模型后查看回答摘要；完整回答收在折叠区。")
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

    if output_row is not None:
        verdict = build_case_verdict(output_row, data.errors, gold, task_info)
        _render_inline_verdict(verdict)
        _render_model_answer(output_row, gold)

        render_numbered_section("04", "评分矩阵", "按 Rubric 维度展示 Gold 要求、模型得分、扣分原因和错误标签。")
        _render_scoring_matrix(output_row, data.errors)

        render_numbered_section("05", "错误归因", "把错误标签转化为错误表现、修正方向和数据优化建议。")
        _render_error_attribution(output_row, data.errors, getattr(data, "optimizations", pd.DataFrame()))

        render_numbered_section("06", "红线提示", "结合 Gold 红线、高严重度错误、关键低分维度和任务风险等级。")
        _render_redline_panel(verdict, gold, output_row, data.errors, task_info)

        render_numbered_section("07", "人工复核", "人工可修订建议分与复核说明；复核确认后才进入正式结论。")
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
        "<th>模型得分</th><th>扣分原因</th><th>对应错误标签</th>"
    )
    body = ""
    for row in rows:
        labels = _labels_html(row["对应错误标签"])
        body += (
            f'<tr><td><span class="rubric-dim">{escape(row["评分维度"])}</span></td>'
            f'<td><span class="rubric-gap">{escape(row["满分"])}</span></td>'
            f'<td><span class="rubric-evidence">{escape(row["理想回复要求 / Gold 要求"])}</span></td>'
            f'<td><span class="rubric-score">{escape(row["模型得分"])}</span></td>'
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
        st.caption("本条评分已复核归档。")
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
            st.success("已复核归档；该评分可进入正式结论。")
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


def _text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text
