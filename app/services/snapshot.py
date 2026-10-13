"""Portable, read-only runtime evidence. Loading never calls a provider or writes a DB."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pandas as pd

from app.persistence.schema import RUNTIME_TABLES
from app.services.formal_records import filter_formal_responses
from app.services.score_evidence import validate_checks
from src.metrics import SCORE_DIMENSION_FULL_MARKS

EXPORT_TYPE = "evaluation_snapshot"
MAX_BYTES = 20 * 1024 * 1024
SECRET_KEYS = {"api_key", "apikey", "authorization", "headers", "password", "token", "access_token", "database_url"}
_TEXT_SENSITIVE = re.compile(
    r'sk-[A-Za-z0-9_-]{12,}|Bearer\s+[^\s"\\]+|(?:/Users/|/home/|[A-Za-z]:\\Users\\)[^\s"，；。]+', re.I
)


def _safe(value, *, reject=False):
    if isinstance(value, dict):
        if reject and any(str(k).lower() in SECRET_KEYS for k in value):
            raise ValueError("快照含敏感配置字段。")
        return {k: _safe(v, reject=reject) for k, v in value.items() if str(k).lower() not in SECRET_KEYS}
    if isinstance(value, list):
        return [_safe(v, reject=reject) for v in value]
    if isinstance(value, str):
        if reject and _TEXT_SENSITIVE.search(value):
            raise ValueError("快照含密钥或内部路径。请先脱敏。")
        # JSON-encoded columns also need structural secret filtering.
        if value.strip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
                safe = _safe(parsed, reject=reject)
                return value if safe == parsed else json.dumps(safe, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        return _TEXT_SENSITIVE.sub("[已脱敏]", value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def export_snapshot(store) -> dict:
    tables = {}
    for name, table in RUNTIME_TABLES.items():
        tables[name] = [{k: v for k, v in r.items() if k in table.c} for r in store.list_rows(name)]
    # Export full live runs, including failed/pending records; never promote mock runs.
    run_ids = {r["run_id"] for r in tables["live_evaluation_runs"] if r.get("provider") not in {"mock", "demo"}}
    for name in tables:
        tables[name] = [r for r in tables[name] if r.get("run_id") in run_ids]
    safe_tables = _safe(tables)
    return {
        "export_type": EXPORT_TYPE,
        "schema_version": 1,
        "provenance": {
            "source": "runtime_database_export",
            "exported_at": datetime.now(UTC).isoformat(),
            "redacted": safe_tables != tables,
            "authenticity": "上传文件声明的来源无法由程序独立认证；哈希及结构校验不证明运行真实性。",
        },
        "tables": safe_tables,
    }


def _unique(rows, fields):
    keys = [tuple(str(r.get(k) or "") for k in fields) for r in rows]
    if any(not all(key) for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("记录身份缺失或重复。")


def load_snapshot(content: bytes | str) -> dict:
    if len(content) > MAX_BYTES:
        raise ValueError("快照超过20 MiB上限。")
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("快照不是有效 JSON。") from exc
    if not isinstance(payload, dict) or payload.get("export_type") != EXPORT_TYPE or payload.get("schema_version") != 1:
        raise ValueError("不是本项目完整评测快照；评分导出和裁判自测不可导入。")
    tables, provenance = payload.get("tables"), payload.get("provenance")
    if not isinstance(tables, dict) or set(tables) != set(RUNTIME_TABLES):
        raise ValueError("快照缺少运行、回答、评分、队列或请求记录。")
    if not isinstance(provenance, dict) or not provenance.get("source") or not provenance.get("exported_at"):
        raise ValueError("快照缺少来源或导出时间。")
    _safe(payload, reject=True)
    for name, rows in tables.items():
        if not isinstance(rows, list) or any(
            not isinstance(r, dict) or set(r) - set(RUNTIME_TABLES[name].c.keys()) for r in rows
        ):
            raise ValueError("快照字段不符合数据结构。")
    _unique(tables["live_evaluation_runs"], ["run_id"])
    for name, fields in [
        ("live_run_responses", ["run_id", "case_id", "model_name"]),
        ("live_run_scores", ["score_run_id", "case_id", "eval_model"]),
        ("live_run_queue", ["run_id", "case_id", "model_id"]),
        ("live_score_queue", ["score_run_id", "case_id", "eval_model"]),
        ("request_attempts", ["attempt_id"]),
    ]:
        _unique(tables[name], fields)
    runs = {r["run_id"]: r for r in tables["live_evaluation_runs"]}
    for row in runs.values():
        if not row.get("created_at") or not row.get("provider") or row["provider"] in {"mock", "demo"}:
            raise ValueError("运行记录缺少真实时间或服务商。")
        for key in (
            "dataset_version",
            "dataset_hash",
            "prompt_hash",
            "generation_parameters_json",
            "judge_parameters_json",
        ):
            if not row.get(key):
                raise ValueError("运行缺少版本或测试配置。")
        try:
            datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            model_ids = json.loads(row.get("model_ids_json") or "[]")
            if not isinstance(model_ids, list) or any(not isinstance(m, str) or not m for m in model_ids):
                raise ValueError("模型配置结构错误。")
            for key in ("generation_parameters_json", "judge_parameters_json"):
                if not isinstance(json.loads(row[key]), dict):
                    raise ValueError("调用参数必须是对象。")
            context = json.loads(row.get("evaluation_context_json") or "{}")
            if not isinstance(context, dict):
                raise ValueError("历史任务上下文必须是对象。")
            for key in ("samples", "gold", "dimensions"):
                records = context.get(key, [])
                if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
                    raise ValueError("历史任务或标准结构错误。")
            for sample in context.get("samples", []):
                if not sample.get("case_id") or not isinstance(sample.get("task"), dict):
                    raise ValueError("历史任务字段错误。")
            for gold in context.get("gold", []):
                if not gold.get("case_id") or not isinstance(gold.get("record"), dict):
                    raise ValueError("历史专业标准字段错误。")
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("运行时间、模型参数或历史上下文无法解析。") from exc
    for name, rows in tables.items():
        for row in rows:
            if row.get("run_id") not in runs:
                raise ValueError("记录缺少对应运行批次。")
            if any(
                str(row.get(k) or "").lower() in {"mock", "demo", "selftest", "synthetic"}
                for k in ("run_mode", "judge_mode", "provider", "judge_provider")
            ):
                raise ValueError("模拟或裁判自测数据不能作为正式历史快照。")
    answers = filter_formal_responses(pd.DataFrame(tables["live_run_responses"]))
    answer_map = {(r["run_id"], r["case_id"], r["model_name"]): r["answer_text"] for r in answers.to_dict("records")}
    for row in tables["live_run_scores"]:
        if row.get("judge_status") != "success":
            continue
        answer = answer_map.get((row.get("run_id"), row.get("case_id"), row.get("eval_model")))
        if answer is None:
            raise ValueError("成功评分缺少正式模型回答。")
        dimensions = [{"field": k, "full_mark": v} for k, v in SCORE_DIMENSION_FULL_MARKS.items()]
        for dim in dimensions:
            value = row.get(dim["field"])
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= dim["full_mark"]:
                raise ValueError("成功评分存在缺失或越界分数。")
        if sum(row[d["field"]] for d in dimensions) != row.get("total_score"):
            raise ValueError("总分与各维度不一致。")
        status = row.get("evidence_status") or "legacy_unverified"
        if status == "invalid":
            raise ValueError("无效评分证据不可作为成功评分。")
        if status == "verified_quotes":
            try:
                context = json.loads(runs[row["run_id"]].get("evaluation_context_json") or "{}")
                gold = next(r["record"] for r in context["gold"] if r["case_id"] == row["case_id"])
                checks = validate_checks(json.loads(row.get("checks_json") or "null"), gold, answer, dimensions)
                row["checks_json"] = json.dumps(checks, ensure_ascii=False)
            except (ValueError, TypeError, KeyError, StopIteration) as exc:
                raise ValueError("评分引文或运行时专业标准无法验证。") from exc
        row["evidence_status"] = status
    return payload


def restore_context(runs, case_ids):
    """Recover original materials only; never use current Gold for a historical run."""
    contexts = []
    for run in runs:
        try:
            value = json.loads(run.get("evaluation_context_json") or "{}")
            if isinstance(value, dict) and isinstance(value.get("samples"), list):
                contexts.append(value)
        except (ValueError, TypeError):
            pass
    context = contexts[-1] if contexts else {}
    tasks = {
        str(r["case_id"]): {**r["task"], "case_id": r["case_id"]}
        for r in context.get("samples", [])
        if isinstance(r, dict) and isinstance(r.get("task"), dict) and r.get("case_id")
    }
    for case in case_ids:
        tasks.setdefault(str(case), {"case_id": str(case), "question": "历史任务正文未保存"})
    gold = {
        str(r["case_id"]): r["record"]
        for r in context.get("gold", [])
        if isinstance(r, dict) and isinstance(r.get("record"), dict) and r.get("case_id")
    }
    return list(tasks.values()), gold, context.get("dimensions", [])
