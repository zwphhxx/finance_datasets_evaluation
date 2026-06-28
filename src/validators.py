from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.data_service import EvaluationData


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


REQUIRED_COLUMNS = {
    "tasks.csv": [
        ("case_id",),
        ("domain",),
        ("scenario",),
        ("task_type",),
        ("difficulty",),
        ("question",),
    ],
    "model_outputs.csv": [
        ("output_id",),
        ("case_id",),
        ("model_name",),
        ("answer", "answer_text"),
    ],
    "scores.csv": [
        ("output_id",),
        ("case_id",),
        ("model_name",),
        ("total_score",),
    ],
    "error_labels.csv": [
        ("output_id",),
        ("error_type",),
        ("severity",),
    ],
    "optimization_plan.csv": [
        ("error_type", "frequent_error"),
        ("root_cause", "likely_cause"),
        ("optimization_action",),
    ],
}

SCORE_COLUMNS = [
    "total_score",
    "accuracy_score",
    "reasoning_score",
    "coverage_score",
    "evidence_score",
    "expression_score",
]


def validate_evaluation_data(data: EvaluationData) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    _validate_required_columns(
        {
            "tasks.csv": data.tasks,
            "model_outputs.csv": data.model_outputs,
            "scores.csv": data.scores,
            "error_labels.csv": data.errors,
            "optimization_plan.csv": data.optimizations,
        },
        errors,
    )
    _validate_gold_answers_schema(data.gold_answers, errors)
    _validate_primary_keys(data, errors)
    _validate_foreign_keys(data, errors)
    _validate_scores(data.scores, errors, warnings)
    _validate_optional_coverage(data, warnings)

    return ValidationResult(errors=errors, warnings=warnings)


def _validate_required_columns(tables: dict[str, pd.DataFrame], errors: list[str]) -> None:
    for filename, required_groups in REQUIRED_COLUMNS.items():
        df = tables[filename]
        for alternatives in required_groups:
            if not any(column in df.columns for column in alternatives):
                errors.append(f"{filename} 缺少必填字段：{alternatives[0]}。")


def _validate_gold_answers_schema(gold_answers: Any, errors: list[str]) -> None:
    if not isinstance(gold_answers, list):
        errors.append("gold_answers.json 格式异常：应为列表。")
        return

    for index, answer in enumerate(gold_answers, start=1):
        if not isinstance(answer, dict):
            errors.append(f"gold_answers.json 第 {index} 条记录格式异常：应为对象。")
            continue
        if "case_id" not in answer:
            errors.append("gold_answers.json 缺少必填字段：case_id。")
        if "gold_answer" not in answer and "conclusion" not in answer:
            errors.append("gold_answers.json 缺少必填字段：gold_answer。")


def _validate_primary_keys(data: EvaluationData, errors: list[str]) -> None:
    _validate_unique(data.tasks, "tasks.csv", "case_id", errors)
    _validate_unique(data.model_outputs, "model_outputs.csv", "output_id", errors)
    _validate_unique(data.scores, "scores.csv", "output_id", errors)
    if "error_id" in data.errors.columns:
        _validate_unique(data.errors, "error_labels.csv", "error_id", errors)


def _validate_unique(df: pd.DataFrame, filename: str, column: str, errors: list[str]) -> None:
    if column not in df.columns:
        return
    if df[column].duplicated().any():
        errors.append(f"{filename} 中 {column} 存在重复记录。")


def _validate_foreign_keys(data: EvaluationData, errors: list[str]) -> None:
    if _has_columns(data.model_outputs, ["case_id"]) and _has_columns(data.tasks, ["case_id"]):
        if _has_orphans(data.model_outputs["case_id"], data.tasks["case_id"]):
            errors.append("model_outputs.csv 中存在无法匹配 tasks.case_id 的记录。")

    if _has_columns(data.scores, ["output_id"]) and _has_columns(data.model_outputs, ["output_id"]):
        if _has_orphans(data.scores["output_id"], data.model_outputs["output_id"]):
            errors.append("scores.csv 中存在无法匹配 model_outputs.output_id 的记录。")

    if _has_columns(data.errors, ["output_id"]) and _has_columns(data.model_outputs, ["output_id"]):
        if _has_orphans(data.errors["output_id"], data.model_outputs["output_id"]):
            errors.append("error_labels.csv 中存在无法匹配 model_outputs.output_id 的记录。")

    if _has_columns(data.tasks, ["case_id"]):
        task_ids = set(data.tasks["case_id"].dropna().astype(str))
        gold_ids = {
            str(answer.get("case_id"))
            for answer in data.gold_answers
            if isinstance(answer, dict) and answer.get("case_id") is not None
        }
        if gold_ids - task_ids:
            errors.append("gold_answers.json 中存在未匹配 tasks.case_id 的记录。")


def _validate_scores(scores: pd.DataFrame, errors: list[str], warnings: list[str]) -> None:
    for column in SCORE_COLUMNS:
        if column not in scores.columns:
            continue

        values = pd.to_numeric(scores[column], errors="coerce")
        if scores[column].isna().any():
            warnings.append(f"scores.csv 中 {column} 评分字段存在缺失。")
        if values.isna().any() and not scores[column].isna().all():
            errors.append(f"scores.csv 中 {column} 存在无法识别的分数值。")
        if ((values < 0) | (values > 100)).any():
            errors.append(f"scores.csv 中 {column} 存在超出 0-100 范围的记录。")


def _validate_optional_coverage(data: EvaluationData, warnings: list[str]) -> None:
    if _has_columns(data.model_outputs, ["output_id"]) and _has_columns(data.scores, ["output_id"]):
        output_ids = _string_set(data.model_outputs["output_id"])
        scored_ids = _string_set(data.scores["output_id"])
        if output_ids - scored_ids:
            warnings.append("部分模型回答尚未评分，不影响查看回答内容。")

    if _has_columns(data.model_outputs, ["output_id"]) and _has_columns(data.errors, ["output_id"]):
        output_ids = _string_set(data.model_outputs["output_id"])
        labeled_ids = _string_set(data.errors["output_id"])
        if output_ids - labeled_ids:
            warnings.append("部分模型回答尚未配置错误标签，不影响评分展示。")

    if _has_columns(data.tasks, ["case_id"]):
        task_ids = _string_set(data.tasks["case_id"])
        gold_ids = {
            str(answer.get("case_id"))
            for answer in data.gold_answers
            if isinstance(answer, dict) and answer.get("case_id") is not None
        }
        if task_ids - gold_ids:
            warnings.append("部分任务暂未配置 Gold Answer，不影响任务和模型回答展示。")


def _has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return all(column in df.columns for column in columns)


def _has_orphans(source: pd.Series, target: pd.Series) -> bool:
    return bool(_string_set(source) - _string_set(target))


def _string_set(values: pd.Series) -> set[str]:
    return set(values.dropna().astype(str))
