"""PR-36 tests: live-eval-driven analysis pages + eval run page.

The standalone「真实模型评测」page is gone; model selection / run / scoring now
lives in the dedicated「发起评测」page, and the existing analysis pages render the
live results via an EvaluationData adapter. These tests use a temporary SQLite DB
and the Mock provider only — no test performs a real outbound API call, and no
test fabricates judge scores beyond what the adapter is explicitly handed.
"""

import tempfile
import unittest
from pathlib import Path

from app.models.registry import get_provider
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
from src.ui.page_config import PAGE_CONFIG_BY_KEY


_TMP = tempfile.TemporaryDirectory()
_DB_PATH = Path(_TMP.name) / "findueval_pr36.db"
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
                "review",
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

    def _render(self, page_key, run_result=None):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        if run_result is not None:
            at.session_state["live_eval_last_run"] = run_result
        at.session_state["current_page"] = page_key
        at.run()
        self.assertEqual(list(at.exception), [], page_key)

    def test_pages_render_without_run(self):
        for page_key in self._PAGES:
            self._render(page_key)

    def test_pages_render_with_live_run(self):
        run = _run(2)
        for page_key in self._PAGES:
            self._render(page_key, run_result=run)


if __name__ == "__main__":
    unittest.main()
