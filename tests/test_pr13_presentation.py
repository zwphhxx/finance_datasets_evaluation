"""PR-13 tests: project-intro numbers stay dynamic and task fields are
presented in business Chinese without leaking raw English field values.
"""

import unittest
from pathlib import Path

from src.data_service import load_all_data
from src.ui import case_study, labels


class CaseStudyPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_home_stats_cover_core_assets_with_live_counts(self):
        stats = {label: value for value, label in case_study._build_home_stats(self.data, {})}
        self.assertIn("正式样本", stats)
        self.assertIn("尽调场景", stats)
        self.assertIn(str(len(self.data.tasks)), stats["正式样本"])

    def test_case_study_source_keeps_three_main_sections(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        for section in ("项目定位", "评测流程", "数据边界"):
            self.assertIn(section, source)
        self.assertNotIn("04\", \"进入操作", source)


class TaskPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.records = labels.build_task_records(self.data.tasks)
        self.table = labels.build_task_table(self.data.tasks)

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
        self.assertEqual("Unknown Domain", labels.display_label("Unknown Domain", labels.DOMAIN_LABELS))
        self.assertEqual("未标注", labels.display_label("", labels.DOMAIN_LABELS))

    def test_long_text_is_summarized(self):
        long_text = "甲" * 400
        summary = labels.summarize_text(long_text)
        self.assertLessEqual(len(summary), labels.SUMMARY_LIMIT + 1)
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
