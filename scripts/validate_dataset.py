#!/usr/bin/env python3
"""数据集质量校验脚本（Dataset validation）。

依据 dataset_manifest.yml 与 label_taxonomy.yml，对 data 目录下的数据资产做
结构与一致性校验，输出通过项、警告项与错误项。

校验内容：
  - case_id 唯一；
  - 每个任务存在 Gold Answer；
  - 每个 Gold Answer 包含核心结论、关键依据，以及答案边界或红线错误；
  - 每个 Gold Answer 的结构化要素完整度（核心结论 / 关键依据 / 边界条件 / 不可接受错误 / 必须覆盖点）；
  - Rubric 维度权重完整且与评分字段一致；
  - 模型回答可关联到有效 case_id 与声明的模型范围；
  - 评分记录可关联到有效 case_id、模型与全部 Rubric 维度；
  - 错误标签均来自 label_taxonomy；
  - 错误标签声明的影响维度落在 Rubric 维度范围内；
  - 数据补强建议可关联到已出现的错误标签；
  - 领域、任务类型、难度、模型取值落在 manifest 声明范围内（超出则告警）。

所有检查均按数据文件动态读取，不硬编码样本数量、模型名称或评分结果。

用法：
    python scripts/validate_dataset.py [--data-dir DIR] [--manifest FILE] [--taxonomy FILE]

无错误项时退出码为 0，存在错误项时退出码为 1。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - 依赖缺失时给出明确指引
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_MANIFEST = DEFAULT_DATA_DIR / "dataset_manifest.yml"
DEFAULT_TAXONOMY = DEFAULT_DATA_DIR / "label_taxonomy.yml"

# 允许以脚本方式（python scripts/validate_dataset.py）运行时导入 src 包。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.gold_quality import QUALITY_FIELDS, evaluate_gold_quality, field_value

# 同一字段在不同数据文件中的命名别名，按出现顺序取第一个存在的列。
ERROR_TYPE_ALIASES = ("error_type", "frequent_error")


@dataclass
class Report:
    """累积校验结论，区分通过项、警告项与错误项。"""

    passed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def ok(self, message: str) -> None:
        self.passed.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def fail(self, message: str) -> None:
        self.errors.append(message)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines: list[str] = []
        lines.append("FinDueEval 数据集校验结果")
        lines.append("=" * 32)
        lines.append(
            f"通过 {len(self.passed)} 项 · 警告 {len(self.warnings)} 项 · 错误 {len(self.errors)} 项"
        )
        lines.append("")

        lines.append(f"通过项（{len(self.passed)}）")
        for item in self.passed:
            lines.append(f"  [PASS] {item}")

        lines.append("")
        lines.append(f"警告项（{len(self.warnings)}）")
        if self.warnings:
            for item in self.warnings:
                lines.append(f"  [WARN] {item}")
        else:
            lines.append("  无")

        lines.append("")
        lines.append(f"错误项（{len(self.errors)}）")
        if self.errors:
            for item in self.errors:
                lines.append(f"  [ERROR] {item}")
        else:
            lines.append("  无")

        lines.append("")
        lines.append("结论：" + ("数据集校验通过。" if self.is_valid else "数据集存在错误项，请先修复。"))
        return "\n".join(lines)


class DatasetError(RuntimeError):
    """数据集文件无法读取时抛出。"""


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise DatasetError("未安装 PyYAML，无法读取 YAML 配置。请先执行 pip install pyyaml。")
    if not path.exists():
        raise DatasetError(f"配置文件未找到：{path.name}。")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise DatasetError(f"配置文件格式异常：{path.name} 应为映射结构。")
    return loaded


def _read_csv(data_dir: Path, filename: str) -> pd.DataFrame:
    path = data_dir / filename
    if not path.exists():
        raise DatasetError(f"数据文件未找到：{filename}。")
    return pd.read_csv(path)


def _read_json(data_dir: Path, filename: str) -> Any:
    path = data_dir / filename
    if not path.exists():
        raise DatasetError(f"数据文件未找到：{filename}。")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _string_set(series: pd.Series) -> set[str]:
    return set(series.dropna().astype(str).str.strip())


def _first_present_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    for column in aliases:
        if column in df.columns:
            return column
    return None


def validate_dataset(
    data_dir: Path | str = DEFAULT_DATA_DIR,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    taxonomy_path: Path | str = DEFAULT_TAXONOMY,
) -> Report:
    """运行全部校验并返回 Report。"""
    data_dir = Path(data_dir)
    report = Report()

    manifest = _load_yaml(Path(manifest_path))
    taxonomy = _load_yaml(Path(taxonomy_path))

    tasks = _read_csv(data_dir, "tasks.csv")
    gold_answers = _read_json(data_dir, "gold_answers.json")
    model_outputs = _read_csv(data_dir, "model_outputs.csv")
    scores = _read_csv(data_dir, "scores.csv")
    errors = _read_csv(data_dir, "error_labels.csv")
    optimizations = _read_csv(data_dir, "optimization_plan.csv")

    _check_case_id_unique(tasks, report)
    _check_gold_answer_coverage(tasks, gold_answers, report)
    _check_gold_answer_fields(manifest, gold_answers, report)
    _check_gold_answer_completeness(gold_answers, report)
    _check_rubric_weights(manifest, scores, report)
    _check_model_output_links(manifest, tasks, model_outputs, report)
    _check_score_links(manifest, tasks, model_outputs, scores, report)
    _check_error_labels_in_taxonomy(taxonomy, errors, report)
    _check_taxonomy_impacted_dimensions(manifest, taxonomy, report)
    _check_optimizations_link_to_errors(errors, optimizations, report)
    _check_scope(manifest, tasks, model_outputs, report)

    return report


def _check_case_id_unique(tasks: pd.DataFrame, report: Report) -> None:
    if "case_id" not in tasks.columns:
        report.fail("tasks.csv 缺少 case_id 字段。")
        return
    duplicated = tasks["case_id"][tasks["case_id"].duplicated()].dropna().astype(str).tolist()
    if duplicated:
        report.fail(f"tasks.csv 中 case_id 存在重复：{', '.join(sorted(set(duplicated)))}。")
    else:
        report.ok(f"case_id 唯一（{tasks['case_id'].nunique()} 个任务）。")


def _gold_case_ids(gold_answers: Any) -> set[str]:
    if not isinstance(gold_answers, list):
        return set()
    return {
        str(entry.get("case_id")).strip()
        for entry in gold_answers
        if isinstance(entry, dict) and entry.get("case_id") is not None
    }


def _check_gold_answer_coverage(tasks: pd.DataFrame, gold_answers: Any, report: Report) -> None:
    if "case_id" not in tasks.columns:
        return
    task_ids = _string_set(tasks["case_id"])
    gold_ids = _gold_case_ids(gold_answers)

    missing = sorted(task_ids - gold_ids)
    if missing:
        report.fail(f"以下任务缺少 Gold Answer：{', '.join(missing)}。")
    else:
        report.ok(f"全部 {len(task_ids)} 个任务均存在 Gold Answer。")

    orphan = sorted(gold_ids - task_ids)
    if orphan:
        report.fail(f"以下 Gold Answer 未匹配任务 case_id：{', '.join(orphan)}。")


def _check_gold_answer_fields(manifest: dict[str, Any], gold_answers: Any, report: Report) -> None:
    gold_config = manifest.get("gold_answer", {})
    required_fields = list(gold_config.get("required_fields", []))
    boundary_any_of = list(gold_config.get("boundary_any_of", []))
    if not isinstance(gold_answers, list):
        report.fail("gold_answers.json 格式异常：应为列表。")
        return

    incomplete: list[str] = []
    for entry in gold_answers:
        if not isinstance(entry, dict):
            report.fail("gold_answers.json 存在非对象记录。")
            continue
        case_id = str(entry.get("case_id", "未知"))
        missing = [f for f in required_fields if field_value(entry, f) is None]
        if boundary_any_of and not any(field_value(entry, f) is not None for f in boundary_any_of):
            missing.append("/".join(boundary_any_of))
        if missing:
            incomplete.append(f"{case_id}（缺 {', '.join(missing)}）")

    if incomplete:
        report.fail("以下 Gold Answer 核心要素不完整：" + "；".join(incomplete) + "。")
    else:
        report.ok(
            "全部 Gold Answer 均包含核心结论、关键依据，以及答案边界或红线错误。"
        )


def _check_gold_answer_completeness(gold_answers: Any, report: Report) -> None:
    """逐条评估 Gold Answer 结构化要素是否齐备，区分满足 / 部分满足评测使用条件。"""
    if not isinstance(gold_answers, list) or not gold_answers:
        return

    partial: list[str] = []
    usable = 0
    for entry in gold_answers:
        if not isinstance(entry, dict):
            continue
        quality = evaluate_gold_quality(entry)
        if quality["is_usable"]:
            usable += 1
        else:
            case_id = str(entry.get("case_id", "未知"))
            partial.append(f"{case_id}（缺 {'、'.join(quality['missing'])}）")

    element_labels = "、".join(label for _, label in QUALITY_FIELDS)
    if partial:
        report.warn(
            "以下 Gold Answer 仅部分满足评测使用条件，建议补齐结构化要素："
            + "；".join(partial)
            + "。"
        )
    if usable:
        report.ok(
            f"{usable} 个 Gold Answer 满足评测使用条件，结构化要素（{element_labels}）齐备。"
        )


def _check_rubric_weights(manifest: dict[str, Any], scores: pd.DataFrame, report: Report) -> None:
    rubric = manifest.get("rubric", {})
    dimensions = rubric.get("dimensions", [])
    if not dimensions:
        report.fail("dataset_manifest.yml 未声明 Rubric 维度。")
        return

    total = rubric.get("total")
    weight_sum = sum(int(dim.get("weight", 0)) for dim in dimensions)
    if total is None:
        report.warn("dataset_manifest.yml 未声明 Rubric 满分 total，已跳过权重合计校验。")
    elif weight_sum != int(total):
        report.fail(f"Rubric 维度权重合计为 {weight_sum}，与声明满分 {total} 不一致。")
    else:
        report.ok(f"Rubric 权重完整：{len(dimensions)} 个维度合计 {weight_sum} 分。")

    missing_columns = [
        dim.get("field") for dim in dimensions if dim.get("field") not in scores.columns
    ]
    if missing_columns:
        report.fail(f"scores.csv 缺少 Rubric 维度字段：{', '.join(missing_columns)}。")
    else:
        report.ok("scores.csv 包含全部 Rubric 维度字段。")


def _check_model_output_links(
    manifest: dict[str, Any],
    tasks: pd.DataFrame,
    model_outputs: pd.DataFrame,
    report: Report,
) -> None:
    declared_models = {str(m).strip() for m in manifest.get("scope", {}).get("models", [])}
    task_ids = _string_set(tasks["case_id"]) if "case_id" in tasks.columns else set()

    if "case_id" in model_outputs.columns and task_ids:
        orphan_cases = sorted(_string_set(model_outputs["case_id"]) - task_ids)
        if orphan_cases:
            report.fail(f"model_outputs.csv 存在无法匹配 tasks.case_id 的记录：{', '.join(orphan_cases)}。")
        else:
            report.ok("model_outputs.csv 全部记录关联到有效 case_id。")
    else:
        report.fail("model_outputs.csv 缺少 case_id 字段，无法校验任务关联。")

    if "model_name" in model_outputs.columns and declared_models:
        unknown_models = sorted(_string_set(model_outputs["model_name"]) - declared_models)
        if unknown_models:
            report.fail(
                f"model_outputs.csv 存在未在 manifest 声明的模型：{', '.join(unknown_models)}。"
            )
        else:
            report.ok("model_outputs.csv 全部模型均在声明的模型范围内。")
    else:
        report.fail("model_outputs.csv 缺少 model_name 字段，无法校验模型关联。")


def _check_score_links(
    manifest: dict[str, Any],
    tasks: pd.DataFrame,
    model_outputs: pd.DataFrame,
    scores: pd.DataFrame,
    report: Report,
) -> None:
    task_ids = _string_set(tasks["case_id"]) if "case_id" in tasks.columns else set()
    declared_models = {str(m).strip() for m in manifest.get("scope", {}).get("models", [])}
    dimensions = manifest.get("rubric", {}).get("dimensions", [])
    dimension_fields = [dim.get("field") for dim in dimensions]

    if "case_id" in scores.columns and task_ids:
        orphan_cases = sorted(_string_set(scores["case_id"]) - task_ids)
        if orphan_cases:
            report.fail(f"scores.csv 存在无法匹配 tasks.case_id 的记录：{', '.join(orphan_cases)}。")
        else:
            report.ok("scores.csv 全部记录关联到有效 case_id。")
    else:
        report.fail("scores.csv 缺少 case_id 字段，无法校验任务关联。")

    if "output_id" in scores.columns and "output_id" in model_outputs.columns:
        orphan_outputs = sorted(_string_set(scores["output_id"]) - _string_set(model_outputs["output_id"]))
        if orphan_outputs:
            report.fail(
                f"scores.csv 存在无法匹配 model_outputs.output_id 的记录：{', '.join(orphan_outputs)}。"
            )
        else:
            report.ok("scores.csv 全部记录关联到有效模型回答。")

    if "model_name" in scores.columns and declared_models:
        unknown_models = sorted(_string_set(scores["model_name"]) - declared_models)
        if unknown_models:
            report.fail(f"scores.csv 存在未在 manifest 声明的模型：{', '.join(unknown_models)}。")
        else:
            report.ok("scores.csv 全部模型均在声明的模型范围内。")

    missing_dimensions = [field_name for field_name in dimension_fields if field_name not in scores.columns]
    if missing_dimensions:
        report.fail(f"scores.csv 缺少 Rubric 维度评分字段：{', '.join(missing_dimensions)}。")
    else:
        report.ok("scores.csv 覆盖全部 Rubric 维度评分字段。")


def _taxonomy_label_names(taxonomy: dict[str, Any]) -> set[str]:
    labels = taxonomy.get("labels", [])
    return {
        str(label.get("name")).strip()
        for label in labels
        if isinstance(label, dict) and label.get("name") is not None
    }


def _check_error_labels_in_taxonomy(
    taxonomy: dict[str, Any],
    errors: pd.DataFrame,
    report: Report,
) -> None:
    defined_labels = _taxonomy_label_names(taxonomy)
    if not defined_labels:
        report.fail("label_taxonomy.yml 未定义任何错误标签。")
        return

    column = _first_present_column(errors, ERROR_TYPE_ALIASES)
    if column is None:
        report.fail("error_labels.csv 缺少 error_type 字段，无法校验标签来源。")
        return

    used_labels = _string_set(errors[column])
    undefined = sorted(used_labels - defined_labels)
    if undefined:
        report.fail(f"error_labels.csv 存在未在 label_taxonomy 定义的标签：{', '.join(undefined)}。")
    else:
        report.ok(f"error_labels.csv 全部标签（{len(used_labels)} 类）均来自 label_taxonomy。")


def _check_taxonomy_impacted_dimensions(
    manifest: dict[str, Any],
    taxonomy: dict[str, Any],
    report: Report,
) -> None:
    """每个错误标签声明的影响维度须为 manifest 中已声明的 Rubric 维度。"""
    dimension_names = {
        str(dim.get("name")).strip()
        for dim in manifest.get("rubric", {}).get("dimensions", [])
        if dim.get("name") is not None
    }
    if not dimension_names:
        report.warn("dataset_manifest.yml 未声明 Rubric 维度名称，跳过影响维度校验。")
        return

    labels = taxonomy.get("labels", [])
    missing: list[str] = []
    invalid: list[str] = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        name = str(label.get("name", "未知")).strip()
        dimension = str(label.get("impacted_dimension", "")).strip()
        if not dimension:
            missing.append(name)
        elif dimension not in dimension_names:
            invalid.append(f"{name}（{dimension}）")

    if invalid:
        report.fail(
            "label_taxonomy.yml 中影响维度不在 Rubric 维度范围内：" + "、".join(invalid) + "。"
        )
    if missing:
        report.warn(
            "label_taxonomy.yml 中以下标签未声明影响维度：" + "、".join(missing) + "。"
        )
    if not invalid and not missing:
        report.ok(f"全部 {len(labels)} 个错误标签均声明了合法的影响维度。")


def _check_optimizations_link_to_errors(
    errors: pd.DataFrame,
    optimizations: pd.DataFrame,
    report: Report,
) -> None:
    error_column = _first_present_column(errors, ERROR_TYPE_ALIASES)
    opt_column = _first_present_column(optimizations, ERROR_TYPE_ALIASES)
    if error_column is None or opt_column is None:
        report.fail("无法定位错误类型字段，跳过数据补强建议关联校验。")
        return

    error_labels = _string_set(errors[error_column])
    plan_labels = _string_set(optimizations[opt_column])
    orphan = sorted(plan_labels - error_labels)
    if orphan:
        report.fail(f"optimization_plan.csv 存在无法关联到错误标签的建议：{', '.join(orphan)}。")
    else:
        report.ok(f"optimization_plan.csv 全部建议（{len(plan_labels)} 类）均关联到已出现的错误标签。")


def _check_scope(
    manifest: dict[str, Any],
    tasks: pd.DataFrame,
    model_outputs: pd.DataFrame,
    report: Report,
) -> None:
    scope = manifest.get("scope", {})
    checks = [
        ("领域", tasks, "domain", scope.get("domains", [])),
        ("任务类型", tasks, "task_type", scope.get("task_types", [])),
        ("难度", tasks, "difficulty", scope.get("difficulties", [])),
    ]
    for label, df, column, declared in checks:
        if column not in df.columns or not declared:
            continue
        declared_set = {str(value).strip() for value in declared}
        extra = sorted(_string_set(df[column]) - declared_set)
        if extra:
            report.warn(f"数据中出现未在 manifest 声明的{label}：{', '.join(extra)}，请同步更新清单。")
        else:
            report.ok(f"{label}取值均在 manifest 声明范围内。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 FinDueEval 数据集结构与一致性。")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据目录，默认 ./data。")
    parser.add_argument("--manifest", default=None, help="数据集清单路径，默认 <data-dir>/dataset_manifest.yml。")
    parser.add_argument("--taxonomy", default=None, help="错误标签体系路径，默认 <data-dir>/label_taxonomy.yml。")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    manifest_path = Path(args.manifest) if args.manifest else data_dir / "dataset_manifest.yml"
    taxonomy_path = Path(args.taxonomy) if args.taxonomy else data_dir / "label_taxonomy.yml"

    try:
        report = validate_dataset(data_dir, manifest_path, taxonomy_path)
    except DatasetError as exc:
        print(f"数据集校验无法执行：{exc}", file=sys.stderr)
        return 2

    print(report.render())
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
