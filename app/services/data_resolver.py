"""运行时数据源解析（从 eval_console 拆出）。

把「base 数据 + 会话中的 live run / score」组装为各分析页可用的 EvaluationData，
并生成全局数据上下文提示信息。本模块不依赖 Streamlit 渲染上下文之外的 UI。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services import dataset_service as ds
from app.services import eval_state
from app.services import scorer as sc
from app.services.live_results import (
    build_live_evaluation_data,
    empty_results_evaluation_data,
)


def resolve_active_data(base) -> tuple[Any, dict[str, Any]]:
    """根据会话中的运行 / 评分结果，返回 (EvaluationData, eval_status)。

    有运行结果则用真实回答 + 裁判成功评分组装 EvaluationData；否则返回结果类全空的对象，
    分析页走空状态。eval_status 提供给页面做「建议分 / 待复核」提示。
    """
    run = eval_state.get_last_run()
    if run is None:
        return empty_results_evaluation_data(base), {
            "live": False,
            "scored": 0,
            "confirmed": 0,
            "pending": 0,
            "run_id": None,
            "score_run_id": None,
        }

    score_result = eval_state.get_last_score()
    score_rows = _collect_score_rows(score_result)
    data = build_live_evaluation_data(base, run, score_rows)
    success_rows = [r for r in score_rows if str(r.get("judge_status")) == "success"]
    confirmed = sum(1 for r in success_rows if str(r.get("review_status")) == "confirmed")
    status = {
        "live": True,
        "scored": len(success_rows),
        "confirmed": confirmed,
        "pending": len(success_rows) - confirmed,
        "run_id": getattr(run, "run_id", None),
        "score_run_id": getattr(score_result, "score_run_id", None),
    }
    return data, status


def _collect_score_rows(score_result) -> list[dict]:
    """优先取已落库行（反映人工复核值），数据库不可用时回退会话内 ScoreOutcome。"""
    if score_result is None:
        return []
    try:
        if ds.database_ready():
            rows = sc.load_score_rows(score_result.score_run_id)
            if rows:
                return rows
    except Exception:
        pass
    rows: list[dict] = []
    for outcome in getattr(score_result, "outcomes", []):
        record = {
            "case_id": outcome.case_id,
            "eval_model": outcome.eval_model,
            "judge_status": outcome.judge_status,
            "total_score": outcome.total_score,
            "review_note": outcome.review_note,
            "review_status": outcome.review_status,
        }
        for key, value in (outcome.scores or {}).items():
            record[key] = value
        rows.append(record)
    return rows


def build_data_context_info(base, eval_status: Mapping[str, Any] | None) -> dict[str, str]:
    """生成供全局提示条展示的当前数据上下文。

    返回字典包含：
      - data_source: SQLite / seed
      - task_count: 当前可用任务数
      - run_id: 当前会话运行 ID（如有）
      - score_status: 评分 / 复核状态摘要
    """
    eval_status = eval_status or {}
    task_count = len(getattr(base, "tasks", []))

    if ds.database_ready():
        data_source = "SQLite 运行时数据"
    else:
        data_source = "data/ seed 文件"

    run_id = eval_status.get("run_id")
    if run_id:
        scored = int(eval_status.get("scored", 0) or 0)
        confirmed = int(eval_status.get("confirmed", 0) or 0)
        pending = int(eval_status.get("pending", 0) or 0)
        if pending > 0:
            score_status = f"评分 {scored} 条 · 待复核 {pending}"
        else:
            score_status = f"评分 {scored} 条 · 已复核 {confirmed}"
    else:
        score_status = "未运行评测"

    return {
        "data_source": data_source,
        "task_count": f"{task_count} 道任务",
        "run_id": str(run_id) if run_id else "—",
        "score_status": score_status,
    }
