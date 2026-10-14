"""Short stage-specific messages; safe diagnostics stay separate from user copy."""

from __future__ import annotations

import json

from app.services.model_display import display_model_name


def failure_label(row, *, phase="judge"):
    code = str(row.get("error_code") or "")
    stage = "AI评分" if phase == "judge" else "模型回答"
    labels = {
        "timeout": "超时",
        "gateway_timeout": "网关超时",
        "rate_limited": "服务限流",
        "unauthorized": "服务鉴权失败",
        "bad_request": "请求配置不兼容",
        "not_found": "模型不可用",
        "judge_parse_error": "格式校验失败",
        "incomplete_response": "输出不完整",
        "invalid_response": "响应格式错误",
        "connection_error": "连接失败",
        "service_unavailable": "服务暂不可用",
    }
    return stage + labels.get(code, "未完成")


def pair_rows(answers, scores, queues=()):
    answers=list(answers)
    existing={(r.get('case_id'),r.get('model_name')) for r in answers}
    for queue in queues:
        if (queue.get('case_id'),queue.get('model_id')) not in existing:
            answers.append(dict(case_id=queue.get('case_id'),model_name=queue.get('model_id'),
                                run_status=queue.get('status'),error_code=queue.get('error_code'),_missing_body=True))
    rows = []
    for answer in answers:
        matches = [
            s
            for s in scores
            if (s.get("case_id"), s.get("eval_model")) == (answer.get("case_id"), answer.get("model_name"))
        ]
        successful = [s for s in matches if s.get("judge_status") == "success"]
        score = max(successful or matches, key=lambda s: str(s.get("created_at") or ""), default=None)
        ok = answer.get("run_status") == "success" and not answer.get('_missing_body')
        state = (
            "成功"
            if score and score.get("judge_status") == "success"
            else failure_label(score)
            if score
            else ("等待评分" if ok else "未开始")
        )
        rows.append(
            {
                "样本": answer.get("case_id"),
                "模型": display_model_name(str(answer.get("model_name")), source="live"),
                "回答状态": "已保存" if ok else '正文未保存' if answer.get('_missing_body') and answer.get('run_status')=='success' else '等待生成' if answer.get('run_status') in {'queued','running'} else failure_label(answer, phase="answer"),
                "评分状态": state,
                "主要问题": ("模型回答已生成，但" + state + "。")
                if score and score.get("judge_status") == "failed" and ok
                else "",
                "_score": score,
            }
        )
    return rows


def safe_attempt_details(attempts):
    rows = []
    for attempt in attempts:
        try:
            details = json.loads(attempt.get("diagnostics_json") or "{}")
        except (TypeError, ValueError):
            details = {}
        rows.append(
            {
                k: attempt.get(k)
                for k in (
                    "phase",
                    "model_id",
                    "attempt_index",
                    "status",
                    "error_code",
                    "latency_ms",
                    "service_endpoint",
                )
            }
            | {
                k: details.get(k, "未记录")
                for k in ("timeout_seconds", "timeout_source", "input_chars", "http_status", "trace_id", "error_stage")
            }
        )
    return rows
