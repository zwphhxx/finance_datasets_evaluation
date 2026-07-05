"""PR-35 tests: multi-model live eval comparison + LLM-as-judge scoring.

Covers multi-model orchestration (run_models / CompareRunResult), the judge prompt
boundary (judge SEES Gold, evaluated model never does), robust JSON parsing with
clamping, mock judge fabricating nothing, persistence to the dedicated
live_run_scores table, human-review confirmation, and page wiring. No test performs
a real outbound API call.
"""

import tempfile
import unittest
from pathlib import Path

from app.models.base import GenerationResult, ModelProvider, STATUS_SUCCESS
from app.models.registry import get_provider
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import scorer as sc
from app.db.repository import Repository
from src.ui.navigation import PAGES


_TMP = tempfile.TemporaryDirectory()
_DB_PATH = Path(_TMP.name) / "findueval_pr35.db"

_DIMENSIONS = [
    {"field": "accuracy_score", "name": "专业准确性", "full_mark": 30},
    {"field": "reasoning_score", "name": "推理与场景适配", "full_mark": 20},
    {"field": "coverage_score", "name": "风险覆盖", "full_mark": 20},
    {"field": "evidence_score", "name": "依据可靠性", "full_mark": 15},
    {"field": "expression_score", "name": "专业表达", "full_mark": 15},
]


def setUpModule():
    ds.initialize_database(_DB_PATH, force=True)


def tearDownModule():
    _TMP.cleanup()


def _sample_tasks(n=2):
    return ds.load_evaluation_data(_DB_PATH).tasks.head(n).to_dict("records")


def _valid_judge_json(scores):
    import json

    return json.dumps(
        {"scores": scores, "rationale": {"accuracy_score": "依据充分"}, "review_note": "注意核实比例"},
        ensure_ascii=False,
    )


class _FakeJudge(ModelProvider):
    """Returns valid judge JSON wrapped in extra prose — exercises robust parsing."""

    name = "fakejudge"

    def __init__(self, scores=None):
        self._scores = scores or {
            "accuracy_score": 40,  # over full_mark on purpose → must clamp to 30
            "reasoning_score": 18,
            "coverage_score": 15,
            "evidence_score": 12,
            "expression_score": 10,
        }

    def list_models(self, model_type="text", sub_type="chat"):
        raise NotImplementedError

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        text = "评分如下：\n" + _valid_judge_json(self._scores) + "\n（仅供参考）"
        return GenerationResult(
            self.name, model_id, STATUS_SUCCESS, response_text=text,
            input_tokens=10, output_tokens=20, total_tokens=30,
        )


class _GarbageJudge(ModelProvider):
    name = "garbage"

    def list_models(self, model_type="text", sub_type="chat"):
        raise NotImplementedError

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        return GenerationResult(self.name, model_id, STATUS_SUCCESS, response_text="无法评分，抱歉。")


class MultiModelRunTests(unittest.TestCase):
    def test_run_models_covers_each_model_and_case(self):
        provider = get_provider("mock")
        result = er.run_models(provider, ["mock/chat-base", "mock/chat-reasoning"], _sample_tasks(2))
        self.assertEqual(result.model_ids, ("mock/chat-base", "mock/chat-reasoning"))
        self.assertEqual(len(result.outcomes), 4)  # 2 models × 2 tasks
        self.assertTrue(result.run_id.startswith("RUN-"))
        pairs = {(o.model_id, o.case_id) for o in result.outcomes}
        self.assertEqual(len(pairs), 4)

    def test_run_models_dedupes_models(self):
        provider = get_provider("mock")
        result = er.run_models(provider, ["mock/chat-base", "mock/chat-base", ""], _sample_tasks(1))
        self.assertEqual(result.model_ids, ("mock/chat-base",))
        self.assertEqual(len(result.outcomes), 1)

    def test_persist_compare_writes_rows_per_model(self):
        provider = get_provider("mock")
        result = er.run_models(provider, ["mock/chat-base", "mock/chat-reasoning"], _sample_tasks(2))
        self.assertTrue(er.persist_compare_result(result, db_path=_DB_PATH))
        frame = Repository(_DB_PATH).list_df("live_run_responses")
        saved = frame[frame["run_id"] == result.run_id]
        self.assertEqual(len(saved), 4)
        self.assertEqual(set(saved["model_name"]), {"mock/chat-base", "mock/chat-reasoning"})


class JudgePromptBoundaryTests(unittest.TestCase):
    def test_judge_sees_gold_but_eval_model_never_does(self):
        task = {"case_id": "X-1", "task_type": "T", "scenario": "S", "question": "Q", "context": "C"}
        gold = {
            "core_conclusion": "GOLD-结论-应进入裁判",
            "must_have_points": ["GOLD要点A"],
            "unacceptable_errors": ["GOLD红线"],
        }
        judge_msgs = sc.build_judge_messages(task, "模型回答内容", gold, _DIMENSIONS)
        judge_joined = " ".join(m["content"] for m in judge_msgs)
        # 裁判应当看到 Gold。
        self.assertIn("GOLD-结论-应进入裁判", judge_joined)
        self.assertIn("GOLD红线", judge_joined)
        # 回归守卫：被评测模型的 prompt 仍不含 Gold。
        eval_joined = " ".join(m["content"] for m in er.build_messages({**task, **gold}))
        for leak in ["GOLD-结论-应进入裁判", "GOLD要点A", "GOLD红线"]:
            self.assertNotIn(leak, eval_joined)

    def test_judge_prompt_lists_all_dimensions(self):
        msgs = sc.build_judge_messages({"question": "Q"}, "ans", {}, _DIMENSIONS)
        joined = " ".join(m["content"] for m in msgs)
        for dim in _DIMENSIONS:
            self.assertIn(dim["field"], joined)
            self.assertIn(str(dim["full_mark"]), joined)


class JudgeParseTests(unittest.TestCase):
    def test_valid_json_clamps_and_sums(self):
        parsed = sc.parse_judge_output(_valid_judge_json({
            "accuracy_score": 40, "reasoning_score": 18, "coverage_score": 15,
            "evidence_score": 12, "expression_score": 10,
        }), _DIMENSIONS)
        self.assertTrue(parsed.ok)
        self.assertEqual(parsed.scores["accuracy_score"], 30)  # clamped from 40
        self.assertEqual(parsed.total, 30 + 18 + 15 + 12 + 10)

    def test_malformed_output_fails_without_fabrication(self):
        parsed = sc.parse_judge_output("完全不是 JSON 的文本", _DIMENSIONS)
        self.assertFalse(parsed.ok)
        self.assertIsNone(parsed.total)
        self.assertEqual(parsed.scores, {})

    def test_missing_dimension_fails(self):
        parsed = sc.parse_judge_output(_valid_judge_json({"accuracy_score": 20}), _DIMENSIONS)
        self.assertFalse(parsed.ok)


class ScoreCompareTests(unittest.TestCase):
    def _compare(self):
        provider = get_provider("mock")
        return er.run_models(provider, ["mock/chat-base", "mock/chat-reasoning"], _sample_tasks(1))

    def test_fake_judge_scores_each_outcome_pending(self):
        compare = self._compare()
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(1)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")
        self.assertEqual(len(result.outcomes), 2)  # both models' answers scored
        for o in result.outcomes:
            self.assertEqual(o.judge_status, STATUS_SUCCESS)
            self.assertEqual(o.review_status, "pending")
            self.assertEqual(o.total_score, 30 + 18 + 15 + 12 + 10)
            self.assertEqual(o.scores["accuracy_score"], 30)
        self.assertTrue(result.score_run_id.startswith("SCORE-"))

    def test_garbage_judge_marks_failed_no_fabrication(self):
        compare = self._compare()
        result = sc.score_compare(_GarbageJudge(), compare, {}, {}, _DIMENSIONS, judge_model_id="judge/x")
        for o in result.outcomes:
            self.assertEqual(o.judge_status, "failed")
            self.assertIsNone(o.total_score)
            self.assertTrue(all(v is None for v in o.scores.values()))

    def test_mock_judge_fabricates_nothing(self):
        compare = self._compare()
        result = sc.score_compare(get_provider("mock"), compare, {}, {}, _DIMENSIONS)
        self.assertTrue(sc.is_mock_score(result))
        for o in result.outcomes:
            self.assertEqual(o.judge_status, "mock")
            self.assertIsNone(o.total_score)
            self.assertTrue(all(v is None for v in o.scores.values()))


class ScorePersistenceTests(unittest.TestCase):
    def test_persist_and_confirm_review(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(1))
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(1)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")

        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))
        rows = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["review_status"], "pending")

        edited = {"accuracy_score": 25, "reasoning_score": 15, "coverage_score": 15,
                  "evidence_score": 10, "expression_score": 10}
        self.assertTrue(sc.confirm_score_review(int(row["id"]), edited, "复核已调整", db_path=_DB_PATH))

        after = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)[0]
        self.assertEqual(after["review_status"], "confirmed")
        self.assertEqual(int(after["accuracy_score"]), 25)
        self.assertEqual(int(after["total_score"]), 75)
        self.assertEqual(after["review_note"], "复核已调整")

    def test_bulk_confirm_only_pending_success_scores(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(2))
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(2)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")

        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))
        rows = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)
        row_ids = [int(row["id"]) for row in rows]
        note = "低风险评分草稿，经人工批量确认归档。"

        outcome = sc.confirm_score_reviews_bulk(row_ids, note, db_path=_DB_PATH)

        self.assertEqual(len(row_ids), outcome["confirmed"])
        self.assertEqual([], outcome["failed"])
        after = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)
        self.assertTrue(all(row["review_status"] == "confirmed" for row in after))
        self.assertTrue(all(row["review_note"] == note for row in after))

    def test_persist_returns_false_without_database(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(1))
        result = sc.score_compare(_FakeJudge(), compare, {}, {}, _DIMENSIONS, judge_model_id="judge/x")
        missing = Path(_TMP.name) / "nope.db"
        self.assertFalse(sc.persist_score_result(result, db_path=missing))

    def test_scoring_does_not_touch_seed_score_records(self):
        before = Repository(_DB_PATH).count("score_records")
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(2))
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(2)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")
        sc.persist_score_result(result, db_path=_DB_PATH)
        after = Repository(_DB_PATH).count("score_records")
        self.assertEqual(before, after)


class ServiceAndWiringTests(unittest.TestCase):
    def test_get_rubric_dimensions_returns_five(self):
        dims = ds.get_rubric_dimensions(_DB_PATH)
        self.assertEqual([d["field"] for d in dims], [d["field"] for d in _DIMENSIONS])
        self.assertEqual(sum(d["full_mark"] for d in dims), 100)

    def test_scoring_wired_through_console(self):
        # 评分仍可用，但入口从独立页迁到总览页控制台；live_eval 页已撤销。
        self.assertNotIn("live_eval", PAGES)
        from src.ui.eval_console import render_eval_console

        self.assertTrue(callable(render_eval_console))
        self.assertTrue(callable(sc.score_compare))


if __name__ == "__main__":
    unittest.main()
