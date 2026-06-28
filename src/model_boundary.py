"""模型边界报告的数据推导（model boundary report derivation）。

集中实现「模型边界报告」页面的纯数据逻辑，供页面与测试共用。所有结论均由当前
评分、错误标签、Gold Answer 边界与红线错误动态推导，不在代码中写死模型结论，也不
夸大模型能力；阈值为评测方法学配置（与 Rubric 满分同类），并在页面上明示判定口径。

三类使用边界（可直接使用 / 需人工复核 / 不可直接使用）按「风险等级 + 能力下限/上限 +
是否观察到高严重度红线类错误」划分；模型维度矩阵在事实依据、推理完整性、风险识别、
专业表达四个 Rubric 维度之外，额外用红线类错误频率推导「边界意识」。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.metrics import (
    ERROR_TYPE_TO_DIMENSION,
    SCORE_DIMENSIONS,
    SCORE_DIMENSION_FULL_MARKS,
    get_error_attribution_actions,
    get_error_distribution_summary,
    get_model_dimension_scores,
    has_columns,
)


# 使用边界判定口径（评测方法学配置，非模型结论）：
#   高风险任务（最终投资判断 / 法律结论 / 交易定价）一律归入「不可直接使用」；
#   中风险任务中，若最弱模型也达到及格下限且未触发高严重度红线类错误，可作为结构化辅助；
#   其余归入「需人工复核」。判定结果完全由数据决定，阈值仅控制划分口径。
HIGH_RISK_VALUE = "高"
MID_RISK_VALUE = "中"
ASSIST_WORST_FLOOR = 55.0  # 最弱模型在该任务上的总分下限（满分 100），低于此不作辅助用途
HIGH_SEVERITY_VALUE = "高"

# 与 label_taxonomy 对齐：这两类错误直接对应答案红线（漏报重大风险、依据造假/错误），
# 用于推导模型的「边界意识」——红线类错误越少，边界意识越稳健。
REDLINE_ERROR_TYPES = ("风险遗漏", "依据错误")

TIER_DIRECT = "direct"
TIER_REVIEW = "review"
TIER_NOT_DIRECT = "not_direct"

# 各使用边界的定义性说明（口径描述，非针对具体模型的结论）。具体成员、数量、分数区间
# 与红线触发情况均由数据动态填充。
TIER_META: dict[str, dict[str, str]] = {
    TIER_DIRECT: {
        "key": TIER_DIRECT,
        "title": "可直接使用场景",
        "definition": "低风险、信息结构化类任务，可作为初稿或结构化辅助，最终结论仍由人工确认。",
    },
    TIER_REVIEW: {
        "key": TIER_REVIEW,
        "title": "需人工复核场景",
        "definition": "财务判断、法律条款、估值假设类任务，模型回答差异较大或存在扣分点，须人工复核后使用。",
    },
    TIER_NOT_DIRECT: {
        "key": TIER_NOT_DIRECT,
        "title": "不可直接使用场景",
        "definition": "最终投资判断、法律结论、交易定价类高风险任务，不可直接由模型给出结论，须人工与合规终审。",
    },
}
TIER_ORDER = [TIER_DIRECT, TIER_REVIEW, TIER_NOT_DIRECT]

# 模型维度矩阵列：前四列取自 Rubric 维度（按业务表达重命名），第五列「边界意识」由红线类
# 错误频率推导。每项为 (Rubric 字段, 矩阵展示名)；查表时用 Rubric 原始维度名，展示用矩阵名。
MATRIX_RUBRIC_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("evidence_score", "事实依据"),
    ("reasoning_score", "推理完整性"),
    ("coverage_score", "风险识别"),
    ("expression_score", "专业表达"),
)
BOUNDARY_AWARENESS_LABEL = "边界意识"

# 达成率分档（与模型诊断页一致）：浅绿 / 米色 / 浅玫瑰，均为低饱和色。
_LEVEL_HIGH = 0.85
_LEVEL_MID = 0.6


def _clean(value: Any, fallback: str = "未标注") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return fallback
    return text


def attainment_level(attainment: float) -> str:
    if attainment >= _LEVEL_HIGH:
        return "success"
    if attainment >= _LEVEL_MID:
        return "warning"
    return "danger"


def build_data_boundary(data, manifest: dict | None = None) -> dict[str, Any]:
    """页面顶部数据边界：样本量、数据集版本、是否使用模拟回答、结论适用范围。"""
    manifest = manifest or {}
    task_count = len(data.tasks)
    model_count = (
        int(data.model_outputs["model_name"].nunique())
        if "model_name" in getattr(data.model_outputs, "columns", [])
        else 0
    )
    output_count = len(data.model_outputs)
    return {
        "task_count": task_count,
        "model_count": model_count,
        "output_count": output_count,
        "version": _clean(manifest.get("version"), "未声明"),
        # 本项目模型回答为模拟生成（未接入真实模型 API），属已知数据性质，如实披露。
        "simulated_answers": True,
        "scope_note": "结论仅用于当前评测集观察，不代表真实模型采购或业务决策。",
    }


def _per_case_scores(scores_df: pd.DataFrame) -> pd.DataFrame:
    """每个 case 的总分均值 / 最高 / 最低，跨模型聚合。"""
    columns = ["case_id", "avg", "best", "worst"]
    if scores_df is None or scores_df.empty or not has_columns(scores_df, ["case_id", "total_score"]):
        return pd.DataFrame(columns=columns)
    grouped = (
        scores_df.groupby("case_id")["total_score"]
        .agg(avg="mean", best="max", worst="min")
        .reset_index()
    )
    return grouped


def _high_severity_counts(errors_df: pd.DataFrame) -> dict[str, int]:
    if errors_df is None or errors_df.empty or not has_columns(errors_df, ["case_id", "severity"]):
        return {}
    high = errors_df[errors_df["severity"].astype(str).str.strip() == HIGH_SEVERITY_VALUE]
    if high.empty:
        return {}
    return high["case_id"].astype(str).value_counts().to_dict()


def classify_task_usage(data) -> list[dict[str, Any]]:
    """逐任务判定使用边界，结果由风险等级、能力下限/上限与红线错误共同决定。"""
    tasks_df = data.tasks
    if tasks_df is None or tasks_df.empty or "case_id" not in tasks_df.columns:
        return []

    score_lookup = {
        str(row["case_id"]): row for _, row in _per_case_scores(data.scores).iterrows()
    }
    high_err = _high_severity_counts(data.errors)

    records: list[dict[str, Any]] = []
    for row in tasks_df.to_dict(orient="records"):
        case_id = _clean(row.get("case_id"))
        risk = _clean(row.get("risk_level"), fallback="")
        scores = score_lookup.get(case_id)
        best = float(scores["best"]) if scores is not None else None
        worst = float(scores["worst"]) if scores is not None else None
        avg = float(scores["avg"]) if scores is not None else None
        hi_err = int(high_err.get(case_id, 0))

        tier = _assign_tier(risk, worst, hi_err)
        records.append(
            {
                "case_id": case_id,
                "domain": _clean(row.get("domain")),
                "task_type": _clean(row.get("task_type")),
                "risk_level": risk or "未标注",
                "avg": avg,
                "best": best,
                "worst": worst,
                "high_severity_errors": hi_err,
                "tier": tier,
            }
        )
    return records


def _assign_tier(risk: str, worst: float | None, high_severity_errors: int) -> str:
    if risk == HIGH_RISK_VALUE:
        return TIER_NOT_DIRECT
    if (
        risk == MID_RISK_VALUE
        and worst is not None
        and worst >= ASSIST_WORST_FLOOR
        and high_severity_errors == 0
    ):
        return TIER_DIRECT
    return TIER_REVIEW


def summarize_usage_tiers(data) -> list[dict[str, Any]]:
    """按使用边界汇总任务数、分数区间、任务类型与红线触发情况，供页面动态展示。"""
    records = classify_task_usage(data)
    by_tier: dict[str, list[dict[str, Any]]] = {tier: [] for tier in TIER_ORDER}
    for record in records:
        by_tier.setdefault(record["tier"], []).append(record)

    summaries: list[dict[str, Any]] = []
    for tier in TIER_ORDER:
        members = by_tier.get(tier, [])
        avgs = [m["avg"] for m in members if m["avg"] is not None]
        redline_hits = sum(1 for m in members if m["high_severity_errors"] > 0)
        task_types: list[str] = []
        for member in members:
            if member["task_type"] not in task_types and member["task_type"] != "未标注":
                task_types.append(member["task_type"])
        summaries.append(
            {
                **TIER_META[tier],
                "count": len(members),
                "cases": [m["case_id"] for m in members],
                "task_types": task_types,
                "score_low": min(avgs) if avgs else None,
                "score_high": max(avgs) if avgs else None,
                "redline_hits": redline_hits,
            }
        )
    return summaries


def build_frequent_risks(data, limit: int = 5) -> list[dict[str, Any]]:
    """高频风险：按错误标签出现次数排序，关联受影响 Rubric 维度与涉及模型/案例数。"""
    summary = get_error_distribution_summary(data.errors)
    if summary.empty:
        return []

    risks: list[dict[str, Any]] = []
    for _, row in summary.head(limit).iterrows():
        error_type = str(row["error_type"])
        models = [m for m in str(row.get("models", "")).split("; ") if m]
        cases = [c for c in str(row.get("cases", "")).split("; ") if c]
        risks.append(
            {
                "error_type": error_type,
                "count": int(row["count"]),
                "dimension": ERROR_TYPE_TO_DIMENSION.get(error_type, "未归类维度"),
                "model_count": len(models),
                "case_count": len(cases),
            }
        )
    return risks


def build_data_actions(data, limit: int = 5) -> list[dict[str, Any]]:
    """数据补强方向：由高频错误关联到既有优化计划中的数据补强动作与验证指标。"""
    actions = get_error_attribution_actions(data.errors, data.optimizations)
    if actions.empty:
        return []

    rows: list[dict[str, Any]] = []
    for _, row in actions.head(limit).iterrows():
        data_action = _clean(row.get("data_action"), fallback="待补充数据补强动作")
        rows.append(
            {
                "error_type": str(row.get("error_type", "")),
                "count": int(row.get("count", 0) or 0),
                "data_action": data_action,
                "validation_metric": _clean(
                    row.get("validation_metric"),
                    fallback="相关错误类型出现次数下降，对应维度评分回升。",
                ),
            }
        )
    return rows


def _boundary_awareness(errors_df: pd.DataFrame, outputs_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """以红线类错误频率推导每个模型的边界意识：红线类错误越少越稳健。

    rate = 红线类错误数 / 模型回答数。rate 为 0 记「稳健」；不高于全体均值记「需关注」；
    高于均值记「偏弱」。完全由数据决定，无固定结论。
    """
    if outputs_df is None or outputs_df.empty or "model_name" not in outputs_df.columns:
        return {}
    output_counts = outputs_df["model_name"].astype(str).value_counts().to_dict()

    redline_counts: dict[str, int] = {}
    if errors_df is not None and not errors_df.empty and has_columns(errors_df, ["model_name", "error_type"]):
        redline = errors_df[errors_df["error_type"].astype(str).isin(REDLINE_ERROR_TYPES)]
        redline_counts = redline["model_name"].astype(str).value_counts().to_dict()

    rates = {
        model: (redline_counts.get(model, 0) / count if count else 0.0)
        for model, count in output_counts.items()
    }
    mean_rate = sum(rates.values()) / len(rates) if rates else 0.0

    result: dict[str, dict[str, Any]] = {}
    for model, rate in rates.items():
        if rate <= 0:
            label, level = "稳健", "success"
        elif rate <= mean_rate:
            label, level = "需关注", "warning"
        else:
            label, level = "偏弱", "danger"
        result[model] = {
            "label": label,
            "level": level,
            "redline_count": redline_counts.get(model, 0),
        }
    return result


def build_boundary_matrix(data) -> dict[str, Any]:
    """模型维度矩阵：事实依据 / 推理完整性 / 风险识别 / 专业表达 + 边界意识。"""
    dimension_scores = get_model_dimension_scores(data.scores)
    if dimension_scores.empty:
        return {"dimensions": [], "rows": []}

    # get_model_dimension_scores 按 Rubric 原始维度名（如「依据可靠性」）聚合；矩阵按业务名
    # （如「事实依据」）展示。这里建立两套映射：展示名 → Rubric 原始名、展示名 → 满分。
    native_label_by_column = dict(SCORE_DIMENSIONS)
    display_labels = [display for _, display in MATRIX_RUBRIC_DIMENSIONS]
    native_by_display = {
        display: native_label_by_column[column] for column, display in MATRIX_RUBRIC_DIMENSIONS
    }
    full_by_display = {
        display: SCORE_DIMENSION_FULL_MARKS[column] for column, display in MATRIX_RUBRIC_DIMENSIONS
    }

    awareness = _boundary_awareness(data.errors, data.model_outputs)

    rows: list[dict[str, Any]] = []
    for model, group in dimension_scores.groupby("model_name"):
        by_dimension = {str(r["dimension"]): float(r["score"]) for _, r in group.iterrows()}
        cells = []
        for display in display_labels:
            full = full_by_display.get(display)
            score = by_dimension.get(native_by_display.get(display, display))
            if score is None or not full:
                cells.append({"dimension": display, "score": None, "full": full, "level": "neutral", "text": "—"})
            else:
                attainment = score / full
                cells.append(
                    {
                        "dimension": display,
                        "score": score,
                        "full": full,
                        "level": attainment_level(attainment),
                        "text": f"{score:.0f}/{full}",
                    }
                )
        model_awareness = awareness.get(str(model), {"label": "样本不足", "level": "neutral", "redline_count": 0})
        cells.append(
            {
                "dimension": BOUNDARY_AWARENESS_LABEL,
                "score": None,
                "full": None,
                "level": model_awareness["level"],
                "text": model_awareness["label"],
                "redline_count": model_awareness["redline_count"],
            }
        )
        rows.append({"model": str(model), "cells": cells})

    rows.sort(key=lambda item: item["model"])
    dimensions = display_labels + [BOUNDARY_AWARENESS_LABEL]
    return {"dimensions": dimensions, "rows": rows}
