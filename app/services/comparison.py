"""Quality comparison uses a shared denominator; operational failures stay visible."""

from __future__ import annotations

import pandas as pd

from app.services.formal_records import filter_formal_scores


def common_sample_comparison(scores: pd.DataFrame, models=None, *, minimum=3) -> dict:
    valid = filter_formal_scores(scores)
    if not valid.empty:
        valid = valid.drop_duplicates(["eval_model", "case_id"], keep="last")
    models = sorted(set(models if models is not None else valid.get("eval_model", [])))
    sets = [set(valid.loc[valid["eval_model"] == model, "case_id"]) if not valid.empty else set() for model in models]
    common = sorted(set.intersection(*sets)) if len(sets) >= 2 else []
    rows = []
    for model in models:
        group = valid[(valid["eval_model"] == model) & valid["case_id"].isin(common)] if not valid.empty else valid
        rows.append(
            {
                "model_id": model,
                "common_count": len(common),
                "avg_total": float(group["total_score"].mean()) if not group.empty else None,
            }
        )
    return {
        "common_count": len(common),
        "case_ids": common,
        "models": rows,
        "sufficient": len(common) >= minimum and len(models) >= 2,
        "reason": f"至少两个模型且共同有效样本不少于 {minimum} 条才能作有限比较；不能推出整体最佳模型。",
    }


def runtime_counts(queue, responses, scores) -> list[dict]:
    answers = {(r["run_id"], r["case_id"], r["model_name"]): r for r in responses}
    judged = {(r["run_id"], r["case_id"], r["eval_model"]): r for r in scores}
    groups = {}
    for row in queue:
        key = (row["run_id"], row["case_id"], row["model_id"])
        model = row["model_id"]
        group = groups.setdefault(
            model,
            dict(
                model_id=model,
                planned=0,
                answer_success=0,
                answer_failed=0,
                judge_success=0,
                judge_failed=0,
                unfinished=0,
                answer_timeout=0,
                judge_timeout=0,
            ),
        )
        group["planned"] += 1
        answer = answers.get(key, {})
        score = judged.get(key, {})
        astatus, jstatus = answer.get("run_status"), score.get("judge_status")
        group["answer_success"] += astatus == "success"
        group["answer_failed"] += astatus == "failed"
        group["judge_success"] += astatus == "success" and jstatus == "success"
        group["judge_failed"] += astatus == "success" and jstatus == "failed"
        group["unfinished"] += astatus not in {"success", "failed"} or (
            astatus == "success" and jstatus not in {"success", "failed"}
        )
        group["answer_timeout"] += answer.get("error_code") == "timeout"
        group["judge_timeout"] += score.get("error_code") == "timeout"
    for row in groups.values():
        row["answer_success_rate"] = row["answer_success"] / row["planned"] if row["planned"] else None
        judged_count = row["judge_success"] + row["judge_failed"]
        row["judge_success_rate"] = row["judge_success"] / judged_count if judged_count else None
    return list(groups.values())


def comparison_for_runs(scores, runs):
    metadata = {r["run_id"]: r for r in runs}
    units = set()
    model_names = set()
    frame = scores.copy()
    labels = []
    for row in scores.to_dict("records"):
        run = metadata.get(row["run_id"], {})
        model = row["eval_model"]
        provider = run.get("provider") or "服务商未知"
        endpoint = run.get("service_endpoint") or "端点未记录"
        label = f"{model} | {provider} | {endpoint}"
        labels.append(label)
        units.add(label)
        model_names.add(model)
    if not frame.empty:
        frame["eval_model"] = labels
    for run in runs:
        import json

        for model in json.loads(run.get("model_ids_json") or "[]"):
            units.add(
                f"{model} | {run.get('provider') or '服务商未知'} | {run.get('service_endpoint') or '端点未记录'}"
            )
            model_names.add(model)
    result = common_sample_comparison(frame, units)
    result["kind"] = "service_endpoint" if len(model_names) == 1 and len(units) > 1 else "model"
    return result
