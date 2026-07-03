"""样本库 CRUD 测试。

覆盖 sample_repository 的新增、更新、归档、校验、搜索、筛选以及页面冒烟测试。
所有测试使用临时 JSON 文件，避免污染 data/samples.json。
"""

import tempfile
import unittest
from pathlib import Path

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
            "gold_answer": '{"core_conclusion": "构成重大资产重组"}',
            "rubric": '["准确性", "完整性"]',
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
        self.assertEqual("已归档", sr.get_sample("SM-007").status)

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


class SamplePageSmokeTests(unittest.TestCase):
    def test_samples_page_is_callable(self):
        from src.ui.samples import render_samples_page
        self.assertTrue(callable(render_samples_page))


if __name__ == "__main__":
    unittest.main()
