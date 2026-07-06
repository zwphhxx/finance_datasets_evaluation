import unittest

import pandas as pd

from src.data_service import load_all_data
from src.metrics import (
    get_model_capability_summaries,
    get_model_dimension_scores,
    get_model_domain_scores,
    get_model_error_type_counts,
    get_model_total_scores,
)


class ModelDiagnosisMetricsTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_model_total_scores_match_existing_average_score_logic(self):
        actual = get_model_total_scores(self.data.scores)
        expected = self.data.scores.groupby("model_name")["total_score"].mean().reset_index()

        pd.testing.assert_frame_equal(actual, expected)

    def test_model_dimension_scores_return_long_form_dimension_averages(self):
        actual = get_model_dimension_scores(self.data.scores)

        self.assertTrue(actual.empty)
        self.assertEqual({"model_name", "dimension", "score"}, set(actual.columns))

    def test_model_error_type_counts_group_by_model_and_error_type(self):
        actual = get_model_error_type_counts(self.data.errors)

        self.assertTrue(actual.empty)
        self.assertEqual({"model_name", "error_type", "count"}, set(actual.columns))

    def test_model_domain_scores_join_scores_to_task_domains(self):
        actual = get_model_domain_scores(self.data.scores, self.data.tasks)

        self.assertTrue(actual.empty)
        self.assertEqual({"model_name", "domain", "scenario", "total_score"}, set(actual.columns))

    def test_model_capability_summaries_are_generated_for_each_model(self):
        summaries = get_model_capability_summaries(
            self.data.scores,
            self.data.errors,
            self.data.tasks,
        )

        self.assertEqual(self.data.scores["model_name"].nunique(), len(summaries))
        for summary in summaries:
            self.assertIn("model_name", summary)
            self.assertIn("summary", summary)
            self.assertIn("样本", summary["summary"])

    def test_diagnosis_metrics_tolerate_empty_data(self):
        empty = pd.DataFrame()

        self.assertTrue(get_model_total_scores(empty).empty)
        self.assertTrue(get_model_dimension_scores(empty).empty)
        self.assertTrue(get_model_error_type_counts(empty).empty)
        self.assertTrue(get_model_domain_scores(empty, empty).empty)
        self.assertEqual([], get_model_capability_summaries(empty, empty, empty))


if __name__ == "__main__":
    unittest.main()
