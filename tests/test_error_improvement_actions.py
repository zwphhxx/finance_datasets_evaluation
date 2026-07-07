import unittest

import pandas as pd

from src.data_service import load_all_data
from src.metrics import (
    get_error_attribution_actions,
    get_error_distribution_summary,
    get_priority_error_samples,
    normalize_optimization_plan,
)


class ErrorImprovementActionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_error_distribution_summary_contains_severity_models_and_cases(self):
        summary = get_error_distribution_summary(self.data.errors)

        self.assertTrue(summary.empty)
        self.assertEqual(
            {"error_type", "count", "severity", "models", "cases"},
            set(summary.columns),
        )

    def test_optimization_plan_is_normalized_from_legacy_columns(self):
        normalized = normalize_optimization_plan(self.data.optimizations)

        self.assertTrue(normalized.empty)
        self.assertIn("error_type", normalized.columns)
        self.assertIn("root_cause", normalized.columns)
        self.assertIn("data_action", normalized.columns)
        self.assertIn("sample_format", normalized.columns)
        self.assertIn("validation_metric", normalized.columns)
        self.assertIn("status", normalized.columns)

    def test_error_attribution_actions_join_errors_to_data_actions(self):
        actions = get_error_attribution_actions(self.data.errors, self.data.optimizations)

        self.assertTrue(actions.empty)
        self.assertIn("error_type", actions.columns)
        self.assertIn("root_cause", actions.columns)
        self.assertIn("data_action", actions.columns)
        self.assertIn("validation_metric", actions.columns)

    def test_priority_error_samples_include_matching_data_action(self):
        samples = get_priority_error_samples(self.data.errors, self.data.optimizations)

        self.assertTrue(samples.empty)
        self.assertIn("case_id", samples.columns)
        self.assertIn("model_name", samples.columns)
        self.assertIn("error_description", samples.columns)
        self.assertIn("data_action", samples.columns)

    def test_error_action_helpers_tolerate_empty_data(self):
        empty = pd.DataFrame()

        self.assertTrue(get_error_distribution_summary(empty).empty)
        self.assertTrue(normalize_optimization_plan(empty).empty)
        self.assertTrue(get_error_attribution_actions(empty, empty).empty)
        self.assertTrue(get_priority_error_samples(empty, empty).empty)


if __name__ == "__main__":
    unittest.main()
