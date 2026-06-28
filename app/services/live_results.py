"""把一次真实多模型评测运行 + 裁判评分，组装成与 seed 完全同形的 EvaluationData（PR-36）。

既有 8 个分析页都通过 `data_bundle["data"]`（EvaluationData）取数。本模块**不改页面逻辑**，
而是用真实运行结果构造列结构一致的 EvaluationData，让页面照常渲染真实回答与裁判建议分：

  - 题库与参考（tasks / gold_answers / gold_answer_map）始终取自 seed，可在未运行时浏览。
  - 结果（model_outputs / scores）只来自真实运行：model_outputs 来自 CompareRunResult 的成功
    outcome，scores 来自已落库（或会话内）的裁判**成功**评分；二者用同式合成的 output_id 对齐，
    以满足 `merge_case_outputs_with_scores` 的 ["output_id", "case_id", "model_name"] 合并键。
  - 单次真实运行无法产出人工标注数据，故 errors / optimizations / evaluation_runs /
    preference_pairs / optimization_comparison 一律置空（保留 seed 的列结构、零行）。

本模块为纯函数，不依赖 Streamlit / session_state，便于单元测试。会话读取与数据源选择在
`src/ui/eval_console.py`。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import pandas as pd

from src.data_service import EvaluationData

# 与 dataset_service._MODEL_OUTPUT_COLUMNS / _SCORE_COLUMNS 保持一致。
MODEL_OUTPUT_COLUMNS = ["output_id", "case_id", "model_name", "answer_text"]
SCORE_COLUMNS = [
    "output_id", "case_id", "model_name",
    "accuracy_score", "reasoning_score", "coverage_score",
    "evidence_score", "expression_score", "total_score", "review_note",
]
_DIMENSION_COLUMNS = (
    "accuracy_score", "reasoning_score", "coverage_score",
    "evidence_score", "expression_score",
)


def synth_output_id(run_id: Any, model_name: Any, case_id: Any) -> str:
    """确定式合成 output_id，保证 model_outputs 与 scores 两侧可对齐。"""
    return f"{run_id}::{model_name}::{case_id}"


def build_live_evaluation_data(base: EvaluationData, run_result, score_rows: Sequence[Mapping[str, Any]]) -> EvaluationData:
    """用一次运行 + 裁判评分行，构造真实结果驱动的 EvaluationData。

    score_rows 为字典序列（来自 live_run_scores 落库行或会话内 ScoreOutcome 规整结果），
    至少含 case_id、eval_model（或 model_name）、judge_status 与各维度分；只采纳
    judge_status=success 的行。output_id 用 run_result.run_id 合成，与 model_outputs 一致。
    """
    run_id = getattr(run_result, "run_id", "")

    output_records = []
    for outcome in getattr(run_result, "outcomes", []):
        if not getattr(outcome, "success", False):
            continue
        output_records.append(
            {
                "output_id": synth_output_id(run_id, outcome.model_id, outcome.case_id),
                "case_id": str(outcome.case_id),
                "model_name": str(outcome.model_id),
                "answer_text": outcome.answer_text or "",
            }
        )
    model_outputs = pd.DataFrame(output_records, columns=MODEL_OUTPUT_COLUMNS)

    score_records = []
    for row in score_rows or []:
        if str(row.get("judge_status")) != "success":
            continue
        model_name = str(row.get("eval_model") or row.get("model_name") or "")
        case_id = str(row.get("case_id") or "")
        record = {
            "output_id": synth_output_id(run_id, model_name, case_id),
            "case_id": case_id,
            "model_name": model_name,
            "review_note": _clean(row.get("review_note")),
        }
        for column in _DIMENSION_COLUMNS:
            record[column] = _as_number(row.get(column))
        record["total_score"] = _as_number(row.get("total_score"))
        score_records.append(record)
    scores = pd.DataFrame(score_records, columns=SCORE_COLUMNS)

    return _assemble(base, model_outputs, scores)


def empty_results_evaluation_data(base: EvaluationData) -> EvaluationData:
    """未运行时：题库与参考保留，结果类全部为空（保留列结构），分析页走空状态分支。"""
    return _assemble(
        base,
        pd.DataFrame(columns=MODEL_OUTPUT_COLUMNS),
        pd.DataFrame(columns=SCORE_COLUMNS),
    )


def _assemble(base: EvaluationData, model_outputs: pd.DataFrame, scores: pd.DataFrame) -> EvaluationData:
    return EvaluationData(
        tasks=base.tasks,
        gold_answers=base.gold_answers,
        gold_answer_map=base.gold_answer_map,
        model_outputs=model_outputs,
        scores=scores,
        errors=_empty_like(base.errors),
        optimizations=_empty_like(base.optimizations),
        evaluation_runs=_empty_like(base.evaluation_runs),
        preference_pairs=_empty_like(base.preference_pairs),
        optimization_comparison=_empty_like(base.optimization_comparison),
    )


def _empty_like(frame: pd.DataFrame) -> pd.DataFrame:
    """保留列结构的零行 DataFrame，使依赖列存在性的页面判断不出错。"""
    if isinstance(frame, pd.DataFrame):
        return frame.iloc[0:0].copy()
    return pd.DataFrame()


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return None if pd.isna(value) else float(value)
        except TypeError:
            return float(value)
    text = _clean(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text
