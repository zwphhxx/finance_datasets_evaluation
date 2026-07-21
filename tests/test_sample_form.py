"""Sample-library form simplification guardrails."""

from __future__ import annotations

import inspect
import unittest

import pandas as pd

from src.ui import samples


class SampleFormSimplificationTests(unittest.TestCase):
    def test_sample_table_uses_professional_scene_column(self):
        self.assertEqual(
            ["样本编号", "任务标题", "专业场景", "测试状态", "完整度"],
            samples._SAMPLE_TABLE_COLUMNS,
        )

    def test_professional_scene_options_are_fixed(self):
        self.assertEqual(["财务场景", "法律场景", "投行场景"], samples.PROFESSIONAL_SCENE_OPTIONS)

    def test_editor_form_omits_derived_and_technical_fields(self):
        source = inspect.getsource(samples._render_sample_editor_dialog_body)
        for forbidden in [
            "历史模型回答标识",
            "错误标签",
            "数据补强方向",
            "评分维度",
            "满分标准",
            "扣分规则",
            "dimension_field",
            "raw_json",
            "Rub" + "ric",
            "理想回复标准 / Gold Answer",
        ]:
            self.assertNotIn(forbidden, source)
        for required in [
            "专业场景",
            "专业标准答案",
            "标准结论",
            "关键依据",
            "边界与需核查事项",
            "本题评分关注点",
            "输出要求",
        ]:
            self.assertIn(required, source)

    def test_csv_template_is_simplified(self):
        self.assertEqual(
            [
                "case_id",
                "title",
                "professional_scene",
                "status",
                "question",
                "context",
                "output_requirement",
                "standard_conclusion",
                "key_evidence",
                "must_have_points",
                "unacceptable_errors",
                "boundary_and_check_items",
                "difficulty",
                "risk_level",
                "manual_review_notes",
                "reviewer_note",
                "scoring_focus",
            ],
            samples._CSV_TEMPLATE_COLUMNS,
        )
        forbidden = {
            "model_answers",
            "error_tags",
            "improvement_suggestions",
            "rubric_dimension_field",
            "rubric_full_mark",
            "rubric_full_mark_standard",
            "rubric_deduction_rules",
        }
        self.assertTrue(forbidden.isdisjoint(set(samples._CSV_TEMPLATE_COLUMNS)))

    def test_new_csv_template_maps_to_existing_sample_shape(self):
        frame = pd.DataFrame([
            {
                "case_id": "CSV-NEW",
                "title": "CSV 样本",
                "professional_scene": "法律场景",
                "status": "已入库",
                "question": "请判断条款风险。",
                "context": "合同审阅背景。",
                "output_requirement": "条款判断 + 依据 + 修改建议",
                "standard_conclusion": "条款需修改。",
                "key_evidence": "触发违约责任。",
                "must_have_points": "说明风险|提出修改建议",
                "unacceptable_errors": "忽略违约责任",
                "boundary_and_check_items": "需核查补充协议。",
                "difficulty": "中等",
                "risk_level": "高",
                "manual_review_notes": "评审责任边界。",
                "reviewer_note": "维护备注",
                "scoring_focus": "重点看条款依据。",
            }
        ])

        records, errors = samples._parse_samples_csv(frame)

        self.assertEqual([], errors)
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("Legal", record["domain"])
        self.assertEqual("条款判断 + 依据 + 修改建议", record["expected_capability"])
        self.assertEqual("中等", record["difficulty"])
        self.assertEqual("高", record["risk_level"])
        self.assertEqual([], record["model_answers"])
        self.assertEqual([], record["error_tags"])
        self.assertEqual([], record["improvement_suggestions"])

    def test_old_csv_template_still_imports(self):
        frame = pd.DataFrame([
            {
                "case_id": "CSV-OLD",
                "title": "旧模板样本",
                "domain": "Capital Markets",
                "task_type": "M&A Analysis",
                "difficulty": "Hard",
                "risk_level": "高",
                "scenario": "旧场景",
                "context": "旧背景",
                "question": "旧任务题",
                "expected_capability": "旧输出要求",
                "gold_core_conclusion": "旧标准结论",
                "gold_key_evidence": "旧关键依据",
                "gold_must_have_points": "旧覆盖点",
                "gold_unacceptable_errors": "旧错误",
                "gold_boundary_conditions": "旧边界",
                "gold_manual_review_notes": "旧评审提示",
                "rubric_dimension_field": "accuracy_score",
                "rubric_dimension_name": "专业准确性",
                "rubric_full_mark": "30",
                "rubric_full_mark_standard": "完整标准",
                "rubric_deduction_rules": "扣分规则",
                "status": "已入库",
            }
        ])

        records, errors = samples._parse_samples_csv(frame)

        self.assertEqual([], errors)
        self.assertEqual(1, len(records))
        self.assertEqual("Capital Markets", records[0]["domain"])
        self.assertTrue(records[0]["rubric"])


if __name__ == "__main__":
    unittest.main()
