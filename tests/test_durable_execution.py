import pytest

from app.persistence import ResultStoreUnavailableError
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


def test_unavailable_persistence_stops_before_provider_construction(monkeypatch):
    provider_calls = []
    status_messages = []

    def unavailable(_provider_name):
        raise ResultStoreUnavailableError("database unavailable")

    monkeypatch.setattr(test_run, "_require_persistence_preflight", unavailable)
    monkeypatch.setattr(
        test_run,
        "get_text_provider",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    monkeypatch.setattr(
        test_run,
        "render_persistence_status",
        lambda message: status_messages.append(message),
        raising=False,
    )

    test_run._execute_run_queue(
        "siliconflow",
        queue_items=[],
        model_ids=[],
        temperature=0.1,
        max_tokens=128,
    )

    assert provider_calls == []
    assert status_messages == ["评测结果数据库暂不可用，当前不会调用模型服务。"]


def test_test_run_page_displays_persistence_outage():
    source = open("src/ui/test_run.py", encoding="utf-8").read()
    render_source = source[
        source.index("def render_test_run_page"):
        source.index("def _default_provider_name")
    ]

    assert "current_result_store_failure()" in render_source
    assert "render_persistence_status" in render_source


def test_checkpoint_rejects_changed_sample_or_prompt():
    current = {
        "dataset_version": "2.0.0",
        "dataset_hash": "d" * 64,
        "prompt_hash": "p" * 64,
    }

    assert test_run._checkpoint_matches_current(dict(current), current)
    assert not test_run._checkpoint_matches_current(
        {**current, "dataset_hash": "x" * 64},
        current,
    )
    assert not test_run._checkpoint_matches_current(
        {**current, "prompt_hash": "x" * 64},
        current,
    )
    assert not test_run._checkpoint_matches_current(None, current)


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
                    "review_status": "ai_final",
                    "status": "active",
                    "total_score": 88,
                }
            ]
        }
    )
    monkeypatch.setattr("app.persistence.get_result_store", lambda db_path=None: store)

    rows = scorer.load_exportable_score_rows()

    assert rows[0]["total_score"] == 88
    assert store.reads == [("live_run_scores", {})]
