"""PR-04 tests: the test-run page behaves like an evaluation execution flow."""

import unittest
from pathlib import Path

from app.models.base import ModelInfo
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import scorer as sc
from src.ui.test_run import (
    build_model_selection_options,
    build_remaining_queue_items,
    build_run_plan_summary,
    build_run_queue_items,
    build_sample_options,
    build_sample_selection_rows,
    build_score_summary_rows,
    filter_sample_selection_options,
    get_advanced_setting_items,
    get_test_run_steps,
    _siliconflow_balance_text,
)


class TestRunFlowStructureTests(unittest.TestCase):
    def test_main_steps_are_execution_flow(self):
        self.assertEqual(
            ["评测配置", "运行结果", "评分草稿"],
            get_test_run_steps(),
        )

    def test_advanced_settings_keep_technical_controls_collapsed(self):
        self.assertEqual([], get_advanced_setting_items())

    def test_selection_controls_are_dialog_driven(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

        self.assertIn('@st.dialog("选择样本"', source)
        self.assertIn('@st.dialog("选择模型"', source)
        self.assertIn("st.data_editor", source)
        self.assertIn('CheckboxColumn("选择"', source)
        self.assertIn("关键词搜索", source)
        self.assertIn("当前没有符合条件的可测样本", source)
        self.assertIn("模型服务：", source)
        self.assertIn("硅基流动", source)
        self.assertIn('st.text_input(\n            "搜索模型"', source)
        self.assertIn("输入模型名称、厂商或关键词", source)
        self.assertIn('st.selectbox("模型"', source)
        self.assertIn("添加到对比列表", source)
        self.assertIn("test_run_model_dialog_selected", source)
        self.assertIn("移除", source)
        self.assertIn("test_run_selected_cases", source)
        self.assertIn("test_run_selected_models", source)
        self.assertIn("test_run_cases_dialog_selected", source)
        self.assertNotIn('render_numbered_section("04"', source)
        self.assertNotIn("st.multiselect(", source)
        self.assertNotIn('st.multiselect(\n        "选择样本"', source)
        self.assertNotIn('st.multiselect("选择对比模型"', source)
        self.assertNotIn("st.checkbox", source)
        self.assertNotIn("test_run_model_check_", source)
        self.assertNotIn("模型服务 provider", source)
        self.assertNotIn('st.expander("高级设置"', source)
        self.assertNotIn("加载 / 刷新模型列表", source)
        self.assertNotIn("手动追加模型 ID", source)
        self.assertNotIn('st.slider("temperature"', source)
        self.assertNotIn('number_input(\n            "max_tokens"', source)
        self.assertNotIn("账户余额：未获取", source)

    def test_run_execution_streams_queue_items_in_page(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        panel_source = source[
            source.index("def _render_configuration_panel"):
            source.index("def _open_sample_dialog")
        ]
        run_button_source = source[
            source.index("def _render_run_button"):
            source.index("def _render_live_run_queue")
        ]

        self.assertIn("运行队列", source)
        self.assertIn("已完成结果", source)
        self.assertIn("等待中", source)
        self.assertIn("已完成回答已保留", source)
        self.assertIn("继续未完成项", source)
        self.assertIn("放弃本次运行", source)
        self.assertIn("er.run_single", source)
        self.assertIn("er.CompareRunResult", source)
        self.assertIn("查看全文", source)
        self.assertIn('@st.dialog("模型回答全文"', source)
        self.assertIn("查看技术明细", source)
        self.assertIn('@st.dialog("技术明细"', source)
        self.assertIn("仅对已完成回答生成评分草稿", source)
        self.assertIn("start_run = _render_run_button(", panel_source)
        self.assertIn("if start_run:", panel_source)
        self.assertLess(panel_source.index("with col3:"), panel_source.index("if start_run:"))
        self.assertLess(panel_source.index("if start_run:"), panel_source.index("_execute_run_queue("))
        self.assertNotIn("_execute_run_queue(", run_button_source)
        self.assertNotIn("progress_callback=_on_progress", source)
        self.assertNotIn('st.expander("查看回答"', source)
        self.assertNotIn('st.expander("查看全部回答"', source)

    def test_model_selection_options_are_bounded_and_searchable(self):
        models = [
            ModelInfo(
                id=f"Vendor/Model-{idx}",
                provider="siliconflow",
                object="model",
                owned_by="Vendor",
                raw={"display_name": f"Finance Model {idx}"},
            )
            for idx in range(35)
        ]
        options, matched_count = build_model_selection_options(models, "")

        self.assertEqual(30, len(options))
        self.assertEqual(35, matched_count)
        self.assertEqual("Vendor/Model-0", options[0])

    def test_model_selection_search_uses_id_name_and_owner_case_insensitively(self):
        models = [
            ModelInfo(
                id="Alpha/General",
                provider="siliconflow",
                object="model",
                owned_by="Alpha",
                raw={"display_name": "General Chat"},
            ),
            ModelInfo(
                id="Beta/Risk",
                provider="siliconflow",
                object="model",
                owned_by="BetaLab",
                raw={"display_name": "Finance Risk"},
            ),
        ]

        self.assertEqual(["Beta/Risk"], build_model_selection_options(models, "finance")[0])
        self.assertEqual(["Beta/Risk"], build_model_selection_options(models, "betalab")[0])
        self.assertEqual(["Alpha/General"], build_model_selection_options(models, "alpha/general")[0])

    def test_balance_text_is_optional(self):
        class _NoBalanceProvider:
            def get_balance(self):
                return None

        class _NumericBalanceProvider:
            def get_balance(self):
                return 12.345

        class _EmptyBalanceProvider:
            def get_balance(self):
                return " "

        self.assertIsNone(_siliconflow_balance_text(_NoBalanceProvider()))
        self.assertIsNone(_siliconflow_balance_text(_EmptyBalanceProvider()))
        self.assertEqual("¥12.35", _siliconflow_balance_text(_NumericBalanceProvider()))


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

    def test_sample_dialog_filters_use_search_scene_and_difficulty(self):
        sample_options = [
            {
                "case_id": "A",
                "title": "收入确认风险",
                "scenario": "财务尽调",
                "difficulty": "中等",
                "task": {"question": "识别收入确认问题", "context": "合同背景"},
            },
            {
                "case_id": "B",
                "title": "诉讼风险",
                "scenario": "法律审核",
                "difficulty": "困难",
                "task": {"question": "核查重大诉讼", "context": "法律背景"},
            },
        ]

        self.assertEqual(["A"], [
            item["case_id"]
            for item in filter_sample_selection_options(sample_options, "合同", "全部", "全部")
        ])
        self.assertEqual(["B"], [
            item["case_id"]
            for item in filter_sample_selection_options(sample_options, "", "法律审核", "困难")
        ])
        self.assertEqual([], filter_sample_selection_options(sample_options, "不存在", "全部", "全部"))

    def test_sample_selection_rows_are_compact_and_mark_selected(self):
        sample_options = [
            {
                "case_id": "A",
                "title": "收入确认风险",
                "scenario": "财务尽调",
                "difficulty": "中等",
                "task": {"question": "不应展示完整题干"},
            },
            {
                "case_id": "B",
                "title": "诉讼风险",
                "scenario": "法律审核",
                "difficulty": "困难",
                "task": {"question": "不应展示完整题干"},
            },
        ]

        rows = build_sample_selection_rows(sample_options, ["B"])

        self.assertEqual(["选择", "样本编号", "任务标题", "场景", "难度", "测试状态"], list(rows[0].keys()))
        self.assertFalse(rows[0]["选择"])
        self.assertTrue(rows[1]["选择"])
        self.assertEqual("可测试", rows[0]["测试状态"])
        self.assertNotIn("不应展示完整题干", str(rows))


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

    def test_run_queue_items_dedupe_models_and_preserve_order(self):
        queue = build_run_queue_items(
            ["m1", "m1", "m2"],
            [{"case_id": "A"}, {"case_id": "B"}],
        )

        self.assertEqual(
            [("m1", "A"), ("m1", "B"), ("m2", "A"), ("m2", "B")],
            [(item["model_id"], item["case_id"]) for item in queue],
        )

    def test_remaining_queue_items_use_completed_model_case_pairs(self):
        queue = build_run_queue_items(["m1", "m2"], [{"case_id": "A"}, {"case_id": "B"}])
        outcomes = [
            er.RunOutcome("A", "", "mock", "m1", "mock", True, answer_text="ok"),
            er.RunOutcome("B", "", "mock", "m2", "failed", False, error_code="timeout"),
        ]

        remaining = build_remaining_queue_items(queue, outcomes)

        self.assertEqual(
            [("m1", "B"), ("m2", "A")],
            [(item["model_id"], item["case_id"]) for item in remaining],
        )


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
