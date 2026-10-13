"""Structured checkpoints and exact quotations; semantic truth remains judge-dependent."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal

STATUSES = {"met": "满足", "partial": "部分满足", "not_met": "未满足", "unknown": "无法判断"}
ERROR_TYPES = {"none", "omission", "calculation", "professional", "unsupported", "contradiction", "uncertain"}


def checkpoints(gold: Mapping) -> list[dict]:
    points = []
    for key, kind in (("must_have_points", "must"), ("unacceptable_errors", "forbidden")):
        values = gold.get(key) or []
        if isinstance(values, str):
            values = [values]
        for index, value in enumerate(values, 1):
            points.append({"point_id": f"{kind}:{index}", "kind": kind, "requirement": str(value)})
    return points


def validate_checks(raw: object, gold: Mapping, answer: str, dimensions: Sequence[Mapping]) -> list[dict]:
    expected = {p["point_id"]: p for p in checkpoints(gold)}
    if raw is None and not expected:
        return []
    if not isinstance(raw, list):
        raise ValueError("缺少结构化 checks 要点评价。")
    fields = {d["field"] for d in dimensions}
    seen = set()
    validated = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("评价要点结构错误。")
        identifier = item.get("point_id")
        if not isinstance(identifier, str) or identifier not in expected or identifier in seen:
            raise ValueError("评价要点缺失、重复或不属于本题。")
        seen.add(identifier)
        status, quote = item.get("status"), item.get("quote")
        if not isinstance(status, str) or status not in STATUSES or not isinstance(quote, str):
            raise ValueError("评价状态或引文格式错误。")
        error_type, dimension, reason = item.get("error_type"), item.get("dimension"), item.get("reason")
        if (
            not isinstance(error_type, str)
            or error_type not in ERROR_TYPES
            or not isinstance(dimension, str)
            or dimension not in fields
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError("评价缺少错误类型、对应维度或评分依据。")
        if quote and quote not in answer:
            raise ValueError(f"{identifier} 引文不在被测回答原文中。")
        if status in {"met", "partial"} and not quote.strip():
            raise ValueError(f"{identifier} 满足或部分满足必须引用回答原文。")
        # A professional-error assertion needs an actual offending quote.
        if expected[identifier]["kind"] == "forbidden" and status == "not_met" and not quote.strip():
            raise ValueError(f"{identifier} 专业错误判断缺少引文。")
        validated.append(
            {
                **expected[identifier],
                "status": status,
                "quote": quote,
                "error_type": error_type,
                "dimension": dimension,
                "reason": reason,
                "quote_verified": bool(quote.strip()),
            }
        )
    if seen != set(expected):
        raise ValueError("评价要点未覆盖所有必须覆盖点和不可接受错误。")
    return validated


_CONTEXT_HASHES = {
    "FD-001": "d315768cc7cf89b43e84e4787a345c81d34fbc166a2a7c35a0a525bdfb2e6111",
    "FD-002": "7dcb58e7e4c9300451457446e04f1af5ba2cfab32e8eebb47403fc9a898105da",
    "CM-001": "0c8f1dc8d259c63d9789fb82a6e3985ee928e99c38978b172914a9a6f3f1c19e",
}

# Fixed, reviewable arithmetic scoped to the original material hash; no eval(), no generated formula.
_RULES = {
    "FD-001": [
        (
            "收入增长率",
            "(12000-8000)/8000*100",
            (Decimal(12000) - 8000) / 8000 * 100,
            r"(?:收入)(?:同比)?(?:增长|增速)[^，；。%]{0,12}?(-?[\d,.]+)\s*[%％]",
        ),
        (
            "应收增长率",
            "(5400-2000)/2000*100",
            (Decimal(5400) - 2000) / 2000 * 100,
            r"应收(?:账款)?(?:同比)?(?:增长|增速)[^，；。%]{0,12}?(-?[\d,.]+)\s*[%％]",
        ),
        (
            "应收占收入比例",
            "5400/12000*100",
            Decimal(5400) / 12000 * 100,
            r"应收(?:账款)?占(?:收入|营业收入)(?:比例)?[^，；。%]{0,12}?(-?[\d,.]+)\s*[%％]",
        ),
        (
            "期后回款比例",
            "2400/5400*100",
            Decimal(2400) / 5400 * 100,
            r"期后回款(?:比例|率)?[^，；。%]{0,12}?(-?[\d,.]+)\s*[%％]",
        ),
    ],
    "FD-002": [
        ("P1应计提", "650-180", Decimal(650) - 180, r"P1[^，；。]{0,16}?计提\s*(-?[\d,.]+)\s*万元"),
        ("库存商品应计提", "800-720", Decimal(800) - 720, r"库存商品[^，；。]{0,16}?计提\s*(-?[\d,.]+)\s*万元"),
        (
            "合计应计提",
            "(650-180)+(800-720)",
            Decimal(650) - 180 + 800 - 720,
            r"(?:合计|总计)[^，；。]{0,10}?计提\s*(-?[\d,.]+)\s*万元",
        ),
        (
            "计提缺口",
            "(650-180)+(800-720)-320",
            Decimal(650) - 180 + 800 - 720 - 320,
            r"(?:计提不足|缺口)[^，；。]{0,8}?(-?[\d,.]+)\s*万元",
        ),
    ],
    "CM-001": [
        (
            "资产比例",
            "52000/100000*100",
            Decimal(52000) / 100000 * 100,
            r"(?:资产总额|总资产)(?:比例)?[^，；。%]{0,12}?(-?[\d,.]+)\s*[%％]",
        ),
        (
            "净资产比例",
            "52000/40000*100",
            Decimal(52000) / 40000 * 100,
            r"净资产(?:比例)?[^，；。%]{0,12}?(-?[\d,.]+)\s*[%％]",
        ),
        (
            "收入比例",
            "42000/80000*100",
            Decimal(42000) / 80000 * 100,
            r"(?:营业收入|收入)(?:比例)?[^，；。%]{0,12}?(-?[\d,.]+)\s*[%％]",
        ),
    ],
}


def numeric_checks(task: Mapping, answer: str) -> list[dict]:
    case = str(task.get("case_id") or "")
    if case not in _RULES:
        return []
    context_hash = hashlib.sha256(str(task.get("context") or "").encode()).hexdigest()
    if context_hash != _CONTEXT_HASHES[case]:
        return [{"status": "not_applicable", "reason": "题目材料已变化；固定公式未应用。"}]
    results = []
    for label, formula, expected, pattern in _RULES[case]:
        matches = list(re.finditer(pattern, answer))
        status, observed, quote = "unknown", None, ""
        if len(matches) == 1:
            quote = matches[0].group(0)
            try:
                observed = Decimal(matches[0].group(1).replace(",", ""))
                status = "match" if abs(observed - expected) <= Decimal("0.1") else "mismatch"
            except ArithmeticError:
                pass
        results.append(
            {
                "metric": label,
                "formula": formula,
                "expected": float(expected),
                "observed": float(observed) if observed is not None else None,
                "status": status,
                "quote": quote,
                "reason": "仅核查明确标注的数值；未表达或存在歧义时无法判断。",
            }
        )
    return results
