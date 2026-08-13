"""Presentation-state contracts for isolated scoring batches."""

from pathlib import Path
from unittest.mock import patch

from app.services import scorer as sc
from src.ui import test_run as tr


def _result(
    score_run_id: str,
    *,
    mode: str = "live",
    statuses: tuple[str, ...] = ("success",),
) -> sc.ScoreResult:
    outcomes = tuple(
        sc.ScoreOutcome(
            case_id=f"CM-{index:03d}",
            task_type="analysis",
            eval_model="vendor/model-a",
            judge_provider="mock" if mode == "mock" else "siliconflow",
            judge_model="judge/model",
            judge_status=status,
            total_score=80 if status == "success" else None,
        )
        for index, status in enumerate(statuses, start=1)
    )
    return sc.ScoreResult(
        score_run_id=score_run_id,
        run_id="RUN-1",
        judge_provider="mock" if mode == "mock" else "siliconflow",
        judge_model="judge/model",
        mode=mode,
        created_at="2026-08-13T12:00:00",
        outcomes=outcomes,
    )


def test_completed_persistence_only_matches_the_current_score_run():
    result = _result("SCORE-2")

    matched = tr.build_score_result_status(result, {"status": "completed"}, "SCORE-2")
    stale = tr.build_score_result_status(result, {"status": "completed"}, "SCORE-1")

    assert matched is not None
    assert matched.kind == "completed"
    assert matched.badge == "已有 1 条评分"
    assert matched.persistence_note == "AI 评分已写入数据库，可在评测结论页查看。"
    assert stale is not None
    assert stale.persistence_note.startswith("当前评分仅在会话内展示")


def test_mock_status_is_exclusive_and_describes_debug_persistence():
    result = _result("DEMO-1", mode="mock", statuses=("mock", "mock"))

    status = tr.build_score_result_status(result, {"status": "completed"}, "DEMO-1")

    assert status is not None
    assert status.kind == "demo"
    assert status.badge == "演示记录"
    assert status.summary == "演示记录 2 条 · 未产生真实评分，不进入评测结论。"
    assert status.persistence_note == "演示记录已保存，用于链路调试。"
    assert "AI 评分已生成" not in status.summary


def test_running_interrupted_failed_and_completed_summaries_are_mutually_exclusive():
    result = _result("SCORE-1", statuses=("success", "failed"))
    base = {
        "queue_items": [object(), object(), object()],
        "skipped_count": 1,
    }

    running = tr.build_score_result_status(result, {**base, "status": "running"}, "")
    interrupted = tr.build_score_result_status(result, {**base, "status": "interrupted"}, "")
    failed = tr.build_score_result_status(result, {**base, "status": "failed"}, "")
    completed = tr.build_score_result_status(result, {**base, "status": "completed"}, "")

    assert running is not None and running.kind == "running" and running.summary.startswith("AI 评分进行中")
    assert interrupted is not None and interrupted.kind == "interrupted" and interrupted.summary.startswith("AI 评分未完成")
    assert failed is not None and failed.kind == "failed" and failed.summary.startswith("AI 评分失败")
    assert completed is not None and completed.kind == "completed" and completed.summary.startswith("AI 评分已完成")
    assert len({item.summary for item in [running, interrupted, failed, completed]}) == 4


def test_new_score_run_clears_stale_persistence_but_continuation_keeps_it():
    state = {tr._PERSISTED_SCORE_RUN_ID_KEY: "SCORE-1"}

    with patch.object(tr.st, "session_state", state):
        tr._prepare_score_run_persistence("SCORE-1", continuing=True)
        assert state[tr._PERSISTED_SCORE_RUN_ID_KEY] == "SCORE-1"

        tr._prepare_score_run_persistence("SCORE-2", continuing=False)
        assert tr._PERSISTED_SCORE_RUN_ID_KEY not in state

        tr._record_score_run_persistence("SCORE-2", persisted=False)
        assert tr._PERSISTED_SCORE_RUN_ID_KEY not in state

        tr._record_score_run_persistence("SCORE-2", persisted=True)
        assert state[tr._PERSISTED_SCORE_RUN_ID_KEY] == "SCORE-2"


def test_failed_incremental_write_clears_current_batch_persistence_claim():
    state = {tr._PERSISTED_SCORE_RUN_ID_KEY: "SCORE-2"}

    with patch.object(tr.st, "session_state", state):
        tr._record_score_run_persistence("SCORE-2", persisted=False)

    assert tr._PERSISTED_SCORE_RUN_ID_KEY not in state


def test_legacy_score_persistence_boolean_is_never_read():
    source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "test_run.py").read_text(
        encoding="utf-8"
    )

    assert 'session_state.get("test_run_score_persisted"' not in source
    assert 'session_state["test_run_score_persisted"]' not in source


def test_score_compare_button_opens_dialog():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        """
from app.services import scorer as sc
from src.ui.test_run import _render_score_compare_dialog, _render_score_detail

dimensions = [{"field": "accuracy_score", "name": "专业准确性", "full_mark": 30}]
outcome = sc.ScoreOutcome(
    case_id="CM-001",
    task_type="analysis",
    eval_model="vendor/model-a",
    judge_provider="siliconflow",
    judge_model="judge/model",
    judge_status="success",
    scores={"accuracy_score": 24},
    total_score=24,
    rationale={"accuracy_score": "判断准确。"},
)
result = sc.ScoreResult(
    score_run_id="SCORE-DIALOG",
    run_id="RUN-1",
    judge_provider="siliconflow",
    judge_model="judge/model",
    mode="live",
    created_at="2026-08-13T12:00:00",
    outcomes=(outcome,),
)
if _render_score_detail(outcome, dimensions, result):
    _render_score_compare_dialog(result, dimensions)
"""
    ).run(timeout=10)

    button = next(item for item in app.button if item.label == "查看评分对比表")
    button.click().run(timeout=10)

    assert len(app.get("dialog")) == 1
    assert len(app.dataframe) == 1
