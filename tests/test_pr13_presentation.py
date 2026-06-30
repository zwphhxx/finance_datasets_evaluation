"""PR-13 tests: overview insight numbers stay dynamic and task fields are
presented in business Chinese without leaking raw English field values.
"""

import unittest

from src.data_service import load_all_data
from src.ui import overview, tasks


class OverviewPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_insight_cards_are_three_and_data_driven(self):
        cards = overview.get_overview_insight_cards(self.data)
        self.assertEqual(["样本资产", "评测机制", "数据优化价值"], [c["label"] for c in cards])

        # Numbers must match the loaded data, never hardcoded.
        self.assertEqual(len(self.data.tasks), cards[0]["value"])
        self.assertEqual(self.data.model_outputs["model_name"].nunique(), cards[1]["value"])
        self.assertEqual(len(self.data.optimizations), cards[2]["value"])

        domain_count = self.data.tasks["domain"].nunique()
        self.assertIn(str(domain_count), cards[0]["note"])

    def test_summary_items_cover_core_assets_with_live_counts(self):
        items = dict(overview.get_overview_summary_items(self.data))
        self.assertIn("任务样本", items)
        self.assertIn("模型回答", items)
        self.assertIn(str(self.data.model_outputs["model_name"].nunique()), items["模型回答"])

    def test_loop_steps_unchanged(self):
        self.assertEqual(
            ["专业任务", "Gold Answer", "模型回答", "Rubric 评分", "错误归因", "数据补强", "复测验证"],
            overview.get_evaluation_loop_steps(),
        )


class TaskPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.records = tasks.build_task_records(self.data.tasks)
        self.table = tasks.build_task_table(self.data.tasks)

    def test_records_match_row_count(self):
        self.assertEqual(len(self.data.tasks), len(self.records))

    def test_known_field_values_are_translated_to_chinese(self):
        record_by_case = {r["case_id"]: r for r in self.records}
        sample = record_by_case["CM-001"]
        self.assertEqual("资本市场", sample["domain_label"])
        self.assertEqual("监管合规分析", sample["task_type_label"])
        self.assertEqual("高难度", sample["difficulty_label"])
        self.assertEqual("高风险", sample["risk_label"])
        self.assertEqual("high", sample["difficulty_badge"])
        self.assertEqual("high", sample["risk_badge"])

    def test_unmapped_values_fall_back_to_raw(self):
        self.assertEqual("Unknown Domain", tasks.display_label("Unknown Domain", tasks.DOMAIN_LABELS))
        self.assertEqual("未标注", tasks.display_label("", tasks.DOMAIN_LABELS))

    def test_long_text_is_summarized(self):
        long_text = "甲" * 400
        summary = tasks.summarize_text(long_text)
        self.assertLessEqual(len(summary), tasks.SUMMARY_LIMIT + 1)
        self.assertTrue(summary.endswith("…"))

    def test_table_uses_business_chinese_headers_in_order(self):
        self.assertEqual(
            ["案例编号", "领域", "任务类型", "难度", "风险等级", "考察能力", "任务摘要"],
            list(self.table.columns),
        )

    def test_table_does_not_leak_raw_english_field_values(self):
        flattened = self.table.astype(str).values.ravel().tolist()
        for raw in ("Capital Markets", "Regulatory Analysis", "Hard", "Medium"):
            self.assertNotIn(raw, flattened)


if __name__ == "__main__":
    unittest.main()
