"""错误标签体系与数据补强动作的配置一致性校验（error configuration checks）。

集中提供一个框架无关的纯函数 evaluate_error_config，供数据服务层与
scripts/validate_dataset.py 共用，识别三类配置问题：

  1. 无效错误标签：缺少定义，或影响维度不在评分标准维度范围内，或错误标注引用了
     未登记的标签；
  2. 没有关联补强动作的高频错误：出现频次达到高频阈值，却没有任一启用的补强动作关联；
  3. related_error_label 不存在的补强动作：补强动作关联到未登记（或为空）的错误标签。

仅做结构与关联校验，不读取文件、不依赖 Streamlit，不编造任何评测结果。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping


# 问题类别常量，便于调用方分组展示或映射到校验报告。
INVALID_LABEL = "invalid_label"
HIGH_FREQ_WITHOUT_ACTION = "high_freq_without_action"
ORPHAN_ACTION = "orphan_action"

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class ConfigIssue:
    kind: str
    severity: str
    target: str
    message: str


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _active(rows: Iterable[Mapping], status_key: str = "status") -> list[dict]:
    active: list[dict] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        status = _clean(row.get(status_key)) or "active"
        if status.lower() != "inactive":
            active.append(dict(row))
    return active


def high_frequency_threshold(error_counts: Mapping[str, int]) -> int:
    """高频阈值：取各错误类型出现次数均值的向上取整，至少为 2。

    阈值由数据动态推导，不硬编码具体数字；样本为空时返回一个不会触发的高值。
    """
    counts = [int(value) for value in error_counts.values() if value is not None]
    if not counts:
        return 10 ** 9
    return max(2, math.ceil(sum(counts) / len(counts)))


def evaluate_error_config(
    labels: Iterable[Mapping],
    error_counts: Mapping[str, int],
    actions: Iterable[Mapping],
    rubric_dimensions: Iterable[str],
    *,
    high_freq_threshold: int | None = None,
) -> list[ConfigIssue]:
    """对错误标签体系与补强动作做配置一致性校验，返回问题列表（空列表表示通过）。

    参数：
      - labels：错误标签记录，含 error_label / definition / related_dimension / status；
      - error_counts：错误类型 → 出现次数（来自错误标注，仅统计有效样本）；
      - actions：补强动作记录，含 related_error_label / status；
      - rubric_dimensions：合法的 评分标准维度名称集合；
      - high_freq_threshold：高频阈值，缺省时由 error_counts 动态推导。
    """
    active_labels = _active(labels)
    active_actions = _active(actions)
    dimension_names = {_clean(name) for name in rubric_dimensions if _clean(name)}
    label_names = {_clean(row.get("error_label")) for row in active_labels if _clean(row.get("error_label"))}

    issues: list[ConfigIssue] = []

    # 1) 无效错误标签：缺定义 / 影响维度越界 / 标注引用未登记标签。
    for row in active_labels:
        name = _clean(row.get("error_label"))
        if not name:
            continue
        if not _clean(row.get("definition")):
            issues.append(ConfigIssue(INVALID_LABEL, SEVERITY_ERROR, name, f"错误标签「{name}」缺少定义。"))
        dimension = _clean(row.get("related_dimension"))
        if dimension and dimension_names and dimension not in dimension_names:
            issues.append(
                ConfigIssue(
                    INVALID_LABEL, SEVERITY_ERROR, name,
                    f"错误标签「{name}」的关联维度「{dimension}」不在评分标准维度范围内。",
                )
            )

    for used_label in (_clean(name) for name in error_counts.keys()):
        if used_label and used_label not in label_names:
            issues.append(
                ConfigIssue(
                    INVALID_LABEL, SEVERITY_ERROR, used_label,
                    f"错误标注引用了未登记的标签「{used_label}」。",
                )
            )

    # 2) 没有关联补强动作的高频错误。
    threshold = high_freq_threshold if high_freq_threshold is not None else high_frequency_threshold(error_counts)
    linked = {_clean(row.get("related_error_label")) for row in active_actions}
    for label, count in error_counts.items():
        name = _clean(label)
        if not name or count is None:
            continue
        if int(count) >= threshold and name not in linked:
            issues.append(
                ConfigIssue(
                    HIGH_FREQ_WITHOUT_ACTION, SEVERITY_WARNING, name,
                    f"高频错误「{name}」（{int(count)} 次，阈值 {threshold}）尚无关联的数据补强动作。",
                )
            )

    # 3) related_error_label 不存在的补强动作。
    for row in active_actions:
        related = _clean(row.get("related_error_label"))
        action_id = _clean(row.get("action_id")) or _clean(row.get("id")) or "（未编号）"
        if not related:
            issues.append(
                ConfigIssue(ORPHAN_ACTION, SEVERITY_ERROR, action_id, f"补强动作 {action_id} 未关联任何错误标签。")
            )
        elif related not in label_names:
            issues.append(
                ConfigIssue(
                    ORPHAN_ACTION, SEVERITY_ERROR, action_id,
                    f"补强动作 {action_id} 关联的错误标签「{related}」不存在。",
                )
            )

    return issues
