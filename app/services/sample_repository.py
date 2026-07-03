"""轻量级样本库数据管理层。

样本数据统一存放在 `data/samples.json`，与现有 task/gold 解耦，避免影响评测核心流程。
首次加载时若 JSON 不存在，从现有 `data/tasks.csv` + `data/gold_answers.json` 自动生成初始样本。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SAMPLE_STATUSES = ["待复核", "已入库", "需优化", "已归档"]
REQUIRED_FIELDS = ["title", "scenario", "task_prompt", "gold_answer", "rubric", "status"]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAMPLES_PATH = _PROJECT_ROOT / "data" / "samples.json"
_TASKS_PATH = _PROJECT_ROOT / "data" / "tasks.csv"
_GOLD_PATH = _PROJECT_ROOT / "data" / "gold_answers.json"


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
            status=str(data.get("status", "待复核")),
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


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
    """从 tasks.csv + gold_answers.json 生成初始样本。"""
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
                model_answers=[],
                error_tags=[],
                improvement_suggestions=[],
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


def create_sample(values: dict[str, Any]) -> None:
    """新增样本。会校验必填字段与 sample_id 唯一性。"""
    errors = validate_sample(values, existing_ids=_existing_ids())
    if errors:
        raise ValueError("；".join(errors))

    now = _now()
    sample = Sample.from_dict({**values, "created_at": now, "updated_at": now})
    samples = load_samples()
    samples.append(sample)
    save_samples(samples)


def update_sample(sample_id: str, changes: dict[str, Any]) -> None:
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

    samples[idx] = Sample.from_dict(updated)
    save_samples(samples)


def set_sample_status(sample_id: str, status: str) -> None:
    """变更样本状态。"""
    if status not in SAMPLE_STATUSES:
        raise ValueError(f"无效状态：{status}，可选：{', '.join(SAMPLE_STATUSES)}")
    update_sample(sample_id, {"status": status})


def archive_sample(sample_id: str) -> None:
    """归档样本（软删除）：状态改为已归档。"""
    set_sample_status(sample_id, "已归档")


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

    status = str(values.get("status", "")).strip()
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
