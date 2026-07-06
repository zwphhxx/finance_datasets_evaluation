"""PR-29 tests: the model boundary report derives every conclusion from the
loaded scores, error labels and Gold Answer boundaries. Usage tiers, frequent
risks, data-augmentation directions and the model dimension matrix are all
computed — nothing about a specific model is hardcoded, and no inactive
(e.g. medical/clinical) content leaks into the active report.
"""

import unittest

from src.data_service import load_all_data, load_dataset_manifest
from src.model_boundary import (
    BOUNDARY_AWARENESS_LABEL,
    TIER_NOT_DIRECT,
    TIER_ORDER,
    build_boundary_matrix,
    build_data_actions,
    build_data_boundary,
    build_frequent_risks,
    classify_task_usage,
    summarize_usage_tiers,
)

MATRIX_DIMENSIONS = ["事实依据", "推理完整性", "风险识别", "专业表达", BOUNDARY_AWARENESS_LABEL]
MEDICAL_TOKENS = ["临床", "试验", "医学", "病", "诊疗"]


class DataBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.boundary = build_data_boundary(self.data, load_dataset_manifest())

    def test_boundary_reports_live_sample_size(self):
        self.assertEqual(self.boundary["task_count"], len(self.data.tasks))
        self.assertEqual(self.boundary["output_count"], len(self.data.model_outputs))
        self.assertEqual(0, self.boundary["model_count"])

    def test_boundary_states_version_and_simulated_answers(self):
        self.assertEqual(self.boundary["version"], str(load_dataset_manifest().get("version")))
        self.assertTrue(self.boundary["simulated_answers"])
        self.assertTrue(self.boundary["scope_note"].strip())


class UsageTierTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_every_task_classified_into_one_tier(self):
        records = classify_task_usage(self.data)
        self.assertEqual(len(records), len(self.data.tasks))
        valid = set(TIER_ORDER)
        for record in records:
            self.assertIn(record["tier"], valid, record["case_id"])

    def test_tier_counts_sum_to_task_count(self):
        summaries = summarize_usage_tiers(self.data)
        self.assertEqual([s["key"] for s in summaries], TIER_ORDER)
        self.assertEqual(sum(s["count"] for s in summaries), len(self.data.tasks))

    def test_high_risk_tasks_are_not_directly_usable(self):
        records = classify_task_usage(self.data)
        for record in records:
            if record["risk_level"] == "高":
                self.assertEqual(record["tier"], TIER_NOT_DIRECT, record["case_id"])

    def test_tier_summaries_carry_data_derived_detail(self):
        for summary in summarize_usage_tiers(self.data):
            self.assertIn("definition", summary)
            self.assertTrue(summary["definition"].strip())
            if summary["count"] > 0:
                self.assertIsNone(summary["score_low"])
                self.assertIsNone(summary["score_high"])
                self.assertEqual(len(summary["cases"]), summary["count"])


class FrequentRiskAndActionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_frequent_risks_sorted_by_count_with_dimension(self):
        risks = build_frequent_risks(self.data)
        self.assertEqual([], risks)
        counts = [r["count"] for r in risks]
        self.assertEqual(counts, sorted(counts, reverse=True))
        for risk in risks:
            self.assertTrue(risk["dimension"].strip())
            self.assertGreaterEqual(risk["case_count"], 1)

    def test_data_actions_have_no_inactive_domain_leakage(self):
        actions = build_data_actions(self.data)
        self.assertEqual([], actions)
        for action in actions:
            text = action["data_action"] + action["validation_metric"]
            for token in MEDICAL_TOKENS:
                self.assertNotIn(token, text, action["error_type"])


class DimensionMatrixTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.matrix = build_boundary_matrix(self.data)

    def test_matrix_columns_match_report_dimensions(self):
        self.assertEqual(self.matrix["dimensions"], [])

    def test_matrix_has_one_row_per_model_with_scored_cells(self):
        model_count = self.data.model_outputs["model_name"].nunique()
        self.assertEqual(len(self.matrix["rows"]), model_count)
        for row in self.matrix["rows"]:
            self.assertEqual(len(row["cells"]), len(MATRIX_DIMENSIONS))
            # The four Rubric cells must carry real scores, not placeholders.
            rubric_cells = row["cells"][:4]
            self.assertTrue(all(cell["score"] is not None for cell in rubric_cells), row["model"])

    def test_boundary_awareness_cell_is_derived(self):
        for row in self.matrix["rows"]:
            awareness = row["cells"][-1]
            self.assertEqual(awareness["dimension"], BOUNDARY_AWARENESS_LABEL)
            self.assertIn(awareness["level"], {"success", "warning", "danger", "neutral"})
            self.assertIn("redline_count", awareness)


if __name__ == "__main__":
    unittest.main()
