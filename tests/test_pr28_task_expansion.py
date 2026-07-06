"""PR-28 tests: the active dataset is the final 13 finance/legal/IB sample set.

Historical inactive and example samples have been removed from the seed files;
runtime model answers and scores are produced in SQLite instead of committed
as seed rows.
"""

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.validate_dataset import validate_dataset
from src import gold_quality as gq
from src.data_service import active_case_ids, load_all_data

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

ALLOWED_DOMAINS = {"Capital Markets", "Financial", "Legal"}


class ActiveScopeTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_active_task_count_in_target_range(self):
        self.assertEqual(13, len(self.data.tasks))

    def test_only_allowed_domains_remain_active(self):
        domains = set(self.data.tasks["domain"].astype(str))
        self.assertEqual(ALLOWED_DOMAINS, domains)

    def test_inactive_cases_excluded_from_all_frames(self):
        active = set(self.data.tasks["case_id"].astype(str))
        for frame in (self.data.model_outputs, self.data.scores, self.data.errors, self.data.preference_pairs):
            cases = set(frame["case_id"].astype(str))
            self.assertTrue(cases.issubset(active), cases - active)
        self.assertEqual(set(self.data.gold_answer_map), active)

    def test_final_seed_contains_no_inactive_cases(self):
        raw = __import__("pandas").read_csv(DATA_DIR / "tasks.csv")
        self.assertIn("status", raw.columns)
        inactive = raw[raw["status"].astype(str).str.lower() == "inactive"]
        self.assertEqual(0, len(inactive))
        self.assertEqual(set(raw["case_id"].astype(str)), active_case_ids(raw))


class ActiveSampleQualityTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_every_active_task_has_complete_gold(self):
        for case_id in self.data.tasks["case_id"].astype(str):
            gold = self.data.gold_answer_map.get(case_id)
            self.assertIsNotNone(gold, case_id)
            self.assertTrue(gq.evaluate_gold_quality(gold)["is_usable"], case_id)

    def test_final_seed_has_no_legacy_scores_or_error_rows(self):
        self.assertEqual(0, len(self.data.scores))
        self.assertEqual(0, len(self.data.errors))


class ValidatorScopeTests(unittest.TestCase):
    def test_real_dataset_reports_active_domain_pass(self):
        report = validate_dataset(DATA_DIR)
        self.assertTrue(report.is_valid, "; ".join(report.errors))
        self.assertTrue(any("active 样本" in line and "domain" in line for line in report.passed))

    def test_out_of_scope_active_domain_is_flagged(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            shutil.copytree(DATA_DIR, data_dir)
            import pandas as pd

            tasks = pd.read_csv(data_dir / "tasks.csv")
            # Flip an active task into a disallowed domain.
            active_idx = tasks.index[tasks["status"].astype(str).str.lower() != "inactive"][0]
            tasks.loc[active_idx, "domain"] = "Industry Research"
            tasks.to_csv(data_dir / "tasks.csv", index=False)

            report = validate_dataset(
                data_dir,
                manifest_path=data_dir / "dataset_manifest.yml",
                taxonomy_path=data_dir / "label_taxonomy.yml",
            )
            self.assertFalse(report.is_valid)
            self.assertTrue(any("不在允许领域范围内" in e for e in report.errors))


if __name__ == "__main__":
    unittest.main()
