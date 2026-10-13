"""Attempt-level usage and dated, explicitly configured API cost estimates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation


def validate_prices(prices):
    if not isinstance(prices, list):
        raise ValueError("价格配置必须是JSON数组。")
    valid = []
    for raw in prices:
        if not isinstance(raw, dict) or any(
            not raw.get(k) for k in ("provider", "model_id", "currency", "source", "effective_from", "effective_until")
        ):
            raise ValueError("每条价格必须包含服务商、适用模型、币种、来源及生效/失效日期。")
        try:
            start, end = date.fromisoformat(raw["effective_from"]), date.fromisoformat(raw["effective_until"])
            rates = [Decimal(str(raw[k])) for k in ("input_per_million", "output_per_million")]
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            raise ValueError("价格日期或Token单价格式错误。") from exc
        if start >= end or any(not r.is_finite() or r < 0 for r in rates):
            raise ValueError("价格区间或单价不合法。")
        for previous in valid:
            if (previous["provider"], previous["model_id"]) == (raw["provider"], raw["model_id"]) and max(
                previous["effective_from"], raw["effective_from"]
            ) < min(previous["effective_until"], raw["effective_until"]):
                raise ValueError("同服务商模型的价格区间重叠。")
        valid.append(dict(raw))
    return valid


def attempt_metrics(attempts):
    groups = {}
    for row in attempts:
        phase = row["phase"]
        group = groups.setdefault(
            phase,
            dict(
                attempts=0,
                success=0,
                failed=0,
                interrupted=0,
                timeouts=0,
                latency_ms=0,
                latency_unknown=0,
                input_tokens=0,
                output_tokens=0,
                usage_unknown=0,
            ),
        )
        group["attempts"] += 1
        group["success"] += row.get("status") == "success"
        group["failed"] += row.get("status") == "failed"
        group["interrupted"] += row.get("status") not in {"success", "failed"}
        group["timeouts"] += row.get("error_code") in {"timeout", "gateway_timeout"}
        if row.get("latency_ms") is None:
            group["latency_unknown"] += 1
        else:
            group["latency_ms"] += row["latency_ms"]
        if row.get("input_tokens") is None or row.get("output_tokens") is None:
            group["usage_unknown"] += 1
        for field_name in ("input_tokens", "output_tokens"):
            value = row.get(field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                group[field_name] = None
            elif group[field_name] is not None:
                group[field_name] += value
    return groups


def cost_summary(attempts, prices, *, expected, passed_tasks=0):
    prices = validate_prices(prices)
    totals = {}
    currencies = set()
    unknown_usage = missing_prices = 0
    seen = {}
    for row in attempts:
        key = tuple(row.get(k) for k in ("run_id", "case_id", "eval_model", "phase"))
        seen[key] = seen.get(key, 0) + 1
        phase = row["phase"]
        group = totals.setdefault(
            phase,
            dict(
                attempt_count=0,
                input_tokens=0,
                output_tokens=0,
                known_subtotal=Decimal(0),
                estimated_cost=None,
                complete=True,
                currency=None,
                currency_subtotals={},
            ),
        )
        group["attempt_count"] += 1
        usage = [row.get(k) for k in ("input_tokens", "output_tokens")]
        usage_known = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in usage)
        if not usage_known:
            unknown_usage += 1
            group["complete"] = False
        for key, value in zip(("input_tokens", "output_tokens"), usage):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                group[key] = None
            elif group[key] is not None:
                group[key] += value
        try:
            requested = date.fromisoformat(row["requested_at"][:10])
        except (ValueError, KeyError, TypeError):
            requested = None
        rule = next(
            (
                p
                for p in prices
                if p["provider"] == row.get("provider")
                and p["model_id"] == row.get("model_id")
                and requested
                and date.fromisoformat(p["effective_from"]) <= requested < date.fromisoformat(p["effective_until"])
            ),
            None,
        )
        if rule is None:
            missing_prices += 1
            group["complete"] = False
        else:
            currencies.add(rule["currency"])
            if group["currency"] and group["currency"] != rule["currency"]:
                group["complete"] = False
            group["currency"] = rule["currency"]
            if usage_known:
                subtotal = (
                    usage[0] * Decimal(str(rule["input_per_million"]))
                    + usage[1] * Decimal(str(rule["output_per_million"]))
                ) / 1000000
                group["currency_subtotals"][rule["currency"]] = (
                    group["currency_subtotals"].get(rule["currency"], Decimal(0)) + subtotal
                )
                group["known_subtotal"] += subtotal
        if row.get("status") not in {"success", "failed"}:
            group["complete"] = False
    missing_attempt_groups = 0
    for item in expected:
        key = tuple(item.get(k) for k in ("run_id", "case_id", "eval_model", "phase"))
        if seen.get(key, 0) < item["minimum_attempts"]:
            missing_attempt_groups += 1
            totals.setdefault(
                item["phase"],
                dict(
                    attempt_count=0,
                    input_tokens=0,
                    output_tokens=0,
                    known_subtotal=Decimal(0),
                    estimated_cost=None,
                    complete=False,
                    currency=None,
                ),
            )["complete"] = False
    complete = (
        bool(attempts)
        and not missing_attempt_groups
        and len(currencies) == 1
        and all(g["complete"] for g in totals.values())
    )
    for group in totals.values():
        subtotals = group.get("currency_subtotals", {})
        group["currency_subtotals"] = {k: float(v) for k, v in subtotals.items()}
        group["known_subtotal"] = float(group["known_subtotal"]) if len(subtotals) <= 1 else None
        group["estimated_cost"] = group["known_subtotal"] if group["complete"] and len(currencies) == 1 else None
    return dict(
        phases=totals,
        complete=complete,
        unknown_usage=unknown_usage,
        missing_prices=missing_prices,
        missing_attempt_groups=missing_attempt_groups,
        currencies=sorted(currencies),
        cost_per_passed_task=sum(g["known_subtotal"] for g in totals.values()) / passed_tasks
        if complete and passed_tasks > 0
        else None,
    )


def expected_attempts(tables):
    expected = []
    for row in tables.get("live_run_responses", []):
        expected.append(
            dict(
                run_id=row["run_id"],
                case_id=row["case_id"],
                eval_model=row["model_name"],
                phase="answer",
                minimum_attempts=1 + int(row.get("retry_count") or 0),
            )
        )
    for row in tables.get("live_run_scores", []):
        import json

        try:
            raw = json.loads(row.get("raw_responses_json") or "[]")
            count = len(raw) if isinstance(raw, list) else 0
        except (ValueError, TypeError):
            count = 0
        expected.append(
            dict(
                run_id=row["run_id"],
                case_id=row["case_id"],
                eval_model=row["eval_model"],
                phase="judge",
                minimum_attempts=max(1, count),
            )
        )
    keyed = {(r["run_id"], r["case_id"], r["eval_model"], r["phase"]): r for r in expected}
    for table, phase, model_field in [
        ("live_run_queue", "answer", "model_id"),
        ("live_score_queue", "judge", "eval_model"),
    ]:
        for row in tables.get(table, []):
            if phase == "judge" and row.get("status") == "skipped":
                continue
            key = (row["run_id"], row["case_id"], row[model_field], phase)
            keyed.setdefault(
                key,
                dict(
                    run_id=row["run_id"],
                    case_id=row["case_id"],
                    eval_model=row[model_field],
                    phase=phase,
                    minimum_attempts=1,
                ),
            )
    return list(keyed.values())
