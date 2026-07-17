"""SQLAlchemy schema for durable runtime evaluation results."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    text,
)

metadata = MetaData()


live_evaluation_runs = Table(
    "live_evaluation_runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("provider", String, nullable=False),
    Column("model_ids_json", Text, nullable=False, server_default=text("'[]'")),
    Column("generation_parameters_json", Text, nullable=False, server_default=text("'{}'")),
    Column("judge_parameters_json", Text, nullable=False, server_default=text("'{}'")),
    Column("dataset_version", String),
    Column("dataset_hash", String(64), nullable=False),
    Column("prompt_hash", String(64), nullable=False),
    Column("status", String, nullable=False, server_default=text("'queued'")),
    Column("completed_count", Integer, nullable=False, server_default=text("0")),
    Column("failed_count", Integer, nullable=False, server_default=text("0")),
    Column("pending_count", Integer, nullable=False, server_default=text("0")),
    Column("last_persistence_error", Text),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)


live_run_responses = Table(
    "live_run_responses",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, nullable=False),
    Column("case_id", String, nullable=False),
    Column("task_type", String),
    Column("provider", String),
    Column("model_name", String, nullable=False),
    Column("run_mode", String),
    Column("run_status", String),
    Column("answer_text", Text),
    Column("answer_length", Integer),
    Column("latency_ms", Integer),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("total_tokens", Integer),
    Column("http_status", Integer),
    Column("trace_id", String),
    Column("finish_reason", String),
    Column("incomplete_reason", Text),
    Column("retry_count", Integer),
    Column("first_finish_reason", String),
    Column("final_finish_reason", String),
    Column("timeout_seconds", Float),
    Column("timeout_source", String),
    Column("error_code", String),
    Column("error_message", Text),
    Column("status", String, nullable=False, server_default=text("'active'")),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)
Index(
    "uq_live_response",
    live_run_responses.c.run_id,
    live_run_responses.c.case_id,
    live_run_responses.c.model_name,
    unique=True,
)


live_run_queue = Table(
    "live_run_queue",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, nullable=False),
    Column("case_id", String, nullable=False),
    Column("task_type", String),
    Column("model_id", String, nullable=False),
    Column("provider", String),
    Column("status", String, nullable=False, server_default=text("'queued'")),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("error_code", String),
    Column("error_message", Text),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)
Index(
    "uq_live_run_queue",
    live_run_queue.c.run_id,
    live_run_queue.c.case_id,
    live_run_queue.c.model_id,
    unique=True,
)


live_run_scores = Table(
    "live_run_scores",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("score_run_id", String, nullable=False),
    Column("run_id", String),
    Column("case_id", String, nullable=False),
    Column("task_type", String),
    Column("eval_model", String, nullable=False),
    Column("judge_provider", String),
    Column("judge_model", String),
    Column("judge_mode", String),
    Column("judge_status", String),
    Column("accuracy_score", Integer),
    Column("reasoning_score", Integer),
    Column("coverage_score", Integer),
    Column("evidence_score", Integer),
    Column("expression_score", Integer),
    Column("total_score", Integer),
    Column("rationale", Text),
    Column("review_note", Text),
    Column("review_status", String, nullable=False, server_default=text("'ai_final'")),
    Column("latency_ms", Integer),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("total_tokens", Integer),
    Column("trace_id", String),
    Column("error_code", String),
    Column("error_message", Text),
    Column("status", String, nullable=False, server_default=text("'active'")),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)
Index(
    "uq_live_score",
    live_run_scores.c.score_run_id,
    live_run_scores.c.case_id,
    live_run_scores.c.eval_model,
    unique=True,
)


live_score_queue = Table(
    "live_score_queue",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("score_run_id", String, nullable=False),
    Column("run_id", String),
    Column("case_id", String, nullable=False),
    Column("task_type", String),
    Column("eval_model", String, nullable=False),
    Column("judge_model", String),
    Column("judge_provider", String),
    Column("status", String, nullable=False, server_default=text("'queued'")),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("error_code", String),
    Column("error_message", Text),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)
Index(
    "uq_live_score_queue",
    live_score_queue.c.score_run_id,
    live_score_queue.c.case_id,
    live_score_queue.c.eval_model,
    unique=True,
)


RUNTIME_TABLES = {
    table.name: table
    for table in (
        live_evaluation_runs,
        live_run_responses,
        live_run_queue,
        live_run_scores,
        live_score_queue,
    )
}
