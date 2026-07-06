"""Replace all seed samples with the final 13-record corpus.

This script is intentionally destructive for seed/sample data: it rewrites the
sample source files and rebuilds the runtime SQLite database so old case_id
records, draft scores, and conclusion caches cannot leak back into the app.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.db import DEFAULT_DB_PATH
from app.db.init_db import initialize_database
from src.data_service import get_project_root

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is part of the project env.
    yaml = None


PROJECT_ROOT = get_project_root()
DEFAULT_SOURCE_CSV = PROJECT_ROOT / "data" / "final_replacement_samples_13.csv"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

EXPECTED_CASE_IDS = [
    "FD-001",
    "FD-002",
    "FD-003",
    "FD-004",
    "FD-005",
    "LD-001",
    "LD-002",
    "LD-003",
    "LD-004",
    "CM-001",
    "CM-002",
    "CM-003",
    "CM-004",
]
EXPECTED_SCENE_COUNTS = {"财务场景": 5, "法律场景": 4, "投行场景": 4}

REQUIRED_SOURCE_COLUMNS = [
    "case_id",
    "title",
    "professional_scene",
    "status",
    "question",
    "context",
    "output_requirement",
    "standard_conclusion",
    "key_evidence",
    "must_have_points",
    "unacceptable_errors",
    "boundary_and_check_items",
    "difficulty",
    "risk_level",
    "manual_review_notes",
    "reviewer_note",
    "scoring_focus",
]

TASK_COLUMNS = [
    "case_id",
    "domain",
    "scenario",
    "task_type",
    "difficulty",
    "question",
    "context",
    "expected_capability",
    "risk_level",
    "status",
]
MODEL_OUTPUT_COLUMNS = ["output_id", "case_id", "model_name", "answer_text"]
SCORE_COLUMNS = [
    "output_id",
    "case_id",
    "model_name",
    "accuracy_score",
    "reasoning_score",
    "coverage_score",
    "evidence_score",
    "expression_score",
    "total_score",
    "review_note",
]
ERROR_LABEL_COLUMNS = [
    "output_id",
    "case_id",
    "model_name",
    "error_type",
    "severity",
    "error_description",
    "correction",
    "optimization_action",
]
OPTIMIZATION_COLUMNS = [
    "frequent_error",
    "typical_problem",
    "affected_cases",
    "likely_cause",
    "optimization_action",
    "data_sample_format",
    "priority",
]
EVALUATION_RUN_COLUMNS = [
    "run_id",
    "run_name",
    "model_name",
    "model_version",
    "prompt_version",
    "eval_scope",
    "run_date",
    "note",
]
PREFERENCE_PAIR_COLUMNS = [
    "pair_id",
    "case_id",
    "preferred_output_id",
    "rejected_output_id",
    "preference_dimension",
    "preference_reason",
    "improvement_instruction",
    "reviewer",
    "review_status",
]
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

SCENE_TO_DOMAIN = {
    "财务场景": "Financial",
    "法律场景": "Legal",
    "投行场景": "Capital Markets",
}
SCENE_TO_TASK_TYPE = {
    "财务场景": "Financial Judgment",
    "法律场景": "Legal Judgment",
    "投行场景": "Investment Banking Judgment",
}
DIFFICULTY_TO_INTERNAL = {"基础": "Easy", "中等": "Medium", "复杂": "Hard"}
RISK_TO_INTERNAL = {"低": "低", "中": "中", "高": "高"}
STATUS_TO_SAMPLE = {"已入库": "已入库", "待复核": "待复核", "需优化": "需优化", "已移出测试": "已移出测试"}
STATUS_TO_FORMAL = {"已入库": "active", "待复核": "draft", "需优化": "draft", "已移出测试": "inactive"}


class ReplaceSamplesError(RuntimeError):
    """Raised when the final sample replacement cannot be performed safely."""


def _clean(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text.strip()


def _split_items(value: Any) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    parts = re.split(r"\n+|[；;|]+", text)
    return [item.strip(" \t\r\n-•、") for item in parts if item.strip(" \t\r\n-•、")]


def _read_source(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        raise ReplaceSamplesError(f"样本替换 CSV 不存在：{csv_path}")
    frame = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig").fillna("")
    missing = [column for column in REQUIRED_SOURCE_COLUMNS if column not in frame.columns]
    if missing:
        raise ReplaceSamplesError("样本替换 CSV 缺少字段：" + "、".join(missing))
    return frame[REQUIRED_SOURCE_COLUMNS].copy()


def _validate_source(frame: pd.DataFrame) -> None:
    case_ids = frame["case_id"].astype(str).str.strip().tolist()
    if case_ids != EXPECTED_CASE_IDS:
        raise ReplaceSamplesError(
            "最终样本编号必须严格为："
            + "、".join(EXPECTED_CASE_IDS)
            + "；当前为："
            + "、".join(case_ids)
        )
    if len(set(case_ids)) != len(case_ids):
        raise ReplaceSamplesError("样本编号存在重复，不能执行覆盖替换。")

    scene_counts = frame["professional_scene"].astype(str).str.strip().value_counts().to_dict()
    if scene_counts != EXPECTED_SCENE_COUNTS:
        raise ReplaceSamplesError(
            "专业场景数量不符合最终口径："
            + json.dumps(scene_counts, ensure_ascii=False)
        )

    required_content = [
        "question",
        "context",
        "standard_conclusion",
        "must_have_points",
        "unacceptable_errors",
        "boundary_and_check_items",
    ]
    failures: list[str] = []
    for _, row in frame.iterrows():
        case_id = _clean(row.get("case_id"))
        for field in required_content:
            if not _clean(row.get(field)):
                failures.append(f"{case_id} 缺少 {field}")
    if failures:
        raise ReplaceSamplesError("样本核心字段不完整：" + "；".join(failures))


def _load_manifest_rubric(data_dir: Path) -> list[dict[str, Any]]:
    if yaml is None:
        raise ReplaceSamplesError("未安装 PyYAML，无法读取 data/dataset_manifest.yml 中的评分标准。")
    manifest_path = data_dir / "dataset_manifest.yml"
    if not manifest_path.exists():
        raise ReplaceSamplesError(f"缺少评分标准配置：{manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle) or {}
    rubric = manifest.get("rubric", {}) if isinstance(manifest, dict) else {}
    dimensions = rubric.get("dimensions", []) or []
    if not dimensions:
        raise ReplaceSamplesError("dataset_manifest.yml 未声明评分标准维度，不能生成样本资产。")
    result = []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        field = _clean(item.get("field") or item.get("dimension_field"))
        if not field:
            continue
        result.append(
            {
                "dimension_field": field,
                "field": field,
                "name": _clean(item.get("name")),
                "full_mark": int(item.get("full_mark") or item.get("weight") or 0),
                "full_mark_standard": _clean(item.get("full_mark_standard")),
                "deduction_rules": _clean(item.get("deduction_rules")),
                "status": _clean(item.get("status")) or "active",
            }
        )
    if not result:
        raise ReplaceSamplesError("dataset_manifest.yml 中的评分标准维度为空。")
    return result


def _gold_entry(row: pd.Series) -> dict[str, Any]:
    case_id = _clean(row["case_id"])
    boundary = _clean(row["boundary_and_check_items"])
    return {
        "case_id": case_id,
        "core_conclusion": _clean(row["standard_conclusion"]),
        "key_evidence": _clean(row["key_evidence"]),
        "analysis": _clean(row["key_evidence"]),
        "must_have_points": _split_items(row["must_have_points"]),
        "unacceptable_errors": _split_items(row["unacceptable_errors"]),
        "boundary_conditions": boundary,
        "materials_to_check": boundary,
        "manual_review_notes": _clean(row["manual_review_notes"]),
        "scoring_focus": _clean(row["scoring_focus"]),
    }


def _task_row(row: pd.Series) -> dict[str, Any]:
    scene = _clean(row["professional_scene"])
    status = _clean(row["status"]) or "已入库"
    return {
        "case_id": _clean(row["case_id"]),
        "domain": SCENE_TO_DOMAIN.get(scene, ""),
        "scenario": _clean(row["title"]),
        "task_type": SCENE_TO_TASK_TYPE.get(scene, ""),
        "difficulty": DIFFICULTY_TO_INTERNAL.get(_clean(row["difficulty"]), _clean(row["difficulty"])),
        "question": _clean(row["question"]),
        "context": _clean(row["context"]),
        "expected_capability": _clean(row["output_requirement"]),
        "risk_level": RISK_TO_INTERNAL.get(_clean(row["risk_level"]), _clean(row["risk_level"])),
        "status": STATUS_TO_FORMAL.get(status, "active"),
    }


def _sample_record(row: pd.Series, rubric_dimensions: list[dict[str, Any]], now: str) -> dict[str, Any]:
    scene = _clean(row["professional_scene"])
    status = STATUS_TO_SAMPLE.get(_clean(row["status"]), "已入库")
    gold = _gold_entry(row)
    return {
        "sample_id": _clean(row["case_id"]),
        "title": _clean(row["title"]),
        "scenario": _clean(row["title"]),
        "task_prompt": _clean(row["question"]),
        "business_context": _clean(row["context"]),
        "domain": SCENE_TO_DOMAIN.get(scene, ""),
        "task_type": SCENE_TO_TASK_TYPE.get(scene, ""),
        "risk_level": _clean(row["risk_level"]),
        "expected_capability": _clean(row["output_requirement"]),
        "gold_answer": json.dumps(gold, ensure_ascii=False, indent=2),
        "rubric": json.dumps(rubric_dimensions, ensure_ascii=False, indent=2),
        "model_answers": [],
        "error_tags": [],
        "improvement_suggestions": [],
        "status": status,
        "difficulty": _clean(row["difficulty"]),
        "reviewer_note": _clean(row["reviewer_note"]),
        "created_at": now,
        "updated_at": now,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding="utf-8")


def _write_empty_csv(path: Path, columns: list[str]) -> None:
    _write_csv(path, [], columns)


def _update_manifest(data_dir: Path) -> None:
    if yaml is None:
        return
    path = data_dir / "dataset_manifest.yml"
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle) or {}
    if not isinstance(manifest, dict):
        return

    manifest["version"] = "1.0.0"
    manifest["updated"] = datetime.now().strftime("%Y-%m-%d")
    manifest["description"] = (
        "最终 13 条脱敏专业任务样本，覆盖财务场景、法律场景和投行场景；"
        "seed 文件只用于初始化，运行结果由 SQLite 在运行期产生。"
    )
    scope = manifest.setdefault("scope", {})
    scope["domains"] = ["Capital Markets", "Financial", "Legal"]
    scope["task_types"] = [
        "Financial Judgment",
        "Legal Judgment",
        "Investment Banking Judgment",
    ]
    scope["difficulties"] = ["Easy", "Medium", "Hard"]
    # Keep a declared model scope even though replacement clears historical
    # model output rows; the dataset validator treats an empty declaration as
    # missing model-scope metadata.
    scope["models"] = ["Model_A_baseline", "Model_B_rag", "Model_C_prompt_v2"]
    boundary = (
        "当前数据集仅包含 13 条脱敏专业任务样本，用于展示财务、法律、投行场景下"
        "模型回答质量、主要问题与使用边界；不代表脱离样本范围的泛化结论。"
    )
    manifest["boundary"] = boundary
    assets = manifest.get("assets", {})
    if isinstance(assets, dict):
        scores = assets.get("scores")
        if isinstance(scores, dict):
            scores["description"] = "模型回答的评分维度记录；当前 seed 仅保留表头，真实评分在运行期产生。"
        model_outputs = assets.get("model_outputs")
        if isinstance(model_outputs, dict):
            model_outputs["description"] = "模型回答记录；当前 seed 仅保留表头，真实回答在运行期产生。"
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(manifest, handle, allow_unicode=True, sort_keys=False)


def replace_samples(
    *,
    csv_path: str | Path = DEFAULT_SOURCE_CSV,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    db_path: str | Path | None = DEFAULT_DB_PATH,
) -> dict[str, int]:
    """Replace seed/sample data with the final 13 samples and rebuild SQLite."""
    csv_path = Path(csv_path)
    data_dir = Path(data_dir)
    db_path = Path(db_path) if db_path is not None else None

    source = _read_source(csv_path)
    _validate_source(source)
    data_dir.mkdir(parents=True, exist_ok=True)

    rubric_dimensions = _load_manifest_rubric(data_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    task_rows = [_task_row(row) for _, row in source.iterrows()]
    gold_rows = [_gold_entry(row) for _, row in source.iterrows()]
    sample_rows = [_sample_record(row, rubric_dimensions, now) for _, row in source.iterrows()]

    _write_csv(data_dir / "tasks.csv", task_rows, TASK_COLUMNS)
    with (data_dir / "gold_answers.json").open("w", encoding="utf-8") as handle:
        json.dump(gold_rows, handle, ensure_ascii=False, indent=2)
    with (data_dir / "samples.json").open("w", encoding="utf-8") as handle:
        json.dump(sample_rows, handle, ensure_ascii=False, indent=2)

    _write_empty_csv(data_dir / "model_outputs.csv", MODEL_OUTPUT_COLUMNS)
    _write_empty_csv(data_dir / "scores.csv", SCORE_COLUMNS)
    _write_empty_csv(data_dir / "error_labels.csv", ERROR_LABEL_COLUMNS)
    _write_empty_csv(data_dir / "optimization_plan.csv", OPTIMIZATION_COLUMNS)
    _write_empty_csv(data_dir / "evaluation_runs.csv", EVALUATION_RUN_COLUMNS)
    _write_empty_csv(data_dir / "preference_pairs.csv", PREFERENCE_PAIR_COLUMNS)
    _write_empty_csv(data_dir / "optimization_comparison.csv", OPTIMIZATION_COMPARISON_COLUMNS)
    _update_manifest(data_dir)

    counts: dict[str, int] = {}
    if db_path is not None:
        counts = initialize_database(db_path=db_path, data_dir=data_dir, force=True)

    return {
        "sample_count": len(sample_rows),
        "task_count": len(task_rows),
        "gold_count": len(gold_rows),
        **counts,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用最终 13 条 CSV 样本覆盖替换项目 seed 与 SQLite。")
    parser.add_argument("--csv", dest="csv_path", default=str(DEFAULT_SOURCE_CSV), help="最终样本 CSV 路径。")
    parser.add_argument("--data-dir", dest="data_dir", default=str(DEFAULT_DATA_DIR), help="要覆盖的数据目录。")
    parser.add_argument("--db", dest="db_path", default=str(DEFAULT_DB_PATH), help="要重建的 SQLite 路径。")
    parser.add_argument("--skip-db", action="store_true", help="只重写 seed 文件，不重建 SQLite。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    counts = replace_samples(
        csv_path=args.csv_path,
        data_dir=args.data_dir,
        db_path=None if args.skip_db else args.db_path,
    )
    print("样本整体替换完成。")
    for key, value in counts.items():
        print(f"  {key:<22} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
