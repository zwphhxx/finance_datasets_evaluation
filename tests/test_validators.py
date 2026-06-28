import unittest
from copy import deepcopy
from dataclasses import replace

import pandas as pd

from src.data_service import load_all_data
from src.validators import validate_evaluation_data


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.data = deepcopy(load_all_data())

    def test_current_seed_data_has_no_validation_errors(self):
        result = validate_evaluation_data(self.data)

        self.assertTrue(result.is_valid)
        self.assertEqual([], result.errors)

    def test_missing_required_column_is_an_error(self):
        data = self.data
        data.tasks.drop(columns=["question"], inplace=True)

        result = validate_evaluation_data(data)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("tasks.csv 缺少必填字段：question" in message for message in result.errors)
        )

    def test_orphan_score_output_id_is_an_error(self):
        data = self.data
        data.scores.loc[len(data.scores)] = {
            "output_id": 9999,
            "case_id": "CM-001",
            "model_name": "Model_X",
            "accuracy_score": 80,
            "reasoning_score": 80,
            "coverage_score": 80,
            "evidence_score": 80,
            "expression_score": 80,
            "total_score": 80,
            "review_note": "orphan score",
        }

        result = validate_evaluation_data(data)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any(
                "scores.csv 中存在无法匹配 model_outputs.output_id 的记录。"
                in message
                for message in result.errors
            )
        )

    def test_score_out_of_range_is_an_error(self):
        data = self.data
        data.scores.loc[data.scores.index[0], "total_score"] = 101

        result = validate_evaluation_data(data)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("scores.csv 中 total_score 存在超出 0-100 范围的记录。" in message for message in result.errors)
        )

    def test_missing_optional_associations_are_warnings(self):
        data = replace(
            self.data,
            scores=pd.DataFrame(columns=self.data.scores.columns),
            errors=pd.DataFrame(columns=self.data.errors.columns),
            gold_answers=self.data.gold_answers[:-1],
        )

        result = validate_evaluation_data(data)

        self.assertTrue(result.is_valid)
        self.assertTrue(any("部分模型回答尚未评分" in message for message in result.warnings))
        self.assertTrue(any("部分模型回答尚未配置错误标签" in message for message in result.warnings))
        self.assertTrue(any("部分任务暂未配置 Gold Answer" in message for message in result.warnings))


if __name__ == "__main__":
    unittest.main()
