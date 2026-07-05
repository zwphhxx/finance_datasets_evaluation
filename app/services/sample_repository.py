"""轻量级样本库数据管理层。

样本库是业务操作视图：待复核、已入库、需优化、已移出测试。
历史 inactive 状态在读取时会规范为已移出测试。
SQLite 可用时，样本库 CRUD 会同步维护正式评测资产：
`task_cases` / `gold_answers` / `rubrics`。`data/samples.json` 保留为轻量管理视图、
导入导出与兼容备份，不再作为正式评测内容的唯一来源。
首次加载时若 JSON 不存在，从现有 `data/tasks.csv` + `data/gold_answers.json` 自动生成初始样本。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REMOVED_FROM_TEST_STATUS = "已移出测试"
_LEGACY_ARCHIVED_STATUS = "已归档"
SAMPLE_STATUSES = ["待复核", "已入库", "需优化", REMOVED_FROM_TEST_STATUS]
FORMAL_STATUS_BY_SAMPLE_STATUS = {
    "待复核": "draft",
    "已入库": "active",
    "需优化": "draft",
    REMOVED_FROM_TEST_STATUS: "inactive",
    _LEGACY_ARCHIVED_STATUS: "inactive",
}
REQUIRED_FIELDS = ["title", "scenario", "task_prompt", "gold_answer", "rubric", "status"]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAMPLES_PATH = _PROJECT_ROOT / "data" / "samples.json"
_TASKS_PATH = _PROJECT_ROOT / "data" / "tasks.csv"
_GOLD_PATH = _PROJECT_ROOT / "data" / "gold_answers.json"
_ERROR_LABELS_PATH = _PROJECT_ROOT / "data" / "error_labels.csv"
_MODEL_OUTPUTS_PATH = _PROJECT_ROOT / "data" / "model_outputs.csv"
_OPTIMIZATION_PLAN_PATH = _PROJECT_ROOT / "data" / "optimization_plan.csv"


@dataclass
class Sample:
    sample_id: str
    title: str
    scenario: str
    task_prompt: str
    business_context: str = ""
    gold_answer: str = ""
    rubric: str = ""
    model_answers: list[str] = field(default_factory=list)
    error_tags: list[str] = field(default_factory=list)
    improvement_suggestions: list[str] = field(default_factory=list)
    status: str = "待复核"
    difficulty: str = ""
    reviewer_note: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Sample":
        return cls(
            sample_id=str(data.get("sample_id", "")),
            title=str(data.get("title", "")),
            scenario=str(data.get("scenario", "")),
            task_prompt=str(data.get("task_prompt", "")),
            business_context=str(data.get("business_context", "")),
            gold_answer=str(data.get("gold_answer", "")),
            rubric=str(data.get("rubric", "")),
            model_answers=_as_str_list(data.get("model_answers")),
            error_tags=_as_str_list(data.get("error_tags")),
            improvement_suggestions=_as_str_list(data.get("improvement_suggestions")),
            status=normalize_sample_status(data.get("status", "待复核")),
            difficulty=str(data.get("difficulty", "")),
            reviewer_note=str(data.get("reviewer_note", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def normalize_sample_status(value: Any) -> str:
    """Normalize historical inactive labels to the current user-facing status."""
    text = str(value or "").strip()
    if text == _LEGACY_ARCHIVED_STATUS:
        return REMOVED_FROM_TEST_STATUS
    return text if text else "待复核"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _load_error_tags_by_case() -> dict[str, list[str]]:
    """从 error_labels.csv 聚合每个 case_id 的错误类型标签。"""
    if not _ERROR_LABELS_PATH.exists():
        return {}
    try:
        df = pd.read_csv(_ERROR_LABELS_PATH, dtype=str).fillna("")
        tags: dict[str, set[str]] = {}
        for _, row in df.iterrows():
            case_id = str(row.get("case_id", "")).strip()
            tag = str(row.get("error_type", "")).strip()
            if case_id and tag:
                tags.setdefault(case_id, set()).add(tag)
        return {case_id: sorted(values) for case_id, values in tags.items()}
    except Exception:
        return {}


def _load_model_answers_by_case() -> dict[str, list[str]]:
    """从 model_outputs.csv 聚合每个 case_id 的模型回答标识。"""
    if not _MODEL_OUTPUTS_PATH.exists():
        return {}
    try:
        df = pd.read_csv(_MODEL_OUTPUTS_PATH, dtype=str).fillna("")
        answers: dict[str, set[str]] = {}
        for _, row in df.iterrows():
            case_id = str(row.get("case_id", "")).strip()
            model = str(row.get("model_name", "")).strip()
            if case_id and model:
                answers.setdefault(case_id, set()).add(model)
        return {case_id: sorted(values) for case_id, values in answers.items()}
    except Exception:
        return {}


def _load_improvement_suggestions_by_case() -> dict[str, list[str]]:
    """从 optimization_plan.csv 聚合每个 case_id 的优化建议。"""
    if not _OPTIMIZATION_PLAN_PATH.exists():
        return {}
    try:
        df = pd.read_csv(_OPTIMIZATION_PLAN_PATH, dtype=str).fillna("")
        suggestions: dict[str, set[str]] = {}
        for _, row in df.iterrows():
            cases_raw = str(row.get("affected_cases", "")).strip()
            action = str(row.get("optimization_action", "")).strip()
            if not cases_raw or not action:
                continue
            for case_id in [c.strip() for c in cases_raw.split(";") if c.strip()]:
                suggestions.setdefault(case_id, set()).add(action)
        return {case_id: sorted(values) for case_id, values in suggestions.items()}
    except Exception:
        return {}


def _samples_path() -> Path:
    return _SAMPLES_PATH


def load_samples() -> list[Sample]:
    """加载所有样本。若 JSON 不存在，则从现有任务与 Gold 初始化并保存。"""
    path = _samples_path()
    if not path.exists():
        samples = seed_samples_from_tasks()
        save_samples(samples)
        return samples

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return []

    if not isinstance(raw, list):
        return []
    return [Sample.from_dict(item) for item in raw]


def save_samples(samples: list[Sample]) -> None:
    """保存样本列表到 JSON。"""
    path = _samples_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            [s.to_dict() for s in samples],
            f,
            ensure_ascii=False,
            indent=2,
        )


def seed_samples_from_tasks() -> list[Sample]:
    """从 tasks.csv + gold_answers.json 生成初始样本，并聚合已有的错误标签、
    模型回答与优化建议，让样本库一初始化就具备可维护的上下文。"""
    if not _TASKS_PATH.exists():
        return []

    tasks = pd.read_csv(_TASKS_PATH, dtype=str).fillna("")
    gold_map: dict[str, dict] = {}
    if _GOLD_PATH.exists():
        try:
            with _GOLD_PATH.open("r", encoding="utf-8") as f:
                records = json.load(f)
            if isinstance(records, list):
                for rec in records:
                    if isinstance(rec, dict) and rec.get("case_id"):
                        gold_map[str(rec["case_id"])] = rec
        except Exception:
            pass

    error_tags_map = _load_error_tags_by_case()
    model_answers_map = _load_model_answers_by_case()
    suggestions_map = _load_improvement_suggestions_by_case()

    samples: list[Sample] = []
    for _, row in tasks.iterrows():
        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            continue
        gold = gold_map.get(case_id)
        gold_text = json.dumps(gold, ensure_ascii=False, indent=2) if gold else ""
        status = "已入库" if gold else "待复核"
        title = str(row.get("scenario", "")).strip() or case_id
        samples.append(
            Sample(
                sample_id=case_id,
                title=title,
                scenario=str(row.get("scenario", "")).strip(),
                task_prompt=str(row.get("question", "")).strip(),
                business_context=str(row.get("context", "")).strip(),
                gold_answer=gold_text,
                rubric="",
                model_answers=model_answers_map.get(case_id, []),
                error_tags=error_tags_map.get(case_id, []),
                improvement_suggestions=suggestions_map.get(case_id, []),
                status=status,
                difficulty=str(row.get("difficulty", "")).strip(),
                reviewer_note="",
                created_at=_now(),
                updated_at=_now(),
            )
        )
    return samples


def list_samples() -> pd.DataFrame:
    """以 DataFrame 形式返回所有样本。"""
    samples = load_samples()
    if not samples:
        return pd.DataFrame(columns=Sample.__dataclass_fields__.keys())
    return pd.DataFrame([s.to_dict() for s in samples])


def get_sample(sample_id: str) -> Sample | None:
    """按 sample_id 查找单个样本。"""
    for sample in load_samples():
        if sample.sample_id == sample_id:
            return sample
    return None


def _existing_ids() -> set[str]:
    return {s.sample_id for s in load_samples()}


def create_sample(values: dict[str, Any], *, db_path: Path | None = None) -> None:
    """新增样本。会校验必填字段与 sample_id 唯一性。"""
    errors = validate_sample(values, existing_ids=_existing_ids())
    if errors:
        raise ValueError("；".join(errors))

    now = _now()
    sample = Sample.from_dict({**values, "created_at": now, "updated_at": now})
    formal_db_path = _resolve_formal_db_path(db_path)
    if formal_db_path is not None:
        _sync_sample_assets_to_formal_layer(sample, db_path=formal_db_path)

    samples = load_samples()
    samples.append(sample)
    save_samples(samples)


def update_sample(sample_id: str, changes: dict[str, Any], *, db_path: Path | None = None) -> None:
    """更新样本字段。sample_id 不可修改；updated_at 自动刷新。"""
    if "sample_id" in changes:
        raise ValueError("不允许修改样本编号 sample_id")

    samples = load_samples()
    idx = next((i for i, s in enumerate(samples) if s.sample_id == sample_id), None)
    if idx is None:
        raise ValueError(f"样本 {sample_id} 不存在")

    current = samples[idx]
    updated = current.to_dict()
    updated.update(changes)
    updated["updated_at"] = _now()

    errors = validate_sample(updated, existing_ids={s.sample_id for s in samples if s.sample_id != sample_id})
    if errors:
        raise ValueError("；".join(errors))

    updated_sample = Sample.from_dict(updated)
    formal_db_path = _resolve_formal_db_path(db_path)
    if formal_db_path is not None:
        _sync_sample_assets_to_formal_layer(updated_sample, db_path=formal_db_path)

    samples[idx] = updated_sample
    save_samples(samples)


def set_sample_status(sample_id: str, status: str, *, db_path: Path | None = None) -> None:
    """变更样本状态。"""
    status = normalize_sample_status(status)
    if status not in SAMPLE_STATUSES:
        raise ValueError(f"无效状态：{status}，可选：{', '.join(SAMPLE_STATUSES)}")
    update_sample(sample_id, {"status": status}, db_path=db_path)


def archive_sample(sample_id: str, *, db_path: Path | None = None) -> None:
    """移出测试（软删除）：保留历史记录，但不再进入正式评测。"""
    set_sample_status(sample_id, REMOVED_FROM_TEST_STATUS, db_path=db_path)


def get_eligible_case_ids() -> list[str]:
    """返回本地样本视图中已入库的编号，保留给兼容场景使用。"""
    return [s.sample_id for s in load_samples() if s.status == "已入库"]


def export_samples_json() -> str:
    """将当前样本库导出为格式化的 JSON 字符串。"""
    return json.dumps(
        [s.to_dict() for s in load_samples()],
        ensure_ascii=False,
        indent=2,
    )


def import_samples(samples_data: list[dict[str, Any]], *, db_path: Path | None = None) -> list[Sample]:
    """导入样本数组，按 sample_id 合并或新增，并统一校验。

    导入失败时抛出 ValueError，保留原数据不变。
    """
    if not isinstance(samples_data, list):
        raise ValueError("导入文件应为样本对象数组")

    samples = load_samples()
    existing_index = {s.sample_id: i for i, s in enumerate(samples)}
    current_ids = {s.sample_id for s in samples}

    errors: list[str] = []
    seen_ids: set[str] = set()
    imported: list[Sample] = []

    for idx, raw in enumerate(samples_data):
        if not isinstance(raw, dict):
            errors.append(f"第 {idx + 1} 项不是对象")
            continue

        sample_id = str(raw.get("sample_id", "")).strip()
        if not sample_id:
            errors.append(f"第 {idx + 1} 项缺少 sample_id")
            continue
        if sample_id in seen_ids:
            errors.append(f"第 {idx + 1} 项 sample_id {sample_id} 重复")
            continue
        seen_ids.add(sample_id)

        item_errors = validate_sample(raw, existing_ids=current_ids - {sample_id})
        if item_errors:
            errors.append(f"样本 {sample_id}：{'；'.join(item_errors)}")
            continue

        sample = Sample.from_dict(raw)
        now = _now()
        if not sample.created_at:
            sample.created_at = now
        if not sample.updated_at:
            sample.updated_at = now

        if sample_id in existing_index:
            samples[existing_index[sample_id]] = sample
        else:
            samples.append(sample)
            current_ids.add(sample_id)
        imported.append(sample)

    if errors:
        raise ValueError("\n".join(errors))

    formal_db_path = _resolve_formal_db_path(db_path)
    if formal_db_path is not None:
        for sample in imported:
            _sync_sample_assets_to_formal_layer(sample, db_path=formal_db_path)

    save_samples(samples)
    return imported


def validate_sample(values: dict[str, Any], existing_ids: set[str] | None = None) -> list[str]:
    """基础校验。返回错误信息列表，空列表表示通过。"""
    errors: list[str] = []
    sample_id = str(values.get("sample_id", "")).strip()

    if not sample_id:
        errors.append("sample_id 为必填项")
    elif existing_ids is not None and sample_id in existing_ids:
        errors.append(f"sample_id {sample_id} 已存在")

    for field_name in REQUIRED_FIELDS:
        value = values.get(field_name)
        if value is None or str(value).strip() == "":
            errors.append(f"{field_name} 为必填项")

    status = normalize_sample_status(values.get("status", ""))
    if status and status not in SAMPLE_STATUSES:
        errors.append(f"status 必须为：{', '.join(SAMPLE_STATUSES)}")

    return errors


def search_samples(keyword: str) -> list[Sample]:
    """按关键词搜索标题、场景、任务描述、业务背景、复核备注。"""
    if not keyword:
        return load_samples()
    kw = str(keyword).lower()
    results = []
    for sample in load_samples():
        text = " ".join(
            [
                sample.sample_id,
                sample.title,
                sample.scenario,
                sample.task_prompt,
                sample.business_context,
                sample.reviewer_note,
            ]
        ).lower()
        if kw in text:
            results.append(sample)
    return results


def filter_samples(
    status: str | None = None,
    scenario: str | None = None,
    difficulty: str | None = None,
    error_tag: str | None = None,
) -> list[Sample]:
    """多条件筛选样本。"""
    results = load_samples()
    if status and status != "全部":
        results = [s for s in results if s.status == status]
    if scenario and scenario != "全部":
        results = [s for s in results if s.scenario == scenario]
    if difficulty and difficulty != "全部":
        results = [s for s in results if s.difficulty == difficulty]
    if error_tag and error_tag != "全部":
        results = [s for s in results if error_tag in s.error_tags]
    return results


def count_by_status() -> dict[str, int]:
    """返回各状态样本数量。"""
    counts = {status: 0 for status in SAMPLE_STATUSES}
    for sample in load_samples():
        if sample.status in counts:
            counts[sample.status] += 1
    return counts


def formal_status_for_sample_status(status: str) -> str:
    """把页面中文业务状态映射为正式任务层状态。"""
    normalized = normalize_sample_status(status)
    if normalized not in FORMAL_STATUS_BY_SAMPLE_STATUS:
        raise ValueError(f"无效状态：{normalized}，可选：{', '.join(SAMPLE_STATUSES)}")
    return FORMAL_STATUS_BY_SAMPLE_STATUS[normalized]


def _resolve_formal_db_path(db_path: Path | None = None) -> Path | None:
    """返回本次样本 CRUD 应同步的 SQLite 路径。

    测试会把 `_SAMPLES_PATH` 指向临时 JSON；这种情况下未显式传入 db_path 时只验证
    文件管理视图，避免意外修改开发库。真实应用使用默认 samples.json 且数据库就绪时，
    会自动同步正式数据层。
    """
    try:
        from app.services import dataset_service as ds

        if db_path is not None:
            path = Path(db_path)
            if not ds.database_ready(path):
                raise ValueError(f"SQLite 数据库未初始化或不可用：{path}。请先初始化数据库。")
            return path

        default_samples_path = _PROJECT_ROOT / "data" / "samples.json"
        if _samples_path() != default_samples_path:
            return None

        path = ds.get_db_path()
        return path if ds.database_ready(path) else None
    except ValueError:
        raise
    except Exception:
        return None


def _sync_sample_assets_to_formal_layer(sample: Sample, *, db_path: Path) -> bool:
    """将样本记录写入正式任务、Gold Answer 与 Rubric 数据层。"""
    from app.services import dataset_service as ds

    payload = sample.to_dict()
    payload["formal_status"] = formal_status_for_sample_status(sample.status)
    try:
        ds.upsert_sample_assets(payload, db_path=db_path)
    except ds.DataLoadError as exc:
        raise ValueError(str(exc)) from exc
    return True


def _sync_status_to_formal_layer(
    sample_id: str,
    sample_status: str,
    *,
    db_path: Path | None = None,
) -> bool:
    """兼容旧调用：优先同步完整样本资产；找不到样本时仅同步状态。"""
    try:
        from app.services import dataset_service as ds

        formal_db_path = _resolve_formal_db_path(db_path)
        if formal_db_path is None:
            return False
        sample = get_sample(sample_id)
        if sample is not None:
            sample.status = sample_status
            return _sync_sample_assets_to_formal_layer(sample, db_path=formal_db_path)
        if ds.get_task_case(sample_id, formal_db_path) is None:
            return False
        ds.set_task_case_status(
            sample_id,
            formal_status_for_sample_status(sample_status),
            db_path=formal_db_path,
        )
        return True
    except Exception:
        return False
