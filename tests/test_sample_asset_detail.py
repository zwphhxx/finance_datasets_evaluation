"""sample detail presents an evaluation asset structure."""

import json
import unittest
import unittest.mock

from app.services import dataset_service as ds
from app.services import sample_repository as sr
from src.ui.samples import (
    _gold_answer_html,
    _quality_requirements_html,
    _review_focus_html,
    _task_detail_html,
    build_rubric_rows_for_display,
    build_sample_asset_sections,
    build_sample_table_rows,
    parse_gold_answer_for_display,
    render_sample_detail_panel,
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

    def test_sample_index_keeps_the_complete_title(self):
        title = "需要在专业样本索引中完整展示的长标题" * 3
        sample = sr.Sample(
            sample_id="CASE-LONG",
            title=title,
            scenario="场景",
            task_prompt="任务题",
            status="已入库",
        )
        readiness = ds.assess_sample_readiness(None, None, [])

        rows = build_sample_table_rows([sample], {sample.sample_id: readiness})

        self.assertEqual(title, rows[0]["任务标题"])

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

    def test_archive_helpers_partition_gold_quality_and_review_fields(self):
        display = parse_gold_answer_for_display({
            "core_conclusion": "核心结论第一段\n\n核心结论第二段",
            "key_evidence": "关键依据",
            "must_have_points": ["覆盖点一", "覆盖点二"],
            "unacceptable_errors": ["错误一"],
            "boundary_conditions": "边界说明",
            "manual_review_notes": "评审提示",
            "scoring_focus": "评分关注点",
        })

        gold_html = _gold_answer_html(display)
        quality_html = _quality_requirements_html(display)
        review_html = _review_focus_html(display)

        self.assertIn('class="document-field"', gold_html)
        self.assertIn("<p>核心结论第一段</p>", gold_html)
        self.assertIn("<p>核心结论第二段</p>", gold_html)
        self.assertIn("关键依据", gold_html)
        self.assertNotIn("覆盖点一", gold_html)
        self.assertNotIn("边界说明", gold_html)

        self.assertIn('class="document-list"', quality_html)
        self.assertIn('class="document-list document-list-risk"', quality_html)
        self.assertIn("覆盖点一", quality_html)
        self.assertIn("错误一", quality_html)
        self.assertNotIn("核心结论第一段", quality_html)

        self.assertIn("边界说明", review_html)
        self.assertIn("评审提示", review_html)
        self.assertIn("评分关注点", review_html)
        self.assertNotIn("覆盖点一", review_html)

    def test_task_detail_uses_document_reading_fields(self):
        html = _task_detail_html("任务题第一段\n\n任务题第二段", "业务背景", "输出要求")

        self.assertIn('class="document-field"', html)
        self.assertIn('class="document-field-title"', html)
        self.assertIn("<p>任务题第一段</p>", html)
        self.assertIn("<p>任务题第二段</p>", html)

    def test_task_detail_escapes_dynamic_html_without_truncating_text(self):
        unsafe = '<script data-long="' + ("甲" * 1200) + '">x</script>'

        html = _task_detail_html(unsafe, unsafe, unsafe)

        self.assertNotIn("<script", html)
        self.assertIn("&lt;script", html)
        self.assertIn("甲" * 1200, html)


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
    def test_sample_detail_action_labels_are_unique_and_keep_raw_case_ids(self):
        from src.ui import samples as sample_ui

        raw_and_expected = [
            ("CM-001", r"查看详情：CM\-001"),
            ("<raw>", r"查看详情：\<raw\>"),
            ("**A**", r"查看详情：\*\*A\*\*"),
            ("[A](url)", r"查看详情：\[A\]\(url\)"),
            (r"`A`\B", r"查看详情：\`A\`\\B"),
        ]
        labels = [sample_ui._sample_detail_action_label(raw) for raw, _ in raw_and_expected]

        self.assertEqual([expected for _, expected in raw_and_expected], labels)
        self.assertEqual(len(labels), len(set(labels)))

    def test_no_test_only_combined_gold_renderer_remains_in_product_source(self):
        from pathlib import Path

        source = Path("src/ui/samples.py").read_text(encoding="utf-8")

        self.assertNotIn("def _gold_detail_html", source)

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

    def test_all_four_archive_tabs_render_in_the_same_pass(self):
        sample = sr.Sample(
            sample_id="CASE-TABS",
            title="样本标题",
            scenario="模拟数据全文",
            task_prompt="任务题全文",
            business_context="业务背景全文",
            status="已入库",
            model_answers=["历史运行唯一标记"],
        )
        readiness = ds.assess_sample_readiness(None, None, [])
        gold = {
            "parsed": False,
            "fields": {
                "标准结论": "专业结论唯一标记",
                "关键依据": "关键依据唯一标记",
                "边界与需核查事项": "边界唯一标记",
                "评审提示": "评审提示唯一标记",
                "本题评分关注点": "评分关注点唯一标记",
            },
            "lists": {
                "必须覆盖点": ["必须覆盖点唯一标记"],
                "不可接受错误": ["不可接受错误唯一标记"],
            },
            "fallback_text": "标准答案原文唯一标记",
        }
        tab_labels: list[str] = []
        html_blocks: list[str] = []

        class Tab:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with unittest.mock.patch(
            "src.ui.samples.st.tabs",
            side_effect=lambda labels: tab_labels.extend(labels) or [Tab() for _ in labels],
        ), unittest.mock.patch(
            "src.ui.samples.render_html", side_effect=lambda html: html_blocks.append(str(html))
        ):
            render_sample_detail_panel(
                sample,
                readiness,
                {},
                gold,
                [{
                    "评分维度": "准确性",
                    "满分": "30",
                    "满分标准": "评分标准唯一标记",
                    "扣分规则": "扣分规则唯一标记",
                }],
            )

        self.assertEqual(
            ["任务与模拟数据", "专业标准答案", "质量要求", "评审重点"],
            tab_labels,
        )
        self.assertEqual(4, len(html_blocks))
        task_html, gold_html, quality_html, review_html = html_blocks
        self.assertIn("任务题全文", task_html)
        self.assertIn("模拟数据全文", task_html)
        for text in ["专业结论唯一标记", "关键依据唯一标记", "标准答案原文唯一标记"]:
            self.assertIn(text, gold_html)
        for text in ["必须覆盖点唯一标记", "不可接受错误唯一标记", "评分标准唯一标记", "扣分规则唯一标记"]:
            self.assertIn(text, quality_html)
        for text in ["边界唯一标记", "评审提示唯一标记", "评分关注点唯一标记", "历史运行唯一标记"]:
            self.assertIn(text, review_html)

        rendered = "".join(html_blocks)
        unique_markers = [
            "任务题全文",
            "业务背景全文",
            "模拟数据全文",
            "专业结论唯一标记",
            "关键依据唯一标记",
            "标准答案原文唯一标记",
            "必须覆盖点唯一标记",
            "不可接受错误唯一标记",
            "评分标准唯一标记",
            "扣分规则唯一标记",
            "边界唯一标记",
            "评审提示唯一标记",
            "评分关注点唯一标记",
            "历史运行唯一标记",
        ]
        for text in unique_markers:
            self.assertEqual(1, rendered.count(text), text)

    def test_single_index_builds_rows_once_and_scrolls_the_selected_raw_case_id(self):
        from src.ui import samples as sample_ui

        sample = sr.Sample(
            sample_id="LEGAL/01 <raw>",
            title="<script>完整标题</script>",
            scenario="场景",
            task_prompt="任务题",
            status="已入库",
        )
        row = {
            "样本编号": sample.sample_id,
            "任务标题": sample.title,
            "专业场景": "法律场景",
            "测试状态": "可测试",
            "完整度": "通过",
        }
        rendered: list[str] = []

        class Region:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with unittest.mock.patch(
            "src.ui.samples.build_sample_table_rows", return_value=[row]
        ) as build_rows, unittest.mock.patch(
            "src.ui.samples._ensure_selected_sample", return_value=sample
        ), unittest.mock.patch(
            "src.ui.samples.st.container", side_effect=lambda *args, **kwargs: Region()
        ), unittest.mock.patch(
            "src.ui.samples.st.columns", return_value=(Region(), Region())
        ), unittest.mock.patch(
            "src.ui.samples.st.button", return_value=True
        ) as button, unittest.mock.patch(
            "src.ui.samples.st.rerun"
        ), unittest.mock.patch(
            "src.ui.samples.render_html", side_effect=lambda html: rendered.append(str(html))
        ), unittest.mock.patch(
            "src.ui.samples._select_sample"
        ) as select_sample, unittest.mock.patch(
            "src.ui.samples.request_scroll"
        ) as scroll:
            sample_ui._render_sample_index([sample], {}, [])

        build_rows.assert_called_once_with([sample], {}, [])
        self.assertEqual(r"查看详情：LEGAL\/01 \<raw\>", button.call_args.args[0])
        select_sample.assert_called_once_with(sample.sample_id)
        scroll.assert_called_once_with("#fde-current-sample")
        html = "".join(rendered)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;完整标题&lt;/script&gt;", html)


if __name__ == "__main__":
    unittest.main()
