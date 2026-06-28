"""PR-14 tests: the case evaluation page derives its rubric, error attribution
and data-fix actions dynamically from the selected case and model, with no
single case or model hardcoded.
"""

import unittest

from src.data_service import load_all_data
from src.metrics import get_case_ids, merge_case_outputs_with_scores
from src.ui import case_detail as cd


class CaseEvaluationDerivationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def _merged(self, case_id):
        return merge_case_outputs_with_scores(self.data.model_outputs, self.data.scores, case_id)

    def test_rubric_rows_sum_to_total_for_every_case_and_model(self):
        checked = 0
        for case_id in get_case_ids(self.data.tasks):
            merged = self._merged(case_id)
            for model in cd.get_case_models(merged):
                row = cd.get_output_row(merged, model)
                rubric = cd.build_rubric_rows(row)
                self.assertEqual(len(cd.RUBRIC), len(rubric))
                self.assertAlmostEqual(
                    float(row["total_score"]),
                    sum(item["score"] for item in rubric),
                    msg=f"{case_id}/{model}",
                )
                checked += 1
        self.assertGreaterEqual(checked, 10)

    def test_rubric_levels_use_chinese_status_labels(self):
        merged = self._merged("CM-001")
        weak = cd.build_rubric_rows(cd.get_output_row(merged, "Model_A_baseline"))
        strong = cd.build_rubric_rows(cd.get_output_row(merged, "Model_C_prompt_v2"))
        self.assertIn(weak[0]["level_text"], {"达标", "部分达标", "需改进"})
        # The strong model should clear more dimensions than the weak baseline.
        weak_pass = sum(1 for r in weak if r["level_text"] == "达标")
        strong_pass = sum(1 for r in strong if r["level_text"] == "达标")
        self.assertGreater(strong_pass, weak_pass)

    def test_error_attribution_is_tied_to_selected_output(self):
        merged = self._merged("CM-001")
        baseline = cd.get_output_row(merged, "Model_A_baseline")
        strong = cd.get_output_row(merged, "Model_C_prompt_v2")

        baseline_errors = cd.build_error_attribution(self.data.errors, self.data.optimizations, baseline["output_id"])
        strong_errors = cd.build_error_attribution(self.data.errors, self.data.optimizations, strong["output_id"])

        self.assertTrue(baseline_errors)
        for record in baseline_errors:
            self.assertIn("error_type", record)
            self.assertIn("severity", record)
            self.assertIn("likely_cause", record)
        # Model_C has no error labels on this case: attribution must be empty.
        self.assertEqual([], strong_errors)

    def test_data_fix_actions_correspond_to_error_labels(self):
        merged = self._merged("FD-001")
        baseline = cd.get_output_row(merged, "Model_A_baseline")
        errors = cd.build_error_attribution(self.data.errors, self.data.optimizations, baseline["output_id"])
        fixes = cd.build_data_fix_actions(self.data.errors, self.data.optimizations, baseline["output_id"])

        self.assertTrue(fixes)
        error_types = {e["error_type"] for e in errors}
        fix_types = {f["error_type"] for f in fixes}
        self.assertEqual(error_types, fix_types)
        for fix in fixes:
            self.assertTrue(fix["action"])
            self.assertIn("priority", fix)

    def test_results_differ_across_cases(self):
        # Guards against accidentally hardcoding a single case/model.
        first = cd.build_rubric_rows(cd.get_output_row(self._merged("CM-001"), "Model_B_rag"))
        second = cd.build_rubric_rows(cd.get_output_row(self._merged("LD-001"), "Model_B_rag"))
        self.assertNotEqual(
            [r["score"] for r in first],
            [r["score"] for r in second],
        )

    def test_unmatched_error_type_falls_back_without_crashing(self):
        import pandas as pd

        empty_plan = pd.DataFrame(columns=self.data.optimizations.columns)
        merged = self._merged("CM-001")
        baseline = cd.get_output_row(merged, "Model_A_baseline")
        records = cd.build_error_attribution(self.data.errors, empty_plan, baseline["output_id"])
        self.assertTrue(records)
        self.assertTrue(records[0]["likely_cause"])  # falls back to correction text


if __name__ == "__main__":
    unittest.main()
