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

        self.assertFalse(summary.empty)
        self.assertEqual(
            {"error_type", "count", "severity", "models", "cases"},
            set(summary.columns),
        )
        risk_row = summary[summary["error_type"] == "风险遗漏"].iloc[0]
        self.assertGreaterEqual(risk_row["count"], 1)
        self.assertIn("Model_A_baseline", risk_row["models"])
        self.assertIn("CM-001", risk_row["cases"])

    def test_optimization_plan_is_normalized_from_legacy_columns(self):
        normalized = normalize_optimization_plan(self.data.optimizations)

        self.assertFalse(normalized.empty)
        self.assertIn("error_type", normalized.columns)
        self.assertIn("root_cause", normalized.columns)
        self.assertIn("data_action", normalized.columns)
        self.assertIn("sample_format", normalized.columns)
        self.assertIn("validation_metric", normalized.columns)
        self.assertIn("status", normalized.columns)
        self.assertIn("增加财务比例计算和减值测试的示例数据", set(normalized["data_action"]))

    def test_error_attribution_actions_join_errors_to_data_actions(self):
        actions = get_error_attribution_actions(self.data.errors, self.data.optimizations)

        self.assertFalse(actions.empty)
        self.assertIn("error_type", actions.columns)
        self.assertIn("root_cause", actions.columns)
        self.assertIn("data_action", actions.columns)
        self.assertIn("validation_metric", actions.columns)
        self.assertIn("风险遗漏", set(actions["error_type"]))

    def test_priority_error_samples_include_matching_data_action(self):
        samples = get_priority_error_samples(self.data.errors, self.data.optimizations)

        self.assertFalse(samples.empty)
        self.assertIn("case_id", samples.columns)
        self.assertIn("model_name", samples.columns)
        self.assertIn("error_description", samples.columns)
        self.assertIn("data_action", samples.columns)
        self.assertTrue(samples["data_action"].notna().any())

    def test_error_action_helpers_tolerate_empty_data(self):
        empty = pd.DataFrame()

        self.assertTrue(get_error_distribution_summary(empty).empty)
        self.assertTrue(normalize_optimization_plan(empty).empty)
        self.assertTrue(get_error_attribution_actions(empty, empty).empty)
        self.assertTrue(get_priority_error_samples(empty, empty).empty)


if __name__ == "__main__":
    unittest.main()
