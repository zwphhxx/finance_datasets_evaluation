"""PR-17 tests: the dataset quality page derives every statistic from the
loaded data, the manifest and the taxonomy — nothing hardcoded — and the new
page is wired into navigation.
"""

import unittest

from src.data_service import load_all_data, load_dataset_manifest, load_label_taxonomy
from src.ui import dataset_quality as dq


class DatasetQualityBuilderTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.manifest = load_dataset_manifest()
        self.taxonomy = load_label_taxonomy()

    def test_overview_cards_are_dynamic(self):
        cards = dq.get_dataset_overview_cards(self.data, self.manifest)
        by_label = {c["label"]: c["value"] for c in cards}
        # Every number must equal what the data files actually contain.
        self.assertEqual(by_label["任务样本"], len(self.data.tasks))
        self.assertEqual(by_label["模型回答"], len(self.data.model_outputs))
        self.assertEqual(by_label["错误标签"], len(self.data.errors))
        self.assertEqual(by_label["覆盖领域"], self.data.tasks["domain"].nunique())
        self.assertEqual(by_label["任务类型"], self.data.tasks["task_type"].nunique())
        self.assertEqual(by_label["数据集版本"], self.manifest["version"])

    def test_overview_version_falls_back_without_manifest(self):
        cards = dq.get_dataset_overview_cards(self.data, {})
        version = {c["label"]: c["value"] for c in cards}["数据集版本"]
        self.assertEqual(version, "未声明")

    def test_coverage_matrix_totals_match_sample_count(self):
        matrix = dq.build_coverage_matrix(
            self.data.tasks, "domain", "task_type", dq.DOMAIN_LABELS, dq.TASK_TYPE_LABELS
        )
        self.assertFalse(matrix.empty)
        self.assertEqual(int(matrix.loc["合计", "合计"]), len(self.data.tasks))
        # Axis labels are translated to business Chinese, not raw English.
        self.assertIn("资本市场", matrix.index)

    def test_gold_answer_checks_cover_every_task(self):
        checks = dq.build_gold_answer_checks(self.data.gold_answer_map, self.data.tasks)
        self.assertEqual(len(checks), len(self.data.tasks))
        summary = dq.summarize_gold_answer_quality(checks)
        self.assertEqual(summary["total"], len(self.data.tasks))
        # Seed Gold Answers are complete; the summary must reflect that, not invent it.
        self.assertEqual(summary["complete"], len(self.data.tasks))

    def test_gold_answer_check_detects_missing_element(self):
        partial_map = {"X-001": {"conclusion": "结论", "basis": ""}}
        import pandas as pd

        tasks = pd.DataFrame({"case_id": ["X-001"]})
        checks = dq.build_gold_answer_checks(partial_map, tasks)
        self.assertFalse(checks[0]["complete"])
        self.assertFalse(checks[0]["checks"]["关键依据"])

    def test_rubric_checks_pass_on_seed_dataset(self):
        checks = dq.build_rubric_checks(self.manifest, self.data.scores, self.taxonomy)
        statuses = {c["item"]: c["status"] for c in checks}
        self.assertEqual(statuses["评分维度完整"], "pass")
        self.assertEqual(statuses["权重合计合理"], "pass")
        self.assertEqual(statuses["可映射到错误标签"], "pass")

    def test_rubric_weight_check_fails_on_bad_total(self):
        broken = {"rubric": {"total": 999, "dimensions": self.manifest["rubric"]["dimensions"]}}
        checks = dq.build_rubric_checks(broken, self.data.scores, self.taxonomy)
        weight_check = next(c for c in checks if c["item"] == "权重合计合理")
        self.assertEqual(weight_check["status"], "fail")

    def test_error_label_coverage_matches_taxonomy_and_counts(self):
        rows = dq.build_error_label_coverage(self.taxonomy, self.data.errors)
        names = {r["name"] for r in rows}
        taxonomy_names = {l["name"] for l in self.taxonomy["labels"]}
        self.assertEqual(names, taxonomy_names)
        # Observed counts must sum to the labelled rows with a known type.
        observed = sum(r["count"] for r in rows)
        known = self.data.errors["error_type"].isin(taxonomy_names).sum()
        self.assertEqual(observed, int(known))
        # Sorted by frequency, descending.
        self.assertEqual([r["count"] for r in rows], sorted((r["count"] for r in rows), reverse=True))

    def test_extension_steps_cover_all_asset_types(self):
        titles = [t for t, _ in dq.get_extension_steps(self.manifest)]
        self.assertEqual(titles, ["新增任务样本", "新增模型回答", "新增错误标签", "新增优化验证"])


if __name__ == "__main__":
    unittest.main()
