"""Real Streamlit rendering guards for the single evaluation action."""

from __future__ import annotations

from textwrap import dedent

from streamlit.testing.v1 import AppTest


def _script(state: str | None, *, api_ready: bool) -> str:
    return dedent(
        f"""
        from types import SimpleNamespace
        import pandas as pd
        import streamlit as st
        from app.services.evaluation_workflow import EvaluationRunStatus
        from src.ui import test_run as tr

        calls = st.session_state.setdefault("guard_calls", [])

        class FakeStore:
            def latest_queue(self, table):
                return {('[{"run_id": "RUN-1", "provider": "siliconflow", "case_id": "C1", "model_id": "vendor/model-1"}]' if state else '[]')}
            def list_rows(self, table, **filters):
                return []

        def forbidden(name):
            def fail(*args, **kwargs):
                calls.append(name)
                raise AssertionError(name + " must not run during page rendering")
            return fail

        base = SimpleNamespace(
            tasks=pd.DataFrame([{{"case_id": "C1", "question": "Q", "task_type": "analysis"}}]),
            gold_answer_map={{"C1": {{"core_conclusion": "gold"}}}},
        )
        sample = {{"case_id": "C1", "title": "样本", "scenario": "财务", "difficulty": "中等", "task": base.tasks.iloc[0].to_dict()}}
        st.session_state["test_run_selected_cases"] = ["C1"]
        st.session_state["test_run_selected_models"] = ["vendor/model-1"]
        originals = {{
            "load_samples": tr.sr.load_samples,
            "rubric": tr.ds.get_testable_rubric_dimensions,
            "sample_options": tr.build_sample_options,
            "eligible": tr.formal.formal_recovery_run_eligible,
            "configured": tr.sf.is_configured,
            "provider": tr.sf.SiliconFlowProvider,
        }}
        tr.sr.load_samples = lambda: []
        tr.ds.get_testable_rubric_dimensions = lambda: []
        tr.build_sample_options = lambda *args, **kwargs: [sample]
        tr.formal.formal_recovery_run_eligible = lambda *args, **kwargs: True
        tr.sf.is_configured = lambda: {api_ready!r}
        tr.sf.SiliconFlowProvider = forbidden("model_provider")

        def load_status(store, run_id):
            return EvaluationRunStatus(
                run_id="RUN-1", score_run_id="SCORE-1", state={state!r},
                total=1, succeeded=0, failed=0, pending=1,
                resumable={state == 'interrupted'!r}, message="",
                persistence_failed_in_session=False,
            )

        try:
            tr.render_test_run_page(
                {{"base": base}},
                store=FakeStore(),
                status_loader=load_status,
                workflow_factory=forbidden("workflow"),
                config_builder=forbidden("config"),
                checkpoint_builder=(lambda *args, **kwargs: "checkpoint"),
                preflight=forbidden("preflight"),
            )
        finally:
            tr.sr.load_samples = originals["load_samples"]
            tr.ds.get_testable_rubric_dimensions = originals["rubric"]
            tr.build_sample_options = originals["sample_options"]
            tr.formal.formal_recovery_run_eligible = originals["eligible"]
            tr.sf.is_configured = originals["configured"]
            tr.sf.SiliconFlowProvider = originals["provider"]
        """
    )


def test_no_api_key_disables_start_without_constructing_live_actions():
    at = AppTest.from_string(_script(None, api_ready=False)).run()

    assert list(at.exception) == []
    start = next(button for button in at.button if button.key == "test_run_start_evaluation")
    assert start.label == "开始评测"
    assert start.disabled is True
    assert at.session_state["guard_calls"] == []


def test_interrupted_page_shows_only_continue_without_running_it():
    at = AppTest.from_string(_script("interrupted", api_ready=True)).run()

    assert list(at.exception) == []
    evaluation_buttons = [
        button for button in at.button
        if button.key in {"test_run_start_evaluation", "test_run_continue_evaluation"}
    ]
    assert [(button.label, button.key) for button in evaluation_buttons] == [
        ("继续评测", "test_run_continue_evaluation")
    ]
    assert at.session_state["guard_calls"] == []
