import unittest

import pandas as pd

from src.data_service import load_all_data
from src.metrics import (
    filter_tasks_by_domain,
    get_error_type_counts,
    get_model_average_scores,
    get_overview_metrics,
    merge_case_outputs_with_scores,
)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.bundle = {
            "data": self.data,
        }

    def test_overview_metrics_match_existing_page_calculations(self):
        metrics = get_overview_metrics(self.bundle)

        self.assertEqual(len(self.data.tasks), metrics["task_count"])
        self.assertEqual(self.data.model_outputs["model_name"].nunique(), metrics["model_count"])
        self.assertIsNone(metrics["average_total_score"])
        self.assertEqual(len(self.data.errors), metrics["error_label_count"])
        self.assertEqual(len(self.data.optimizations), metrics["optimization_count"])

    def test_model_average_scores_keep_groupby_mean_logic(self):
        actual = get_model_average_scores(self.data.scores)
        expected = self.data.scores.groupby("model_name")["total_score"].mean().reset_index()

        pd.testing.assert_frame_equal(actual, expected)

    def test_error_type_counts_keep_value_counts_logic(self):
        actual = get_error_type_counts(self.data.errors)
        expected = self.data.errors["error_type"].value_counts().reset_index()
        expected.columns = ["error_type", "count"]

        pd.testing.assert_frame_equal(actual, expected)

    def test_task_filter_returns_all_or_selected_domain(self):
        self.assertEqual(len(self.data.tasks), len(filter_tasks_by_domain(self.data.tasks, "全部")))
        domain = self.data.tasks["domain"].iloc[0]
        filtered = filter_tasks_by_domain(self.data.tasks, domain)

        self.assertTrue((filtered["domain"] == domain).all())

    def test_case_outputs_merge_scores_with_left_join(self):
        case_id = self.data.tasks["case_id"].iloc[0]
        actual = merge_case_outputs_with_scores(self.data.model_outputs, self.data.scores, case_id)
        expected = pd.merge(
            self.data.model_outputs[self.data.model_outputs["case_id"] == case_id],
            self.data.scores,
            on=["output_id", "case_id", "model_name"],
            how="left",
        )

        pd.testing.assert_frame_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
