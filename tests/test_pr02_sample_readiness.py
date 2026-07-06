"""PR-02 tests: sample completeness and testability gate."""

import json
import tempfile
import unittest
from pathlib import Path

from app.services import dataset_service as ds
from app.services import sample_repository as sr
from src.ui.samples import build_sample_readiness_map
from src.ui.test_run import eligible_case_ids


class SampleReadinessTests(unittest.TestCase):
    _SENTINEL = object()

    def setUp(self):
        self.task = {
            "case_id": "CASE-READY",
            "question": "请完成尽调判断。",
            "context": "业务背景材料。",
            "scenario": "收入真实性核查",
            "status": ds.ACTIVE_STATUS,
        }
        self.gold = {
            "core_conclusion": "需要进一步核查后判断。",
            "must_have_points": ["核查合同与流水"],
            "unacceptable_errors": ["无依据给出确定结论"],
        }
        self.rubric = [{
            "field": "accuracy_score",
            "name": "准确性",
            "full_mark": 30,
            "full_mark_standard": "结论准确且依据充分。",
            "deduction_rules": "事实错误、缺少依据或结论跳跃时扣分。",
        }]

    def _assess(self, task=_SENTINEL, gold=_SENTINEL, rubric=_SENTINEL):
        return ds.assess_sample_readiness(
            self.task if task is self._SENTINEL else task,
            self.gold if gold is self._SENTINEL else gold,
            self.rubric if rubric is self._SENTINEL else rubric,
        )

    def test_complete_active_sample_is_testable(self):
        readiness = self._assess()
        self.assertTrue(readiness.is_testable)
        self.assertEqual("完整，可测试", readiness.label)
        self.assertEqual([], readiness.missing_items)

    def test_missing_gold_answer_is_not_testable(self):
        readiness = self._assess(gold=None)
        self.assertFalse(readiness.is_testable)
        self.assertIn("缺少专业标准答案", readiness.missing_items)

    def test_missing_must_have_points_is_not_testable(self):
        readiness = self._assess(gold={"core_conclusion": "有结论", "unacceptable_errors": ["错误"]})
        self.assertFalse(readiness.is_testable)
        self.assertIn("缺少必须覆盖点", readiness.missing_items)

    def test_missing_unacceptable_errors_is_not_testable(self):
        readiness = self._assess(gold={"core_conclusion": "有结论", "must_have_points": ["要点"]})
        self.assertFalse(readiness.is_testable)
        self.assertIn("缺少不可接受错误", readiness.missing_items)

    def test_missing_rubric_is_not_testable(self):
        readiness = self._assess(rubric=[])
        self.assertFalse(readiness.is_testable)
        self.assertIn("缺少评分维度配置", readiness.missing_items)

    def test_rubric_with_only_dimension_and_full_mark_is_not_testable(self):
        rubric = [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}]
        self.assertFalse(ds.has_rubric_criteria(rubric))
        readiness = self._assess(rubric=rubric)
        self.assertFalse(readiness.is_testable)
        self.assertIn("缺少评分标准满分标准", readiness.missing_items)
        self.assertIn("缺少评分标准扣分规则", readiness.missing_items)

    def test_rubric_missing_full_mark_standard_is_not_testable(self):
        rubric = [{
            "field": "accuracy_score",
            "name": "准确性",
            "full_mark": 30,
            "deduction_rules": "事实错误扣分。",
        }]
        self.assertFalse(ds.has_rubric_criteria(rubric))
        self.assertIn("缺少评分标准满分标准", self._assess(rubric=rubric).missing_items)

    def test_rubric_missing_deduction_rules_is_not_testable(self):
        rubric = [{
            "field": "accuracy_score",
            "name": "准确性",
            "full_mark": 30,
            "full_mark_standard": "结论准确且依据充分。",
        }]
        self.assertFalse(ds.has_rubric_criteria(rubric))
        self.assertIn("缺少评分标准扣分规则", self._assess(rubric=rubric).missing_items)

    def test_complete_rubric_is_testable(self):
        self.assertTrue(ds.has_rubric_criteria(self.rubric))
        self.assertTrue(self._assess().is_testable)

    def test_archived_sample_is_not_testable(self):
        task = {**self.task, "status": ds.INACTIVE_STATUS}
        readiness = self._assess(task=task)
        self.assertFalse(readiness.is_testable)
        self.assertEqual("已移出测试", readiness.label)
        self.assertIn("样本已移出测试", readiness.missing_items)

    def test_missing_task_fields_are_reported(self):
        task = {**self.task, "question": "", "context": "", "scenario": ""}
        readiness = self._assess(task=task)
        self.assertFalse(readiness.is_testable)
        self.assertIn("缺少任务题", readiness.missing_items)
        self.assertIn("缺少业务背景", readiness.missing_items)
        self.assertIn("缺少场景", readiness.missing_items)


class SharedReadinessGateTests(unittest.TestCase):
    def test_sample_library_and_test_run_use_same_gate(self):
        samples = [
            sr.Sample(sample_id="A", title="A", scenario="场景", task_prompt="题干", status="已入库"),
            sr.Sample(sample_id="B", title="B", scenario="场景", task_prompt="题干", status="已入库"),
        ]
        tasks = [
            {"case_id": "A", "question": "题干", "context": "背景", "scenario": "场景", "status": "active"},
            {"case_id": "B", "question": "题干", "context": "背景", "scenario": "场景", "status": "active"},
        ]
        gold_map = {
            "A": {
                "core_conclusion": "有结论",
                "must_have_points": ["要点"],
                "unacceptable_errors": ["错误"],
            },
            "B": {"core_conclusion": "缺少必须覆盖点"},
        }
        rubric = [{
            "field": "accuracy_score",
            "name": "准确性",
            "full_mark": 30,
            "full_mark_standard": "结论准确且依据充分。",
            "deduction_rules": "事实错误扣分。",
        }]

        readiness = build_sample_readiness_map(samples, tasks, gold_map, rubric)
        sample_library_testable = [case_id for case_id, item in readiness.items() if item.is_testable]

        self.assertEqual(["A"], eligible_case_ids(tasks, gold_map, rubric))
        self.assertEqual(["A"], sample_library_testable)


class SampleRepositoryReadinessGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        self.tmp.write("[]")
        self.tmp.close()
        self.original_path = sr._SAMPLES_PATH
        sr._SAMPLES_PATH = Path(self.tmp.name)

    def tearDown(self):
        sr._SAMPLES_PATH = self.original_path
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_cannot_mark_incomplete_sample_as_entered_when_db_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findueval.db"
            ds.ensure_seed_database(db_path, force=True)
            values = {
                "sample_id": "PR02-INCOMPLETE",
                "title": "不完整样本",
                "scenario": "场景",
                "task_prompt": "题干",
                "business_context": "背景",
                "gold_answer": json.dumps({"core_conclusion": "只有结论"}, ensure_ascii=False),
                "rubric": json.dumps([{"dimension_field": "accuracy_score"}], ensure_ascii=False),
                "status": "待复核",
            }
            sr.create_sample(values, db_path=db_path)

            with self.assertRaisesRegex(ValueError, "缺少必须覆盖点"):
                sr.set_sample_status("PR02-INCOMPLETE", "已入库", db_path=db_path)

            self.assertEqual("待复核", sr.get_sample("PR02-INCOMPLETE").status)
            self.assertEqual(ds.DRAFT_STATUS, ds.get_task_case("PR02-INCOMPLETE", db_path)["status"])


if __name__ == "__main__":
    unittest.main()
