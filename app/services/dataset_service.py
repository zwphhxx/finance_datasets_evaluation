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
from app.db.init_db import initialize_database
from app.db.repository import Repository
from src.error_config import evaluate_error_config
from src.data_service import (
    DATA_FILES,
    OPTIMIZATION_COMPARISON_COLUMNS,
    DataLoadError,
    EvaluationData,
    _read_yaml_file,
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


# --------------------------------------------------------------------------- #
# 最小 CRUD（PR-31）
#
# 仅写入 SQLite，不回写 data/ 下的 seed 文件；写入后清空缓存，使任务样本页、
# 样板题评测页等读取方在下一次 rerun 立即看到最新数据。所有写入统一经由
# repository，页面层不出现任何 SQL。
# --------------------------------------------------------------------------- #

# Gold Answer 中以 JSON 数组存储的要素与标量要素（与 init_db 的导入口径一致）。
_GOLD_LIST_FIELDS = ("must_have_points", "unacceptable_errors")
_GOLD_SCALAR_FIELDS = (
    "core_conclusion",
    "key_evidence",
    "analysis",
    "materials_to_check",
    "boundary_conditions",
    "manual_review_notes",
)
_GOLD_EDITABLE_FIELDS = (
    "core_conclusion",
    "key_evidence",
    "boundary_conditions",
    "manual_review_notes",
    "must_have_points",
    "unacceptable_errors",
)

# 任务题可维护字段（与 task_cases 业务列对应；元数据列由数据库维护）。
TASK_EDITABLE_FIELDS = (
    "domain",
    "scenario",
    "task_type",
    "difficulty",
    "question",
    "context",
    "expected_capability",
    "risk_level",
)

# 样本评判标准字段（Gold Answer 核心要素）
JUDGMENT_CRITERIA_FIELDS = (
    "core_conclusion",
    "must_have_points",
    "unacceptable_errors",
)

ACTIVE_STATUS = "active"
INACTIVE_STATUS = "inactive"
DRAFT_STATUS = "draft"


def has_judgment_criteria(gold_record: dict | None) -> bool:
    """检查样本是否具备完整的评判标准（Gold Answer 核心要素）。"""
    if not isinstance(gold_record, dict):
        return False
    # 必须同时存在核心结论、必须覆盖点、不可接受错误
    core = _clean(gold_record.get("core_conclusion"))
    must = _as_list(gold_record.get("must_have_points"))
    unacc = _as_list(gold_record.get("unacceptable_errors"))
    return bool(core) and bool(must) and bool(unacc)


def get_sample_status(task_record: dict | None, gold_record: dict | None) -> str:
    """返回样本状态：具备完整评判标准则为 active，否则为 draft。"""
    task_status = str((task_record or {}).get("status") or ACTIVE_STATUS).strip().lower()
    if task_status == INACTIVE_STATUS:
        return INACTIVE_STATUS
    if not has_judgment_criteria(gold_record):
        return DRAFT_STATUS
    return ACTIVE_STATUS


def can_enter_formal_testing(task_record: dict | None, gold_record: dict | None) -> bool:
    """样本是否允许进入正式测试（必须非 draft、非 inactive）。"""
    status = get_sample_status(task_record, gold_record)
    return status not in {DRAFT_STATUS, INACTIVE_STATUS}


def _invalidate_caches() -> None:
    """写入后清空 Streamlit 数据缓存，确保各页面读取到最新数据。"""
    try:
        st.cache_data.clear()
    except Exception:
        # 在无 Streamlit 运行时上下文（如纯函数测试）下静默跳过。
        pass


def _repository(db_path: Path | None = None) -> Repository:
    return Repository(db_path or get_db_path())


def ensure_seed_database(db_path: Path | None = None, *, force: bool = False) -> dict[str, int]:
    """从现有 seed 文件初始化 SQLite 数据层，返回各表行数。

    仅读取 data/ 下的 CSV/JSON/YAML 作为初始化来源，不修改它们；初始化后清空缓存。
    """
    path = db_path or get_db_path()
    counts = initialize_database(path, force=force)
    _invalidate_caches()
    return counts


# -- 任务题 ------------------------------------------------------------------ #
def list_task_cases(db_path: Path | None = None) -> pd.DataFrame:
    """返回全部任务题（含停用），用于管理页展示。"""
    return _repository(db_path).list_df("task_cases")


def list_dataset_versions(db_path: Path | None = None) -> list[str]:
    """返回数据集中出现过的版本号（去重、降序）。

    数据库可用时取自 task_cases.version；否则回退读取 manifest 声明的版本。
    供「真实模型评测」等页面做数据集版本选择。
    """
    path = db_path or get_db_path()
    if database_ready(path):
        frame = _repository(path).list_df("task_cases")
        if "version" in frame.columns:
            versions = sorted({str(v) for v in frame["version"].dropna().tolist()}, reverse=True)
            if versions:
                return versions
    manifest = _read_yaml_file("dataset_manifest.yml", get_data_dir())
    version = str(manifest.get("version") or "") if isinstance(manifest, dict) else ""
    return [version] if version else []


def get_task_case(case_id: str, db_path: Path | None = None) -> dict | None:
    return _repository(db_path).get("task_cases", case_id)


def create_task_case(values: dict, *, db_path: Path | None = None) -> None:
    """新增任务题。values 以 task_cases 业务列为键，case_id 必填且不可重复。"""
    case_id = str(values.get("case_id") or "").strip()
    if not case_id:
        raise DataLoadError("任务编号（case_id）不能为空。")
    repository = _repository(db_path)
    if repository.get("task_cases", case_id) is not None:
        raise DataLoadError(f"任务编号已存在：{case_id}。")
    payload = {"case_id": case_id}
    for field in TASK_EDITABLE_FIELDS:
        payload[field] = _clean(values.get(field))
    payload["status"] = str(values.get("status") or ACTIVE_STATUS).strip() or ACTIVE_STATUS
    repository.insert("task_cases", payload)
    _invalidate_caches()


def update_task_case(case_id: str, changes: dict, *, db_path: Path | None = None) -> None:
    """编辑任务题的业务字段（不改动 case_id）。"""
    editable = {field: _clean(changes[field]) for field in TASK_EDITABLE_FIELDS if field in changes}
    if "status" in changes:
        editable["status"] = str(changes["status"] or ACTIVE_STATUS).strip() or ACTIVE_STATUS
    if not editable:
        return
    _repository(db_path).update("task_cases", case_id, editable)
    _invalidate_caches()


def set_task_case_status(case_id: str, status: str, *, db_path: Path | None = None) -> None:
    """变更任务题状态。停用即 status=inactive，不做物理删除。"""
    _repository(db_path).update("task_cases", case_id, {"status": status})
    _invalidate_caches()


# -- Gold Answer ------------------------------------------------------------- #
def list_gold_answer_case_ids(db_path: Path | None = None) -> list[str]:
    """返回已有 Gold Answer 的任务编号列表，供管理页选择编辑。"""
    frame = _repository(db_path).list_df("gold_answers")
    if "case_id" not in frame.columns:
        return []
    return [str(case_id) for case_id in frame["case_id"].tolist()]


def get_gold_answer_record(case_id: str, db_path: Path | None = None) -> dict | None:
    """返回某题 Gold Answer 的原始条目（以 raw_json 为准），供编辑回显。"""
    row = _repository(db_path).get("gold_answers", case_id)
    if row is None:
        return None
    raw = row.get("raw_json")
    if raw:
        try:
            entry = json.loads(raw)
            if isinstance(entry, dict):
                return entry
        except (TypeError, json.JSONDecodeError):
            pass
    # raw_json 缺失或异常时退回结构化列，保证仍可编辑。
    return {key: row.get(key) for key in ("case_id", *_GOLD_SCALAR_FIELDS)}


def update_gold_answer(case_id: str, fields: dict, *, db_path: Path | None = None) -> None:
    """编辑 Gold Answer 的核心要素，结构化列与 raw_json 同步更新。

    raw_json 始终作为页面展示的权威来源：在原始条目上就地修改被编辑的键，
    其余键原样保留，确保无损兼容，不破坏现有展示。
    """
    repository = _repository(db_path)
    row = repository.get("gold_answers", case_id)
    if row is None:
        raise DataLoadError(f"未找到 Gold Answer：{case_id}。")

    entry = get_gold_answer_record(case_id, db_path) or {"case_id": case_id}
    changes: dict[str, object] = {}

    for field in _GOLD_EDITABLE_FIELDS:
        if field not in fields:
            continue
        if field in _GOLD_LIST_FIELDS:
            items = _as_list(fields[field])
            entry[field] = items
            changes[field] = json.dumps(items, ensure_ascii=False) if items else None
        else:
            text = _clean(fields[field])
            entry[field] = text
            changes[field] = text

    if not changes:
        return
    changes["raw_json"] = json.dumps(entry, ensure_ascii=False)
    repository.update("gold_answers", case_id, changes)
    _invalidate_caches()


# -- Rubric ------------------------------------------------------------------ #
def list_rubrics(db_path: Path | None = None) -> pd.DataFrame:
    """返回全部评分维度（含权重、满分标准与扣分规则），用于管理页展示。"""
    return _repository(db_path).list_df("rubrics")


def get_rubric_dimensions(db_path: Path | None = None) -> list[dict]:
    """返回评分维度 [{field, name, full_mark}]，供裁判评分与对比表统一取用。

    维度顺序与满分以 src.metrics 的方法学配置为准（不硬编码第二份）；当 rubrics 表存在且
    有对应行时，用表中的 name / full_mark 覆盖，使数据库初始化后维度信息来自数据。
    """
    from src.metrics import SCORE_DIMENSIONS, SCORE_DIMENSION_FULL_MARKS

    overrides: dict[str, dict] = {}
    try:
        frame = list_rubrics(db_path)
        if "dimension_field" in frame.columns:
            for _, row in frame.iterrows():
                overrides[str(row["dimension_field"])] = row.to_dict()
    except Exception:
        overrides = {}

    dimensions: list[dict] = []
    for field, default_name in SCORE_DIMENSIONS:
        row = overrides.get(field, {})
        full_mark = _as_int(row.get("full_mark")) if row.get("full_mark") is not None else None
        if not full_mark:
            full_mark = SCORE_DIMENSION_FULL_MARKS.get(field)
        name = _clean(row.get("name")) or default_name
        dimensions.append({"field": field, "name": name, "full_mark": full_mark})
    return dimensions


def update_rubric(dimension_field: str, changes: dict, *, db_path: Path | None = None) -> None:
    """编辑评分维度的权重、满分标准与扣分规则。"""
    allowed = {"weight", "full_mark", "full_mark_standard", "deduction_rules"}
    editable: dict[str, object] = {}
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key in {"weight", "full_mark"}:
            editable[key] = _as_int(value)
        else:
            editable[key] = _clean(value)
    if not editable:
        return
    _repository(db_path).update("rubrics", dimension_field, editable)
    _invalidate_caches()


# -- 错误标签体系（error taxonomy） ------------------------------------------ #
ERROR_LABEL_EDITABLE_FIELDS = (
    "definition",
    "typical_symptom",
    "severity_level",
    "related_dimension",
    "suggested_data_action",
    "validation_metric",
)
# 补强动作的业务字段 → improvement_actions 列映射（related_error_label 复用 frequent_error）。
_ACTION_FIELD_TO_COLUMN = {
    "related_error_label": "frequent_error",
    "action_type": "action_type",
    "action_description": "optimization_action",
    "expected_effect": "expected_effect",
    "validation_method": "validation_method",
    "priority": "priority",
}


def list_error_taxonomy(db_path: Path | None = None) -> pd.DataFrame:
    """返回全部错误标签（含停用），用于管理页展示。"""
    return _repository(db_path).list_df("error_taxonomy")


def get_error_label(error_label: str, db_path: Path | None = None) -> dict | None:
    return _repository(db_path).get("error_taxonomy", error_label)


def active_error_labels(db_path: Path | None = None) -> set[str]:
    frame = list_error_taxonomy(db_path)
    if "error_label" not in frame.columns:
        return set()
    if "status" in frame.columns:
        frame = frame[frame["status"].astype(str).str.strip().str.lower() != INACTIVE_STATUS]
    return {str(label) for label in frame["error_label"].tolist()}


def create_error_label(values: dict, *, db_path: Path | None = None) -> None:
    """新增错误标签。error_label 必填且不可重复。"""
    error_label = str(values.get("error_label") or "").strip()
    if not error_label:
        raise DataLoadError("错误标签（error_label）不能为空。")
    repository = _repository(db_path)
    if repository.get("error_taxonomy", error_label) is not None:
        raise DataLoadError(f"错误标签已存在：{error_label}。")
    payload = {"error_label": error_label}
    for field in ERROR_LABEL_EDITABLE_FIELDS:
        payload[field] = _clean(values.get(field))
    payload["status"] = str(values.get("status") or ACTIVE_STATUS).strip() or ACTIVE_STATUS
    repository.insert("error_taxonomy", payload)
    _invalidate_caches()


def update_error_label(error_label: str, changes: dict, *, db_path: Path | None = None) -> None:
    editable = {f: _clean(changes[f]) for f in ERROR_LABEL_EDITABLE_FIELDS if f in changes}
    if "status" in changes:
        editable["status"] = str(changes["status"] or ACTIVE_STATUS).strip() or ACTIVE_STATUS
    if not editable:
        return
    _repository(db_path).update("error_taxonomy", error_label, editable)
    _invalidate_caches()


def set_error_label_status(error_label: str, status: str, *, db_path: Path | None = None) -> None:
    """停用即 status=inactive，不做物理删除（保留历史标签）。"""
    _repository(db_path).update("error_taxonomy", error_label, {"status": status})
    _invalidate_caches()


# -- 数据补强动作（improvement actions） ------------------------------------- #
def list_improvement_actions(db_path: Path | None = None) -> pd.DataFrame:
    """返回全部补强动作（含停用、含治理补充列），用于管理页展示。"""
    return _repository(db_path).list_df("improvement_actions", order_by="id")


def get_improvement_action(action_db_id: int, db_path: Path | None = None) -> dict | None:
    return _repository(db_path).get("improvement_actions", action_db_id)


def _next_action_id(repository: Repository) -> str:
    frame = repository.list_df("improvement_actions", order_by="id")
    max_index = 0
    for value in frame.get("action_id", []) if "action_id" in frame.columns else []:
        text = str(value or "").strip()
        if text.upper().startswith("DA-") and text[3:].isdigit():
            max_index = max(max_index, int(text[3:]))
    return f"DA-{max_index + 1:03d}"


def create_improvement_action(values: dict, *, db_path: Path | None = None) -> None:
    """新增补强动作。必须关联到一个已登记的错误标签。"""
    related = str(values.get("related_error_label") or "").strip()
    if not related:
        raise DataLoadError("数据补强动作必须关联错误标签（related_error_label）。")
    repository = _repository(db_path)
    if related not in active_error_labels(db_path):
        raise DataLoadError(f"关联的错误标签不存在或已停用：{related}。")
    payload = {"action_id": _next_action_id(repository)}
    for field, column in _ACTION_FIELD_TO_COLUMN.items():
        payload[column] = _clean(values.get(field))
    payload["status"] = str(values.get("status") or ACTIVE_STATUS).strip() or ACTIVE_STATUS
    repository.insert("improvement_actions", payload)
    _invalidate_caches()


def update_improvement_action(action_db_id: int, changes: dict, *, db_path: Path | None = None) -> None:
    related = changes.get("related_error_label")
    if related is not None and str(related).strip():
        if str(related).strip() not in active_error_labels(db_path):
            raise DataLoadError(f"关联的错误标签不存在或已停用：{str(related).strip()}。")
    editable = {
        column: _clean(changes[field])
        for field, column in _ACTION_FIELD_TO_COLUMN.items()
        if field in changes
    }
    if "status" in changes:
        editable["status"] = str(changes["status"] or ACTIVE_STATUS).strip() or ACTIVE_STATUS
    if not editable:
        return
    _repository(db_path).update("improvement_actions", action_db_id, editable)
    _invalidate_caches()


def set_improvement_action_status(action_db_id: int, status: str, *, db_path: Path | None = None) -> None:
    _repository(db_path).update("improvement_actions", action_db_id, {"status": status})
    _invalidate_caches()


# -- 配置一致性校验 ---------------------------------------------------------- #
def evaluate_error_configuration(db_path: Path | None = None) -> list:
    """对当前 SQLite 中的错误标签体系与补强动作做配置校验，返回 ConfigIssue 列表。"""
    repository = _repository(db_path)
    labels = repository.list_df("error_taxonomy").to_dict(orient="records")

    annotations = repository.list_df("error_annotations", order_by="id")
    error_counts: dict[str, int] = {}
    if "error_type" in annotations.columns:
        error_counts = {
            str(label): int(count)
            for label, count in annotations["error_type"].dropna().astype(str).value_counts().items()
        }

    actions_frame = repository.list_df("improvement_actions", order_by="id")
    actions = []
    for record in actions_frame.to_dict(orient="records"):
        actions.append(
            {
                "action_id": record.get("action_id") or record.get("id"),
                "related_error_label": record.get("frequent_error"),
                "status": record.get("status"),
            }
        )

    rubric_names = []
    rubrics = repository.list_df("rubrics")
    if "name" in rubrics.columns:
        rubric_names = [str(name) for name in rubrics["name"].dropna().tolist()]

    return evaluate_error_config(labels, error_counts, actions, rubric_names)


# -- 小工具 ------------------------------------------------------------------ #
def _clean(value: object) -> str | None:
    """空白/缺失统一规整为 None，其余转为去除首尾空白的字符串。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _as_list(value: object) -> list[str]:
    """将多行文本或列表规整为去空白、去空行的字符串列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        items = [line.strip() for line in str(value).splitlines()]
    return [item for item in items if item]


def _as_int(value: object) -> int | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return int(float(cleaned))
    except (TypeError, ValueError):
        return None
