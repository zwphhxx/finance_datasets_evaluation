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

import pandas as pd

from app.models.base import GenerationResult, ModelProvider, STATUS_FAILED, STATUS_SUCCESS
from app.models.registry import get_provider
from app.services import conclusions as cc
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


class _SequenceJudge(ModelProvider):
    name = "sequencejudge"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.kwargs_seen = []

    def list_models(self, model_type="text", sub_type="chat"):
        raise NotImplementedError

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        self.calls += 1
        self.kwargs_seen.append(dict(kwargs))
        item = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if item == "success":
            scores = {
                "accuracy_score": 26,
                "reasoning_score": 18,
                "coverage_score": 18,
                "evidence_score": 13,
                "expression_score": 13,
            }
            return GenerationResult(
                self.name,
                model_id,
                STATUS_SUCCESS,
                response_text=_valid_judge_json(scores),
            )
        return GenerationResult(
            self.name,
            model_id,
            STATUS_FAILED,
            error_code=str(item),
            error_message=f"{item} failed",
        )


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

    def test_retryable_judge_error_retries_until_success(self):
        provider = _SequenceJudge(["timeout", "success"])
        sleeps = []

        outcome = sc.score_single(
            provider,
            "judge/x",
            {"case_id": "C1", "task_type": "analysis", "question": "Q"},
            "模型回答",
            {},
            _DIMENSIONS,
            eval_model="vendor/model",
            retry_delays=(0, 0),
            sleep_fn=sleeps.append,
        )

        self.assertTrue(outcome.ok)
        self.assertEqual(2, provider.calls)
        self.assertEqual(1, outcome.retry_count)
        self.assertEqual([0], sleeps)

    def test_retryable_judge_error_stops_after_two_retries(self):
        provider = _SequenceJudge(["timeout", "gateway_timeout", "rate_limited"])
        sleeps = []

        outcome = sc.score_single(
            provider,
            "judge/x",
            {"case_id": "C1", "task_type": "analysis", "question": "Q"},
            "模型回答",
            {},
            _DIMENSIONS,
            eval_model="vendor/model",
            retry_delays=(0, 0),
            sleep_fn=sleeps.append,
        )

        self.assertEqual("failed", outcome.judge_status)
        self.assertEqual(3, provider.calls)
        self.assertEqual(2, outcome.retry_count)
        self.assertEqual([0, 0], sleeps)
        self.assertIn("已重试 2 次", outcome.error_message)

    def test_non_retryable_judge_errors_do_not_retry(self):
        for error_code in [
            "unauthorized",
            "bad_request",
            "not_found",
            "missing_api_key",
            "judge_parse_error",
            "invalid_response",
        ]:
            provider = _SequenceJudge([error_code, "success"])
            outcome = sc.score_single(
                provider,
                "judge/x",
                {"case_id": "C1", "task_type": "analysis", "question": "Q"},
                "模型回答",
                {},
                _DIMENSIONS,
                eval_model="vendor/model",
                retry_delays=(0, 0),
                sleep_fn=lambda _: None,
            )
            self.assertEqual("failed", outcome.judge_status, error_code)
            self.assertEqual(1, provider.calls, error_code)
            self.assertEqual(0, outcome.retry_count, error_code)

    def test_score_compare_continues_when_one_score_fails_after_retries(self):
        compare = self._compare()
        provider = _SequenceJudge(["timeout", "timeout", "timeout", "success"])

        result = sc.score_compare(
            provider,
            compare,
            {},
            {},
            _DIMENSIONS,
            judge_model_id="judge/x",
            retry_delays=(0, 0),
            sleep_fn=lambda _: None,
        )

        self.assertEqual(2, len(result.outcomes))
        self.assertEqual(["failed", "success"], [outcome.judge_status for outcome in result.outcomes])
        self.assertEqual(4, provider.calls)


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

    def test_confirm_review_returns_false_when_row_missing(self):
        edited = {"accuracy_score": 25, "reasoning_score": 15, "coverage_score": 15,
                  "evidence_score": 10, "expression_score": 10}

        self.assertFalse(sc.confirm_score_review(99999999, edited, "不存在的评分", db_path=_DB_PATH))

    def test_skip_review_returns_false_when_row_missing(self):
        self.assertFalse(sc.skip_score_review(99999999, "暂不采用：不存在的评分", db_path=_DB_PATH))

    def test_confirm_review_returns_false_when_row_already_processed(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(1))
        result = sc.score_compare(_FakeJudge(), compare, {}, {}, _DIMENSIONS, judge_model_id="judge/x")
        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))
        row = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)[0]
        edited = {"accuracy_score": 25, "reasoning_score": 15, "coverage_score": 15,
                  "evidence_score": 10, "expression_score": 10}

        self.assertTrue(sc.confirm_score_review(int(row["id"]), edited, "首次确认", db_path=_DB_PATH))
        self.assertFalse(sc.confirm_score_review(int(row["id"]), edited, "重复确认", db_path=_DB_PATH))

    def test_confirm_review_returns_false_for_failed_judge_score(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(1))
        result = sc.score_compare(_GarbageJudge(), compare, {}, {}, _DIMENSIONS, judge_model_id="judge/x")
        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))
        row = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)[0]
        edited = {"accuracy_score": 25, "reasoning_score": 15, "coverage_score": 15,
                  "evidence_score": 10, "expression_score": 10}

        self.assertFalse(sc.confirm_score_review(int(row["id"]), edited, "失败评分不能确认", db_path=_DB_PATH))

    def test_incremental_score_persist_dedupes_final_persist(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(1))
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(1)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")
        outcome = result.outcomes[0]

        self.assertTrue(
            sc.persist_score_outcome(
                result.score_run_id,
                result.run_id,
                result.judge_provider,
                result.judge_model,
                result.mode,
                outcome,
                db_path=_DB_PATH,
            )
        )
        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))

        rows = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)
        self.assertEqual(1, len(rows))
        self.assertEqual("pending", rows[0]["review_status"])
        self.assertEqual(outcome.case_id, rows[0]["case_id"])
        self.assertEqual(outcome.eval_model, rows[0]["eval_model"])

    def test_score_queue_is_created_before_scoring_and_recovers_status(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(2))
        queue_items = list(compare.outcomes)
        score_run_id = "SCORE-QUEUE-RECOVER"

        self.assertTrue(
            sc.initialize_score_queue(
                score_run_id,
                compare.run_id,
                queue_items,
                "fakejudge",
                "judge/x",
                db_path=_DB_PATH,
            )
        )
        queued = sc.load_score_queue(score_run_id, db_path=_DB_PATH)
        self.assertEqual(2, len(queued))
        self.assertEqual({"queued"}, {row["status"] for row in queued})

        first = queue_items[0]
        sc.mark_score_queue_item_running(score_run_id, first.case_id, first.model_id, db_path=_DB_PATH)
        score = sc.score_single(
            _FakeJudge(),
            "judge/x",
            _sample_tasks(1)[0],
            first.answer_text,
            {},
            _DIMENSIONS,
            eval_model=first.model_id,
        )
        self.assertTrue(
            sc.persist_score_outcome(
                score_run_id,
                compare.run_id,
                "fakejudge",
                "judge/x",
                "live",
                score,
                db_path=_DB_PATH,
            )
        )

        summary = sc.summarize_score_queue(score_run_id, db_path=_DB_PATH)
        self.assertEqual(1, summary["success"])
        self.assertEqual(1, summary["queued"])
        restored = sc.restore_score_result_from_db(score_run_id, db_path=_DB_PATH)
        self.assertIsNotNone(restored)
        self.assertEqual(1, len(restored.outcomes))
        self.assertEqual("success", restored.outcomes[0].judge_status)

    def test_score_queue_failed_items_do_not_enter_pending_confirmation(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(1))
        score_run_id = "SCORE-QUEUE-FAILED"
        run_outcome = compare.outcomes[0]
        sc.initialize_score_queue(
            score_run_id,
            compare.run_id,
            [run_outcome],
            "fakejudge",
            "judge/x",
            db_path=_DB_PATH,
        )
        failed = sc.ScoreOutcome(
            case_id=run_outcome.case_id,
            task_type=run_outcome.task_type,
            eval_model=run_outcome.model_id,
            judge_provider="fakejudge",
            judge_model="judge/x",
            judge_status="failed",
            scores={field["field"]: None for field in _DIMENSIONS},
            total_score=None,
            error_code="timeout",
            error_message="请求超时",
        )
        sc.persist_score_outcome(score_run_id, compare.run_id, "fakejudge", "judge/x", "live", failed, db_path=_DB_PATH)

        queue = sc.load_score_queue(score_run_id, db_path=_DB_PATH)
        self.assertEqual("failed", queue[0]["status"])
        retry_items = sc.queue_items_for_status(score_run_id, {"failed"}, db_path=_DB_PATH)
        self.assertEqual([(run_outcome.case_id, run_outcome.model_id)], [(item["case_id"], item["eval_model"]) for item in retry_items])
        rows = sc.load_score_rows(score_run_id, db_path=_DB_PATH)
        self.assertEqual("failed", rows[0]["judge_status"])
        self.assertNotEqual("confirmed", rows[0]["review_status"])

    def test_failed_score_row_can_be_updated_by_retry_success_without_duplicate(self):
        failed = sc.ScoreOutcome(
            case_id="C-RETRY",
            task_type="analysis",
            eval_model="vendor/model-retry",
            judge_provider="fakejudge",
            judge_model="judge/x",
            judge_status="failed",
            scores={field["field"]: None for field in _DIMENSIONS},
            total_score=None,
            error_code="timeout",
            error_message="请求超时。已重试 2 次。",
            retry_count=2,
        )
        success = sc.ScoreOutcome(
            case_id="C-RETRY",
            task_type="analysis",
            eval_model="vendor/model-retry",
            judge_provider="fakejudge",
            judge_model="judge/x",
            judge_status="success",
            scores={
                "accuracy_score": 26,
                "reasoning_score": 18,
                "coverage_score": 18,
                "evidence_score": 13,
                "expression_score": 13,
            },
            total_score=88,
            rationale={"accuracy_score": "依据充分"},
            review_note="重试后评分成功",
            retry_count=1,
        )

        for outcome in [failed, success]:
            self.assertTrue(
                sc.persist_score_outcome(
                    "SCORE-RETRY-UPDATE",
                    "RUN-RETRY-UPDATE",
                    "fakejudge",
                    "judge/x",
                    "live",
                    outcome,
                    db_path=_DB_PATH,
                )
            )

        rows = sc.load_score_rows("SCORE-RETRY-UPDATE", db_path=_DB_PATH)
        self.assertEqual(1, len(rows))
        self.assertEqual("success", rows[0]["judge_status"])
        self.assertEqual(88, int(rows[0]["total_score"]))
        self.assertEqual("pending", rows[0]["review_status"])

    def test_skip_score_review_marks_not_adopted(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(1))
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(1)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")

        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))
        row = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)[0]

        self.assertTrue(sc.skip_score_review(int(row["id"]), "暂不采用：需补充材料", db_path=_DB_PATH))

        after = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)[0]
        self.assertEqual("skipped", after["review_status"])
        self.assertEqual("暂不采用：需补充材料", after["review_note"])

    def test_bulk_confirm_only_pending_success_scores(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(2))
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(2)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")

        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))
        rows = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)
        row_ids = [int(row["id"]) for row in rows]
        note = "低风险评分草稿，经人工批量确认生效。"

        outcome = sc.confirm_score_reviews_bulk(row_ids, note, db_path=_DB_PATH)

        self.assertEqual(len(row_ids), outcome["confirmed"])
        self.assertEqual(len(row_ids), outcome["confirmed_count"])
        self.assertEqual(sorted(row_ids), sorted(outcome["confirmed_ids"]))
        self.assertEqual([], outcome["failed_ids"])
        self.assertEqual("已确认 2 条评分。", outcome["summary"])
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

    def test_export_defaults_to_confirmed_and_can_include_pending(self):
        provider = get_provider("mock")
        compare = er.run_models(provider, ["mock/chat-base"], _sample_tasks(2))
        tasks_by_case = {str(r["case_id"]): r for r in _sample_tasks(2)}
        result = sc.score_compare(_FakeJudge(), compare, {}, tasks_by_case, _DIMENSIONS, judge_model_id="judge/x")

        self.assertTrue(sc.persist_score_result(result, db_path=_DB_PATH))
        rows = sc.load_score_rows(result.score_run_id, db_path=_DB_PATH)
        self.assertEqual(2, len(rows))
        first_id = int(rows[0]["id"])
        edited = {
            "accuracy_score": 25,
            "reasoning_score": 15,
            "coverage_score": 15,
            "evidence_score": 10,
            "expression_score": 10,
        }
        self.assertTrue(sc.confirm_score_review(first_id, edited, "确认用于导出", db_path=_DB_PATH))

        confirmed_only = [
            row for row in sc.load_exportable_score_rows(db_path=_DB_PATH)
            if row["score_run_id"] == result.score_run_id
        ]
        self.assertEqual(1, len(confirmed_only))
        self.assertEqual("confirmed", confirmed_only[0]["review_status"])

        with_pending = [
            row for row in sc.load_exportable_score_rows(include_pending=True, db_path=_DB_PATH)
            if row["score_run_id"] == result.score_run_id
        ]
        self.assertEqual(["confirmed", "pending"], sorted(row["review_status"] for row in with_pending))
        payload = sc.build_score_export_payload(confirmed_only)
        text = sc.serialize_score_export_payload(payload)
        self.assertEqual("confirmed_score_export", payload["export_type"])
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("财务/法律/投行场景大模型对比评测", payload["project_name"])
        self.assertEqual("confirmed", payload["scope"])
        self.assertEqual(1, len(payload["records"]))
        self.assertNotIn("rows", payload)
        self.assertIn(sc.SCORE_EXPORT_TYPE, text)
        self.assertNotIn("api_key", text.lower())
        self.assertNotIn("authorization", text.lower())
        forbidden = {"trace_id", "error_code", "error_message", "latency_ms", "input_tokens", "output_tokens", "total_tokens"}
        self.assertTrue(forbidden.isdisjoint(payload["records"][0]))

    def test_export_excludes_skipped_failed_seed_and_inactive_rows(self):
        repo = Repository(_DB_PATH)
        score_run_id = "SCORE-EXPORT-FILTER"
        base = {
            "score_run_id": score_run_id,
            "run_id": "RUN-EXPORT-FILTER",
            "case_id": "CM-001",
            "task_type": "demo",
            "judge_provider": "fakejudge",
            "judge_model": "judge/x",
            "judge_mode": "live",
            "judge_status": "success",
            "accuracy_score": 25,
            "reasoning_score": 15,
            "coverage_score": 15,
            "evidence_score": 10,
            "expression_score": 10,
            "total_score": 75,
            "rationale": "{}",
            "review_note": "导出过滤测试",
            "status": "active",
        }
        rows = [
            {**base, "case_id": "CM-001", "eval_model": "vendor/model-confirmed", "review_status": "confirmed"},
            {**base, "case_id": "CM-002", "eval_model": "vendor/model-pending", "review_status": "pending"},
            {**base, "case_id": "CM-003", "eval_model": "vendor/model-skipped", "review_status": "skipped"},
            {**base, "case_id": "CM-004", "eval_model": "vendor/model-failed", "judge_status": "failed", "review_status": "confirmed"},
            {**base, "case_id": "CM-005", "eval_model": "Model_A_baseline", "review_status": "confirmed"},
            {**base, "case_id": "CM-006", "eval_model": "vendor/model-inactive", "review_status": "confirmed", "status": "inactive"},
        ]
        for row in rows:
            repo.insert("live_run_scores", row)

        confirmed_only = [
            row for row in sc.load_exportable_score_rows(db_path=_DB_PATH)
            if row["score_run_id"] == score_run_id
        ]
        self.assertEqual(["vendor/model-confirmed"], [row["eval_model"] for row in confirmed_only])

        with_pending = [
            row for row in sc.load_exportable_score_rows(include_pending=True, db_path=_DB_PATH)
            if row["score_run_id"] == score_run_id
        ]
        self.assertEqual(
            ["vendor/model-confirmed", "vendor/model-pending"],
            sorted(row["eval_model"] for row in with_pending),
        )

    def test_import_project_exported_scores_and_skip_duplicates(self):
        source_rows = [
            {
                "score_run_id": "SCORE-IMPORT-1",
                "run_id": "RUN-IMPORT-1",
                "case_id": "CM-001",
                "task_type": "demo",
                "eval_model": "vendor/model-import",
                "judge_provider": "fakejudge",
                "judge_model": "judge/x",
                "judge_mode": "live",
                "judge_status": "success",
                "accuracy_score": 25,
                "reasoning_score": 15,
                "coverage_score": 15,
                "evidence_score": 10,
                "expression_score": 10,
                "total_score": 75,
                "rationale": {"accuracy_score": "依据充分"},
                "review_note": "导入确认记录",
                "review_status": "confirmed",
                "status": "active",
            }
        ]
        payload = sc.build_score_export_payload(source_rows)
        text = sc.serialize_score_export_payload(payload)
        parsed = sc.parse_score_import_content("confirmed_scores.json", text)
        self.assertTrue(parsed["ok"], parsed["errors"])

        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "imported.db"
            ds.initialize_database(target_db, force=True)
            result = sc.import_score_rows(parsed["rows"], db_path=target_db)
            self.assertEqual(1, result["imported_count"])
            self.assertEqual(0, result["failed_count"])

            imported = Repository(target_db).list_df("live_run_scores")
            matched = imported[imported["score_run_id"] == "SCORE-IMPORT-1"]
            self.assertEqual(1, len(matched))
            self.assertEqual("confirmed", matched.iloc[0]["review_status"])
            confirmed, pending = cc.split_live_scores(imported)
            summary = cc.summarize_formal(pd.DataFrame(), confirmed)
            self.assertEqual(1, summary["confirmed_rows"])
            self.assertEqual(0, len(pending))

            duplicate = sc.import_score_rows(parsed["rows"], duplicate_action="skip", db_path=target_db)
            self.assertEqual(0, duplicate["imported_count"])
            self.assertEqual(1, duplicate["skipped_count"])

    def test_import_rejects_seed_models_and_sensitive_fields(self):
        bad_rows = [
            {
                "score_run_id": "SCORE-BAD",
                "run_id": "RUN-BAD",
                "case_id": "CM-001",
                "eval_model": "Model_A_baseline",
                "judge_model": "judge/x",
                "judge_status": "success",
                "total_score": 80,
                "review_status": "confirmed",
            },
            {
                "score_run_id": "SCORE-BAD2",
                "run_id": "RUN-BAD",
                "case_id": "CM-001",
                "eval_model": "vendor/model",
                "judge_model": "judge/x",
                "judge_status": "success",
                "total_score": 80,
                "review_status": "confirmed",
                "Authorization": "secret",
            },
        ]
        parsed = sc.validate_score_import_rows(bad_rows)
        self.assertFalse(parsed["ok"])
        self.assertEqual([], parsed["rows"])
        self.assertTrue(any("示例模型" in error for error in parsed["errors"]))
        self.assertTrue(any("敏感字段" in error for error in parsed["errors"]))

    def test_import_rejects_non_project_export_and_missing_fields(self):
        not_project = sc.parse_score_import_content(
            "other.json",
            '{"export_type":"other","schema_version":1,"records":[]}',
        )
        self.assertFalse(not_project["ok"])
        self.assertTrue(any("不是项目导出的" in error for error in not_project["errors"]))

        missing = sc.parse_score_import_content(
            "confirmed_scores.json",
            '{"export_type":"confirmed_score_export","schema_version":1,"records":[{"case_id":"C1"}]}',
        )
        self.assertFalse(missing["ok"])
        self.assertTrue(any("缺少必要字段" in error for error in missing["errors"]))

    def test_demo_score_export_file_can_be_loaded_or_reports_missing(self):
        payload = sc.load_demo_score_export_payload()

        self.assertEqual("confirmed_score_export", payload["export_type"])
        self.assertEqual(1, payload["schema_version"])
        self.assertIn("records", payload)


class ServiceAndWiringTests(unittest.TestCase):
    def test_get_rubric_dimensions_returns_five(self):
        dims = ds.get_rubric_dimensions(_DB_PATH)
        self.assertEqual([d["field"] for d in dims], [d["field"] for d in _DIMENSIONS])
        self.assertEqual(sum(d["full_mark"] for d in dims), 100)

    def test_scoring_wired_through_current_test_run_page(self):
        # 评分仍可用，但入口收敛到「发起评测」页；live_eval 页已撤销。
        self.assertNotIn("live_eval", PAGES)
        from src.ui.test_run import render_test_run_page

        self.assertTrue(callable(render_test_run_page))
        self.assertTrue(callable(sc.score_compare))


if __name__ == "__main__":
    unittest.main()
