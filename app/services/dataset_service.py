"""数据集服务层（dataset service）。

页面与指标层通过本模块获取评测数据，尽量避免直接读取文件：

  - 当 SQLite 数据库已初始化时，从 repository 读取核心对象（任务题、Gold Answer、
    Rubric 评分、模型回答、错误标签、数据补强动作、评测批次），并投影回与原始
    CSV/JSON 完全一致的列结构，确保页面展示结果不变。
  - 当数据库尚未初始化时，回退到现有 CSV/JSON 加载（src.data_service），实现「逐步切换、
    旧数据兼容」。
  - 偏好对照（preference_pairs）与优化前后对比（optimization_comparison）暂未迁移到
    SQLite，仍从种子文件读取，以最小改动保持页面功能完整。

活跃样本过滤与 EvaluationData 结构复用 src.data_service，避免口径漂移。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from app.db import DEFAULT_DB_PATH
from app.db.repository import Repository
from src.data_service import (
    DATA_FILES,
    OPTIMIZATION_COMPARISON_COLUMNS,
    DataLoadError,
    EvaluationData,
    _restrict_to_active,
    build_gold_answer_map,
    get_data_dir,
    load_all_data,
    read_csv_file,
    read_optional_csv_file,
)

DB_PATH_ENV = "FINDUEVAL_DB_PATH"

# 各 DataFrame 对应的原始列（与种子文件表头一致）。从数据库读取后投影到这些列，
# 自动剔除 created_at/updated_at/version 等元数据列，使结果与旧数据完全一致。
_TASK_COLUMNS = [
    "case_id", "domain", "scenario", "task_type", "difficulty",
    "question", "context", "expected_capability", "risk_level", "status",
]
_MODEL_OUTPUT_COLUMNS = ["output_id", "case_id", "model_name", "answer_text"]
_SCORE_COLUMNS = [
    "output_id", "case_id", "model_name",
    "accuracy_score", "reasoning_score", "coverage_score",
    "evidence_score", "expression_score", "total_score", "review_note",
]
_ERROR_COLUMNS = [
    "output_id", "case_id", "model_name", "error_type", "severity",
    "error_description", "correction", "optimization_action",
]
_IMPROVEMENT_COLUMNS = [
    "frequent_error", "typical_problem", "affected_cases", "likely_cause",
    "optimization_action", "data_sample_format", "priority",
]
_EVAL_RUN_COLUMNS = [
    "run_id", "run_name", "model_name", "model_version",
    "prompt_version", "eval_scope", "run_date", "note",
]


def get_db_path() -> Path:
    configured = os.getenv(DB_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_DB_PATH


def database_ready(db_path: Path | None = None) -> bool:
    """数据库文件存在且任务表已有数据时，视为可用。"""
    path = db_path or get_db_path()
    if not path.exists():
        return False
    try:
        return Repository(path).count("task_cases") > 0
    except Exception:
        return False


def load_evaluation_data(db_path: Path | None = None) -> EvaluationData:
    """返回 EvaluationData：数据库可用则读库，否则回退到种子文件。"""
    path = db_path or get_db_path()
    if database_ready(path):
        return _load_from_db(str(path), path.stat().st_mtime)
    return load_all_data()


def _project(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """投影到原始列顺序，缺列补空，剔除元数据列。"""
    present = [column for column in columns if column in frame.columns]
    projected = frame[present].copy()
    for column in columns:
        if column not in projected.columns:
            projected[column] = None
    return projected[columns].reset_index(drop=True)


def _gold_answers_from_db(repository: Repository) -> list[dict]:
    """从 raw_json 还原 Gold Answer 原始条目，保持与 gold_answers.json 一致。"""
    frame = repository.list_df("gold_answers")
    answers = []
    for raw in frame["raw_json"].tolist():
        if raw is None:
            continue
        try:
            answers.append(json.loads(raw))
        except (TypeError, json.JSONDecodeError) as exc:
            raise DataLoadError(f"Gold Answer raw_json 解析失败：{exc}") from exc
    return answers


@st.cache_data(show_spinner=False)
def _load_from_db(db_path_value: str, _mtime: float) -> EvaluationData:
    """从 SQLite 构建 EvaluationData。_mtime 仅用于缓存失效。"""
    repository = Repository(db_path_value)

    tasks = _project(repository.list_df("task_cases"), _TASK_COLUMNS)
    gold_answers = _gold_answers_from_db(repository)
    model_outputs = _project(repository.list_df("model_responses"), _MODEL_OUTPUT_COLUMNS)
    scores = _project(repository.list_df("score_records"), _SCORE_COLUMNS)
    errors = _project(repository.list_df("error_annotations", order_by="id"), _ERROR_COLUMNS)
    optimizations = _project(repository.list_df("improvement_actions", order_by="id"), _IMPROVEMENT_COLUMNS)
    evaluation_runs = _project(repository.list_df("evaluation_runs"), _EVAL_RUN_COLUMNS)

    # 偏好对照与优化前后对比暂未迁移，仍读取种子文件，保持页面功能完整。
    data_dir = get_data_dir()
    preference_pairs = read_csv_file(DATA_FILES["preference_pairs"], data_dir)
    optimization_comparison = read_optional_csv_file(
        DATA_FILES["optimization_comparison"], OPTIMIZATION_COMPARISON_COLUMNS, data_dir
    )

    # 复用既有活跃样本过滤口径，使读库结果与读文件结果完全一致。
    tasks, gold_answers, model_outputs, scores, errors, preference_pairs = _restrict_to_active(
        tasks, gold_answers, model_outputs, scores, errors, preference_pairs
    )

    return EvaluationData(
        tasks=tasks,
        gold_answers=gold_answers,
        gold_answer_map=build_gold_answer_map(gold_answers),
        model_outputs=model_outputs,
        scores=scores,
        errors=errors,
        optimizations=optimizations,
        evaluation_runs=evaluation_runs,
        preference_pairs=preference_pairs,
        optimization_comparison=optimization_comparison,
    )
