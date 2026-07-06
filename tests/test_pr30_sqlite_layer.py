"""PR-30 tests: the SQLite data layer initializes from the existing seed files,
preserves every table's base fields (status / created_at / updated_at, plus
version on core objects), exposes basic CRUD through the repository, and feeds
the service layer an EvaluationData that is identical to the CSV/JSON loader —
so pages render the same results whether they read the database or the seed.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db import SCHEMA_PATH
from app.db.init_db import InitError, initialize_database
from app.db.repository import TABLE_PRIMARY_KEYS, Repository
from app.services.dataset_service import database_ready, load_evaluation_data
from src.data_service import (
    _read_yaml_file,
    get_data_dir,
    load_all_data,
    read_csv_file,
    read_json_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TMP = tempfile.TemporaryDirectory()
_DB_PATH = Path(_TMP.name) / "findueval_pr30.db"
_COUNTS: dict[str, int] = {}


def setUpModule():
    global _COUNTS
    _COUNTS = initialize_database(_DB_PATH, force=True)


def tearDownModule():
    _TMP.cleanup()


def _seed_counts() -> dict[str, int]:
    data_dir = get_data_dir()
    manifest = _read_yaml_file("dataset_manifest.yml", data_dir)
    rubric_dims = len((manifest.get("rubric", {}) or {}).get("dimensions", []) or [])
    taxonomy = _read_yaml_file("label_taxonomy.yml", data_dir)
    taxonomy_labels = len((taxonomy.get("labels", []) or []) if isinstance(taxonomy, dict) else [])
    return {
        "task_cases": len(read_csv_file("tasks.csv", data_dir)),
        "gold_answers": len(read_json_file("gold_answers.json", data_dir)),
        "rubrics": rubric_dims,
        "model_responses": len(read_csv_file("model_outputs.csv", data_dir)),
        "score_records": len(read_csv_file("scores.csv", data_dir)),
        "error_annotations": len(read_csv_file("error_labels.csv", data_dir)),
        "improvement_actions": len(read_csv_file("optimization_plan.csv", data_dir)),
        "evaluation_runs": len(read_csv_file("evaluation_runs.csv", data_dir)),
        "error_taxonomy": taxonomy_labels,
    }


class InitializationTests(unittest.TestCase):
    def test_row_counts_match_seed_files(self):
        self.assertEqual(_COUNTS, _seed_counts())

    def test_database_ready_reflects_state(self):
        self.assertTrue(database_ready(_DB_PATH))
        self.assertFalse(database_ready(Path(_TMP.name) / "missing.db"))

    def test_refuses_overwrite_without_force(self):
        with self.assertRaises(InitError):
            initialize_database(_DB_PATH, force=False)

    def test_seed_files_remain_present(self):
        # 初始化不得改动或删除任何种子文件。
        for name in ["tasks.csv", "gold_answers.json", "scores.csv"]:
            self.assertTrue((PROJECT_ROOT / "data" / name).exists(), name)


class SchemaFieldTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(str(_DB_PATH))

    def tearDown(self):
        self.connection.close()

    def _columns(self, table: str) -> set[str]:
        return {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}

    def test_every_table_has_base_fields(self):
        for table in TABLE_PRIMARY_KEYS:
            columns = self._columns(table)
            self.assertTrue({"status", "created_at", "updated_at"}.issubset(columns), table)

    def test_core_objects_track_version(self):
        for table in ["task_cases", "gold_answers", "rubrics"]:
            self.assertIn("version", self._columns(table), table)

    def test_seeded_rubrics_include_standards_and_deduction_rules(self):
        rows = self.connection.execute(
            "SELECT dimension_field, full_mark_standard, deduction_rules FROM rubrics"
        ).fetchall()

        self.assertTrue(rows)
        for field, standard, rules in rows:
            self.assertTrue(str(standard or "").strip(), field)
            self.assertTrue(str(rules or "").strip(), field)

    def test_schema_file_is_used(self):
        self.assertTrue(SCHEMA_PATH.exists())


class RepositoryCrudTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(_DB_PATH)

    def test_insert_get_update_delete_roundtrip(self):
        before = self.repo.count("evaluation_runs")
        self.repo.insert("evaluation_runs", {"run_id": "RUN-PR30", "run_name": "临时批次", "model_name": "m"})
        self.assertEqual(self.repo.count("evaluation_runs"), before + 1)

        row = self.repo.get("evaluation_runs", "RUN-PR30")
        self.assertEqual(row["run_name"], "临时批次")
        self.assertEqual(row["status"], "active")  # 默认值
        self.assertTrue(row["created_at"])

        self.repo.update("evaluation_runs", "RUN-PR30", {"run_name": "已更新"})
        self.assertEqual(self.repo.get("evaluation_runs", "RUN-PR30")["run_name"], "已更新")

        self.repo.delete("evaluation_runs", "RUN-PR30")
        self.assertEqual(self.repo.count("evaluation_runs"), before)

    def test_list_df_preserves_numeric_dtype(self):
        scores = self.repo.list_df("score_records")
        self.assertEqual(str(scores["total_score"].dtype), "int64")


class ServiceParityTests(unittest.TestCase):
    """The DB-backed EvaluationData must equal the seed-loaded one on everything
    the pages read, so display results do not change."""

    @classmethod
    def setUpClass(cls):
        cls.csv = load_all_data()
        cls.db = load_evaluation_data(_DB_PATH)

    def test_frame_shapes_and_columns_match(self):
        for name in ["tasks", "model_outputs", "scores", "errors", "optimizations", "evaluation_runs"]:
            csv_df = getattr(self.csv, name)
            db_df = getattr(self.db, name)
            self.assertEqual(len(csv_df), len(db_df), name)
            self.assertEqual(list(csv_df.columns), list(db_df.columns), name)

    def test_active_case_ids_match(self):
        self.assertEqual(set(self.csv.tasks["case_id"]), set(self.db.tasks["case_id"]))

    def test_gold_answers_identical(self):
        csv_map = {g["case_id"]: g for g in self.csv.gold_answers}
        db_map = {g["case_id"]: g for g in self.db.gold_answers}
        self.assertEqual(csv_map, db_map)
        self.assertEqual(set(self.csv.gold_answer_map), set(self.db.gold_answer_map))

    def test_numeric_aggregates_match(self):
        csv_avg = self.csv.scores.groupby("model_name")["total_score"].mean().round(4).to_dict()
        db_avg = self.db.scores.groupby("model_name")["total_score"].mean().round(4).to_dict()
        self.assertEqual(csv_avg, db_avg)
        self.assertEqual(str(self.csv.scores["total_score"].dtype), str(self.db.scores["total_score"].dtype))

    def test_unmigrated_frames_still_supplied(self):
        self.assertEqual(len(self.csv.preference_pairs), len(self.db.preference_pairs))
        self.assertEqual(len(self.csv.optimization_comparison), len(self.db.optimization_comparison))


if __name__ == "__main__":
    unittest.main()
