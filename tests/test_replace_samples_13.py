"""Guardrails for replacing the sample corpus with the final 13 records."""

from __future__ import annotations

import importlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CSV = PROJECT_ROOT / "data" / "final_replacement_samples_13.csv"
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


class ReplaceSamples13Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        shutil.copy2(SOURCE_CSV, self.data_dir / SOURCE_CSV.name)
        for name in ["dataset_manifest.yml", "label_taxonomy.yml"]:
            shutil.copy2(PROJECT_ROOT / "data" / name, self.data_dir / name)
        self.db_path = self.root / "app" / "db" / "findueval.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_replace(self) -> dict[str, int]:
        try:
            module = importlib.import_module("scripts.replace_samples")
        except ModuleNotFoundError:
            self.fail("scripts.replace_samples is required for repeatable full sample replacement")
        return module.replace_samples(
            csv_path=self.data_dir / SOURCE_CSV.name,
            data_dir=self.data_dir,
            db_path=self.db_path,
        )

    def test_replace_samples_rebuilds_seed_files_without_legacy_records(self):
        summary = self._run_replace()

        tasks = pd.read_csv(self.data_dir / "tasks.csv", dtype=str).fillna("")
        samples = json.loads((self.data_dir / "samples.json").read_text(encoding="utf-8"))
        gold_answers = json.loads((self.data_dir / "gold_answers.json").read_text(encoding="utf-8"))

        self.assertEqual(13, summary["sample_count"])
        self.assertEqual(EXPECTED_CASE_IDS, tasks["case_id"].tolist())
        self.assertEqual(EXPECTED_CASE_IDS, [item["sample_id"] for item in samples])
        self.assertEqual(EXPECTED_CASE_IDS, [item["case_id"] for item in gold_answers])
        self.assertEqual(13, tasks["case_id"].nunique())
        self.assertNotIn("MED-001", set(tasks["case_id"]))
        self.assertNotIn("MA-001", set(tasks["case_id"]))
        self.assertIn("净利润与经营现金流背离", tasks.loc[tasks["case_id"] == "FD-004", "scenario"].iloc[0])
        self.assertNotIn("应收账款回款风险", tasks.loc[tasks["case_id"] == "FD-004", "scenario"].iloc[0])

        self.assertEqual({"Financial": 5, "Legal": 4, "Capital Markets": 4}, tasks["domain"].value_counts().to_dict())
        for entry in gold_answers:
            for field in [
                "core_conclusion",
                "key_evidence",
                "must_have_points",
                "unacceptable_errors",
                "boundary_conditions",
                "materials_to_check",
            ]:
                self.assertTrue(entry.get(field), f"{entry['case_id']} missing {field}")

    def test_replace_samples_clears_historical_seed_outputs(self):
        self._run_replace()

        expected_empty_csvs = [
            "model_outputs.csv",
            "scores.csv",
            "error_labels.csv",
            "optimization_plan.csv",
            "evaluation_runs.csv",
            "preference_pairs.csv",
            "optimization_comparison.csv",
        ]
        for name in expected_empty_csvs:
            frame = pd.read_csv(self.data_dir / name, dtype=str).fillna("")
            self.assertEqual(0, len(frame), name)

    def test_replace_samples_rebuilds_sqlite_and_removes_live_history(self):
        self._run_replace()

        self.assertTrue(self.db_path.exists())
        with sqlite3.connect(str(self.db_path)) as conn:
            self.assertEqual(13, conn.execute("SELECT COUNT(*) FROM task_cases").fetchone()[0])
            self.assertEqual(13, conn.execute("SELECT COUNT(*) FROM gold_answers").fetchone()[0])
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM task_cases WHERE case_id='MED-001'").fetchone()[0])
            for table in [
                "model_responses",
                "score_records",
                "error_annotations",
                "improvement_actions",
                "evaluation_runs",
                "live_run_responses",
                "live_run_queue",
                "live_run_scores",
                "live_score_queue",
            ]:
                self.assertEqual(0, conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], table)


if __name__ == "__main__":
    unittest.main()
