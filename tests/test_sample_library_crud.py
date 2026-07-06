"""样本库 CRUD 测试。

覆盖 sample_repository 的新增、更新、移出测试、校验、搜索、筛选以及页面冒烟测试。
所有测试使用临时 JSON 文件，避免污染 data/samples.json。
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.services import dataset_service as ds
from app.services import sample_repository as sr


class SampleRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        self.tmp.write("[]")
        self.tmp.close()
        self.original_path = sr._SAMPLES_PATH
        sr._SAMPLES_PATH = Path(self.tmp.name)

    def tearDown(self):
        sr._SAMPLES_PATH = self.original_path
        Path(self.tmp.name).unlink(missing_ok=True)

    def _sample_values(self, sample_id: str = "SM-001", title: str = "测试样本"):
        return {
            "sample_id": sample_id,
            "title": title,
            "scenario": "某公司拟进行重大资产重组",
            "task_prompt": "请评估该交易是否构成重大资产重组。",
            "business_context": "上市公司现金收购",
            "gold_answer": json.dumps({
                "case_id": sample_id,
                "core_conclusion": "构成重大资产重组",
                "must_have_points": ["测算交易指标比例"],
                "unacceptable_errors": ["未测算比例即下结论"],
            }, ensure_ascii=False),
            "rubric": json.dumps([{
                "dimension_field": "accuracy_score",
                "full_mark_standard": "结论需基于明确测算。",
                "deduction_rules": "缺少关键测算应扣分。",
            }], ensure_ascii=False),
            "status": "待复核",
            "difficulty": "Hard",
            "reviewer_note": "",
        }

    def test_create_sample_appears_in_list(self):
        sr.create_sample(self._sample_values("SM-001"))
        samples = sr.load_samples()
        self.assertEqual(1, len(samples))
        self.assertEqual("SM-001", samples[0].sample_id)
        self.assertEqual("待复核", samples[0].status)

    def test_create_rejects_duplicate_id(self):
        sr.create_sample(self._sample_values("SM-DUP"))
        with self.assertRaises(ValueError) as ctx:
            sr.create_sample(self._sample_values("SM-DUP"))
        self.assertIn("已存在", str(ctx.exception))

    def test_create_rejects_missing_required_fields(self):
        values = {"sample_id": "SM-002"}
        with self.assertRaises(ValueError) as ctx:
            sr.create_sample(values)
        self.assertIn("title", str(ctx.exception))

    def test_create_rejects_invalid_status(self):
        values = self._sample_values("SM-003")
        values["status"] = "无效状态"
        with self.assertRaises(ValueError) as ctx:
            sr.create_sample(values)
        self.assertIn("status", str(ctx.exception))

    def test_update_changes_fields_and_timestamp(self):
        from datetime import datetime

        sr.create_sample(self._sample_values("SM-004"))
        old = sr.get_sample("SM-004")
        old_updated = datetime.fromisoformat(old.updated_at)
        sr.update_sample("SM-004", {"title": "更新后的标题"})
        updated = sr.get_sample("SM-004")
        new_updated = datetime.fromisoformat(updated.updated_at)
        self.assertEqual("更新后的标题", updated.title)
        self.assertGreaterEqual(new_updated, old_updated)

    def test_update_rejects_changing_sample_id(self):
        sr.create_sample(self._sample_values("SM-005"))
        with self.assertRaises(ValueError) as ctx:
            sr.update_sample("SM-005", {"sample_id": "SM-NEW"})
        self.assertIn("sample_id", str(ctx.exception))

    def test_status_transition(self):
        sr.create_sample(self._sample_values("SM-006"))
        sr.set_sample_status("SM-006", "已入库")
        self.assertEqual("已入库", sr.get_sample("SM-006").status)

    def test_archive_sets_status(self):
        sr.create_sample(self._sample_values("SM-007"))
        sr.archive_sample("SM-007")
        self.assertEqual("已移出测试", sr.get_sample("SM-007").status)

    def test_search_finds_by_keyword(self):
        sr.create_sample(self._sample_values("SM-SEARCH", title="收入真实性核查"))
        sr.create_sample(self._sample_values("SM-OTHER", title="存货跌价测试"))
        results = sr.search_samples("收入")
        self.assertEqual(1, len(results))
        self.assertEqual("SM-SEARCH", results[0].sample_id)

    def test_filter_by_status(self):
        sr.create_sample(self._sample_values("SM-A", title="A"))
        sr.create_sample(self._sample_values("SM-B", title="B"))
        sr.set_sample_status("SM-B", "已入库")
        filtered = sr.filter_samples(status="已入库")
        self.assertEqual(1, len(filtered))
        self.assertEqual("SM-B", filtered[0].sample_id)

    def test_filter_by_error_tag(self):
        values = self._sample_values("SM-TAG")
        values["error_tags"] = ["风险遗漏", "依据不足"]
        sr.create_sample(values)
        filtered = sr.filter_samples(error_tag="风险遗漏")
        self.assertEqual(1, len(filtered))

    def test_seed_from_tasks_creates_samples(self):
        # 在真实项目数据上验证初始化逻辑
        samples = sr.seed_samples_from_tasks()
        self.assertGreater(len(samples), 0)
        for sample in samples:
            self.assertTrue(sample.sample_id)
            self.assertTrue(sample.title)

    def test_final_seed_does_not_carry_legacy_run_history(self):
        """最终 13 条样本 seed 不应再挂载旧模型回答、错误标签或优化建议。"""
        samples = sr.seed_samples_from_tasks()
        self.assertGreater(len(samples), 0)
        for sample in samples:
            self.assertEqual([], sample.error_tags)
            self.assertEqual([], sample.model_answers)
            self.assertEqual([], sample.improvement_suggestions)

    def test_get_eligible_case_ids_returns_approved_only(self):
        sr.create_sample(self._sample_values("SM-ELIGIBLE"))
        sr.create_sample(self._sample_values("SM-PENDING"))
        sr.set_sample_status("SM-ELIGIBLE", "已入库")
        eligible = sr.get_eligible_case_ids()
        self.assertIn("SM-ELIGIBLE", eligible)
        self.assertNotIn("SM-PENDING", eligible)

    def test_sample_status_syncs_to_formal_task_layer_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findueval.db"
            ds.ensure_seed_database(db_path, force=True)
            case_id = str(ds.list_task_cases(db_path).iloc[0]["case_id"])

            sr.create_sample(self._sample_values(case_id))
            sr.set_sample_status(case_id, "需优化", db_path=db_path)
            self.assertEqual(ds.DRAFT_STATUS, ds.get_task_case(case_id, db_path)["status"])

            sr.set_sample_status(case_id, "已入库", db_path=db_path)
            self.assertEqual(ds.ACTIVE_STATUS, ds.get_task_case(case_id, db_path)["status"])

            sr.archive_sample(case_id, db_path=db_path)
            self.assertEqual(ds.INACTIVE_STATUS, ds.get_task_case(case_id, db_path)["status"])

    def test_create_sample_writes_formal_task_gold_and_rubric_when_db_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findueval.db"
            ds.ensure_seed_database(db_path, force=True)
            values = self._sample_values("PR01-NEW", title="PR01 新增样本")
            values["status"] = "已入库"

            sr.create_sample(values, db_path=db_path)

            task = ds.get_task_case("PR01-NEW", db_path)
            self.assertIsNotNone(task)
            self.assertEqual(values["scenario"], task["scenario"])
            self.assertEqual(values["task_prompt"], task["question"])
            self.assertEqual(values["business_context"], task["context"])
            self.assertEqual(values["difficulty"], task["difficulty"])
            self.assertEqual(ds.ACTIVE_STATUS, task["status"])

            gold = ds.get_gold_answer_record("PR01-NEW", db_path)
            self.assertEqual("构成重大资产重组", gold["core_conclusion"])
            self.assertEqual(["测算交易指标比例"], gold["must_have_points"])
            self.assertEqual(["未测算比例即下结论"], gold["unacceptable_errors"])
            self.assertTrue(ds.can_enter_formal_testing(task, gold, ds.get_rubric_dimensions(db_path)))

            rubrics = ds.list_rubrics(db_path)
            row = rubrics[rubrics["dimension_field"] == "accuracy_score"].iloc[0]
            self.assertEqual("结论需基于明确测算。", row["full_mark_standard"])
            self.assertEqual("缺少关键测算应扣分。", row["deduction_rules"])

            sync_result = sr.verify_sample_asset_sync("PR01-NEW", db_path=db_path)
            self.assertTrue(sync_result["ok"])
            self.assertTrue(sync_result["task_exists"])
            self.assertTrue(sync_result["gold_exists"])
            self.assertTrue(sync_result["rubric_exists"])
            self.assertTrue(sync_result["is_testable"])

    def test_update_sample_updates_formal_task_gold_and_rubric_when_db_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findueval.db"
            ds.ensure_seed_database(db_path, force=True)
            values = self._sample_values("PR01-EDIT", title="PR01 编辑样本")
            values["status"] = "已入库"
            sr.create_sample(values, db_path=db_path)

            updated_gold = json.dumps({
                "case_id": "PR01-EDIT",
                "core_conclusion": "需补充材料后判断",
                "must_have_points": ["说明待核材料"],
                "unacceptable_errors": ["把待核事项写成确定结论"],
            }, ensure_ascii=False)
            updated_rubric = json.dumps([{
                "dimension_field": "accuracy_score",
                "full_mark_standard": "更新后的满分标准。",
                "deduction_rules": "更新后的扣分规则。",
            }], ensure_ascii=False)

            sr.update_sample(
                "PR01-EDIT",
                {
                    "scenario": "更新后的场景",
                    "task_prompt": "更新后的任务题。",
                    "business_context": "更新后的业务背景",
                    "difficulty": "Medium",
                    "gold_answer": updated_gold,
                    "rubric": updated_rubric,
                    "status": "需优化",
                },
                db_path=db_path,
            )

            task = ds.get_task_case("PR01-EDIT", db_path)
            self.assertEqual("更新后的场景", task["scenario"])
            self.assertEqual("更新后的任务题。", task["question"])
            self.assertEqual("更新后的业务背景", task["context"])
            self.assertEqual("Medium", task["difficulty"])
            self.assertEqual(ds.DRAFT_STATUS, task["status"])

            gold = ds.get_gold_answer_record("PR01-EDIT", db_path)
            self.assertEqual("需补充材料后判断", gold["core_conclusion"])
            self.assertEqual(["说明待核材料"], gold["must_have_points"])
            self.assertEqual(["把待核事项写成确定结论"], gold["unacceptable_errors"])

            rubrics = ds.list_rubrics(db_path)
            row = rubrics[rubrics["dimension_field"] == "accuracy_score"].iloc[0]
            self.assertEqual("更新后的满分标准。", row["full_mark_standard"])
            self.assertEqual("更新后的扣分规则。", row["deduction_rules"])
            self.assertFalse(ds.can_enter_formal_testing(task, gold, ds.get_rubric_dimensions(db_path)))

            sync_result = sr.verify_sample_asset_sync("PR01-EDIT", db_path=db_path)
            self.assertTrue(sync_result["ok"])
            self.assertFalse(sync_result["is_testable"])

    def test_verify_sample_asset_sync_reports_missing_formal_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findueval.db"
            ds.ensure_seed_database(db_path, force=True)

            sync_result = sr.verify_sample_asset_sync("NOT-IN-DB", db_path=db_path)

            self.assertFalse(sync_result["ok"])
            self.assertIn("task_cases 缺少该样本", sync_result["missing_items"])
            self.assertIn("gold_answers 缺少该样本", sync_result["missing_items"])

    def test_sync_all_samples_to_formal_assets_repairs_management_view(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findueval.db"
            ds.ensure_seed_database(db_path, force=True)
            values = self._sample_values("PR04-SYNC", title="PR04 同步样本")
            values["status"] = "已入库"
            sr.create_sample(values)

            self.assertIsNone(ds.get_task_case("PR04-SYNC", db_path))

            result = sr.sync_all_samples_to_formal_assets(db_path=db_path)

            self.assertTrue(result["sqlite_ready"])
            self.assertEqual(1, result["success_count"])
            self.assertEqual(0, result["failed_count"])
            self.assertIsNotNone(ds.get_task_case("PR04-SYNC", db_path))
            self.assertTrue(sr.verify_sample_asset_sync("PR04-SYNC", db_path=db_path)["ok"])

    def test_sample_data_source_status_reports_sqlite_unavailable(self):
        status = sr.sample_data_source_status(db_path=Path(self.tmp.name).with_suffix(".db"))

        self.assertFalse(status["sqlite_ready"])
        self.assertEqual("seed / samples.json", status["source"])
        self.assertIn("SQLite", status["message"])

    def test_export_and_import_samples(self):
        sr.create_sample(self._sample_values("SM-EXP"))
        exported = sr.export_samples_json()
        self.assertIn("SM-EXP", exported)

        imported = sr.import_samples([{
            "sample_id": "SM-EXP",
            "title": "导入后标题",
            "scenario": "某公司拟进行重大资产重组",
            "task_prompt": "请评估。",
            "gold_answer": "{}",
            "rubric": "[]",
            "status": "待复核",
        }])
        self.assertEqual(1, len(imported))
        updated = sr.get_sample("SM-EXP")
        self.assertEqual("导入后标题", updated.title)

    def test_import_samples_rejects_invalid_records(self):
        sr.create_sample(self._sample_values("SM-VALID"))
        with self.assertRaises(ValueError) as ctx:
            sr.import_samples([
                {"sample_id": "SM-VALID", "title": "有标题"},  # 缺少必填字段
            ])
        self.assertIn("必填项", str(ctx.exception))


class SamplePageSmokeTests(unittest.TestCase):
    def test_samples_page_is_callable(self):
        from src.ui.samples import render_samples_page
        self.assertTrue(callable(render_samples_page))


if __name__ == "__main__":
    unittest.main()
