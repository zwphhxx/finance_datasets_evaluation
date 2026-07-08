"""Gold Answer 结构化字段与质量治理（Gold Answer quality governance）。

集中定义 Gold Answer 的结构化字段、字段别名与质量评估逻辑，供样板题页、数据集
质量页与校验脚本共用，避免各处分别判断造成口径漂移。

质量状态由字段完整度动态推导，不存储固定结论，也不编造依据：无法确认的内容应在
数据中写成「需进一步核验」「待补充依据」，而非伪造法规、公告或财务数据。
"""

from __future__ import annotations

from typing import Any

# 规范字段名 → 接受的数据键（含历史别名），按出现顺序取第一个存在且非空的值。
# 历史别名用于兼容早期 gold_answers.json 与既有测试，迁移后仍可被正确解析。
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "core_conclusion": ("core_conclusion", "conclusion"),
    "key_evidence": ("key_evidence", "basis"),
    "boundary_conditions": ("boundary_conditions", "risk_boundary"),
    "must_have_points": ("must_have_points",),
    "unacceptable_errors": ("unacceptable_errors", "red_line_errors"),
    "manual_review_notes": ("manual_review_notes",),
}

# 参与完整性评估的结构化字段 → 中文标签。must_have_points 视为评分支撑要素。
QUALITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("core_conclusion", "核心结论"),
    ("key_evidence", "关键依据"),
    ("boundary_conditions", "边界条件"),
    ("unacceptable_errors", "不可接受错误"),
    ("must_have_points", "必须覆盖点"),
)

STATUS_USABLE = "满足评测使用条件"
STATUS_PARTIAL = "部分满足评测使用条件"

_EMPTY_TOKENS = {"", "nan", "none", "null"}


def _is_present(value: Any) -> bool:
    """是否为有效值。空字符串、占位 nan/none/空列表均视为缺失。"""
    if value is None:
        return False
    if isinstance(value, dict):
        return len(value) > 0
    if isinstance(value, (list, tuple, set)):
        return any(_is_present(item) for item in value)
    return str(value).strip().lower() not in _EMPTY_TOKENS


def field_value(gold: Any, canonical: str) -> Any:
    """按规范字段名解析存储值，兼容历史别名；缺失返回 None。"""
    if not isinstance(gold, dict):
        return None
    for key in FIELD_ALIASES.get(canonical, (canonical,)):
        if key in gold and _is_present(gold[key]):
            return gold[key]
    return None


def field_text(gold: Any, canonical: str, fallback: str = "") -> str:
    """解析为单段文本，列表以分号连接。"""
    value = field_value(gold, canonical)
    if value is None:
        return fallback
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "；".join(parts) if parts else fallback
    return str(value).strip() or fallback


def field_list(gold: Any, canonical: str) -> list[str]:
    """解析为字符串列表，单值包装为单元素列表。"""
    value = field_value(gold, canonical)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def evaluate_gold_quality(gold: Any) -> dict:
    """评估单条 Gold Answer 的完整性，质量状态由字段完整度动态推导。

    返回字段：
      - field_status：各结构化要素是否具备（中文标签 → bool）；
      - present / missing：具备与缺失的要素标签；
      - is_usable：核心结构化要素是否齐备；
      - status：满足 / 部分满足评测使用条件；
      - manual_review：评审提示（无则为空串）。
    """
    field_status: dict[str, bool] = {}
    present: list[str] = []
    missing: list[str] = []
    for canonical, label in QUALITY_FIELDS:
        ok = field_value(gold, canonical) is not None
        field_status[label] = ok
        (present if ok else missing).append(label)

    is_usable = not missing
    return {
        "field_status": field_status,
        "present": present,
        "missing": missing,
        "is_usable": is_usable,
        "status": STATUS_USABLE if is_usable else STATUS_PARTIAL,
        "manual_review": field_text(gold, "manual_review_notes", ""),
    }
