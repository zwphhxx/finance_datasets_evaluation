from __future__ import annotations

import re
from html import escape

import pandas as pd
import streamlit as st

from src.metrics import (
    ERROR_TYPE_TO_DIMENSION,
    get_case_ids,
    get_errors_for_output,
    get_preference_pair_details_for_case,
    get_task_by_case_id,
    merge_case_outputs_with_scores,
)
from app.services import dataset_service as ds
from app.services import scorer as sc
from src.ui.common import has_value
from src.gold_quality import evaluate_gold_quality, field_list, field_text
from src.ui.page_config import get_page_config
from src.ui.tasks import (
    DIFFICULTY_LABELS,
    DOMAIN_LABELS,
    RISK_LABELS,
    TASK_TYPE_LABELS,
    display_label,
    summarize_text,
)
from src.ui.components import (
    render_answer_boundary_panel,
    render_card,
    render_empty_state,
    render_empty_state_with_actions,
    render_html,
    render_info_panel,
    render_preference_comparison,
    render_page_shell,
    render_review_caveat,
    render_section_title,
)


# 当 Rubric 数据表未维护满分标准时，用作 Gold 要求展示的默认依据文案。
# 真实来源应为 dataset_service.get_rubric_dimensions() 返回的 full_mark_standard。
_DEFAULT_DIMENSION_BASIS = {
    "accuracy_score": "结论与关键计算是否准确，并对照判断依据。",
    "reasoning_score": "分析逻辑是否完整，是否贴合任务场景。",
    "coverage_score": "是否覆盖必须关注的风险点与核查事项。",
    "evidence_score": "是否提供法规、数据等可靠依据支撑结论。",
    "expression_score": "表达是否清晰、审慎，符合专业报告风格。",
}

# 保留旧版 RUBRIC 常量以兼容既有测试；页面实际渲染使用 _get_rubric() 从 DB / manifest 读取。
RUBRIC = [
    ("accuracy_score", "专业准确性", 30, _DEFAULT_DIMENSION_BASIS["accuracy_score"]),
    ("reasoning_score", "推理与场景适配", 20, _DEFAULT_DIMENSION_BASIS["reasoning_score"]),
    ("coverage_score", "风险覆盖", 20, _DEFAULT_DIMENSION_BASIS["coverage_score"]),
    ("evidence_score", "依据可靠性", 15, _DEFAULT_DIMENSION_BASIS["evidence_score"]),
    ("expression_score", "专业表达", 15, _DEFAULT_DIMENSION_BASIS["expression_score"]),
]

SEVERITY_BADGE = {"高": "danger", "中": "warning", "低": "neutral"}
PRIORITY_BADGE = {"高": "danger", "中": "warning", "低": "neutral"}

ANSWER_SUMMARY_LIMIT = 220

# 裁判结论阈值（评测方法学配置，非针对具体模型 / 案例的结论）。满分按 100 计。
VERDICT_DIRECT_FLOOR = 85.0  # 总分达到此线且无显著维度短板，方可作为「可直接使用」候选
VERDICT_PASS_FLOOR = 60.0    # 及格线，低于此线不可直接使用
VERDICT_WEAK_RATIO = 0.6     # 分项达成率低于此值视为维度短板

# 三类使用边界的展示标题与状态色（低饱和：绿 / 米 / 玫瑰）。
_VERDICT_TIERS = {
    "direct": ("可直接使用", "success"),
    "review": ("必须人工复核", "warning"),
    "not_direct": ("不可直接使用", "danger"),
    "none": ("暂无裁判结论", "neutral"),
}


# --- data derivation (pure, dynamic on case + model) --------------------------

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


def _get_rubric() -> list[dict]:
    """返回当前生效的 Rubric 维度，优先使用 DB / manifest 维护的值。"""
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


def _optimization_lookup(optimization_df: pd.DataFrame) -> dict[str, dict]:
    if optimization_df.empty or "frequent_error" not in optimization_df:
        return {}
    return {
        str(row["frequent_error"]): row.to_dict()
        for _, row in optimization_df.iterrows()
    }


def build_error_attribution(errors_df: pd.DataFrame, optimization_df: pd.DataFrame, output_id) -> list[dict]:
    """Errors tied to one model output, joined to a likely data cause."""
    errors = get_errors_for_output(errors_df, output_id)
    if errors.empty:
        return []
    lookup = _optimization_lookup(optimization_df)
    records = []
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        plan = lookup.get(error_type, {})
        likely_cause = _text(plan.get("likely_cause"), _text(error.get("correction"), "暂无记录"))
        records.append(
            {
                "error_type": error_type,
                "severity": _text(error.get("severity"), "未标注"),
                "description": _text(error.get("error_description"), "暂无说明"),
                "likely_cause": likely_cause,
            }
        )
    return records


def build_data_fix_actions(errors_df: pd.DataFrame, optimization_df: pd.DataFrame, output_id) -> list[dict]:
    """Executable data actions, one per distinct error label of this output."""
    errors = get_errors_for_output(errors_df, output_id)
    if errors.empty:
        return []
    lookup = _optimization_lookup(optimization_df)
    records = []
    seen = set()
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        if error_type in seen:
            continue
        seen.add(error_type)
        plan = lookup.get(error_type, {})
        action = _text(plan.get("optimization_action"), _text(error.get("optimization_action"), "暂无对应动作"))
        records.append(
            {
                "error_type": error_type,
                "action": action,
                "sample_format": _text(plan.get("data_sample_format"), "暂无样本格式"),
                "priority": _text(plan.get("priority"), "未标注"),
                "typical_problem": _text(plan.get("typical_problem"), ""),
            }
        )
    return records


def build_point_coverage(points, answer_text) -> tuple[list[str], list[str]]:
    """Approximate which must-have points the answer covers, by keyword match.

    Coverage is a presentation heuristic over the answer text, not stored data;
    it works for any case/model and is labelled as approximate in the UI.
    """
    answer = _normalize_text(answer_text)
    covered: list[str] = []
    missed: list[str] = []
    for point in points:
        text = str(point).strip()
        if not text:
            continue
        keywords = [token for token in re.split(r"[，。、；：（）()/\s,.;:]+", text) if len(token) >= 3]
        if keywords:
            hit = any(_normalize_text(token) in answer for token in keywords)
        else:
            hit = _normalize_text(text) in answer
        (covered if hit else missed).append(text)
    return covered, missed


def _normalize_text(value) -> str:
    return re.sub(r"\s+", "", str(value))


def _has_red_line(errors_df, output_id) -> bool:
    """A red-line error is triggered when this output carries a high-severity label."""
    errors = get_errors_for_output(errors_df, output_id)
    if errors.empty or "severity" not in errors.columns:
        return False
    return any(_text(value) == "高" for value in errors["severity"].tolist())


def _errors_by_dimension(errors_df, output_id):
    """Bucket this output's error labels under the Rubric dimension each affects."""
    errors = get_errors_for_output(errors_df, output_id)
    by_dimension: dict[str, list[tuple[str, str]]] = {}
    unmapped: list[tuple[str, str]] = []
    if errors.empty:
        return by_dimension, unmapped
    for _, error in errors.iterrows():
        error_type = _text(error.get("error_type"), "未分类错误")
        severity = _text(error.get("severity"), "")
        dimension = ERROR_TYPE_TO_DIMENSION.get(error_type)
        if dimension:
            by_dimension.setdefault(dimension, []).append((error_type, severity))
        else:
            unmapped.append((error_type, severity))
    return by_dimension, unmapped


def detect_redline_hits(errors_df, output_id, gold) -> list[str]:
    """Red-line hits for one model output, derived dynamically.

    Two sources, both from data: high-severity error labels on this output, and
    this output's error text approximately matching the case's Gold
    `unacceptable_errors`. Nothing is hardcoded; returns [] when no signal.
    """
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
                keywords = [token for token in re.split(r"[，。、；：（）()/\s,.;:]+", text) if len(token) >= 3]
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


def _suggested_data_action(errors_df, optimization_df, output_id) -> str:
    """Pick a data-improvement action for this output, dynamically.

    Prefers an action linked through the optimization plan / error labels; when
    errors exist but no mapping is available, asks for the missing label mapping
    rather than inventing a fix; when there is no error at all, says so plainly.
    """
    actions = build_data_fix_actions(errors_df, optimization_df, output_id)
    for action in actions:
        if action["action"] and action["action"] != "暂无对应动作":
            return f'{action["error_type"]} → {action["action"]}'
    if actions:
        return "待补充标签映射"
    return "未触发错误标签，暂无补强动作"


def _weakest_rubric(rubric_rows: list[dict]) -> tuple[str, bool]:
    """Return (weakest dimension text, has a below-threshold weak dimension)."""
    if not rubric_rows:
        return "暂无分项评分", False
    weakest = min(rubric_rows, key=lambda row: (row["score"] / row["full"] if row["full"] else 0.0))
    weak_text = f'{weakest["dimension"]}（{weakest["score"]:.0f}/{weakest["full"]}）'
    has_weak = any(
        (row["full"] and row["score"] / row["full"] < VERDICT_WEAK_RATIO) for row in rubric_rows
    )
    return weak_text, has_weak


def build_case_verdict(output_row, errors_df, gold, optimization_df, task_info) -> dict:
    """Derive the redline verdict for one (case, model) from its data.

    Tier order of precedence: a red-line hit overrides everything; otherwise a
    high-risk task stays human-only; otherwise the total score and dimension
    shortfalls decide direct / review / not-direct. Fully dynamic and robust to
    missing output, scores, errors or Gold.
    """
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
            "suggested_action": "未触发错误标签，暂无补强动作",
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
        "suggested_action": _suggested_data_action(errors_df, optimization_df, output_id),
    }


def build_case_model_comparison(merged_outputs, errors_df, gold, optimization_df, task_info) -> list[dict]:
    """同一道题下、每个模型一行的对比结论。

    复用 ``build_case_verdict`` 推导每个模型的使用边界结论、总分、最弱维度与红线
    命中数，便于并排对照。完全由当前 case 的数据动态生成，无模型 / 分数硬编码；
    无模型回答时返回空列表。
    """
    rows: list[dict] = []
    for model in get_case_models(merged_outputs):
        output_row = get_output_row(merged_outputs, model)
        verdict = build_case_verdict(output_row, errors_df, gold, optimization_df, task_info)
        total = output_row.get("total_score") if output_row is not None else None
        rows.append(
            {
                "model_name": str(model),
                "tier": verdict["tier"],
                "title": verdict["title"],
                "level": verdict["level"],
                "score_text": verdict["score_text"],
                "total": float(total) if has_value(total) else None,
                "weakest": verdict["weakest"],
                "redline_count": len(verdict["redline_hits"]),
                "review_note": _text(output_row.get("review_note"), "") if output_row is not None else "",
            }
        )
    # 有分在前、分高在前，仅为展示稳定性；页面文案明确这是样本内观察而非排行榜。
    rows.sort(key=lambda row: (row["total"] is None, -(row["total"] or 0.0), row["model_name"]))
    return rows


def build_case_rationale(task_info, gold, comparison: list[dict]) -> dict:
    """这道题为什么能测出模型能力：考察能力、Gold 锚点数量与模型分差。

    全部由任务与 Gold 数据动态推导：必须覆盖点 / 红线作为评测锚点，模型间总分差
    用来说明该题是否能区分模型表现。缺任务或缺 Gold 时各字段安全回退。
    """
    capability = _text(task_info.get("expected_capability"), "") if task_info is not None else ""
    domain = display_label(task_info.get("domain"), DOMAIN_LABELS) if task_info is not None else "未标注领域"
    risk = (
        RISK_LABELS.get(_text(task_info.get("risk_level")), _text(task_info.get("risk_level"), "未标注"))
        if task_info is not None
        else "未标注"
    )
    must_points = field_list(gold, "must_have_points") if isinstance(gold, dict) else []
    red_lines = field_list(gold, "unacceptable_errors") if isinstance(gold, dict) else []
    totals = [row["total"] for row in comparison if row.get("total") is not None]
    spread = (max(totals) - min(totals)) if len(totals) >= 2 else None
    return {
        "capability": capability,
        "domain": domain,
        "risk": risk,
        "must_count": len(must_points),
        "redline_count": len(red_lines),
        "model_count": len(comparison),
        "score_spread": spread,
    }


# --- rendering ---------------------------------------------------------------

def render_case_detail_page(data_bundle: dict) -> None:
    seed_data = data_bundle.get("base") or data_bundle["data"]
    live_data = data_bundle["data"]
    eval_status = data_bundle.get("eval_status") or {}
    live = bool(eval_status.get("live"))

    render_page_shell(get_page_config("case_detail"))
    render_review_caveat(eval_status)
    render_info_panel(
        "怎么读这一页",
        "这里用一道真实尽调题做拆解：先看它考察什么、优秀回答的锚点（Gold Answer）是什么，"
        "再并排对照各模型回答差在哪里。重点是“这道题为什么能测出模型能力”，而不只是分数。",
    )

    # 始终以 seed 题库决定可选样本，保证未运行真实评测时也能拆解离线评价。
    case_ids = get_case_ids(seed_data.tasks)
    if not case_ids:
        render_empty_state_with_actions(
            "暂无可展示的任务样本。",
            [("去数据集管理", "dataset_admin"), ("浏览数据集质量", "dataset_quality")],
        )
        return

    # 数据来源：默认离线 seed 评价；有真实运行时可切换查看本次结果，但不覆盖离线评价。
    data = _resolve_source(seed_data, live_data, live)

    # 1) 选择样本
    domain_by_case = _domain_by_case(seed_data.tasks)
    selected_case = st.selectbox(
        "选择任务",
        case_ids,
        format_func=lambda case_id: f"{case_id} · {domain_by_case.get(case_id, '未标注领域')}",
    )

    task_rows = get_task_by_case_id(data.tasks, selected_case)
    if task_rows.empty:
        render_empty_state("未找到该任务的记录。")
        return
    task_info = task_rows.iloc[0]
    gold = data.gold_answer_map.get(selected_case)
    merged = merge_case_outputs_with_scores(data.model_outputs, data.scores, selected_case)
    comparison = build_case_model_comparison(merged, data.errors, gold, data.optimizations, task_info)

    # 2) 这道题为什么能测出模型能力（先给框架性结论）
    _render_why_this_case(task_info, gold, comparison)

    # 3) 任务背景与考察能力
    render_section_title("任务背景与考察能力", "这道题放在什么尽调场景下、要考察模型哪种专业能力。")
    _render_task_context(task_info)
    with st.expander("查看任务题全文", expanded=False):
        _render_task_brief(task_info)

    # 4) Gold Answer（评测锚点）
    _render_gold_standard(gold)

    # 5) 模型回答对比（并排结论）+ 单模型深拆
    render_section_title("模型回答对比", "先并排看各模型在本题上的结论，再切换查看单个模型的回答与扣分。")
    _render_model_comparison(comparison)

    if comparison:
        selected_model = st.selectbox("选择模型", [row["model_name"] for row in comparison], key="case_detail_model")
        output_row = get_output_row(merged, selected_model)
    else:
        st.selectbox("选择模型", ["暂无模型回答"], disabled=True, key="case_detail_model")
        output_row = None

    verdict = build_case_verdict(output_row, data.errors, gold, data.optimizations, task_info)
    _render_verdict_card(verdict)
    _render_model_answer(output_row, gold)

    # 6) 多维度评分（证据）
    _render_scoring_matrix(output_row, data.errors)

    # 7) 人工点评（动态读取 review_note）
    _render_human_review_note(output_row)

    # 8) 红线提示（边界）
    _render_redline_panel(verdict, gold, output_row, data.errors)

    # 9) 人工复核（仅在已初始化 SQLite 的真实运行下可归档，不破坏评分归档）
    _render_case_review(output_row, eval_status)

    # 10) 偏好样本对照
    _render_preference_section(data.preference_pairs, data.model_outputs, selected_case)


def _resolve_source(seed_data, live_data, live: bool):
    """决定本页取数来源：默认离线 seed 评价；真实运行时可切换，但绝不覆盖离线评价。"""
    if not live:
        st.caption("当前展示离线 seed 评价（尚未运行真实评测）。运行真实评测后可在此切换查看本次结果。")
        return seed_data
    choice = st.radio(
        "样本来源",
        ["离线 seed 评价", "本次运行结果"],
        horizontal=True,
        help="默认展示离线 seed 评价；本次运行结果仅供对照，不会覆盖离线评价。",
    )
    if choice == "本次运行结果":
        st.caption("正在查看本次真实运行结果；离线 seed 评价不受影响。")
        return live_data
    st.caption("正在查看离线 seed 评价（默认）。")
    return seed_data


def _render_why_this_case(task_info: pd.Series, gold, comparison: list[dict]) -> None:
    render_section_title("这道题为什么能测出模型能力", "先讲清考察点与评测锚点，再用模型分差验证区分度。")
    rationale = build_case_rationale(task_info, gold, comparison)
    capability = rationale["capability"] or "暂无明确的考察能力说明"
    anchor = (
        f'以 {rationale["must_count"]} 个必须覆盖点与 {rationale["redline_count"]} 条不可接受错误（红线）作为评测锚点'
        if (rationale["must_count"] or rationale["redline_count"])
        else "该题尚未配置必须覆盖点与红线锚点"
    )
    if rationale["score_spread"] is not None and rationale["model_count"] >= 2:
        spread = (
            f'{rationale["model_count"]} 个模型在本题上的总分差约 {rationale["score_spread"]:.0f} 分，'
            "说明该题能区分模型表现。"
            if rationale["score_spread"] > 0
            else f'{rationale["model_count"]} 个模型在本题上总分接近，区分度有限，需结合维度与红线判断。'
        )
    else:
        spread = "当前样本内模型回答不足以比较区分度，运行更多模型后可观察分差。"
    render_info_panel(
        "考察点与区分度",
        f"本题属于 {rationale['domain']} 领域（风险 {rationale['risk']}），考察模型的「{capability}」。"
        f"评测{anchor}：答得对要对照依据、答得全要覆盖风险、不能踩红线。{spread}",
    )


def _render_model_comparison(comparison: list[dict]) -> None:
    if not comparison:
        render_empty_state("该任务暂无模型回答记录，无法并排对比。")
        return
    header = "<th>模型</th><th>使用边界结论</th><th>总分</th><th>最弱维度</th><th>红线命中</th>"
    body = ""
    for row in comparison:
        redline = f'{row["redline_count"]} 项' if row["redline_count"] else "未命中"
        body += (
            f'<tr><td><span class="rubric-dim">{escape(row["model_name"])}</span></td>'
            f'<td><span class="status-badge status-{escape(row["level"])}">{escape(row["title"])}</span></td>'
            f'<td><span class="rubric-score">{escape(row["score_text"])}</span></td>'
            f'<td><span class="rubric-gap">{escape(row["weakest"])}</span></td>'
            f'<td><span class="rubric-gap">{escape(redline)}</span></td></tr>'
        )
    render_html(
        '<table class="rubric-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    st.caption("并排结论为样本内观察，不构成模型排行榜；切换下方“选择模型”查看单题回答与扣分依据。")


def _render_human_review_note(output_row: pd.Series | None) -> None:
    render_section_title("人工点评", "复核人对该回答的点评，动态读取自评分记录的 review_note。")
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录，暂无人工点评。")
        return
    note = _text(output_row.get("review_note"), "")
    if note:
        render_info_panel("复核点评", note)
    else:
        st.caption("该回答暂无人工点评（review_note 为空）。")


def _render_redline_panel(verdict: dict, gold, output_row: pd.Series | None, errors_df) -> None:
    render_section_title("红线提示", "结合 Gold 不可接受错误、低分维度与错误标签动态生成。")

    blocks: list[str] = []

    hits = verdict.get("redline_hits") or []
    if hits:
        blocks.append(
            '<div class="fact-label">命中红线</div><div class="boundary-list">'
            + "".join(f'<div class="redline-item">{escape(hit)}</div>' for hit in hits)
            + "</div>"
        )

    rubric_rows = build_rubric_rows(output_row) if output_row is not None else []
    weak_dims = [r for r in rubric_rows if r["full"] and r["score"] / r["full"] < VERDICT_WEAK_RATIO]
    if weak_dims:
        blocks.append(
            '<div class="fact-label">低分维度预警</div><div class="boundary-list">'
            + "".join(
                f'<div class="point-item">{escape(r["dimension"])}（{r["score"]:.0f}/{r["full"]}）</div>'
                for r in weak_dims
            )
            + "</div>"
        )

    errors = (
        get_errors_for_output(errors_df, output_row.get("output_id"))
        if output_row is not None
        else pd.DataFrame()
    )
    if not errors.empty:
        badges = "".join(
            f'<span class="status-badge status-{SEVERITY_BADGE.get(_text(error.get("severity")), "neutral")}">'
            f'{escape(_text(error.get("error_type"), "未分类错误"))}</span>'
            for _, error in errors.iterrows()
        )
        blocks.append(f'<div class="fact-label">错误标签</div><div class="task-card-badges">{badges}</div>')

    red_lines = field_list(gold, "unacceptable_errors") if isinstance(gold, dict) else []
    if red_lines:
        blocks.append(
            '<div class="fact-label">本题标定的不可接受错误（Gold 红线）</div><div class="boundary-list">'
            + "".join(f'<div class="redline-item">{escape(str(item))}</div>' for item in red_lines)
            + "</div>"
        )

    if blocks:
        render_card("".join(blocks), class_name="fact-card")
    else:
        render_empty_state("本题未触发红线提示：无高严重度错误、无明显低分维度，且 Gold 未标定红线。")


def _render_verdict_card(verdict: dict) -> None:
    if verdict["redline_hits"]:
        redline_html = '<div class="boundary-list">' + "".join(
            f'<div class="redline-item">{escape(hit)}</div>' for hit in verdict["redline_hits"]
        ) + "</div>"
    else:
        redline_html = '<div class="verdict-field-value">未观察到</div>'

    render_html(
        f"""
        <div class="verdict-card verdict-card-{escape(verdict["tier"])}">
            <div class="verdict-head">
                <span class="status-badge status-{escape(verdict["level"])}">{escape(verdict["title"])}</span>
                <span class="verdict-score">总分 {escape(verdict["score_text"])}</span>
            </div>
            <div class="verdict-reason">{escape(verdict["reason"])}</div>
            <div class="verdict-grid">
                <div class="verdict-field">
                    <div class="verdict-field-label">红线命中</div>
                    {redline_html}
                </div>
                <div class="verdict-field">
                    <div class="verdict-field-label">建议动作</div>
                    <div class="verdict-field-value">{escape(verdict["suggested_action"])}</div>
                </div>
            </div>
        </div>
        """
    )


def _render_task_context(task_info: pd.Series) -> None:
    domain = display_label(task_info.get("domain"), DOMAIN_LABELS)
    task_type = display_label(task_info.get("task_type"), TASK_TYPE_LABELS)
    difficulty = DIFFICULTY_LABELS.get(_text(task_info.get("difficulty")), _text(task_info.get("difficulty")))
    risk = RISK_LABELS.get(_text(task_info.get("risk_level")), _text(task_info.get("risk_level")))
    requirement = _text(task_info.get("question"), _text(task_info.get("scenario"), "暂无任务要求"))
    st.caption(
        f"{domain} · {task_type} · 难度 {difficulty} · 风险 {risk} ｜ {summarize_text(requirement, 80)}"
    )


def _render_task_brief(task_info: pd.Series) -> None:
    render_section_title("任务题")
    background = _text(task_info.get("context"), "暂无背景材料")
    requirement = _text(task_info.get("question"), _text(task_info.get("scenario"), "暂无任务要求"))
    capability = _text(task_info.get("expected_capability"), "暂无考察能力说明")
    domain = display_label(task_info.get("domain"), DOMAIN_LABELS)
    task_type = display_label(task_info.get("task_type"), TASK_TYPE_LABELS)
    difficulty = DIFFICULTY_LABELS.get(_text(task_info.get("difficulty")), _text(task_info.get("difficulty")))
    risk = RISK_LABELS.get(_text(task_info.get("risk_level")), _text(task_info.get("risk_level")))
    boundary = f"{domain} · {task_type} · 难度 {difficulty} · 风险 {risk}"

    fields = [
        ("任务背景", summarize_text(background, 160)),
        ("任务要求", summarize_text(requirement, 160)),
        ("考察能力", capability),
        ("数据边界", boundary),
    ]
    render_card(
        "".join(
            f'<div class="fact-field"><div class="fact-label">{escape(label)}</div>'
            f'<div class="fact-value">{escape(value)}</div></div>'
            for label, value in fields
        ),
        class_name="fact-card",
    )
    if len(background) > 160 or len(requirement) > 160:
        with st.expander("查看任务全文"):
            st.markdown("**任务要求**")
            st.write(requirement)
            if background and background != "暂无背景材料":
                st.markdown("**任务背景**")
                st.write(background)


def _render_gold_standard(gold: dict | None) -> None:
    render_section_title("Gold Answer / 评测标准")
    if not isinstance(gold, dict):
        render_empty_state("该任务暂无 Gold Answer 记录。")
        return

    quality = evaluate_gold_quality(gold)
    status_class = "success" if quality["is_usable"] else "warning"
    render_html(
        f'<span class="status-badge status-{status_class}">当前 Gold Answer {escape(quality["status"])}</span>'
    )

    render_answer_boundary_panel(
        "评测标准",
        [
            ("标准结论", field_text(gold, "core_conclusion", "需进一步补充")),
            ("判断依据", field_text(gold, "key_evidence", "待补充依据")),
            ("边界条件", field_text(gold, "boundary_conditions", "待补充边界")),
        ],
    )

    must_points = field_list(gold, "must_have_points")
    if must_points:
        render_html(
            '<div class="fact-label">必须覆盖点</div><div class="boundary-list">'
            + "".join(f'<div class="point-item">{escape(str(point))}</div>' for point in must_points)
            + "</div>"
        )

    red_lines = field_list(gold, "unacceptable_errors")
    if red_lines:
        render_html(
            '<div class="fact-label">不可接受错误（红线）</div><div class="boundary-list">'
            + "".join(f'<div class="redline-item">{escape(str(item))}</div>' for item in red_lines)
            + "</div>"
        )

    review = quality["manual_review"]
    if review:
        st.caption(f"人工复核提示：{review}")


def _render_model_answer(output_row: pd.Series | None, gold) -> None:
    render_section_title("模型回答")
    if output_row is None:
        render_empty_state("该任务暂无模型回答记录。")
        return

    answer = _text(output_row.get("answer_text"), "暂无回答内容。")
    render_card(
        '<div class="fact-field"><div class="fact-label">回答摘要</div>'
        f'<div class="fact-value">{escape(summarize_text(answer, ANSWER_SUMMARY_LIMIT))}</div></div>',
        class_name="fact-card",
    )
    if len(answer) > ANSWER_SUMMARY_LIMIT:
        with st.expander("查看完整模型回答"):
            st.write(answer)

    must_points = field_list(gold, "must_have_points") if isinstance(gold, dict) else []
    if must_points:
        covered, missed = build_point_coverage(must_points, answer)
        st.caption("要点覆盖基于关键词近似匹配，仅供对照参考。")
        if covered:
            render_html(
                '<div class="fact-label">已覆盖要点</div><div class="boundary-list">'
                + "".join(f'<div class="point-item">{escape(point)}</div>' for point in covered)
                + "</div>"
            )
        if missed:
            render_html(
                '<div class="fact-label">遗漏要点</div><div class="boundary-list">'
                + "".join(f'<div class="redline-item">{escape(point)}</div>' for point in missed)
                + "</div>"
            )


def _render_scoring_matrix(output_row: pd.Series | None, errors_df) -> None:
    render_section_title("评分矩阵", "维度、权重、Gold 要求、模型得分、扣分与对应错误标签。")
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
    render_html(
        '<table class="rubric-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table>"
    )
    if unmapped:
        extra = "、".join(f"{error_type}（{severity}）" for error_type, severity in unmapped)
        st.caption(f"其他错误标签：{extra}")


def _render_case_review(output_row: pd.Series | None, eval_status: dict) -> None:
    """在当前 (case, model) 评分未复核时，提供就地复核表单。"""
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
        render_info_panel("复核状态", "本条评分已复核归档。")
        return

    dimensions = ds.get_rubric_dimensions()
    render_section_title("人工复核", "对照 Gold Answer 与模型回答，确认或修订各维度分。")
    cols = st.columns(len(dimensions))
    edited: dict[str, int] = {}
    for i, dim in enumerate(dimensions):
        field_name = dim["field"]
        full_mark = int(dim.get("full_mark") or 0)
        current = row.get(field_name)
        value = int(current) if current is not None and str(current) != "nan" else 0
        edited[field_name] = cols[i].number_input(
            dim["name"], min_value=0, max_value=full_mark, value=min(value, full_mark),
            step=1, key=f"case_review_score::{row['id']}::{field_name}",
        )
    note = st.text_area(
        "复核说明", value=str(row.get("review_note") or ""), key=f"case_review_note::{row['id']}"
    )
    if st.button("确认并归档（人工复核通过）", key=f"case_review_confirm::{row['id']}"):
        if sc.confirm_score_review(int(row["id"]), edited, note):
            st.success("已归档为已复核（confirmed）。")
            st.rerun()
        else:
            st.warning("归档失败：请确认 SQLite 数据层已初始化。")


def _render_preference_section(preference_pairs_df, model_outputs_df, selected_case: str) -> None:
    pairs = get_preference_pair_details_for_case(preference_pairs_df, model_outputs_df, selected_case)
    if pairs.empty:
        return

    render_section_title("偏好样本对照", "同题不同回答的偏好判断，用于沉淀改进方向。")
    for _, pair in pairs.iterrows():
        preferred_meta = (
            f"output_id {_display(pair.get('preferred_output_id'), '暂无')} · "
            f"{_display(pair.get('preferred_model_name'), '未标注模型')}"
        )
        rejected_meta = (
            f"output_id {_display(pair.get('rejected_output_id'), '暂无')} · "
            f"{_display(pair.get('rejected_model_name'), '未标注模型')}"
        )
        with st.expander(
            f"{_display(pair.get('pair_id'), '偏好样本')} · {_display(pair.get('preference_dimension'), '未标注维度')}",
            expanded=False,
        ):
            if has_value(pair.get("preference_reason")):
                render_info_panel("偏好理由", _text(pair.get("preference_reason")))
            render_preference_comparison(
                "偏好回答",
                pair.get("preferred_answer_text"),
                "对照回答",
                pair.get("rejected_answer_text"),
                preferred_meta=preferred_meta,
                rejected_meta=rejected_meta,
            )


# --- small helpers -----------------------------------------------------------

def _domain_by_case(tasks_df: pd.DataFrame) -> dict[str, str]:
    if tasks_df.empty or "case_id" not in tasks_df:
        return {}
    return {
        str(row.get("case_id")): display_label(row.get("domain"), DOMAIN_LABELS)
        for _, row in tasks_df.iterrows()
    }


def _text(value, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def _display(value, fallback: str) -> str:
    return str(value) if has_value(value) else fallback
