"""the active dataset is the final 13 finance/legal/IB sample set.

Historical inactive and example samples have been removed from the seed files;
runtime model answers and scores are produced in SQLite instead of committed
as seed rows.
"""

import csv
import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services import eval_runner as er
from scripts.validate_dataset import validate_dataset
from src import gold_quality as gq
from src.data_service import active_case_ids, load_all_data

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SOURCE_CSV = DATA_DIR / "professional_samples_13.csv"

ALLOWED_DOMAINS = {"Capital Markets", "Financial", "Legal"}
EXPECTED_CASE_IDS = [
    "FD-001",
    "FD-002",
    "FD-003",
    "FD-004",
    "FD-005",
    "LD-001",
    "LD-002",
    "LD-003",
    "LD-004",
    "CM-001",
    "CM-002",
    "CM-003",
    "CM-004",
]


class ActiveScopeTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_active_task_count_in_target_range(self):
        self.assertEqual(13, len(self.data.tasks))

    def test_only_allowed_domains_remain_active(self):
        domains = set(self.data.tasks["domain"].astype(str))
        self.assertEqual(ALLOWED_DOMAINS, domains)

    def test_case_id_set_remains_final_13_records(self):
        self.assertEqual(EXPECTED_CASE_IDS, self.data.tasks["case_id"].astype(str).tolist())

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

    def test_every_context_contains_numeric_simulated_data(self):
        for _, task in self.data.tasks.iterrows():
            context = str(task.get("context") or "")
            self.assertRegex(context, r"\d", task.get("case_id"))

    def test_standard_conclusions_are_data_based_not_insufficient_materials(self):
        for case_id, gold in self.data.gold_answer_map.items():
            conclusion = str(gold.get("core_conclusion") or "").strip()
            self.assertTrue(conclusion.startswith("基于已提供模拟数据"), case_id)
            self.assertNotRegex(conclusion[:80], r"资料不足|无法判断", case_id)

    def test_output_requirements_force_preliminary_judgment(self):
        for _, task in self.data.tasks.iterrows():
            case_id = str(task.get("case_id") or "")
            requirement = str(task.get("expected_capability") or "").strip()
            self.assertIn("初步判断", requirement, case_id)
            self.assertIn("初步结论、关键数据依据、主要风险、后续核查边界", requirement, case_id)
            self.assertIn("每部分不超过3条", requirement, case_id)
            self.assertIn("全文不超过900字", requirement, case_id)
            self.assertIn("不得以资料不足作为主要结论", requirement, case_id)

    def test_all_seed_output_requirements_are_compact_and_consistent(self):
        expected = (
            "请基于已提供模拟数据形成初步判断，按‘初步结论、关键数据依据、主要风险、后续核查边界’四部分作答。"
            "每部分不超过3条，全文不超过900字。不得以资料不足作为主要结论。"
        )
        tasks = set(self.data.tasks["expected_capability"].astype(str))
        self.assertEqual({expected}, tasks)

        with SOURCE_CSV.open(encoding="utf-8-sig", newline="") as handle:
            csv_rows = list(csv.DictReader(handle))
        self.assertEqual({expected}, {str(row.get("output_requirement") or "") for row in csv_rows})

        samples = json.loads((PROJECT_ROOT / "data" / "samples.json").read_text(encoding="utf-8"))
        self.assertEqual({expected}, {str(item.get("expected_capability") or "") for item in samples})

    def test_model_prompt_uses_context_but_not_standard_answer_fields(self):
        task = self.data.tasks[self.data.tasks["case_id"] == "FD-001"].iloc[0].to_dict()
        gold = self.data.gold_answer_map["FD-001"]
        combined = {**task, **gold}

        messages = er.build_messages(combined)
        prompt = "\n".join(item["content"] for item in messages)

        self.assertIn("2025", prompt)
        self.assertIn("应收账款", prompt)
        self.assertIn("初步判断", prompt)
        for leak in [
            str(gold["core_conclusion"])[:40],
            str(gold["key_evidence"])[:40],
            "必须计算并指出收入增长 50.0%",
            "忽略已给出的应收账款增速",
        ]:
            self.assertNotIn(leak, prompt)

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
