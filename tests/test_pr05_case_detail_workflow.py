import unittest

import pandas as pd

from src.data_service import load_all_data
from src.metrics import (
    get_optimization_suggestions_for_case,
    get_preference_pair_details_for_case,
)


class CaseDetailWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_preference_pair_details_include_preferred_and_rejected_answers(self):
        details = get_preference_pair_details_for_case(
            self.data.preference_pairs,
            self.data.model_outputs,
            "CM-001",
        )

        self.assertFalse(details.empty)
        self.assertIn("preferred_model_name", details.columns)
        self.assertIn("rejected_model_name", details.columns)
        self.assertIn("preferred_answer_text", details.columns)
        self.assertIn("rejected_answer_text", details.columns)
        self.assertEqual("Model_C_prompt_v2", details.iloc[0]["preferred_model_name"])
        self.assertEqual("Model_A_baseline", details.iloc[0]["rejected_model_name"])

    def test_optimization_suggestions_are_linked_from_case_error_types(self):
        suggestions = get_optimization_suggestions_for_case(
            self.data.errors,
            self.data.optimizations,
            "CM-001",
        )

        self.assertFalse(suggestions.empty)
        self.assertIn("frequent_error", suggestions.columns)
        self.assertIn("optimization_action", suggestions.columns)
        self.assertIn("风险遗漏", set(suggestions["frequent_error"]))

    def test_case_detail_helpers_tolerate_empty_related_data(self):
        empty_pairs = pd.DataFrame(columns=self.data.preference_pairs.columns)
        empty_errors = pd.DataFrame(columns=self.data.errors.columns)

        preference_details = get_preference_pair_details_for_case(
            empty_pairs,
            self.data.model_outputs,
            "CM-001",
        )
        suggestions = get_optimization_suggestions_for_case(
            empty_errors,
            self.data.optimizations,
            "CM-001",
        )

        self.assertTrue(preference_details.empty)
        self.assertTrue(suggestions.empty)


if __name__ == "__main__":
    unittest.main()
