"""PR-15 tests: the diagnostics, error-attribution and validation pages derive
their conclusions, cards and tables dynamically from the loaded data, with no
single model, error type or metric hardcoded.
"""

import unittest

import pandas as pd

from src.data_service import load_all_data
from src.metrics import (
    get_dimension_gap_ranking,
    get_error_attribution_actions,
    SCORE_DIMENSION_FULL_MARKS,
)
from src.ui import error_analysis as ea
from src.ui import model_diagnosis as md
from src.ui import optimization_compare as oc


class ModelDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_diagnosis_conclusion_is_derived_from_scores(self):
        diagnosis = md.build_diagnosis(self.data.scores, self.data.errors)
        self.assertIsNotNone(diagnosis)
        # Ranking is sorted high-to-low and the spread equals top minus bottom.
        scores = [score for _, score in diagnosis["ranking"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertAlmostEqual(
            diagnosis["spread"], diagnosis["top_score"] - diagnosis["bottom_score"]
        )
        self.assertEqual(diagnosis["top_model"], diagnosis["ranking"][0][0])
        self.assertEqual(diagnosis["bottom_model"], diagnosis["ranking"][-1][0])

    def test_weakest_dimension_matches_gap_ranking(self):
        diagnosis = md.build_diagnosis(self.data.scores, self.data.errors)
        gap = get_dimension_gap_ranking(self.data.scores)
        self.assertEqual(diagnosis["weakest_dimension"], gap.iloc[0]["dimension"])
        self.assertTrue(0.0 <= diagnosis["weakest_attainment"] <= 1.0)

    def test_dimension_gap_uses_declared_full_marks(self):
        gap = get_dimension_gap_ranking(self.data.scores)
        for _, row in gap.iterrows():
            self.assertIn(row["full_mark"], SCORE_DIMENSION_FULL_MARKS.values())
            self.assertAlmostEqual(row["attainment"], row["avg_score"] / row["full_mark"])

    def test_empty_scores_yield_no_diagnosis(self):
        empty = pd.DataFrame(columns=self.data.scores.columns)
        self.assertIsNone(md.build_diagnosis(empty, self.data.errors))


class ErrorAttributionTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.actions = get_error_attribution_actions(self.data.errors, self.data.optimizations)

    def test_action_path_columns_are_preserved(self):
        path = ea.build_error_action_path(self.actions)
        self.assertEqual(list(path.columns), ea.ACTION_PATH_COLUMNS)
        self.assertFalse(path.empty)

    def test_top_data_actions_are_priority_sorted_and_deduped(self):
        cards = ea.build_top_data_actions(self.actions, limit=3)
        self.assertTrue(cards)
        self.assertLessEqual(len(cards), 3)
        ranks = [ea.PRIORITY_RANK.get(c["priority"], 9) for c in cards]
        self.assertEqual(ranks, sorted(ranks))
        for card in cards:
            self.assertTrue(card["data_action"])
            self.assertTrue(card["validation_metric"])

    def test_error_label_table_uses_business_columns(self):
        table = ea.build_error_label_table(self.actions)
        self.assertEqual(list(table.columns), ea.ERROR_TABLE_COLUMNS)
        self.assertFalse(table.empty)
        # The impact column ties each error type to its frequency and severity.
        self.assertTrue(table["影响范围"].str.contains("次").all())

    def test_empty_actions_degrade_gracefully(self):
        empty = pd.DataFrame(columns=self.actions.columns)
        self.assertEqual([], ea.build_top_data_actions(empty))
        self.assertTrue(ea.build_error_label_table(empty).empty)


class OptimizationValidationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.comparison = self.data.optimization_comparison

    def test_key_change_cards_track_direction(self):
        cards = oc.build_key_change_cards(self.comparison)
        labels = {card["label"] for card in cards}
        self.assertIn("平均总分", labels)
        self.assertIn("红线错误率", labels)
        by_label = {card["label"]: card for card in cards}
        # Scores improve when they rise; rates improve when they fall.
        self.assertEqual(by_label["平均总分"]["kind"], "score")
        self.assertEqual(by_label["红线错误率"]["kind"], "rate")

    def test_validation_conclusion_flags_effectiveness(self):
        conclusion = oc.build_validation_conclusion(self.comparison)
        self.assertIsNotNone(conclusion)
        self.assertIn("effective", conclusion)
        self.assertIsInstance(conclusion["effective"], bool)
        self.assertTrue(conclusion["residual_label"])

    def test_collect_tables_keeps_contract(self):
        tables = oc.collect_optimization_compare_tables({"data": self.data})
        self.assertIn("metrics", tables)
        self.assertIn("summary", tables)

    def test_insufficient_rows_yield_no_cards(self):
        single = self.comparison.head(1)
        self.assertEqual([], oc.build_key_change_cards(single))
        self.assertIsNone(oc.build_validation_conclusion(single))


if __name__ == "__main__":
    unittest.main()
