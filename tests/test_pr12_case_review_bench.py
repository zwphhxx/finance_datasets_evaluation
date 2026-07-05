"""PR-12 tests: the case-detail page is a three-column "redline review bench".

Covers the dynamically-derived verdict (``build_case_verdict``), the red-line
hit detector (``detect_redline_hits``), the suggested-action picker
(``_suggested_data_action``), and that ``render_case_detail_page`` survives the
empty states: no real run, no model answer, no Gold, no per-dimension scores,
no error labels. Every conclusion must come from the current case+model data —
no model name, case_id, score or error type is hardcoded in the source.
"""

import unittest
import warnings
from pathlib import Path

import pandas as pd

from app.services.live_results import empty_results_evaluation_data
from src.data_service import load_all_data
from src.metrics import get_case_ids, merge_case_outputs_with_scores
from src.ui import case_detail as cd
from src.validators import validate_evaluation_data


def _output_row(total=None, **dims):
    """A single merged output row; dims default to a strong, balanced profile."""
    profile = {
        "accuracy_score": 30,
        "reasoning_score": 20,
        "coverage_score": 20,
        "evidence_score": 15,
        "expression_score": 15,
    }
    profile.update(dims)
    return pd.Series({"output_id": "OUT-X", "model_name": "M", "total_score": total, **profile})


def _errors(*rows):
    cols = ["output_id", "error_type", "severity", "error_description"]
    return pd.DataFrame(list(rows), columns=cols)


class RedlineHitDetectionTests(unittest.TestCase):
    def test_no_errors_yields_no_hits(self):
        self.assertEqual([], cd.detect_redline_hits(_errors(), "OUT-X", None))

    def test_high_severity_error_is_a_hit(self):
        errors = _errors(
            {"output_id": "OUT-X", "error_type": "风险遗漏", "severity": "高", "error_description": "漏报担保"},
            {"output_id": "OUT-X", "error_type": "表达不清", "severity": "低", "error_description": "措辞"},
        )
        hits = cd.detect_redline_hits(errors, "OUT-X", None)
        self.assertTrue(any("高严重度错误" in h and "风险遗漏" in h for h in hits))
        # Low-severity error alone must not raise a hit.
        self.assertFalse(any("表达不清" in h for h in hits))

    def test_gold_unacceptable_error_is_approx_matched(self):
        errors = _errors(
            {"output_id": "OUT-X", "error_type": "合规误判", "severity": "中", "error_description": "漏报重大担保事项"},
        )
        gold = {"unacceptable_errors": ["漏报重大担保事项"]}
        hits = cd.detect_redline_hits(errors, "OUT-X", gold)
        self.assertTrue(any("疑似触及红线" in h for h in hits))

    def test_hits_are_deduplicated(self):
        errors = _errors(
            {"output_id": "OUT-X", "error_type": "风险遗漏", "severity": "高", "error_description": "a"},
            {"output_id": "OUT-X", "error_type": "风险遗漏", "severity": "高", "error_description": "b"},
        )
        hits = cd.detect_redline_hits(errors, "OUT-X", None)
        self.assertEqual(len(hits), len(set(hits)))


class SuggestedActionTests(unittest.TestCase):
    def test_no_error_states_no_action(self):
        action = cd._suggested_data_action(_errors(), pd.DataFrame(), "OUT-X")
        self.assertEqual("未触发错误标签，暂无补强动作", action)

    def test_unmapped_error_asks_for_label_mapping(self):
        # An error with no matching optimization plan → ask for the mapping,
        # never invent a concrete fix.
        errors = _errors(
            {"output_id": "OUT-X", "error_type": "罕见错误类型", "severity": "中", "error_description": "x"},
        )
        action = cd._suggested_data_action(errors, pd.DataFrame(), "OUT-X")
        self.assertEqual("待补充标签映射", action)


class VerdictDerivationTests(unittest.TestCase):
    def test_none_when_no_model_output(self):
        verdict = cd.build_case_verdict(None, _errors(), None, pd.DataFrame(), None)
        self.assertEqual("none", verdict["tier"])
        self.assertEqual("未评分", verdict["score_text"])
        self.assertEqual([], verdict["redline_hits"])

    def test_tolerates_missing_dimension_scores(self):
        # total present but no sub-scores: must not crash, weakest falls back,
        # and a valid tier is still derived from the total.
        row = pd.Series({"output_id": "OUT-X", "model_name": "M", "total_score": 90})
        verdict = cd.build_case_verdict(row, _errors(), None, pd.DataFrame(), pd.Series({"risk_level": "中"}))
        self.assertEqual("暂无分项评分", verdict["weakest"])
        self.assertIn(verdict["tier"], {"direct", "review", "not_direct"})

    def test_direct_when_high_score_and_no_weakness_or_redline(self):
        verdict = cd.build_case_verdict(
            _output_row(total=92), _errors(), {}, pd.DataFrame(), pd.Series({"risk_level": "中"})
        )
        self.assertEqual("direct", verdict["tier"])
        self.assertEqual("可作为初稿参考", verdict["title"])

    def test_review_when_passing_but_weak_dimension(self):
        verdict = cd.build_case_verdict(
            _output_row(total=70, reasoning_score=4), _errors(), {}, pd.DataFrame(),
            pd.Series({"risk_level": "中"}),
        )
        self.assertEqual("review", verdict["tier"])

    def test_not_direct_below_pass_floor(self):
        verdict = cd.build_case_verdict(
            _output_row(total=40), _errors(), {}, pd.DataFrame(), pd.Series({"risk_level": "中"})
        )
        self.assertEqual("not_direct", verdict["tier"])

    def test_redline_hit_overrides_high_score(self):
        errors = _errors(
            {"output_id": "OUT-X", "error_type": "风险遗漏", "severity": "高", "error_description": "漏报"},
        )
        verdict = cd.build_case_verdict(
            _output_row(total=95), errors, {}, pd.DataFrame(), pd.Series({"risk_level": "中"})
        )
        self.assertEqual("not_direct", verdict["tier"])
        self.assertTrue(verdict["redline_hits"])
        self.assertIn("一票否决", verdict["reason"])

    def test_high_risk_task_stays_human_only(self):
        verdict = cd.build_case_verdict(
            _output_row(total=92), _errors(), {}, pd.DataFrame(), pd.Series({"risk_level": "高"})
        )
        self.assertEqual("not_direct", verdict["tier"])

    def test_verdict_payload_has_all_keys(self):
        verdict = cd.build_case_verdict(
            _output_row(total=92), _errors(), {}, pd.DataFrame(), pd.Series({"risk_level": "中"})
        )
        for key in ("tier", "title", "level", "reason", "redline_hits", "weakest", "score_text", "suggested_action"):
            self.assertIn(key, verdict)


class CaseDetailRenderTests(unittest.TestCase):
    """The bench must render in bare mode across every empty state."""

    def setUp(self):
        warnings.simplefilter("ignore")
        self.base = load_all_data()
        self.validation = validate_evaluation_data(self.base)

    def _bundle(self, data, live, score_run_id=None):
        return {
            "data": data,
            "base": self.base,
            "validation_result": self.validation,
            "eval_status": {"live": live, "run_id": "RUN-1", "score_run_id": score_run_id},
        }

    def test_renders_with_real_run(self):
        cd.render_case_detail_page(self._bundle(self.base, True))

    def test_renders_without_run(self):
        empty = empty_results_evaluation_data(self.base)
        cd.render_case_detail_page(self._bundle(empty, False))

    def test_renders_with_no_errors(self):
        no_errors = self.base
        import dataclasses

        no_errors = dataclasses.replace(self.base, errors=self.base.errors.iloc[0:0])
        cd.render_case_detail_page(self._bundle(no_errors, True))


class NoHardcodingSourceTests(unittest.TestCase):
    def test_verdict_logic_does_not_hardcode_case_or_model(self):
        source = Path("src/ui/case_detail.py").read_text(encoding="utf-8")
        # Verdict must be derived, not pinned to a specific seed case or model.
        for forbidden in ("CM-001", "qwen", "deepseek", "gpt-"):
            self.assertNotIn(forbidden, source)
        # Point coverage must stay labelled as approximate, never "精确".
        self.assertIn("近似匹配", source)


if __name__ == "__main__":
    unittest.main()
