"""PR-23 tests: diagnostics, error-attribution and validation pages expose
evidence-and-action structures (comparison table, dimension matrix, priority
error→action table, open-issues list) all derived dynamically from the data.
"""

import unittest

import pandas as pd

from src.data_service import load_all_data
from src.metrics import (
    ERROR_TYPE_TO_DIMENSION,
    get_error_attribution_actions,
    get_model_total_scores,
)
from src.ui import error_analysis as ea
from src.ui import model_diagnosis as md
from src.ui import optimization_compare as oc


class ModelDiagnosisTableTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_comparison_rows_one_per_model_sorted_desc(self):
        rows = md.build_model_comparison_rows(self.data.scores, self.data.errors, self.data.tasks)
        totals = get_model_total_scores(self.data.scores)
        self.assertEqual(len(totals), len(rows))
        scores = [row["avg_score"] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        required = {"model", "avg_score", "strongest_dim", "weakest_dim", "top_error", "boundary"}
        for row in rows:
            self.assertTrue(required.issubset(row.keys()))
            self.assertTrue(row["strongest_dim"])
            self.assertTrue(row["boundary"])

    def test_dimension_matrix_is_models_by_dimensions(self):
        matrix = md.build_dimension_matrix(self.data.scores)
        self.assertTrue(matrix["dimensions"])
        models = {row["model"] for row in matrix["rows"]}
        self.assertEqual(set(get_model_total_scores(self.data.scores)["model_name"]), models)
        for row in matrix["rows"]:
            self.assertEqual(len(row["cells"]), len(matrix["dimensions"]))
            for cell in row["cells"]:
                self.assertIn(cell["level"], {"success", "warning", "danger", "neutral"})

    def test_empty_scores_yield_no_rows(self):
        empty = pd.DataFrame(columns=self.data.scores.columns)
        self.assertEqual([], md.build_model_comparison_rows(empty, self.data.errors, self.data.tasks))
        self.assertEqual([], md.build_dimension_matrix(empty)["rows"])


class ErrorImprovementTableTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.actions = get_error_attribution_actions(self.data.errors, self.data.optimizations)

    def test_improvement_table_columns_and_priority_order(self):
        table = ea.build_error_improvement_table(self.actions, self.data.errors)
        self.assertEqual(list(table.columns), ea.ERROR_IMPROVEMENT_COLUMNS)
        self.assertFalse(table.empty)
        # Rows are sorted by priority rank, derived from the data, not raw order.
        ranks = [
            ea.PRIORITY_RANK.get(
                self.actions.set_index("error_type").loc[label, "priority"]
                if label in set(self.actions["error_type"])
                else "",
                9,
            )
            for label in table["错误标签"]
        ]
        self.assertEqual(ranks, sorted(ranks))

    def test_impact_dimension_uses_taxonomy_mapping(self):
        table = ea.build_error_improvement_table(self.actions, self.data.errors)
        for _, row in table.iterrows():
            expected = ERROR_TYPE_TO_DIMENSION.get(row["错误标签"], "综合表现")
            self.assertEqual(expected, row["影响维度"])

    def test_empty_actions_degrade_gracefully(self):
        empty = pd.DataFrame(columns=self.actions.columns)
        self.assertTrue(ea.build_error_improvement_table(empty, self.data.errors).empty)


class OpenIssuesTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_open_issues_reference_sample_size_and_simulation(self):
        issues = oc.build_open_issues(
            self.data.optimization_comparison, self.data.scores, self.data.errors
        )
        self.assertTrue(issues)
        joined = " ".join(issues)
        self.assertIn("样本量", joined)
        self.assertIn("模拟", joined)

    def test_key_metric_order_starts_with_average_score(self):
        self.assertEqual("平均总分", oc.KEY_METRICS[0]["label"])
        labels = {metric["label"] for metric in oc.KEY_METRICS}
        self.assertIn("依据可靠性", labels)
        self.assertIn("幻觉率", labels)
        self.assertIn("红线错误率", labels)


if __name__ == "__main__":
    unittest.main()
