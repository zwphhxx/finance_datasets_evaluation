import json
import sqlite3
from pathlib import Path

from app.models.base import GenerationResult
from app.persistence.result_store import ResultStore
from app.services import eval_runner as er
from app.services import scorer as sc
from app.services.run_checkpoint import build_run_metadata


def test_legacy_schema_is_migrated_without_changing_rows(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(Path("app/db/schema.sql").read_text())
        conn.execute(
            "INSERT INTO live_run_scores (id,score_run_id,run_id,case_id,eval_model) VALUES (1,'s','r','c','m')"
        )
    store = ResultStore(f"sqlite:///{path}")
    store.ensure_schema()
    store.ensure_schema()
    row = store.list_rows("live_run_scores")[0]
    assert row["run_id"] == "r"
    assert row["checks_json"] is None
    assert row["evidence_status"] is None


def test_metadata_retains_original_tasks_and_gold():
    result = build_run_metadata(
        run_id="r",
        provider="p",
        model_ids=["m"],
        queue_items=[{"case_id": "c", "task": {"question": "original"}}],
        generation_parameters={},
        judge_parameters={},
        dataset_version="v",
        prompt_payload=["system"],
        gold_map={"c": {"core_conclusion": "gold"}},
        dimensions=[],
    )
    context = json.loads(result["evaluation_context_json"])
    assert context["samples"][0]["task"]["question"] == "original"
    assert context["gold"][0]["record"]["core_conclusion"] == "gold"


class Provider:
    name = "fixture"

    def __init__(self):
        self.calls = 0

    def generate_response(self, model, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return GenerationResult(
                self.name,
                model,
                "failed",
                "partial",
                finish_reason="length",
                input_tokens=100,
                output_tokens=200,
                error_code="incomplete_response",
            )
        return GenerationResult(self.name, model, "success", "完整回答。", input_tokens=50, output_tokens=40)


def test_answer_retry_attempts_persist_immediately_and_keep_all_usage(tmp_path):
    store = ResultStore(f"sqlite:///{tmp_path / 'attempts.db'}")
    store.ensure_schema()
    observed = []

    def save(attempt):
        store.save_request_attempt({**attempt, "run_id": "r", "case_id": "c", "eval_model": "m"})
        observed.append(attempt)

    outcome = er.run_single(Provider(), "m", {"case_id": "c"}, attempt_callback=save)
    rows = store.list_rows("request_attempts", run_id="r")
    assert len(rows) == len(outcome.attempts) == 2
    assert [row["input_tokens"] for row in rows] == [100, 50]
    assert [row["attempt_index"] for row in rows] == [1, 2]
    assert all(row["requested_at"] and row["latency_ms"] is not None for row in rows)
    assert len(observed) == 4  # started + returned for every attempt


def test_judge_parse_failures_are_independent_attempts():
    class Judge:
        name = "fixture"

        def generate_response(self, model, messages, **kwargs):
            return GenerationResult(self.name, model, "success", "invalid", input_tokens=5)

    result = sc.score_single(
        Judge(),
        "judge",
        {"case_id": "c"},
        "answer",
        {},
        [{"field": "accuracy_score", "full_mark": 30}],
        retry_delays=(0,),
        sleep_fn=lambda _: None,
    )
    assert len(result.attempts) == 2
    assert result.attempts[0]["error_code"] == "judge_parse_error"
    assert result.attempts[0]["output_tokens"] is None


def test_direct_persist_retains_attempts_without_workflow(tmp_path):
    path = tmp_path / "direct.db"
    store = ResultStore(f"sqlite:///{path}")
    store.ensure_schema()
    outcome = er.run_single(Provider(), "m", {"case_id": "c"})
    result = er.RunResult("r", "fixture", "m", "live", "2026-10-13T00:00:00", (outcome,))
    assert er.persist_run_result(result, db_path=path)
    store = ResultStore(f"sqlite:///{path}")
    assert len(store.list_rows("request_attempts")) == 2


def test_imported_verified_evidence_must_match_stored_answer_and_original_gold(tmp_path):
    store = ResultStore(f"sqlite:///{tmp_path / 'import.db'}")
    store.ensure_schema()
    metadata = build_run_metadata(
        run_id="r",
        provider="p",
        model_ids=["m"],
        queue_items=[{"case_id": "c", "task": {"question": "Q"}}],
        generation_parameters={},
        judge_parameters={},
        dataset_version="v",
        prompt_payload=[],
        gold_map={"c": {"must_have_points": ["风险判断"]}},
        dimensions=[{"field": "accuracy_score", "full_mark": 30}],
    )
    store.initialize_run(metadata, [{"run_id": "r", "case_id": "c", "model_id": "m"}])
    store.save_run_outcome(
        dict(run_id="r", case_id="c", model_name="m", run_status="success", answer_text="实际回答"),
        queue_status="success",
    )
    score = dict(
        run_id="r",
        score_run_id="s",
        case_id="c",
        eval_model="m",
        judge_status="success",
        total_score=80,
        evidence_status="verified_quotes",
        checks_json=json.dumps(
            [
                dict(
                    point_id="must:1",
                    status="met",
                    quote="虚构引文",
                    error_type="none",
                    dimension="accuracy_score",
                    reason="r",
                )
            ]
        ),
    )
    result = store.import_formal_scores([score])
    assert result["imported_count"] == 0
    assert result["errors"]
    assert store.list_rows("live_run_scores") == []


def test_restored_score_outcome_preserves_evidence_for_resaving():
    row = dict(
        case_id="c",
        eval_model="m",
        judge_status="success",
        total_score=25,
        accuracy_score=25,
        evidence_status="verified_quotes",
        checks_json='[{"point_id":"must:1","quote":"原文"}]',
        numeric_checks_json='[{"status":"match"}]',
        raw_responses_json='["raw original"]',
    )
    restored = sc._score_outcome_from_row(row)
    serialized = sc.serialize_score_outcome("s", "r", "p", "j", "live", restored)
    assert json.loads(serialized["checks_json"]) == json.loads(row["checks_json"])
    assert serialized["evidence_status"] == "verified_quotes"
    assert json.loads(serialized["raw_responses_json"]) == ["raw original"]
