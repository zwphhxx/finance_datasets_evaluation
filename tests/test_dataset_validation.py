"""the standalone dataset validator runs against the data assets,
driven by dataset_manifest.yml and label_taxonomy.yml, and reports passes,
warnings and errors. Negative cases prove the checks actually catch defects.
"""

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.validate_dataset import Report, validate_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


class DatasetValidatorHappyPathTests(unittest.TestCase):
    def setUp(self):
        self.report = validate_dataset(DATA_DIR)

    def test_real_dataset_passes(self):
        self.assertIsInstance(self.report, Report)
        self.assertTrue(self.report.is_valid, msg="; ".join(self.report.errors))
        self.assertEqual([], self.report.errors)
        self.assertGreater(len(self.report.passed), 0)

    def test_report_exposes_three_buckets(self):
        rendered = self.report.render()
        self.assertIn("通过项", rendered)
        self.assertIn("警告项", rendered)
        self.assertIn("错误项", rendered)


class DatasetValidatorNegativeTests(unittest.TestCase):
    """Each test mutates a throwaway copy of the dataset and expects a failure."""

    def _fresh_copy(self, tmp: str) -> Path:
        target = Path(tmp) / "data"
        shutil.copytree(DATA_DIR, target)
        return target

    def _run(self, data_dir: Path) -> Report:
        # Manifest and taxonomy live inside the copied data dir.
        return validate_dataset(data_dir)

    def test_duplicate_case_id_is_flagged(self):
        with TemporaryDirectory() as tmp:
            data_dir = self._fresh_copy(tmp)
            tasks = pd.read_csv(data_dir / "tasks.csv")
            tasks = pd.concat([tasks, tasks.iloc[[0]]], ignore_index=True)
            tasks.to_csv(data_dir / "tasks.csv", index=False)

            report = self._run(data_dir)
            self.assertFalse(report.is_valid)
            self.assertTrue(any("case_id 存在重复" in e for e in report.errors))

    def test_missing_gold_answer_is_flagged(self):
        with TemporaryDirectory() as tmp:
            data_dir = self._fresh_copy(tmp)
            gold = json.loads((data_dir / "gold_answers.json").read_text(encoding="utf-8"))
            dropped = gold.pop()
            (data_dir / "gold_answers.json").write_text(
                json.dumps(gold, ensure_ascii=False), encoding="utf-8"
            )

            report = self._run(data_dir)
            self.assertFalse(report.is_valid)
            self.assertTrue(any("缺少专业标准答案" in e for e in report.errors))
            self.assertTrue(any(dropped["case_id"] in e for e in report.errors))

    def test_incomplete_gold_answer_is_flagged(self):
        with TemporaryDirectory() as tmp:
            data_dir = self._fresh_copy(tmp)
            gold = json.loads((data_dir / "gold_answers.json").read_text(encoding="utf-8"))
            gold[0]["key_evidence"] = ""  # remove a required core field
            (data_dir / "gold_answers.json").write_text(
                json.dumps(gold, ensure_ascii=False), encoding="utf-8"
            )

            report = self._run(data_dir)
            self.assertFalse(report.is_valid)
            self.assertTrue(any("核心要素不完整" in e for e in report.errors))

    def test_unknown_error_label_is_flagged(self):
        with TemporaryDirectory() as tmp:
            data_dir = self._fresh_copy(tmp)
            errors = pd.read_csv(data_dir / "error_labels.csv")
            tasks = pd.read_csv(data_dir / "tasks.csv")
            row = {
                "output_id": "OUT-UNKNOWN-LABEL",
                "case_id": str(tasks.iloc[0]["case_id"]),
                "model_name": "Model_A_baseline",
                "error_type": "未登记标签",
                "severity": "medium",
                "error_description": "临时测试未知错误标签。",
                "correction": "补充标签体系。",
                "optimization_action": "补充验证样本。",
            }
            errors = pd.concat([errors, pd.DataFrame([row])], ignore_index=True)
            errors.to_csv(data_dir / "error_labels.csv", index=False)

            report = self._run(data_dir)
            self.assertFalse(report.is_valid)
            self.assertTrue(any("未在 label_taxonomy 定义" in e for e in report.errors))

    def test_out_of_scope_domain_is_a_warning_not_error(self):
        with TemporaryDirectory() as tmp:
            data_dir = self._fresh_copy(tmp)
            tasks = pd.read_csv(data_dir / "tasks.csv")
            tasks.loc[tasks.index[0], "domain"] = "Unlisted Domain"
            tasks.to_csv(data_dir / "tasks.csv", index=False)

            report = self._run(data_dir)
            self.assertTrue(any("未在 manifest 声明的领域" in w for w in report.warnings))


if __name__ == "__main__":
    unittest.main()
