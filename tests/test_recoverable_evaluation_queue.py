"""live-eval-driven analysis pages + eval run page.

The standalone「真实模型评测」page is gone; model selection / run / scoring now
lives in the dedicated「发起评测」page, and the existing analysis pages render the
live results via an EvaluationData adapter. These tests use a temporary SQLite DB
and the Mock provider only — no test performs a real outbound API call, and no
test fabricates judge scores beyond what the adapter is explicitly handed.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from app.models.registry import get_provider
from app.persistence import get_result_store
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services.live_results import (
    MODEL_OUTPUT_COLUMNS,
    SCORE_COLUMNS,
    build_live_evaluation_data,
    empty_results_evaluation_data,
    synth_output_id,
)
from src.ui.navigation import PAGES

_TMP = tempfile.TemporaryDirectory()
_DB_PATH = Path(_TMP.name) / "recoverable_queue_test.db"
_MODEL = "mock/chat-base"


def setUpModule():
    ds.initialize_database(_DB_PATH, force=True)


def tearDownModule():
    _TMP.cleanup()


def _base():
    return ds.load_evaluation_data(_DB_PATH)


def _sample_tasks(n=2):
    return _base().tasks.head(n).to_dict("records")


def _run(n=2):
    return er.run_models(get_provider("mock"), [_MODEL], _sample_tasks(n))


def _score_rows_for(run_result):
    """Build judge-success score rows for every successful outcome.

    Scores are arbitrary fixtures supplied to the adapter — the point is to
    exercise output_id alignment and column mapping, not to assert any value.
    """
    rows = []
    for outcome in run_result.outcomes:
        if not outcome.success:
            continue
        rows.append(
            {
                "case_id": outcome.case_id,
                "eval_model": outcome.model_id,
                "judge_status": "success",
                "accuracy_score": 20,
                "reasoning_score": 15,
                "coverage_score": 15,
                "evidence_score": 10,
                "expression_score": 10,
                "total_score": 70,
                "review_note": "fixture",
                "review_status": "pending",
            }
        )
    return rows


class LiveResultsAdapterTests(unittest.TestCase):
    def test_build_live_evaluation_data_shapes_and_alignment(self):
        base = _base()
        run = _run(2)
        rows = _score_rows_for(run)
        data = build_live_evaluation_data(base, run, rows)

        # 列结构与 dataset_service 一致。
        self.assertEqual(list(data.model_outputs.columns), MODEL_OUTPUT_COLUMNS)
        self.assertEqual(list(data.scores.columns), SCORE_COLUMNS)

        # 题库 / Gold 取自 base，未被结果置换。
        self.assertEqual(len(data.tasks), len(base.tasks))
        self.assertEqual(data.gold_answer_map, base.gold_answer_map)

        # model_outputs 来自成功 outcome；model_name 为 model_id。
        success = [o for o in run.outcomes if o.success]
        self.assertEqual(len(data.model_outputs), len(success))
        self.assertEqual(set(data.model_outputs["model_name"]), {_MODEL})

        # output_id 两侧用同式合成，可对齐合并。
        for outcome in success:
            expected = synth_output_id(run.run_id, outcome.model_id, outcome.case_id)
            self.assertIn(expected, set(data.model_outputs["output_id"]))
            self.assertIn(expected, set(data.scores["output_id"]))
        self.assertEqual(
            set(data.model_outputs["output_id"]), set(data.scores["output_id"])
        )

        # 单次运行无法产出人工标注数据：结果类全空，但保留列结构。
        for frame in (
            data.errors,
            data.optimizations,
            data.evaluation_runs,
            data.preference_pairs,
            data.optimization_comparison,
        ):
            self.assertTrue(frame.empty)

    def test_only_success_scores_are_kept(self):
        base = _base()
        run = _run(1)
        rows = _score_rows_for(run)
        rows.append(
            {"case_id": rows[0]["case_id"], "eval_model": _MODEL, "judge_status": "mock"}
        )
        data = build_live_evaluation_data(base, run, rows)
        # mock 行被丢弃，不产生伪造分数。
        self.assertEqual(len(data.scores), len(_score_rows_for(run)))

    def test_empty_results_evaluation_data(self):
        base = _base()
        data = empty_results_evaluation_data(base)

        self.assertFalse(data.tasks.empty)
        self.assertEqual(data.gold_answer_map, base.gold_answer_map)
        self.assertTrue(data.model_outputs.empty)
        self.assertTrue(data.scores.empty)
        self.assertEqual(list(data.model_outputs.columns), MODEL_OUTPUT_COLUMNS)
        self.assertEqual(list(data.scores.columns), SCORE_COLUMNS)


class PageRemovalTests(unittest.TestCase):
    def test_kept_pages_are_the_evaluation_loop_pages(self):
        self.assertEqual(
            [
                "case_study",
                "samples",
                "test_run",
                "conclusions",
            ],
            list(PAGES.keys()),
        )


class PromptBoundaryRegressionTests(unittest.TestCase):
    def test_candidate_prompt_never_contains_gold(self):
        base = _base()
        case_id = str(base.tasks.iloc[0]["case_id"])
        gold = base.gold_answer_map.get(case_id, {})
        task = base.tasks.iloc[0].to_dict()
        messages = er.build_messages(task)
        blob = " ".join(m.get("content", "") for m in messages)
        for value in gold.values():
            text = str(value).strip()
            if len(text) >= 8:
                self.assertNotIn(text, blob)


class AppRenderTests(unittest.TestCase):
    """Render each kept page through the full app with / without a live run."""

    _PAGES = [
        "case_study",
        "samples",
        "test_run",
        "review",
        "conclusions",
    ]

    def _render(self, page_key, *, database_url, run_result=None):
        from streamlit.testing.v1 import AppTest

        # AppTest restores its own environment snapshot after each run. Reapply the
        # isolated URL for every page so a multi-page test can never fall through
        # to the developer machine's Streamlit secrets.
        with mock.patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
            self.assertEqual(
                get_result_store().engine.url.get_backend_name(), "sqlite"
            )
            at = AppTest.from_file(
                str(Path(__file__).resolve().parents[1] / "app.py")
            )
            if run_result is not None:
                at.session_state["live_eval_last_run"] = run_result
            at.session_state["current_page"] = page_key
            at.run(timeout=30)
            self.assertEqual(list(at.exception), [], page_key)

    @pytest.mark.usefixtures("isolated_app_database")
    def test_pages_render_without_run(self):
        database_url = os.environ["DATABASE_URL"]
        for page_key in self._PAGES:
            self._render(page_key, database_url=database_url)

    @pytest.mark.usefixtures("isolated_app_database")
    def test_pages_render_with_live_run(self):
        database_url = os.environ["DATABASE_URL"]
        run = _run(2)
        for page_key in self._PAGES:
            self._render(page_key, database_url=database_url, run_result=run)


class FormalRecoveryTests(unittest.TestCase):
    def test_recovery_never_offers_demo_or_mock_answer_runs(self):
        runs = [
            {"run_id": "RUN-LIVE", "provider": "vendor", "status": "completed"},
            {"run_id": "RUN-DEMO", "provider": "demo", "status": "completed"},
            {"run_id": "RUN-MOCK", "provider": "vendor", "status": "completed"},
        ]
        queue = [
            {"run_id": "RUN-LIVE", "case_id": "FD-001", "model_id": "vendor/live", "status": "success"},
            {"run_id": "RUN-DEMO", "case_id": "FD-001", "model_id": "vendor/demo", "status": "queued"},
            {"run_id": "RUN-MOCK", "case_id": "FD-001", "model_id": "vendor/mock", "status": "queued"},
        ]
        responses = [
            {
                "run_id": "RUN-LIVE", "case_id": "FD-001", "model_name": "vendor/live",
                "provider": "vendor", "run_mode": "live", "run_status": "success", "answer_text": "正式回答",
            },
            {
                "run_id": "RUN-DEMO", "case_id": "FD-001", "model_name": "vendor/demo",
                "provider": "demo", "run_mode": "demo", "run_status": "success", "answer_text": "演示回答",
            },
            {
                "run_id": "RUN-MOCK", "case_id": "FD-001", "model_name": "vendor/mock",
                "provider": "mock", "run_mode": "mock", "run_status": "success", "answer_text": "模拟回答",
            },
        ]

        summaries = er.build_persisted_answer_run_summaries(runs, queue, responses)

        self.assertEqual(["RUN-LIVE"], [row["run_id"] for row in summaries])

    def test_queued_demo_or_mock_runs_without_answers_are_not_recovery_candidates(self):
        class Store:
            def latest_queue(self, table):
                assert table == "live_run_queue"
                return [
                    {"run_id": "RUN-LIVE", "provider": "vendor", "status": "queued"},
                    {"run_id": "RUN-DEMO", "provider": "demo", "status": "queued"},
                    {"run_id": "RUN-MOCK", "provider": "mock", "status": "queued"},
                ]

        with mock.patch("app.persistence.get_result_store", return_value=Store()):
            candidates = er.latest_run_queue()

        self.assertEqual(["RUN-LIVE"], [row["run_id"] for row in candidates])


if __name__ == "__main__":
    unittest.main()
