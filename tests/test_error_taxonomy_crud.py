"""Error-taxonomy and improvement-action write-path tests.

Error labels and data-improvement actions become maintainable in SQLite: labels
are seeded from label_taxonomy.yml, actions from optimization_plan.csv. Writes
stay in SQLite (seed files untouched), every action must link to a
registered error label, deactivation is a soft status flip, and the shared
configuration check (src.error_config) detects invalid labels, high-frequency
errors without actions and orphan actions — while staying clean on the seed.
"""

import tempfile
import unittest
from pathlib import Path

from app.services import dataset_service as ds
from src.data_service import get_data_dir, read_csv_file
from src.error_config import (
    INVALID_LABEL,
    ORPHAN_ACTION,
    evaluate_error_config,
)

_TMP = tempfile.TemporaryDirectory()
_DB_PATH = Path(_TMP.name) / "error_taxonomy_test.db"


def setUpModule():
    ds.initialize_database(_DB_PATH, force=True)


def tearDownModule():
    _TMP.cleanup()


def _reseed():
    ds.initialize_database(_DB_PATH, force=True)


class ErrorLabelCrudTests(unittest.TestCase):
    def setUp(self):
        _reseed()

    def test_seed_labels_come_from_taxonomy(self):
        labels = ds.list_error_taxonomy(_DB_PATH)
        # 标签数量与 seed 的 label_taxonomy.yml 一致，不新增、不伪造。
        from src.data_service import _read_yaml_file

        taxonomy = _read_yaml_file("label_taxonomy.yml", get_data_dir())
        self.assertEqual(len(labels), len(taxonomy.get("labels", [])))
        # severity_level / validation_metric 在 taxonomy 中无来源，初始留空。
        self.assertTrue(labels["severity_level"].isna().all())
        self.assertTrue(labels["validation_metric"].isna().all())

    def test_create_and_activate_label(self):
        ds.create_error_label(
            {
                "error_label": "测试标签",
                "definition": "测试用定义",
                "related_dimension": "",
                "severity_level": "中",
            },
            db_path=_DB_PATH,
        )
        self.assertIn("测试标签", ds.active_error_labels(_DB_PATH))
        row = ds.get_error_label("测试标签", _DB_PATH)
        self.assertEqual(row["definition"], "测试用定义")
        self.assertEqual(row["severity_level"], "中")

    def test_create_rejects_blank_and_duplicate(self):
        with self.assertRaises(Exception):
            ds.create_error_label({"error_label": "  "}, db_path=_DB_PATH)
        existing = next(iter(ds.active_error_labels(_DB_PATH)))
        with self.assertRaises(Exception):
            ds.create_error_label({"error_label": existing}, db_path=_DB_PATH)

    def test_deactivate_is_soft_delete(self):
        label = next(iter(ds.active_error_labels(_DB_PATH)))
        ds.set_error_label_status(label, ds.INACTIVE_STATUS, db_path=_DB_PATH)
        self.assertEqual(ds.get_error_label(label, _DB_PATH)["status"], "inactive")
        self.assertNotIn(label, ds.active_error_labels(_DB_PATH))
        # 记录仍在表中，可再次启用。
        ds.set_error_label_status(label, ds.ACTIVE_STATUS, db_path=_DB_PATH)
        self.assertIn(label, ds.active_error_labels(_DB_PATH))

    def test_edit_does_not_touch_seed_file(self):
        seed_before = read_csv_file("optimization_plan.csv", get_data_dir())
        label = next(iter(ds.active_error_labels(_DB_PATH)))
        ds.update_error_label(label, {"definition": "改动不应回写 seed"}, db_path=_DB_PATH)
        seed_after = read_csv_file("optimization_plan.csv", get_data_dir())
        self.assertTrue(seed_before.equals(seed_after))


class ImprovementActionCrudTests(unittest.TestCase):
    def setUp(self):
        _reseed()

    def test_seed_actions_carry_action_id_and_link(self):
        actions = ds.list_improvement_actions(_DB_PATH)
        seed = read_csv_file("optimization_plan.csv", get_data_dir())
        self.assertEqual(len(actions), len(seed))
        self.assertTrue(actions["action_id"].astype(str).str.startswith("DA-").all())
        # related_error_label 复用 frequent_error，保留原始关联。
        self.assertTrue(actions["frequent_error"].notna().all())

    def test_create_requires_existing_label(self):
        with self.assertRaises(Exception):
            ds.create_improvement_action(
                {"related_error_label": "不存在的标签", "action_description": "x"},
                db_path=_DB_PATH,
            )

    def test_create_links_to_active_label_and_gets_next_id(self):
        label = next(iter(ds.active_error_labels(_DB_PATH)))
        before = ds.list_improvement_actions(_DB_PATH)
        ds.create_improvement_action(
            {
                "related_error_label": label,
                "action_type": "补样本",
                "action_description": "新增补强动作",
                "priority": "高",
            },
            db_path=_DB_PATH,
        )
        after = ds.list_improvement_actions(_DB_PATH)
        self.assertEqual(len(after), len(before) + 1)
        new_row = after.iloc[-1]
        self.assertEqual(new_row["frequent_error"], label)
        self.assertEqual(new_row["action_type"], "补样本")
        # 业务编号唯一递增，不与既有 action_id 冲突。
        self.assertEqual(after["action_id"].nunique(), len(after))

    def test_deactivate_action_is_soft_delete(self):
        label = next(iter(ds.active_error_labels(_DB_PATH)))
        ds.create_improvement_action(
            {
                "related_error_label": label,
                "action_type": "补样本",
                "action_description": "用于停用测试的临时动作",
            },
            db_path=_DB_PATH,
        )
        action_id = int(ds.list_improvement_actions(_DB_PATH)["id"].iloc[-1])
        ds.set_improvement_action_status(action_id, ds.INACTIVE_STATUS, db_path=_DB_PATH)
        self.assertEqual(ds.get_improvement_action(action_id, _DB_PATH)["status"], "inactive")


class ConfigurationCheckTests(unittest.TestCase):
    def setUp(self):
        _reseed()

    def test_clean_seed_has_no_issues(self):
        self.assertEqual(ds.evaluate_error_configuration(_DB_PATH), [])

    def test_detects_invalid_label_and_orphan_action(self):
        # 停用一个被错误标注引用的标签，会同时产生「无效标签引用」与「孤立补强动作」。
        from app.services import dataset_service

        repository = dataset_service._repository(_DB_PATH)
        used_label = next(iter(ds.active_error_labels(_DB_PATH)))
        case_id = str(ds.list_task_cases(_DB_PATH).iloc[0]["case_id"])
        repository.insert(
            "model_responses",
            {
                "output_id": 320001,
                "case_id": case_id,
                "model_name": "Model_A_baseline",
                "answer_text": "临时模型回答。",
            },
        )
        repository.insert(
            "error_annotations",
            {
                "output_id": 320001,
                "case_id": case_id,
                "model_name": "Model_A_baseline",
                "error_type": used_label,
                "severity": "中",
                "error_description": "测试停用标签引用。",
            },
        )
        ds.create_improvement_action(
            {
                "related_error_label": used_label,
                "action_type": "补样本",
                "action_description": "用于孤立动作测试的临时动作",
            },
            db_path=_DB_PATH,
        )
        ds.set_error_label_status(used_label, ds.INACTIVE_STATUS, db_path=_DB_PATH)

        issues = ds.evaluate_error_configuration(_DB_PATH)
        kinds = {issue.kind for issue in issues}
        self.assertIn(INVALID_LABEL, kinds)
        self.assertIn(ORPHAN_ACTION, kinds)

    def test_high_frequency_without_action_is_warning(self):
        labels = [{"error_label": "孤独错误", "definition": "有定义", "status": "active"}]
        counts = {"孤独错误": 9}
        issues = evaluate_error_config(labels, counts, actions=[], rubric_dimensions=[])
        self.assertTrue(any(issue.kind == "high_freq_without_action" for issue in issues))


if __name__ == "__main__":
    unittest.main()
