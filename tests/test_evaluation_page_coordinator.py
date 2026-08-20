from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.persistence import ResultStoreError, ResultStoreUnavailableError
from app.services.evaluation_workflow import (
    COMPLETED,
    FAILED,
    INTERRUPTED,
    PARTIAL,
    RUNNING,
    STOPPED,
    EvaluationRunStatus,
    WorkflowCheckpointError,
    WorkflowStopped,
)
from src.ui import evaluation_config as ec
from src.ui import evaluation_results as er_ui
from src.ui import test_run as tr


class RerunRequested(RuntimeError):
    pass


class FakeStreamlit:
    def __init__(self, *, click_key: str = ""):
        self.session_state = {
            "test_run_selected_cases": ["C1"],
            "test_run_selected_models": ["vendor/model-1"],
        }
        self.click_key = click_key
        self.buttons: list[dict] = []
        self.messages: list[str] = []
        self.popovers: list[dict] = []
        self.sequence: list[str] = []

    def container(self, *args, **kwargs):
        return nullcontext()

    def empty(self):
        return SimpleNamespace(container=lambda: nullcontext())

    def popover(self, *args, **kwargs):
        self.popovers.append({"label": args[0] if args else "", "type": kwargs.get("type")})
        return nullcontext()

    def button(self, label, *, key, disabled=False, **kwargs):
        self.sequence.append(f"button:{key}")
        self.buttons.append(
            {"label": label, "key": key, "disabled": disabled, "type": kwargs.get("type")}
        )
        return key == self.click_key and not disabled

    def caption(self, value, *args, **kwargs):
        self.messages.append(str(value))

    def warning(self, value, *args, **kwargs):
        self.messages.append(str(value))

    def markdown(self, value, *args, **kwargs):
        self.messages.append(str(value))

    def file_uploader(self, *args, **kwargs):
        return None

    def download_button(self, *args, **kwargs):
        raise AssertionError("download must be prepared explicitly before it is rendered")

    def rerun(self):
        raise RerunRequested


class FakeStore:
    def __init__(
        self,
        *,
        has_run: bool,
        latest_error: Exception | None = None,
        metadata: dict | None = None,
        metadata_error: Exception | None = None,
        ping_result: bool = True,
    ):
        self.has_run = has_run
        self.latest_error = latest_error
        self.metadata = metadata or {
            "run_id": "RUN-1",
            "provider": "siliconflow",
            "run_mode": "live",
            "status": "running",
        }
        self.metadata_error = metadata_error
        self.ping_result = ping_result
        self.is_postgresql = True
        self.calls: list[tuple] = []

    def latest_queue(self, table):
        self.calls.append(("latest_queue", table))
        if self.latest_error is not None:
            raise self.latest_error
        return (
            [{"run_id": "RUN-1", "provider": "siliconflow", "case_id": "C1", "model_id": "vendor/model-1"}]
            if self.has_run
            else []
        )

    def list_rows(self, table, **filters):
        self.calls.append(("list_rows", table, filters))
        if table == "live_evaluation_runs":
            if self.metadata_error is not None:
                raise self.metadata_error
            return [self.metadata] if self.has_run else []
        return []

    def ping(self):
        self.calls.append(("ping",))
        return self.ping_result


def _status(state: str) -> EvaluationRunStatus:
    return EvaluationRunStatus(
        run_id="RUN-1",
        score_run_id="SCORE-1",
        state=state,
        total=1,
        succeeded=1 if state in {COMPLETED, PARTIAL} else 0,
        failed=1 if state in {FAILED, PARTIAL} else 0,
        pending=1 if state in {RUNNING, INTERRUPTED, STOPPED} else 0,
        resumable=state == INTERRUPTED,
        message="persistence stopped" if state == STOPPED else "",
        persistence_failed_in_session=state == STOPPED,
    )


def _bundle():
    task = {"case_id": "C1", "question": "Q", "task_type": "analysis"}
    return {
        "base": SimpleNamespace(
            tasks=pd.DataFrame([task]),
            gold_answer_map={"C1": {"core_conclusion": "gold"}},
        )
    }


def _render(
    monkeypatch,
    state: str | None,
    *,
    api_ready=True,
    click_key="",
    workflow=None,
    checkpoint_valid=True,
    checkpoint_error: Exception | None = None,
    latest_error: Exception | None = None,
    status_error: Exception | None = None,
    preflight=None,
    metadata: dict | None = None,
    metadata_error: Exception | None = None,
    store_override=None,
    dialog: str = "",
    capture_errors=False,
):
    fake_st = FakeStreamlit(click_key=click_key)
    if dialog:
        fake_st.session_state["test_run_dialog"] = dialog
    store = store_override or FakeStore(
        has_run=state is not None,
        latest_error=latest_error,
        metadata=metadata,
        metadata_error=metadata_error,
    )
    events: list[str] = []
    monkeypatch.setattr(tr, "st", fake_st)
    monkeypatch.setattr(ec, "st", fake_st)
    monkeypatch.setattr(tr, "render_page_heading", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tr,
        "render_numbered_section",
        lambda number, *args, **kwargs: fake_st.sequence.append(f"section:{number}"),
    )
    monkeypatch.setattr(ec, "render_evaluation_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(ec, "render_pending_dialogs", lambda *args, **kwargs: None)
    monkeypatch.setattr(tr, "render_persistence_status", lambda value: fake_st.messages.append(value))
    monkeypatch.setattr(tr, "render_evaluation_status", lambda status: events.append(f"status:{status.state}"))
    monkeypatch.setattr(
        tr,
        "render_evaluation_records_dialog",
        lambda *args: events.append("records-dialog"),
        raising=False,
    )
    monkeypatch.setattr(tr.sr, "load_samples", lambda: [])
    monkeypatch.setattr(tr.ds, "get_testable_rubric_dimensions", lambda: [])
    monkeypatch.setattr(tr.ds, "get_rubric_dimensions", lambda: [{"field": "accuracy_score"}])
    monkeypatch.setattr(tr.ds, "list_dataset_versions", lambda: ["v1"])
    monkeypatch.setattr(
        tr,
        "build_sample_options",
        lambda *args, **kwargs: [{"case_id": "C1", "task": _bundle()["base"].tasks.iloc[0].to_dict()}],
    )
    monkeypatch.setattr(tr.sf, "is_configured", lambda: api_ready)
    def model_provider_factory(*args, **kwargs):
        events.append("model_provider")
        raise AssertionError("model provider must not be constructed during page rendering")

    monkeypatch.setattr(tr.sf, "SiliconFlowProvider", model_provider_factory)
    monkeypatch.setattr(tr.cd, "clear_conclusions_caches", lambda: events.append("clear"))

    def status_loader(_store, run_id):
        events.append(f"load:{run_id}")
        if status_error is not None:
            raise status_error
        return _status(state)  # type: ignore[arg-type]

    def checkpoint_builder(*args, **kwargs):
        events.append("checkpoint")
        if checkpoint_error is not None:
            raise checkpoint_error
        if not checkpoint_valid:
            from app.services.evaluation_workflow import WorkflowCheckpointError

            raise WorkflowCheckpointError("changed")
        return "checkpoint-config"
    workflow_object = workflow or SimpleNamespace(
        start_evaluation=lambda config: events.append(f"start:{config}"),
        continue_evaluation=lambda run_id, config: events.append(f"continue:{run_id}:{config}"),
    )
    def workflow_factory(*args, **kwargs):
        events.append("workflow")
        return workflow_object

    def config_builder(*args, **kwargs):
        events.append("config")
        return "new-config"

    try:
        tr.render_test_run_page(
            _bundle(),
            store=store,
            status_loader=status_loader,
            workflow_factory=workflow_factory,
            config_builder=config_builder,
            checkpoint_builder=checkpoint_builder,
            preflight=preflight or (lambda _store, _provider: events.append("preflight")),
        )
    except RerunRequested:
        events.append("rerun")
    except Exception as exc:
        if not capture_errors:
            raise
        events.append(f"error:{type(exc).__name__}:{exc}")
    return fake_st, store, events


@pytest.mark.parametrize("state", [COMPLETED, PARTIAL, FAILED])
def test_terminal_runs_offer_lazy_records_and_allow_a_new_batch(monkeypatch, state):
    ui, store, events = _render(monkeypatch, state)

    assert not any(
        call[:2] in {
            ("list_rows", "live_run_responses"),
            ("list_rows", "live_run_scores"),
        }
        for call in store.calls
    )
    assert any(button["key"] == "test_run_open_records_RUN_1" for button in ui.buttons)
    assert [(button["key"], button["disabled"]) for button in ui.buttons if "evaluation" in button["key"]] == [
        ("test_run_start_evaluation", False)
    ]


def test_primary_action_is_rendered_before_progress_and_history(monkeypatch):
    ui, _store, _events = _render(monkeypatch, COMPLETED)

    assert ui.sequence.index("button:test_run_start_evaluation") < ui.sequence.index("section:02")
    assert ui.sequence.index("section:02") < ui.sequence.index("button:test_run_open_records_RUN_1")


def test_history_button_opens_the_target_batch_dialog(monkeypatch):
    _ui, _store, events = _render(
        monkeypatch,
        COMPLETED,
        click_key="test_run_open_records_RUN_1",
    )

    assert events.count("records-dialog") == 1


def test_lazy_record_loader_uses_exact_run_and_score_batch_filters():
    store = FakeStore(has_run=True)

    answers, scores = er_ui.load_evaluation_records(store, _status(COMPLETED))

    assert answers == []
    assert scores == []
    assert ("list_rows", "live_run_responses", {"run_id": "RUN-1"}) in store.calls
    assert (
        "list_rows",
        "live_run_scores",
        {"score_run_id": "SCORE-1"},
    ) in store.calls


@pytest.mark.parametrize(
    ("state", "expected_key"),
    [(RUNNING, None), (INTERRUPTED, "test_run_continue_evaluation"), (STOPPED, None)],
)
def test_active_states_expose_only_the_allowed_action(monkeypatch, state, expected_key):
    ui, _store, events = _render(monkeypatch, state)

    action_keys = [button["key"] for button in ui.buttons if "evaluation" in button["key"]]
    assert action_keys == ([] if expected_key is None else [expected_key])
    assert "workflow" not in events


def test_read_only_page_load_never_constructs_or_runs_live_workflow(monkeypatch):
    ui, store, events = _render(monkeypatch, INTERRUPTED)

    assert store.calls[0] == ("latest_queue", "live_run_queue")
    assert events[0] == "load:RUN-1"
    assert "status:interrupted" in events
    assert "workflow" not in events
    assert not any(event.startswith(("start:", "continue:")) for event in events)


@pytest.mark.parametrize("run_mode", ["demo", "mock"])
def test_non_formal_metadata_with_real_provider_is_never_offered_for_recovery(
    monkeypatch, run_mode
):
    ui, _store, events = _render(
        monkeypatch,
        INTERRUPTED,
        metadata={
            "run_id": "RUN-1",
            "provider": "siliconflow",
            "run_mode": run_mode,
            "status": "partial",
        },
    )

    action_keys = [button["key"] for button in ui.buttons if "evaluation" in button["key"]]
    assert action_keys == ["test_run_start_evaluation"]
    assert "test_run_continue_evaluation" not in action_keys
    assert "load:RUN-1" not in events


def test_formal_partial_metadata_remains_eligible_for_read_only_status(monkeypatch):
    _ui, _store, events = _render(
        monkeypatch,
        PARTIAL,
        metadata={
            "run_id": "RUN-1",
            "provider": "siliconflow",
            "run_mode": "live",
            "status": "partial",
        },
    )

    assert "load:RUN-1" in events
    assert "status:partial" in events


def test_no_api_key_disables_start_without_preflight_or_workflow(monkeypatch):
    ui, _store, events = _render(
        monkeypatch,
        None,
        api_ready=False,
        click_key="test_run_start_evaluation",
    )

    start = next(button for button in ui.buttons if button["key"] == "test_run_start_evaluation")
    assert start["disabled"] is True
    assert "preflight" not in events
    assert "workflow" not in events


@pytest.mark.parametrize(
    "checkpoint_error",
    [ResultStoreError("checkpoint offline"), ResultStoreUnavailableError("checkpoint offline")],
)
def test_checkpoint_storage_failure_disables_continue_without_reporting_config_change(
    monkeypatch, checkpoint_error
):
    ui, _store, events = _render(
        monkeypatch,
        INTERRUPTED,
        checkpoint_error=checkpoint_error,
        click_key="test_run_continue_evaluation",
    )

    continue_button = next(
        button for button in ui.buttons if button["key"] == "test_run_continue_evaluation"
    )
    assert continue_button["disabled"] is True
    assert any("数据库" in message and "不可用" in message for message in ui.messages)
    assert not any("样本或参数已变化" in message for message in ui.messages)
    assert "workflow" not in events
    assert "model_provider" not in events
    assert not any(event.startswith("continue:") for event in events)


@pytest.mark.parametrize("failure_point", ["latest", "metadata", "status"])
def test_storage_read_failure_disables_all_evaluation_actions(monkeypatch, failure_point):
    kwargs = {
        "latest": {"state": None, "latest_error": ResultStoreUnavailableError("offline")},
        "metadata": {"state": INTERRUPTED, "metadata_error": ResultStoreError("offline")},
        "status": {"state": INTERRUPTED, "status_error": ResultStoreError("offline")},
    }[failure_point]

    ui, _store, events = _render(monkeypatch, **kwargs)

    actions = [button for button in ui.buttons if "evaluation" in button["key"]]
    assert actions and all(button["disabled"] for button in actions)
    assert any("数据库" in message and "不可用" in message for message in ui.messages)
    assert "workflow" not in events


def test_current_store_ping_false_stops_even_when_global_store_is_healthy(monkeypatch):
    import app.persistence as persistence

    class HealthyGlobalStore:
        is_postgresql = True

        @staticmethod
        def ping():
            return True

    current_store = FakeStore(has_run=False, ping_result=False)
    monkeypatch.setattr(persistence, "get_result_store", lambda: HealthyGlobalStore())

    _ui, _store, events = _render(
        monkeypatch,
        None,
        click_key="test_run_start_evaluation",
        preflight=tr._require_persistence_preflight,
        store_override=current_store,
        capture_errors=True,
    )

    assert not any(event.startswith("error:") for event in events)
    assert "workflow" not in events
    assert not any(event.startswith("start:") for event in events)
    assert [event for event in events if event.startswith("status:")] == ["status:stopped"]
    assert ("ping",) in current_store.calls


def test_current_healthy_store_is_not_blocked_by_bad_global_store(monkeypatch):
    import app.persistence as persistence

    def bad_global_store():
        raise AssertionError("global store must not be read by action preflight")

    current_store = FakeStore(has_run=False, ping_result=True)
    monkeypatch.setattr(persistence, "get_result_store", bad_global_store)

    _ui, _store, events = _render(
        monkeypatch,
        None,
        click_key="test_run_start_evaluation",
        preflight=tr._require_persistence_preflight,
        store_override=current_store,
    )

    assert "workflow" in events
    assert "start:new-config" in events
    assert ("ping",) in current_store.calls


def test_model_dialog_never_constructs_provider_when_store_is_unavailable(monkeypatch):
    _ui, _store, events = _render(
        monkeypatch,
        None,
        latest_error=ResultStoreUnavailableError("offline"),
        dialog="models",
    )

    assert "model_provider" not in events
    assert "workflow" not in events


def test_model_dialog_never_constructs_provider_when_current_store_ping_fails(monkeypatch):
    current_store = FakeStore(has_run=False, ping_result=False)

    ui, _store, events = _render(
        monkeypatch,
        None,
        dialog="models",
        store_override=current_store,
        preflight=tr._require_persistence_preflight,
    )

    assert "model_provider" not in events
    assert "workflow" not in events
    assert ("ping",) in current_store.calls
    assert any("模型列表" in message and "暂不可读取" in message for message in ui.messages)


def test_start_click_preflights_before_workflow_and_runs_once(monkeypatch):
    _ui, _store, events = _render(
        monkeypatch,
        None,
        click_key="test_run_start_evaluation",
    )

    assert events[-6:] == ["preflight", "config", "workflow", "start:new-config", "clear", "rerun"]


def test_continue_uses_checkpoint_config_and_never_current_form_config(monkeypatch):
    _ui, _store, events = _render(
        monkeypatch,
        INTERRUPTED,
        click_key="test_run_continue_evaluation",
    )

    assert "config" not in events
    assert events[-6:] == [
        "checkpoint",
        "preflight",
        "workflow",
        "continue:RUN-1:checkpoint-config",
        "clear",
        "rerun",
    ]


def test_changed_checkpoint_disables_continue_with_clear_explanation(monkeypatch):
    ui, _store, events = _render(
        monkeypatch,
        INTERRUPTED,
        click_key="test_run_continue_evaluation",
        checkpoint_valid=False,
    )

    button = next(item for item in ui.buttons if item["key"] == "test_run_continue_evaluation")
    assert button["disabled"] is True
    assert any("当前样本或参数已变化，不能继续旧批次" in message for message in ui.messages)
    assert "preflight" not in events
    assert "workflow" not in events


def test_workflow_stop_replaces_current_status_with_one_stopped_state(monkeypatch):
    def stop(*_args):
        raise WorkflowStopped("could not persist evaluation outcome")

    workflow = SimpleNamespace(start_evaluation=stop, continue_evaluation=stop)

    _ui, _store, events = _render(
        monkeypatch,
        INTERRUPTED,
        click_key="test_run_continue_evaluation",
        workflow=workflow,
    )

    assert [event for event in events if event.startswith("status:")] == ["status:stopped"]
    assert "clear" in events
    assert "rerun" not in events


@pytest.mark.parametrize(
    ("state", "click_key", "method_name"),
    [
        (None, "test_run_start_evaluation", "start_evaluation"),
        (INTERRUPTED, "test_run_continue_evaluation", "continue_evaluation"),
    ],
)
@pytest.mark.parametrize(
    "failure",
    [
        WorkflowStopped("partial results were persisted"),
        ResultStoreError("persistence failed after a partial write"),
        WorkflowCheckpointError("checkpoint failed after a partial write"),
    ],
)
def test_workflow_failure_paths_invalidate_conclusion_cache(
    monkeypatch,
    state,
    click_key,
    method_name,
    failure,
):
    def fail(*_args):
        raise failure

    workflow = SimpleNamespace(
        start_evaluation=lambda *_args: None,
        continue_evaluation=lambda *_args: None,
    )
    setattr(workflow, method_name, fail)

    _ui, _store, events = _render(
        monkeypatch,
        state,
        click_key=click_key,
        workflow=workflow,
    )

    assert "clear" in events
    assert "rerun" not in events


def test_next_successful_read_derives_interrupted_without_session_override(monkeypatch):
    _ui, _store, events = _render(monkeypatch, INTERRUPTED)

    assert [event for event in events if event.startswith("status:")] == ["status:interrupted"]


def test_maintenance_is_a_tertiary_popover_without_primary_actions(monkeypatch):
    ui, _store, _events = _render(monkeypatch, None)

    assert {item["label"] for item in ui.popovers} == {"评测维护"}
    assert ui.popovers[0]["type"] == "tertiary"
    maintenance_buttons = [
        item for item in ui.buttons if item["key"].startswith("test_run_maintenance_")
    ]
    assert {item["key"] for item in maintenance_buttons} == {
        "test_run_maintenance_prepare_export",
        "test_run_maintenance_open_samples",
    }
    assert all(item["type"] != "primary" for item in maintenance_buttons)


def test_maintenance_import_uses_current_store_and_public_result_keys():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
    maintenance = source[source.index("def _render_evaluation_maintenance"):]

    assert "result_store=store" in maintenance
    assert "result.get('imported_count')" in maintenance
    assert "result.get('skipped_count')" in maintenance
    assert "result.get('imported')" not in maintenance
    assert "result.get('skipped')" not in maintenance
