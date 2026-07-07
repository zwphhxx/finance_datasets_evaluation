"""Gold Answer quality governance.

Each Gold Answer carries the structured fields; the central evaluator derives a
usable / partially-usable status from data; the validator reads those fields
dynamically with nothing hardcoded.
"""

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.validate_dataset import validate_dataset
from src import gold_quality as gq
from src.data_service import load_all_data

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

CANONICAL_FIELDS = (
    "core_conclusion",
    "key_evidence",
    "boundary_conditions",
    "must_have_points",
    "unacceptable_errors",
    "manual_review_notes",
)


class GoldAnswerStructureTests(unittest.TestCase):
    def setUp(self):
        self.gold = json.loads((DATA_DIR / "gold_answers.json").read_text(encoding="utf-8"))

    def test_every_gold_answer_has_canonical_fields(self):
        self.assertTrue(self.gold)
        for entry in self.gold:
            for field in CANONICAL_FIELDS:
                self.assertIn(field, entry, f"{entry.get('case_id')}/{field}")
                self.assertTrue(gq.field_value(entry, field) is not None, f"{entry.get('case_id')}/{field}")

    def test_no_legacy_field_names_remain(self):
        for entry in self.gold:
            for legacy in ("conclusion", "basis", "risk_boundary", "red_line_errors"):
                self.assertNotIn(legacy, entry, f"{entry.get('case_id')}/{legacy}")


class GoldQualityEvaluatorTests(unittest.TestCase):
    def test_seed_gold_answers_are_usable(self):
        data = load_all_data()
        for gold in data.gold_answer_map.values():
            quality = gq.evaluate_gold_quality(gold)
            self.assertTrue(quality["is_usable"], quality["missing"])
            self.assertEqual(quality["status"], gq.STATUS_USABLE)

    def test_partial_gold_answer_reports_missing(self):
        quality = gq.evaluate_gold_quality({"core_conclusion": "结论"})
        self.assertFalse(quality["is_usable"])
        self.assertEqual(quality["status"], gq.STATUS_PARTIAL)
        self.assertIn("关键依据", quality["missing"])

    def test_resolver_honors_legacy_aliases(self):
        legacy = {"conclusion": "结论", "basis": "依据", "risk_boundary": "边界", "red_line_errors": ["红线"]}
        self.assertEqual(gq.field_text(legacy, "core_conclusion"), "结论")
        self.assertEqual(gq.field_text(legacy, "key_evidence"), "依据")
        self.assertEqual(gq.field_list(legacy, "unacceptable_errors"), ["红线"])


class ValidatorCompletenessTests(unittest.TestCase):
    def test_real_dataset_reports_usable_gold_answers(self):
        report = validate_dataset(DATA_DIR)
        self.assertTrue(report.is_valid, "; ".join(report.errors))
        self.assertTrue(any("满足评测使用条件" in line for line in report.passed))

    def test_missing_boundary_and_red_line_is_flagged(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            shutil.copytree(DATA_DIR, data_dir)
            gold_path = data_dir / "gold_answers.json"
            gold = json.loads(gold_path.read_text(encoding="utf-8"))
            gold[0].pop("boundary_conditions", None)
            gold[0].pop("unacceptable_errors", None)
            gold_path.write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")

            report = validate_dataset(
                data_dir,
                manifest_path=data_dir / "dataset_manifest.yml",
                taxonomy_path=data_dir / "label_taxonomy.yml",
            )
            self.assertTrue(any("部分满足评测使用条件" in w for w in report.warnings))


if __name__ == "__main__":
    unittest.main()
