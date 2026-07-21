"""sample detail presents an evaluation asset structure."""

import json
import unittest

from app.services import dataset_service as ds
from app.services import sample_repository as sr
from src.ui.samples import (
    _gold_detail_html,
    _task_detail_html,
    build_rubric_rows_for_display,
    build_sample_asset_sections,
    build_sample_table_rows,
    parse_gold_answer_for_display,
)


class SampleListSummaryTests(unittest.TestCase):
    def test_sample_table_rows_keep_list_compact(self):
        sample = sr.Sample(
            sample_id="CASE-1",
            title="样本标题",
            scenario="场景",
            task_prompt="很长的任务题" * 20,
            business_context="很长的业务背景" * 20,
            gold_answer=json.dumps({"core_conclusion": "结论"}, ensure_ascii=False),
            rubric=json.dumps([{"dimension_field": "accuracy_score"}], ensure_ascii=False),
            error_tags=["错误标签"],
            status="已入库",
            difficulty="Hard",
            updated_at="2026-07-05 12:00:00",
        )
        readiness = ds.assess_sample_readiness(
            {"case_id": "CASE-1", "question": "题", "context": "背景", "scenario": "场景", "status": "active"},
            {"core_conclusion": "结论", "must_have_points": ["要点"], "unacceptable_errors": ["错误"]},
            [{
                "field": "accuracy_score",
                "name": "准确性",
                "full_mark": 30,
                "full_mark_standard": "结论准确且依据充分。",
                "deduction_rules": "事实错误扣分。",
            }],
        )

        rows = build_sample_table_rows([sample], {"CASE-1": readiness})

        self.assertEqual(
            ["样本编号", "任务标题", "专业场景", "测试状态", "完整度"],
            list(rows[0].keys()),
        )
        self.assertEqual("可测试", rows[0]["测试状态"])
        self.assertEqual("通过", rows[0]["完整度"])
        self.assertNotIn("状态", rows[0])
        self.assertNotIn("难度", rows[0])
        self.assertNotIn("缺失项摘要", rows[0])
        self.assertNotIn("task_prompt", rows[0])
        self.assertNotIn("gold_answer", rows[0])
        self.assertNotIn("rubric", rows[0])
        self.assertNotIn("error_tags", rows[0])

    def test_sample_table_rows_merge_readiness_states(self):
        sample = sr.Sample(
            sample_id="CASE-2",
            title="待补充样本",
            scenario="场景",
            task_prompt="任务题",
            status="已入库",
            difficulty="Medium",
            updated_at="",
        )
        readiness = ds.assess_sample_readiness(
            {"case_id": "CASE-2", "question": "题", "context": "", "scenario": "场景", "status": "active"},
            {},
            [],
        )

        rows = build_sample_table_rows([sample], {"CASE-2": readiness})

        self.assertEqual("待补充", rows[0]["测试状态"])


class GoldAnswerDisplayTests(unittest.TestCase):
    def test_gold_answer_json_is_structured(self):
        raw = json.dumps(
            {
                "core_conclusion": "核心结论",
                "key_evidence": "关键依据",
                "must_have_points": ["覆盖点一", "覆盖点二"],
                "unacceptable_errors": ["错误一"],
                "boundary_conditions": "边界条件",
                "manual_review_notes": "评审提示",
            },
            ensure_ascii=False,
        )

        display = parse_gold_answer_for_display(raw)

        self.assertTrue(display["parsed"])
        self.assertEqual("核心结论", display["fields"]["标准结论"])
        self.assertEqual(["覆盖点一", "覆盖点二"], display["lists"]["必须覆盖点"])
        self.assertEqual(["错误一"], display["lists"]["不可接受错误"])
        self.assertEqual("", display["fallback_text"])

    def test_invalid_gold_answer_text_falls_back_without_crashing(self):
        display = parse_gold_answer_for_display("无法解析的自由文本")

        self.assertFalse(display["parsed"])
        self.assertEqual("无法解析的自由文本", display["fallback_text"])
        self.assertEqual("待补充", display["fields"]["标准结论"])

    def test_gold_answer_detail_uses_document_reading_fields(self):
        display = parse_gold_answer_for_display({
            "core_conclusion": "核心结论第一段\n\n核心结论第二段",
            "key_evidence": "关键依据",
            "must_have_points": ["覆盖点一", "覆盖点二"],
            "unacceptable_errors": ["错误一"],
            "boundary_conditions": "边界说明",
        })

        html = _gold_detail_html(display)

        self.assertIn('class="document-field"', html)
        self.assertIn('class="document-field-title"', html)
        self.assertIn('class="document-list"', html)
        self.assertIn('class="document-list document-list-risk"', html)
        self.assertIn("<p>核心结论第一段</p>", html)
        self.assertIn("<p>核心结论第二段</p>", html)

    def test_task_detail_uses_document_reading_fields(self):
        html = _task_detail_html("任务题第一段\n\n任务题第二段", "业务背景", "输出要求")

        self.assertIn('class="document-field"', html)
        self.assertIn('class="document-field-title"', html)
        self.assertIn("<p>任务题第一段</p>", html)
        self.assertIn("<p>任务题第二段</p>", html)


class ScoringStandardDisplayTests(unittest.TestCase):
    def test_rubric_rows_use_dynamic_dimensions_and_rules(self):
        dimensions = [
            {
                "field": "accuracy_score",
                "name": "准确性",
                "full_mark": 30,
                "full_mark_standard": "结论准确且有依据",
                "deduction_rules": "事实错误扣分",
                "related_error_type": "事实错误",
            }
        ]

        rows = build_rubric_rows_for_display(dimensions)

        self.assertEqual("准确性", rows[0]["评分维度"])
        self.assertEqual("30", rows[0]["满分"])
        self.assertEqual("结论准确且有依据", rows[0]["满分标准"])
        self.assertEqual("事实错误扣分", rows[0]["扣分规则"])
        self.assertEqual("事实错误", rows[0]["关联错误类型或说明"])

    def test_missing_rubric_rows_show_pending(self):
        self.assertEqual([], build_rubric_rows_for_display([]))

    def test_incomplete_rubric_rows_show_missing_items_without_fake_standards(self):
        rows = build_rubric_rows_for_display([
            {"field": "accuracy_score", "name": "准确性", "full_mark": 30}
        ])

        self.assertEqual("准确性", rows[0]["评分维度"])
        self.assertEqual("30", rows[0]["满分"])
        self.assertEqual("缺少满分标准；缺少扣分规则", rows[0]["缺失项"])
        self.assertNotIn("满分标准", rows[0])
        self.assertNotIn("扣分规则", rows[0])


class AssetSectionTests(unittest.TestCase):
    def test_asset_sections_have_required_order_and_prompt_boundary(self):
        sample = sr.Sample(
            sample_id="CASE-2",
            title="样本标题",
            scenario="场景",
            task_prompt="任务题",
            business_context="业务背景",
            status="已入库",
            difficulty="Medium",
            reviewer_note="维护备注",
        )
        readiness = ds.assess_sample_readiness(
            {"case_id": "CASE-2", "question": "任务题", "context": "业务背景", "scenario": "场景", "status": "active"},
            {"core_conclusion": "结论", "must_have_points": ["要点"], "unacceptable_errors": ["错误"]},
            [{
                "field": "accuracy_score",
                "name": "准确性",
                "full_mark": 30,
                "full_mark_standard": "结论准确且依据充分。",
                "deduction_rules": "事实错误扣分。",
            }],
        )

        sections = build_sample_asset_sections(
            sample=sample,
            readiness=readiness,
            task_record={"expected_capability": "考察能力"},
            gold_display=parse_gold_answer_for_display(
                {"core_conclusion": "结论", "must_have_points": ["要点"], "unacceptable_errors": ["错误"]}
            ),
            rubric_rows=[{
                "评分维度": "准确性",
                "满分": "30",
                "满分标准": "结论准确且依据充分。",
                "扣分规则": "事实错误扣分。",
            }],
        )

        self.assertEqual(
            [
                "基础信息",
                "任务内容",
                "专业标准答案",
                "评分标准",
                "历史运行与优化",
                "准入检查",
            ],
            [section["title"] for section in sections],
        )
        self.assertIn("被测模型只看到任务题、业务背景和输出要求", sections[1]["caption"])
        self.assertIn("裁判评分链路", sections[2]["caption"])


if __name__ == "__main__":
    unittest.main()
