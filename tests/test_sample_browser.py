"""the task browser builds one compact row per task with Gold
Answer / model-answer / error-label status derived from the data files, and the
top filters narrow that row set. Nothing is hardcoded.
"""

import unittest

from src.data_service import load_all_data
from src.ui import samples
from src.ui.page_config import get_page_config


class TaskBrowserTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.rows = samples.build_case_overview_rows(self.data)

    def test_title_is_task_sample(self):
        self.assertEqual("样本库", get_page_config("samples").title)

    def test_one_row_per_task_with_expected_columns(self):
        self.assertEqual(len(self.data.tasks), len(self.rows))
        required = {
            "case_id",
            "domain_label",
            "task_type_label",
            "difficulty_label",
            "capability",
            "has_gold",
            "model_answer_count",
            "error_label_count",
        }
        for row in self.rows:
            self.assertTrue(required.issubset(row.keys()))

    def test_counts_match_linked_data(self):
        outputs = self.data.model_outputs
        errors = self.data.errors
        for row in self.rows:
            case_id = row["case_id"]
            expected_answers = int((outputs["case_id"].astype(str) == case_id).sum())
            expected_errors = int((errors["case_id"].astype(str) == case_id).sum())
            self.assertEqual(expected_answers, row["model_answer_count"], case_id)
            self.assertEqual(expected_errors, row["error_label_count"], case_id)

    def test_gold_status_reflects_gold_answer_map(self):
        for row in self.rows:
            gold = self.data.gold_answer_map.get(row["case_id"]) or {}
            expected = bool(str(gold.get("core_conclusion", "")).strip())
            self.assertEqual(expected, row["has_gold"], row["case_id"])

    def test_filter_by_gold_and_answer(self):
        with_gold = samples.filter_case_rows(self.rows, gold="有")
        self.assertTrue(all(r["has_gold"] for r in with_gold))

        without_answer = samples.filter_case_rows(self.rows, answer="无")
        self.assertTrue(all(r["model_answer_count"] == 0 for r in without_answer))

        first_domain = self.rows[0]["domain_label"]
        by_domain = samples.filter_case_rows(self.rows, domain=first_domain)
        self.assertTrue(all(r["domain_label"] == first_domain for r in by_domain))

    def test_capability_is_not_long_text(self):
        for row in self.rows:
            self.assertLessEqual(len(row["capability"]), 41)


if __name__ == "__main__":
    unittest.main()
