"""PR-13 tests: the model-diagnosis page is a "capability fingerprint" board.

Covers the fingerprint builder (``build_model_fingerprints``), the red-line
counter derived from severity (``count_model_redline_errors``), the
usage-boundary tendency mapping, and that the page renders without crashing
when there are no scores or no error labels. Every figure must come from the
loaded data — no model name, score or error type is hardcoded.
"""

import unittest
import warnings
from pathlib import Path

import pandas as pd

from app.services.live_results import empty_results_evaluation_data
from src.data_service import load_all_data
from src.metrics import get_model_total_scores
from src.ui import components, model_diagnosis as md
from src.ui.conclusions import render_conclusions_page
from src.ui.page_config import get_page_config
from src.validators import validate_evaluation_data


class FingerprintConfigTests(unittest.TestCase):
    def test_page_title_is_capability_fingerprint(self):
        config = get_page_config("conclusions")
        self.assertIn("评测结论", config.title)

    def test_fingerprint_component_and_styles_exist(self):
        self.assertTrue(hasattr(components, "render_fingerprint_cards"))
        for token in [".fingerprint-grid", ".fingerprint-card", ".fingerprint-note"]:
            self.assertIn(token, components.STYLE_CSS)


class FingerprintBuilderTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_one_card_per_model_sorted_desc(self):
        cards = md.build_model_fingerprints(self.data.scores, self.data.errors, self.data.tasks)
        totals = get_model_total_scores(self.data.scores)
        self.assertEqual(len(totals), len(cards))
        scores = [card["avg_score"] for card in cards]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_card_payload_has_all_fingerprint_fields(self):
        cards = md.build_model_fingerprints(self.data.scores, self.data.errors, self.data.tasks)
        required = {
            "model", "avg_score", "strongest_dim", "weakest_dim",
            "top_error", "redline_count", "tendency", "tendency_level", "tendency_note",
        }
        for card in cards:
            self.assertTrue(required.issubset(card.keys()))
            self.assertIn(card["tendency_level"], {"success", "warning", "danger"})
            # Tendency wording must never claim an absolute ranking.
            self.assertIn("倾向", card["tendency"])
            # Notes stay scoped to the current sample.
            self.assertIn("样本", card["tendency_note"])

    def test_empty_scores_yield_no_cards(self):
        empty = pd.DataFrame(columns=self.data.scores.columns)
        self.assertEqual([], md.build_model_fingerprints(empty, self.data.errors, self.data.tasks))

    def test_cards_tolerate_no_error_labels(self):
        empty_errors = self.data.errors.iloc[0:0]
        cards = md.build_model_fingerprints(self.data.scores, empty_errors, self.data.tasks)
        self.assertEqual(len(cards), len(get_model_total_scores(self.data.scores)))
        for card in cards:
            self.assertEqual(0, card["redline_count"])
            self.assertEqual("无高频错误", card["top_error"])


class RedlineCountTests(unittest.TestCase):
    def _errors(self, *rows):
        cols = ["output_id", "model_name", "error_type", "severity", "error_description"]
        return pd.DataFrame(list(rows), columns=cols)

    def test_zero_when_no_errors(self):
        self.assertEqual(0, md.count_model_redline_errors(self._errors(), "M"))

    def test_counts_only_high_severity_for_the_model(self):
        errors = self._errors(
            {"output_id": "1", "model_name": "M", "error_type": "风险遗漏", "severity": "高", "error_description": "a"},
            {"output_id": "2", "model_name": "M", "error_type": "表达问题", "severity": "低", "error_description": "b"},
            {"output_id": "3", "model_name": "M", "error_type": "依据错误", "severity": "high", "error_description": "c"},
            {"output_id": "4", "model_name": "OTHER", "error_type": "风险遗漏", "severity": "高", "error_description": "d"},
        )
        # Two high-severity hits for M ("高" and "high"); the OTHER model's hit is excluded.
        self.assertEqual(2, md.count_model_redline_errors(errors, "M"))

    def test_counter_is_not_tied_to_specific_error_types(self):
        # A previously-unseen error type still counts when its severity is high.
        errors = self._errors(
            {"output_id": "1", "model_name": "M", "error_type": "全新错误类型", "severity": "高", "error_description": "x"},
        )
        self.assertEqual(1, md.count_model_redline_errors(errors, "M"))


class BoundaryTendencyTests(unittest.TestCase):
    def test_redline_forces_not_direct(self):
        tendency, level, _ = md._boundary_tendency(95.0, 0.9, 1)
        self.assertEqual("danger", level)
        self.assertIn("不可直接用", tendency)

    def test_below_pass_floor_is_not_direct(self):
        _, level, _ = md._boundary_tendency(40.0, 0.5, 0)
        self.assertEqual("danger", level)

    def test_high_score_no_weak_tends_direct(self):
        tendency, level, _ = md._boundary_tendency(90.0, 0.8, 0)
        self.assertEqual("success", level)
        self.assertIn("可直接用", tendency)

    def test_weak_dimension_keeps_review(self):
        tendency, level, _ = md._boundary_tendency(90.0, 0.4, 0)
        self.assertEqual("warning", level)
        self.assertIn("需复核", tendency)


class FingerprintRenderTests(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")
        self.base = load_all_data()
        self.validation = validate_evaluation_data(self.base)

    def _bundle(self, data, live):
        return {
            "data": data,
            "base": self.base,
            "validation_result": self.validation,
            "eval_status": {"live": live, "run_id": "RUN-1"},
        }

    def test_renders_with_real_run(self):
        render_conclusions_page(self._bundle(self.base, True))

    def test_renders_without_run(self):
        render_conclusions_page(self._bundle(empty_results_evaluation_data(self.base), False))

    def test_renders_with_no_error_labels(self):
        import dataclasses

        no_errors = dataclasses.replace(self.base, errors=self.base.errors.iloc[0:0])
        render_conclusions_page(self._bundle(no_errors, True))


class NoHardcodingSourceTests(unittest.TestCase):
    def test_fingerprint_logic_does_not_hardcode_models_or_error_types(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        for forbidden in ("Model_A", "Model_B", "Model_C", "qwen", "deepseek"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
