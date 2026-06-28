import unittest
from copy import deepcopy
from dataclasses import replace

import pandas as pd

from src.data_service import load_all_data
from src.metrics import get_preference_pairs_for_case
from src.validators import validate_evaluation_data


class EvaluationRunAndPreferencePairTests(unittest.TestCase):
    def setUp(self):
        self.data = deepcopy(load_all_data())

    def test_evaluation_runs_and_preference_pairs_are_loaded(self):
        self.assertIn(
            "run_id",
            self.data.evaluation_runs.columns,
        )
        self.assertIn(
            "pair_id",
            self.data.preference_pairs.columns,
        )
        self.assertGreaterEqual(len(self.data.evaluation_runs), 1)
        self.assertGreaterEqual(len(self.data.preference_pairs), 1)

    def test_preference_pairs_can_be_filtered_by_case(self):
        pairs = get_preference_pairs_for_case(self.data.preference_pairs, "CM-001")

        self.assertFalse(pairs.empty)
        self.assertTrue((pairs["case_id"] == "CM-001").all())

    def test_preference_pair_orphan_output_is_validation_error(self):
        preference_pairs = self.data.preference_pairs.copy()
        preference_pairs.loc[len(preference_pairs)] = {
            "pair_id": "PP-999",
            "case_id": "CM-001",
            "preferred_output_id": 9999,
            "rejected_output_id": 1,
            "preference_dimension": "专业准确性",
            "preference_reason": "测试孤立 output_id。",
            "improvement_instruction": "补齐引用。",
            "reviewer": "QA",
            "review_status": "reviewed",
        }
        data = replace(self.data, preference_pairs=preference_pairs)

        result = validate_evaluation_data(data)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any(
                "preference_pairs.csv 中存在无法匹配 model_outputs.output_id 的记录。"
                in message
                for message in result.errors
            )
        )

    def test_empty_preference_pairs_is_warning_only(self):
        data = replace(
            self.data,
            preference_pairs=pd.DataFrame(columns=self.data.preference_pairs.columns),
        )

        result = validate_evaluation_data(data)

        self.assertTrue(result.is_valid)
        self.assertTrue(
            any("preference_pairs.csv 暂无偏好样本" in message for message in result.warnings)
        )


if __name__ == "__main__":
    unittest.main()
