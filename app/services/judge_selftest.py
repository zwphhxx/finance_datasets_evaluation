"""Explicitly triggered nine-call judge check, completely outside formal evaluation storage."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.services.scorer import score_single


def load_cases() -> list[dict]:
    return json.loads(Path(__file__).with_name("judge_selftest_cases.json").read_text())


def assess(case, outcomes) -> dict:
    reasons = []
    if any(not o.ok for o in outcomes.values()):
        reasons.append("存在评分失败，不能完成可靠性比较。")
    if any(o.evidence_status != "verified_quotes" for o in outcomes.values()):
        reasons.append("评分引文未通过原文校验。")
    correct, bad, concise = (outcomes[k] for k in ("correct", "major_error", "concise"))
    detected = any(
        c.get("point_id") == case["fault_point"]
        and c.get("status") == "not_met"
        and c.get("error_type") in {"professional", "calculation", "contradiction"}
        and c.get("quote_verified")
        and case["fault_quote"] in c.get("quote", "")
        for c in bad.checks
    )
    if not detected:
        reasons.append("未识别预设重大专业错误或未引用对应原文。")
    if all(o.ok and o.total_score is not None for o in outcomes.values()):
        if correct.total_score - bad.total_score < 10 or correct.scores.get("accuracy_score", 0) <= bad.scores.get(
            "accuracy_score", 0
        ):
            reasons.append("重大错误扣分不足：总分差需至少10分且专业准确性需降低。")
        if correct.total_score - concise.total_score > 10:
            reasons.append("简短正确回答低于完整回答超过10分，可能存在篇幅偏好，需复核评分依据。")
        if bad.total_score >= concise.total_score:
            reasons.append("错误回答未低于简短正确回答。")
    return {
        "case_id": case["case_id"],
        "passed": not reasons,
        "error_detected": detected,
        "reasons": reasons,
        "outcomes": {k: asdict(o) for k, o in outcomes.items()},
    }


def run_selftest(provider, judge_model, dimensions, *, max_calls=9, max_tokens=3072) -> dict:
    if max_calls != 9 or getattr(provider, "name", "") in {"mock", "demo"}:
        raise ValueError("裁判自测必须显式授权9次请求并配置真实服务；禁止自动调用。")
    results = []
    for case in load_cases():
        outcomes = {
            kind: score_single(
                provider,
                judge_model,
                case["task"],
                answer,
                case["gold"],
                dimensions,
                eval_model="synthetic_judge_selftest",
                retry_delays=(),
                max_tokens=max_tokens,
            )
            for kind, answer in case["answers"].items()
        }
        results.append(assess(case, outcomes))
    return {
        "export_type": "judge_selftest",
        "schema_version": 1,
        "data_kind": "synthetic_judge_selftest",
        "created_at": datetime.now(UTC).isoformat(),
        "provider": provider.name,
        "judge_model": judge_model,
        "max_calls": 9,
        "max_tokens": max_tokens,
        "results": results,
        "boundary": "仅3个任务、9个固定人工回答；通过不代表评分体系全面可靠。分差阈值是观察规则，不是精确预设得分。",
    }
