"""PR-20 tests: the home page is a dataset summary whose headline metrics and
model-performance summary are computed from data files, never hardcoded.
"""

import unittest

from src.data_service import load_all_data
from src.metrics import get_dimension_gap_ranking
from src.ui import overview
from src.ui.page_config import get_page_config


class DatasetSummaryTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_overview_title_is_redline_cockpit(self):
        config = get_page_config("overview")
        self.assertIn("红线评测台", config.title)

    def test_metric_cards_are_at_most_four_and_data_driven(self):
        cards = overview.get_dataset_metric_cards(self.data)
        self.assertLessEqual(len(cards), 4)
        self.assertEqual(["任务样本", "覆盖领域", "模型回答", "错误标签"], [c["label"] for c in cards])

        by_label = {c["label"]: c["value"] for c in cards}
        self.assertEqual(len(self.data.tasks), by_label["任务样本"])
        self.assertEqual(self.data.tasks["domain"].nunique(), by_label["覆盖领域"])
        self.assertEqual(len(self.data.model_outputs), by_label["模型回答"])
        self.assertEqual(len(self.data.errors), by_label["错误标签"])

    def test_domain_coverage_counts_sum_to_task_total(self):
        items = overview.get_domain_coverage_items(self.data.tasks)
        self.assertTrue(items)
        total = sum(int(value.split()[0]) for _, value in items)
        self.assertEqual(len(self.data.tasks), total)

    def test_model_performance_summary_matches_metrics(self):
        summary = overview.build_model_performance_summary(self.data.scores, self.data.errors)
        self.assertIsNotNone(summary)

        expected_avg = float(self.data.scores["total_score"].mean())
        self.assertAlmostEqual(expected_avg, summary["avg_score"], places=4)

        gap = get_dimension_gap_ranking(self.data.scores)
        self.assertEqual(str(gap.iloc[0]["dimension"]), summary["weakest_dimension"])

        top = self.data.errors["error_type"].dropna().astype(str).value_counts()
        self.assertEqual(str(top.index[0]), summary["top_error_type"])
        self.assertEqual(int(top.iloc[0]), summary["top_error_count"])

    def test_summary_is_none_without_scores(self):
        empty = self.data.scores.iloc[0:0]
        self.assertIsNone(overview.build_model_performance_summary(empty, self.data.errors))


if __name__ == "__main__":
    unittest.main()
