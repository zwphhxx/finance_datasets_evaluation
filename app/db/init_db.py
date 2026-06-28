"""初始化 SQLite 数据库并从现有 data/ 种子文件导入数据（PR-30）。

用法：
    python -m app.db.init_db            # 在默认路径创建数据库（已存在则报错）
    python -m app.db.init_db --force    # 覆盖重建
    python -m app.db.init_db --db /tmp/findueval.db --data-dir /path/to/data

设计要点：
  - 种子来源仍为 data/ 下的 CSV/JSON 与 dataset_manifest.yml，不新增、不伪造任何数据；
    导入行数与种子文件一一对应。
  - 现有数据文件继续保留为 seed，初始化不会修改它们。
  - 默认不覆盖已存在的数据库，避免破坏后续 CRUD 产生的记录；需重建时显式传入 --force。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from app.db import DEFAULT_DB_PATH, SCHEMA_PATH
from app.db.repository import Repository
from src.data_service import (
    _read_yaml_file,
    get_data_dir,
    read_csv_file,
    read_json_file,
)

# Gold Answer 中以 JSON 数组存储的字段（其余为标量文本）。
_GOLD_LIST_FIELDS = ("must_have_points", "unacceptable_errors")
_GOLD_SCALAR_FIELDS = (
    "core_conclusion",
    "key_evidence",
    "analysis",
    "materials_to_check",
    "boundary_conditions",
    "manual_review_notes",
)


class InitError(RuntimeError):
    """数据库初始化失败时抛出。"""


def _cell(value: Any) -> Any:
    """将 pandas 缺失值规整为 None，其余原样返回。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value
    # 还原 numpy 标量为 Python 原生类型，便于 sqlite3 绑定。
    if hasattr(value, "item"):
        return value.item()
    return value


def _task_rows(data_dir: Path, version: str) -> list[dict]:
    tasks = read_csv_file("tasks.csv", data_dir)
    rows = []
    for record in tasks.to_dict(orient="records"):
        status = _cell(record.get("status")) or "active"
        rows.append(
            {
                "case_id": _cell(record.get("case_id")),
                "domain": _cell(record.get("domain")),
                "scenario": _cell(record.get("scenario")),
                "task_type": _cell(record.get("task_type")),
                "difficulty": _cell(record.get("difficulty")),
                "question": _cell(record.get("question")),
                "context": _cell(record.get("context")),
                "expected_capability": _cell(record.get("expected_capability")),
                "risk_level": _cell(record.get("risk_level")),
                "status": status,
                "version": version,
            }
        )
    return rows


def _gold_rows(data_dir: Path, version: str) -> list[dict]:
    gold_answers = read_json_file("gold_answers.json", data_dir)
    if not isinstance(gold_answers, list):
        raise InitError("gold_answers.json 应为列表。")
    rows = []
    for entry in gold_answers:
        if not isinstance(entry, dict):
            continue
        row = {"case_id": _cell(entry.get("case_id"))}
        for field in _GOLD_SCALAR_FIELDS:
            row[field] = _cell(entry.get(field))
        for field in _GOLD_LIST_FIELDS:
            value = entry.get(field)
            row[field] = json.dumps(value, ensure_ascii=False) if value is not None else None
        # raw_json 保留原始条目，作为页面重建 Gold Answer 的权威来源。
        row["raw_json"] = json.dumps(entry, ensure_ascii=False)
        row["version"] = version
        rows.append(row)
    return rows


def _rubric_rows(data_dir: Path, version: str) -> list[dict]:
    manifest = _read_yaml_file("dataset_manifest.yml", data_dir)
    rubric = manifest.get("rubric", {}) if isinstance(manifest, dict) else {}
    total = rubric.get("total")
    rows = []
    for dimension in rubric.get("dimensions", []) or []:
        if not isinstance(dimension, dict):
            continue
        weight = dimension.get("weight")
        rows.append(
            {
                "dimension_field": _cell(dimension.get("field")),
                "name": _cell(dimension.get("name")),
                "weight": _cell(weight),
                "full_mark": _cell(weight),
                "total": _cell(total),
                "version": version,
            }
        )
    return rows


def _simple_rows(data_dir: Path, filename: str, columns: list[str]) -> list[dict]:
    frame = read_csv_file(filename, data_dir)
    return [{column: _cell(record.get(column)) for column in columns} for record in frame.to_dict(orient="records")]


def _error_taxonomy_rows(data_dir: Path) -> list[dict]:
    """从 label_taxonomy.yml 导入错误标签体系，作为可维护的运行时标签层。

    severity_level 与 validation_metric 在 taxonomy 中不存在，留空待维护，不预置编造内容。
    """
    taxonomy = _read_yaml_file("label_taxonomy.yml", data_dir)
    version = str(taxonomy.get("version") or "0") if isinstance(taxonomy, dict) else "0"
    rows = []
    for label in (taxonomy.get("labels", []) or []) if isinstance(taxonomy, dict) else []:
        if not isinstance(label, dict):
            continue
        name = _cell(label.get("name"))
        if not name:
            continue
        rows.append(
            {
                "error_label": name,
                "definition": _cell(label.get("definition")),
                "typical_symptom": _cell(label.get("typical_signs")),
                "severity_level": None,
                "related_dimension": _cell(label.get("impacted_dimension")),
                "suggested_data_action": _cell(label.get("data_direction")),
                "validation_metric": None,
                "version": version,
            }
        )
    return rows


def _improvement_rows(data_dir: Path) -> list[dict]:
    """从 optimization_plan.csv 导入补强动作，并补上可读业务编号 action_id。

    action_type / expected_effect / validation_method 在 seed 中不存在，留空待维护；
    frequent_error 同时作为「关联错误标签」(related_error_label) 的取值来源。
    """
    frame = read_csv_file("optimization_plan.csv", data_dir)
    columns = [
        "frequent_error", "typical_problem", "affected_cases", "likely_cause",
        "optimization_action", "data_sample_format", "priority",
    ]
    rows = []
    for index, record in enumerate(frame.to_dict(orient="records"), start=1):
        row = {column: _cell(record.get(column)) for column in columns}
        row["action_id"] = f"DA-{index:03d}"
        row["action_type"] = None
        row["expected_effect"] = None
        row["validation_method"] = None
        rows.append(row)
    return rows


def _seed(repository: Repository, data_dir: Path, version: str) -> dict[str, int]:
    """导入全部种子数据，返回各表行数。"""
    repository.bulk_insert("task_cases", _task_rows(data_dir, version))
    repository.bulk_insert("gold_answers", _gold_rows(data_dir, version))
    repository.bulk_insert("rubrics", _rubric_rows(data_dir, version))
    repository.bulk_insert(
        "model_responses",
        _simple_rows(data_dir, "model_outputs.csv", ["output_id", "case_id", "model_name", "answer_text"]),
    )
    repository.bulk_insert(
        "score_records",
        _simple_rows(
            data_dir,
            "scores.csv",
            [
                "output_id", "case_id", "model_name",
                "accuracy_score", "reasoning_score", "coverage_score",
                "evidence_score", "expression_score", "total_score", "review_note",
            ],
        ),
    )
    repository.bulk_insert(
        "error_annotations",
        _simple_rows(
            data_dir,
            "error_labels.csv",
            ["output_id", "case_id", "model_name", "error_type", "severity",
             "error_description", "correction", "optimization_action"],
        ),
    )
    repository.bulk_insert("improvement_actions", _improvement_rows(data_dir))
    repository.bulk_insert("error_taxonomy", _error_taxonomy_rows(data_dir))
    repository.bulk_insert(
        "evaluation_runs",
        _simple_rows(
            data_dir,
            "evaluation_runs.csv",
            ["run_id", "run_name", "model_name", "model_version",
             "prompt_version", "eval_scope", "run_date", "note"],
        ),
    )
    return {table: repository.count(table) for table in [
        "task_cases", "gold_answers", "rubrics", "model_responses",
        "score_records", "error_annotations", "improvement_actions",
        "evaluation_runs", "error_taxonomy",
    ]}


def initialize_database(
    db_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    *,
    force: bool = False,
) -> dict[str, int]:
    """创建数据库结构并导入种子数据，返回各表行数。"""
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    data_dir = Path(data_dir) if data_dir else get_data_dir()

    if db_path.exists():
        if not force:
            raise InitError(f"数据库已存在：{db_path}。如需重建请使用 --force。")
        db_path.unlink()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = sqlite3.connect(str(db_path))
    try:
        connection.executescript(schema_sql)
        connection.commit()
    finally:
        connection.close()

    manifest = _read_yaml_file("dataset_manifest.yml", data_dir)
    version = str(manifest.get("version") or "0") if isinstance(manifest, dict) else "0"

    repository = Repository(db_path)
    return _seed(repository, data_dir, version)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化 FinDueEval SQLite 数据库并导入种子数据。")
    parser.add_argument("--db", dest="db_path", default=None, help="数据库文件路径（默认 app/db/findueval.db）。")
    parser.add_argument("--data-dir", dest="data_dir", default=None, help="种子数据目录（默认 data/）。")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的数据库。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    counts = initialize_database(args.db_path, args.data_dir, force=args.force)
    target = Path(args.db_path) if args.db_path else DEFAULT_DB_PATH
    print(f"数据库初始化完成：{target}")
    for table, count in counts.items():
        print(f"  {table:<22} {count} 行")
    print("种子数据导入完成，现有 data/ 文件保持不变。")


if __name__ == "__main__":
    main()
