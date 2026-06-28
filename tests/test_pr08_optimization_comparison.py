import unittest
from copy import deepcopy
from dataclasses import replace

import pandas as pd

from src.data_service import load_all_data
from src.metrics import (
    get_optimization_change_summary,
    get_optimization_comparison_metrics,
)
from src.ui.optimization_compare import collect_optimization_compare_tables
from src.validators import validate_evaluation_data


EXPECTED_COLUMNS = {
    "experiment_id",
    "version",
    "change_type",
    "change_description",
    "avg_score",
    "hallucination_rate",
    "evidence_score",
    "reasoning_score",
    "red_line_error_rate",
    "note",
}


class OptimizationComparisonTests(unittest.TestCase):
    def setUp(self):
        self.data = deepcopy(load_all_data())

    def test_optimization_comparison_data_is_loaded(self):
        comparison = self.data.optimization_comparison

        self.assertFalse(comparison.empty)
        self.assertEqual(EXPECTED_COLUMNS, set(comparison.columns))
        self.assertGreaterEqual(len(comparison), 2)

    def test_empty_optimization_comparison_is_warning_only(self):
        data = replace(
            self.data,
            optimization_comparison=pd.DataFrame(columns=list(EXPECTED_COLUMNS)),
        )

        result = validate_evaluation_data(data)

        self.assertTrue(result.is_valid)
        self.assertTrue(
            any("optimization_comparison.csv 暂无优化前后对比数据" in message for message in result.warnings)
        )

    def test_comparison_metrics_preserve_versions_and_numeric_columns(self):
        metrics = get_optimization_comparison_metrics(self.data.optimization_comparison)

        self.assertFalse(metrics.empty)
        self.assertEqual(EXPECTED_COLUMNS, set(metrics.columns))
        for column in [
            "avg_score",
            "hallucination_rate",
            "evidence_score",
            "reasoning_score",
            "red_line_error_rate",
        ]:
            self.assertTrue(pd.api.types.is_numeric_dtype(metrics[column]))

    def test_change_summary_compares_first_and_last_versions(self):
        summary = get_optimization_change_summary(self.data.optimization_comparison)

        self.assertGreaterEqual(len(summary), 3)
        self.assertTrue(any("平均分" in item for item in summary))
        self.assertTrue(any("红线错误率" in item for item in summary))
        self.assertTrue(any("当前评测集观察" in item for item in summary))

    def test_collect_optimization_compare_tables_tolerates_empty_data(self):
        data = replace(
            self.data,
            optimization_comparison=pd.DataFrame(columns=list(EXPECTED_COLUMNS)),
        )
        bundle = {"data": data, "validation_result": validate_evaluation_data(data)}

        tables = collect_optimization_compare_tables(bundle)

        self.assertIn("metrics", tables)
        self.assertIn("summary", tables)
        self.assertTrue(tables["metrics"].empty)
        self.assertEqual([], tables["summary"])


if __name__ == "__main__":
    unittest.main()
