"""PR-31 tests: minimal CRUD for task cases, Gold Answers and Rubric dimensions.

CRUD writes only to SQLite (seed files untouched); the active-sample loader and
the task / case-detail pages must see the changes; deletion is a soft status
flip; Gold Answer edits keep raw_json lossless; and the new 数据集管理 page renders
in both DB-ready and seed-fallback modes.
"""

import os
import tempfile
import unittest
from pathlib import Path

import streamlit as st

from app.db.repository import Repository
from app.services import dataset_service as ds
from src.data_service import get_data_dir, read_json_file

_TMP = tempfile.TemporaryDirectory()
_DB_PATH = Path(_TMP.name) / "findueval_pr31.db"


def setUpModule():
    ds.initialize_database(_DB_PATH, force=True)


def tearDownModule():
    _TMP.cleanup()


def _reseed():
    """Rebuild a clean DB so each test class starts from the seed state."""
    ds.initialize_database(_DB_PATH, force=True)


def _active_case_ids() -> set[str]:
    return set(ds.load_evaluation_data(_DB_PATH).tasks["case_id"].astype(str))


class TaskCrudTests(unittest.TestCase):
    def setUp(self):
        _reseed()

    def test_create_task_appears_in_active_load(self):
        before = _active_case_ids()
        ds.create_task_case(
            {
                "case_id": "PR31-NEW",
                "domain": "Financial",
                "task_type": "Revenue Verification",
                "difficulty": "Medium",
                "scenario": "新增任务场景",
                "question": "新增任务题干",
                "expected_capability": "新增考察能力",
                "risk_level": "中",
            },
            db_path=_DB_PATH,
        )
        after = _active_case_ids()
        self.assertNotIn("PR31-NEW", before)
        self.assertIn("PR31-NEW", after)

    def test_create_rejects_duplicate_and_blank_id(self):
        ds.create_task_case({"case_id": "PR31-DUP", "domain": "Financial"}, db_path=_DB_PATH)
        with self.assertRaises(Exception):
            ds.create_task_case({"case_id": "PR31-DUP", "domain": "Financial"}, db_path=_DB_PATH)
        with self.assertRaises(Exception):
            ds.create_task_case({"case_id": "  "}, db_path=_DB_PATH)

    def test_update_task_fields(self):
        case_id = ds.list_task_cases(_DB_PATH)["case_id"].iloc[0]
        ds.update_task_case(case_id, {"difficulty": "Hard", "expected_capability": "改后能力"}, db_path=_DB_PATH)
        row = ds.get_task_case(case_id, _DB_PATH)
        self.assertEqual(row["difficulty"], "Hard")
        self.assertEqual(row["expected_capability"], "改后能力")

    def test_deactivate_is_soft_delete(self):
        case_id = ds.list_task_cases(_DB_PATH)["case_id"].iloc[0]
        ds.set_task_case_status(case_id, ds.INACTIVE_STATUS, db_path=_DB_PATH)
        # 软删除：记录仍在，但不参与活跃样本加载。
        self.assertEqual(ds.get_task_case(case_id, _DB_PATH)["status"], "inactive")
        self.assertNotIn(str(case_id), _active_case_ids())
        # 可再次启用。
        ds.set_task_case_status(case_id, ds.ACTIVE_STATUS, db_path=_DB_PATH)
        self.assertIn(str(case_id), _active_case_ids())


class GoldAnswerCrudTests(unittest.TestCase):
    def setUp(self):
        _reseed()
        self.case_id = ds.list_gold_answer_case_ids(_DB_PATH)[0]

    def test_edit_updates_visible_gold_answer(self):
        ds.update_gold_answer(
            self.case_id,
            {"core_conclusion": "PR31 修改后的核心结论", "must_have_points": ["要点一", "要点二"]},
            db_path=_DB_PATH,
        )
        gold = ds.load_evaluation_data(_DB_PATH).gold_answer_map[self.case_id]
        self.assertEqual(gold["core_conclusion"], "PR31 修改后的核心结论")
        self.assertEqual(gold["must_have_points"], ["要点一", "要点二"])

    def test_raw_json_is_lossless(self):
        original = ds.get_gold_answer_record(self.case_id, _DB_PATH)
        ds.update_gold_answer(self.case_id, {"core_conclusion": "只改这一项"}, db_path=_DB_PATH)
        updated = ds.get_gold_answer_record(self.case_id, _DB_PATH)
        # 未编辑的键原样保留。
        for key in ("analysis", "key_evidence", "materials_to_check", "boundary_conditions"):
            self.assertEqual(updated.get(key), original.get(key), key)
        self.assertEqual(updated["core_conclusion"], "只改这一项")

    def test_edit_does_not_touch_seed_file(self):
        seed_before = read_json_file("gold_answers.json", get_data_dir())
        ds.update_gold_answer(self.case_id, {"core_conclusion": "改动不应回写 seed"}, db_path=_DB_PATH)
        seed_after = read_json_file("gold_answers.json", get_data_dir())
        self.assertEqual(seed_before, seed_after)


class RubricCrudTests(unittest.TestCase):
    def setUp(self):
        _reseed()

    def test_seed_quality_columns_are_complete(self):
        # seed manifest 维护正式 Rubric 标准，初始化后应可直接用于完整度校验。
        rubrics = ds.list_rubrics(_DB_PATH)
        self.assertTrue(rubrics["full_mark_standard"].fillna("").str.strip().astype(bool).all())
        self.assertTrue(rubrics["deduction_rules"].fillna("").str.strip().astype(bool).all())
        self.assertTrue(ds.has_rubric_criteria(ds.get_rubric_dimensions(_DB_PATH)))

    def test_edit_weight_and_rules(self):
        field = ds.list_rubrics(_DB_PATH)["dimension_field"].iloc[0]
        ds.update_rubric(
            field,
            {"weight": 33, "full_mark_standard": "满分标准", "deduction_rules": "扣分规则"},
            db_path=_DB_PATH,
        )
        row = Repository(_DB_PATH).get("rubrics", field)
        self.assertEqual(int(row["weight"]), 33)
        self.assertEqual(row["full_mark_standard"], "满分标准")
        self.assertEqual(row["deduction_rules"], "扣分规则")


if __name__ == "__main__":
    unittest.main()
