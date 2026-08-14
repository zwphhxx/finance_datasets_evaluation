import pytest

from app.services import conclusions, scorer
from src.ui import test_run


class _FakeStore:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table
        self.reads = []

    def list_rows(self, table, **filters):
        self.reads.append((table, filters))
        return list(self.rows_by_table.get(table, []))


def test_persistence_gate_stops_before_provider_call():
    events = []
    with pytest.raises(RuntimeError, match="runtime persistence required"):
        events.append("initialize")
        test_run._persistence_gate(False)
        events.append("provider")

    assert events == ["initialize"]


def test_status_reader_does_not_construct_model_providers(monkeypatch):
    events = []

    class Reader:
        def __init__(self, store, answer_provider, judge_provider):
            events.append((store, answer_provider, judge_provider))

        def load_evaluation_status(self, run_id):
            return run_id

    monkeypatch.setattr(test_run, "EvaluationWorkflow", Reader)
    monkeypatch.setattr(
        test_run,
        "get_text_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider constructed")),
    )

    assert test_run._load_evaluation_status("store", "RUN-1") == "RUN-1"
    assert events == [("store", None, None)]


def test_conclusion_reader_uses_result_store(monkeypatch):
    store = _FakeStore(
        {
            "live_run_scores": [
                {
                    "score_run_id": "SCORE-1",
                    "case_id": "FD-001",
                    "eval_model": "vendor/model",
                    "judge_status": "success",
                    "total_score": 88,
                }
            ]
        }
    )
    monkeypatch.setattr("app.persistence.get_result_store", lambda db_path=None: store)

    frame = conclusions.load_live_scores()

    assert frame.iloc[0]["total_score"] == 88
    assert store.reads == [("live_run_scores", {})]


def test_score_export_reader_uses_result_store(monkeypatch):
    store = _FakeStore(
        {
            "live_run_scores": [
                {
                    "score_run_id": "SCORE-1",
                    "run_id": "RUN-1",
                    "case_id": "FD-001",
                    "eval_model": "vendor/model",
                    "judge_status": "success",
                    "judge_mode": "live",
                    "judge_provider": "test-live",
                    "review_status": "ai_final",
                    "status": "active",
                    "total_score": 88,
                }
            ],
            "live_run_responses": [
                {
                    "run_id": "RUN-1",
                    "case_id": "FD-001",
                    "model_name": "vendor/model",
                    "provider": "test-live",
                    "run_mode": "live",
                    "run_status": "success",
                    "answer_text": "saved answer",
                    "status": "active",
                }
            ],
        }
    )
    monkeypatch.setattr("app.persistence.get_result_store", lambda db_path=None: store)

    rows = scorer.load_exportable_score_rows()

    assert rows[0]["total_score"] == 88
    assert store.reads == [("live_run_scores", {}), ("live_run_responses", {})]
