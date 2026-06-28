from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:
    import yaml
except ImportError:  # PyYAML is optional; the Demo degrades gracefully without it.
    yaml = None


DATASET_MANIFEST_FILE = "dataset_manifest.yml"
LABEL_TAXONOMY_FILE = "label_taxonomy.yml"


DATA_FILES = {
    "tasks": "tasks.csv",
    "gold_answers": "gold_answers.json",
    "model_outputs": "model_outputs.csv",
    "scores": "scores.csv",
    "errors": "error_labels.csv",
    "optimizations": "optimization_plan.csv",
    "evaluation_runs": "evaluation_runs.csv",
    "preference_pairs": "preference_pairs.csv",
    "optimization_comparison": "optimization_comparison.csv",
}

OPTIMIZATION_COMPARISON_COLUMNS = [
    "experiment_id",
    "version",
    "change_type",
    "change_description",
    "avg_score",
    "hallucination_rate",
    "evidence_score",
    "reasoning_score",
    "red_line_error_rate",
    "note",
]


class DataLoadError(RuntimeError):
    """Raised when seed data cannot be loaded into the Streamlit app."""


@dataclass(frozen=True)
class EvaluationData:
    tasks: pd.DataFrame
    gold_answers: list[dict[str, Any]]
    gold_answer_map: dict[str, dict[str, Any]]
    model_outputs: pd.DataFrame
    scores: pd.DataFrame
    errors: pd.DataFrame
    optimizations: pd.DataFrame
    evaluation_runs: pd.DataFrame
    preference_pairs: pd.DataFrame
    optimization_comparison: pd.DataFrame


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_data_dir() -> Path:
    configured_dir = os.getenv("FINDUEVAL_DATA_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser().resolve()
    return get_project_root() / "data"


def _resolve_data_file(filename: str, data_dir: Path | None = None) -> Path:
    directory = data_dir or get_data_dir()
    path = directory / filename
    if not path.exists():
        raise DataLoadError(
            f"数据文件未找到：{filename}。请检查 data 目录或 FINDUEVAL_DATA_DIR 配置。"
        )
    if not path.is_file():
        raise DataLoadError(f"数据路径不是文件：{filename}。请检查数据目录配置。")
    return path


def read_csv_file(filename: str, data_dir: Path | None = None) -> pd.DataFrame:
    path = _resolve_data_file(filename, data_dir)
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise DataLoadError(f"数据文件为空或缺少表头：{filename}。") from exc
    except UnicodeDecodeError as exc:
        raise DataLoadError(f"数据文件编码异常：{filename}。请使用 UTF-8 或兼容编码。") from exc
    except Exception as exc:
        raise DataLoadError(f"数据文件读取失败：{filename}。{exc}") from exc


def read_optional_csv_file(
    filename: str,
    columns: list[str],
    data_dir: Path | None = None,
) -> pd.DataFrame:
    directory = data_dir or get_data_dir()
    path = directory / filename
    if not path.exists():
        return pd.DataFrame(columns=columns)
    if not path.is_file():
        raise DataLoadError(f"数据路径不是文件：{filename}。请检查数据目录配置。")
    return read_csv_file(filename, data_dir)


def read_json_file(filename: str, data_dir: Path | None = None) -> Any:
    path = _resolve_data_file(filename, data_dir)
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"JSON 数据格式异常：{filename}。{exc.msg}") from exc
    except UnicodeDecodeError as exc:
        raise DataLoadError(f"数据文件编码异常：{filename}。请使用 UTF-8 编码。") from exc
    except Exception as exc:
        raise DataLoadError(f"数据文件读取失败：{filename}。{exc}") from exc


def build_gold_answer_map(gold_answers: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(gold_answers, list):
        raise DataLoadError("Gold Answer 文件格式异常：gold_answers.json 应为列表。")

    answer_map: dict[str, dict[str, Any]] = {}
    for answer in gold_answers:
        if not isinstance(answer, dict):
            continue
        case_id = answer.get("case_id")
        if case_id:
            answer_map[str(case_id)] = answer
    return answer_map


def load_all_data() -> EvaluationData:
    return _load_all_data(str(get_data_dir()))


@st.cache_data(show_spinner=False)
def _load_all_data(data_dir_value: str) -> EvaluationData:
    data_dir = Path(data_dir_value)
    gold_answers = read_json_file(DATA_FILES["gold_answers"], data_dir)

    return EvaluationData(
        tasks=read_csv_file(DATA_FILES["tasks"], data_dir),
        gold_answers=gold_answers,
        gold_answer_map=build_gold_answer_map(gold_answers),
        model_outputs=read_csv_file(DATA_FILES["model_outputs"], data_dir),
        scores=read_csv_file(DATA_FILES["scores"], data_dir),
        errors=read_csv_file(DATA_FILES["errors"], data_dir),
        optimizations=read_csv_file(DATA_FILES["optimizations"], data_dir),
        evaluation_runs=read_csv_file(DATA_FILES["evaluation_runs"], data_dir),
        preference_pairs=read_csv_file(DATA_FILES["preference_pairs"], data_dir),
        optimization_comparison=read_optional_csv_file(
            DATA_FILES["optimization_comparison"],
            OPTIMIZATION_COMPARISON_COLUMNS,
            data_dir,
        ),
    )


def _read_yaml_file(filename: str, data_dir: Path | None = None) -> dict[str, Any]:
    """Read a YAML config file, returning {} when absent or unparseable.

    Manifest and taxonomy describe the dataset; they are not required for the
    Demo to render, so any read failure degrades to an empty mapping rather
    than raising.
    """
    directory = data_dir or get_data_dir()
    path = directory / filename
    if yaml is None or not path.exists() or not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


@st.cache_data(show_spinner=False)
def load_dataset_manifest() -> dict[str, Any]:
    return _read_yaml_file(DATASET_MANIFEST_FILE)


@st.cache_data(show_spinner=False)
def load_label_taxonomy() -> dict[str, Any]:
    return _read_yaml_file(LABEL_TAXONOMY_FILE)
