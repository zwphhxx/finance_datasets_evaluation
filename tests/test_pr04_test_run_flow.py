"""PR-04 tests: the test-run page behaves like an evaluation execution flow."""

import unittest

from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import scorer as sc
from src.ui.test_run import (
    build_run_plan_summary,
    build_sample_options,
    build_score_summary_rows,
    get_advanced_setting_items,
    get_test_run_steps,
)


class TestRunFlowStructureTests(unittest.TestCase):
    def test_main_steps_are_execution_flow(self):
        self.assertEqual(
            ["选择样本", "选择对比模型", "运行模型回答", "生成评分草稿"],
            get_test_run_steps(),
        )

    def test_advanced_settings_keep_technical_controls_collapsed(self):
        items = get_advanced_setting_items()
        for expected in [
            "模型服务 provider",
            "连通性检查",
            "加载 / 刷新模型列表",
            "手动追加模型 ID",
            "temperature",
            "max_tokens",
            "trace_id",
            "HTTP 状态码",
            "错误码和原始错误信息",
        ]:
            self.assertIn(expected, items)


class SampleSelectionTests(unittest.TestCase):
    def test_sample_options_use_unified_readiness_and_compact_labels(self):
        tasks = [
            {
                "case_id": "A",
                "status": ds.ACTIVE_STATUS,
                "question": "这是一段较长的任务题干" * 8,
                "context": "背景",
                "scenario": "财务尽调",
                "task_type": "risk_identification",
            },
            {
                "case_id": "B",
                "status": ds.DRAFT_STATUS,
                "question": "题干",
                "context": "背景",
                "scenario": "法律尽调",
                "task_type": "analysis",
            },
        ]
        gold_map = {
            "A": {
                "core_conclusion": "结论",
                "must_have_points": ["覆盖点"],
                "unacceptable_errors": ["错误"],
            },
            "B": {
                "core_conclusion": "结论",
                "must_have_points": ["覆盖点"],
                "unacceptable_errors": ["错误"],
            },
        }
        dimensions = [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}]

        options = build_sample_options(tasks, gold_map, dimensions)

        self.assertEqual(["A"], [item["case_id"] for item in options])
        self.assertIn("A", options[0]["label"])
        self.assertIn("财务尽调", options[0]["label"])
        self.assertLessEqual(len(options[0]["label"]), 90)
        self.assertNotIn("Gold", options[0]["label"])
        self.assertNotIn("Rubric", options[0]["label"])


class RunPlanTests(unittest.TestCase):
    def test_run_plan_summary_disables_without_samples_or_models(self):
        self.assertFalse(build_run_plan_summary([], [{"case_id": "A"}])["can_run"])
        self.assertFalse(build_run_plan_summary(["m1"], [])["can_run"])

    def test_run_plan_summary_counts_expected_responses(self):
        summary = build_run_plan_summary(["m1", "m2"], [{"case_id": "A"}, {"case_id": "B"}])

        self.assertEqual(2, summary["model_count"])
        self.assertEqual(2, summary["sample_count"])
        self.assertEqual(4, summary["planned_responses"])
        self.assertTrue(summary["can_run"])


class ScoreDraftTests(unittest.TestCase):
    def test_score_summary_rows_use_dynamic_dimensions_and_pending_review(self):
        dimensions = [
            {"field": "accuracy_score", "name": "准确性", "full_mark": 30},
            {"field": "coverage_score", "name": "覆盖度", "full_mark": 20},
        ]
        result = sc.ScoreResult(
            score_run_id="S1",
            run_id="R1",
            judge_provider="mock",
            judge_model="judge",
            mode="mock",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="A",
                    task_type="analysis",
                    eval_model="m1",
                    judge_provider="mock",
                    judge_model="judge",
                    judge_status="success",
                    scores={"accuracy_score": 20, "coverage_score": 10},
                    total_score=30,
                ),
            ),
        )

        rows = build_score_summary_rows(result, dimensions)

        self.assertEqual("m1", rows[0]["模型"])
        self.assertEqual("A", rows[0]["样本"])
        self.assertEqual("20", rows[0]["准确性"])
        self.assertEqual("10", rows[0]["覆盖度"])
        self.assertEqual("30", rows[0]["总分"])
        self.assertEqual("待人工复核", rows[0]["裁判状态"])


class ScoringInputTests(unittest.TestCase):
    def test_score_compare_only_scores_successful_answers(self):
        compare = er.CompareRunResult(
            run_id="R1",
            provider="mock",
            model_ids=("m1", "m2"),
            mode="mock",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                er.RunOutcome("A", "analysis", "mock", "m1", "mock", True, answer_text="回答"),
                er.RunOutcome("A", "analysis", "mock", "m2", "failed", False, error_message="失败"),
            ),
        )
        dimensions = [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}]

        result = sc.score_compare(
            provider=_MockJudgeProvider(),
            compare_result=compare,
            gold_map={"A": {"core_conclusion": "结论"}},
            tasks_by_case={"A": {"case_id": "A", "question": "题干"}},
            dimensions=dimensions,
        )

        self.assertEqual(1, len(result.outcomes))
        self.assertEqual("m1", result.outcomes[0].eval_model)


class _MockJudgeProvider:
    name = "mock"

    def generate_response(self, *args, **kwargs):  # pragma: no cover - mock provider scoring does not call this.
        raise AssertionError("mock scorer should not call provider.generate_response")


if __name__ == "__main__":
    unittest.main()
