"""PR-28 tests: the active dataset is the expanded IB / finance / legal sample
set; inactive (e.g. Medical) samples are excluded from every loaded frame and
from statistics; the validator enforces the active-domain scope. All assertions
read live data — nothing hardcoded to a specific count beyond the 12–15 range.
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
        self.assertGreaterEqual(len(self.data.tasks), 12)
        self.assertLessEqual(len(self.data.tasks), 15)

    def test_only_allowed_domains_remain_active(self):
        domains = set(self.data.tasks["domain"].astype(str))
        self.assertTrue(domains.issubset(ALLOWED_DOMAINS), domains)
        self.assertNotIn("Medical", domains)

    def test_inactive_cases_excluded_from_all_frames(self):
        active = set(self.data.tasks["case_id"].astype(str))
        for frame in (self.data.model_outputs, self.data.scores, self.data.errors, self.data.preference_pairs):
            cases = set(frame["case_id"].astype(str))
            self.assertTrue(cases.issubset(active), cases - active)
        self.assertEqual(set(self.data.gold_answer_map), active)

    def test_inactive_marker_drives_filtering(self):
        # The raw file still carries an inactive row; the loader must drop it.
        raw = __import__("pandas").read_csv(DATA_DIR / "tasks.csv")
        self.assertIn("status", raw.columns)
        inactive = raw[raw["status"].astype(str).str.lower() == "inactive"]
        self.assertTrue(len(inactive) >= 1)
        active = active_case_ids(raw)
        for case_id in inactive["case_id"].astype(str):
            self.assertNotIn(case_id, active)


class ActiveSampleQualityTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_every_active_task_has_complete_gold(self):
        for case_id in self.data.tasks["case_id"].astype(str):
            gold = self.data.gold_answer_map.get(case_id)
            self.assertIsNotNone(gold, case_id)
            self.assertTrue(gq.evaluate_gold_quality(gold)["is_usable"], case_id)

    def test_every_active_task_has_scores_and_error_coverage(self):
        scored_cases = set(self.data.scores["case_id"].astype(str))
        for case_id in self.data.tasks["case_id"].astype(str):
            self.assertIn(case_id, scored_cases, case_id)
        # The active error labels still exercise the full taxonomy.
        taxonomy_types = {"风险遗漏", "依据错误", "可执行性弱", "推理不足", "场景错配", "表达问题"}
        self.assertEqual(set(self.data.errors["error_type"].astype(str)), taxonomy_types)


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
