"""PR-05 tests: review page emphasizes matrix, attribution, redlines and restrained tags."""

import unittest
from pathlib import Path

import pandas as pd

from src.ui import components
from src.ui import review


def _score_row(**overrides):
    base = {
        "output_id": "OUT-1",
        "case_id": "CASE-1",
        "model_name": "model-x",
        "accuracy_score": 18,
        "coverage_score": 8,
        "total_score": 55,
        "review_note": "",
    }
    base.update(overrides)
    return pd.Series(base)


def _errors(*rows):
    return pd.DataFrame(
        rows,
        columns=[
            "output_id",
            "case_id",
            "model_name",
            "error_type",
            "severity",
            "error_description",
            "correction",
            "optimization_action",
        ],
    )


class ReviewStructureTests(unittest.TestCase):
    def test_review_sections_have_required_order(self):
        self.assertEqual(
            [
                "待确认评分",
                "当前评分摘要",
                "评分依据",
                "确认处理",
            ],
            review.get_review_sections(),
        )

    def test_scoring_matrix_is_not_hidden_in_expander(self):
        source = Path("src/ui/review.py").read_text(encoding="utf-8")
        self.assertNotIn('with st.expander("评分矩阵"', source)
        self.assertIn('render_numbered_section("03", REVIEW_SECTIONS[2]', source)
        self.assertIn("build_review_recommendation", source)

    def test_confirmation_actions_are_dialog_based(self):
        source = Path("src/ui/review.py").read_text(encoding="utf-8")
        self.assertIn('@st.dialog("确认生效"', source)
        self.assertIn('@st.dialog("修订后确认"', source)
        self.assertIn('@st.dialog("暂不采用"', source)
        actions_source = source.split("def _render_confirmation_actions", 1)[1].split('@st.dialog("确认生效"', 1)[0]
        self.assertNotIn("number_input", actions_source)
        self.assertNotIn("text_area", actions_source)

    def test_review_page_does_not_use_risk_note_cards(self):
        source = Path("src/ui/review.py").read_text(encoding="utf-8")
        self.assertNotIn("review-risk-note", source)
        self.assertNotIn('st.markdown("### 命中红线")', source)
        self.assertNotIn('st.markdown("### 关键维度低分")', source)
        self.assertIn('@st.dialog("评分材料"', source)
        self.assertIn('"查看评分材料"', source)


class ReviewMatrixTests(unittest.TestCase):
    def test_review_basis_rows_keep_main_table_compact(self):
        dimensions = [
            {
                "field": "accuracy_score",
                "name": "准确性",
                "full_mark": 30,
                "deduction_rules": "事实错误扣分",
            },
            {
                "field": "coverage_score",
                "name": "覆盖度",
                "full_mark": 20,
                "deduction_rules": "",
            },
        ]

        rows = review.build_review_basis_rows(_score_row(), pd.DataFrame(), dimensions)

        self.assertEqual(["维度", "得分", "评分依据", "需关注点"], list(rows[0].keys()))
        self.assertEqual("18 / 30", rows[0]["得分"])
        self.assertEqual("未返回明确依据", rows[0]["评分依据"])
        self.assertIn("扣分规则", rows[0]["需关注点"])

    def test_scoring_matrix_rows_use_dynamic_rubric_and_error_labels(self):
        dimensions = [
            {
                "field": "accuracy_score",
                "name": "准确性",
                "full_mark": 30,
                "full_mark_standard": "结论准确且依据充分",
                "deduction_rules": "事实错误扣分",
            },
            {
                "field": "coverage_score",
                "name": "覆盖度",
                "full_mark": 20,
                "full_mark_standard": "",
                "deduction_rules": "",
            },
        ]
        errors = _errors(
            {
                "output_id": "OUT-1",
                "case_id": "CASE-1",
                "model_name": "model-x",
                "error_type": "风险遗漏",
                "severity": "高",
                "error_description": "未覆盖关键风险",
                "correction": "补充关键风险判断",
                "optimization_action": "增加风险覆盖样本",
            }
        )

        rows = review.build_review_scoring_matrix_rows(_score_row(), errors, dimensions)

        self.assertEqual(["准确性", "覆盖度"], [row["评分维度"] for row in rows])
        self.assertEqual("18 / 30", rows[0]["模型得分"])
        self.assertEqual("结论准确且依据充分", rows[0]["理想回复要求 / Gold 要求"])
        self.assertEqual("事实错误扣分", rows[0]["扣分原因"])
        self.assertEqual("未返回明确依据", rows[0]["评分依据"])
        self.assertEqual("风险遗漏", rows[1]["对应错误标签"])
        self.assertEqual("暂无规则", rows[1]["扣分原因"])

    def test_scoring_matrix_handles_missing_scores_and_rubric_fields(self):
        rows = review.build_review_scoring_matrix_rows(
            pd.Series({"output_id": "OUT-1"}),
            pd.DataFrame(),
            [{"field": "accuracy_score", "name": "准确性"}],
        )

        self.assertEqual("待补充", rows[0]["模型得分"])
        self.assertEqual("待补充", rows[0]["理想回复要求 / Gold 要求"])
        self.assertEqual("暂无错误标签", rows[0]["对应错误标签"])


class RecommendationTests(unittest.TestCase):
    def test_high_score_with_rationale_can_be_confirmed(self):
        row = _score_row(
            total_score=90,
            accuracy_score=28,
            coverage_score=18,
            answer_text="回答内容",
            judge_status="success",
            rationale='{"accuracy_score":"核心结论准确且依据充分","coverage_score":"覆盖主要风险点与核查事项"}',
            review_note="可确认",
        )

        recommendation = review.build_review_recommendation(
            row,
            pd.DataFrame(),
            {},
            pd.Series({"risk_level": "中"}),
            review.build_rubric_rows(row),
        )

        self.assertEqual("建议确认", recommendation["recommendation"])

    def test_redline_or_low_score_is_not_recommended_for_archive(self):
        row = _score_row(
            total_score=45,
            answer_text="回答内容",
            judge_status="success",
            rationale='{"accuracy_score":"依据不足"}',
            review_note="需谨慎",
        )
        errors = _errors(
            {
                "output_id": "OUT-1",
                "case_id": "CASE-1",
                "model_name": "model-x",
                "error_type": "风险遗漏",
                "severity": "高",
                "error_description": "未覆盖关键风险",
                "correction": "补充关键风险判断",
                "optimization_action": "增加风险覆盖样本",
            }
        )

        recommendation = review.build_review_recommendation(
            row,
            errors,
            {"unacceptable_errors": ["未覆盖关键风险"]},
            pd.Series({"risk_level": "中"}),
            review.build_rubric_rows(row),
        )

        self.assertEqual("不建议采用", recommendation["recommendation"])
        self.assertTrue(any("高严重度错误" in reason for reason in recommendation["reasons"]))


class ReviewQueueTests(unittest.TestCase):
    def _item(self, recommendation: str, status: str = "pending", source: str = "live"):
        return {
            "case_id": f"CASE-{recommendation}",
            "model_name": "provider/model-x",
            "display_model": "model-x",
            "source": source,
            "output_row": _score_row(review_status=status),
            "recommendation": {"recommendation": recommendation, "level": "success", "reasons": ["依据充分"]},
        }

    def test_queue_stats_separate_pending_recommendations_and_confirmed(self):
        items = [
            self._item("建议确认"),
            self._item("建议复核"),
            self._item("不建议采用"),
            self._item("建议确认", status="confirmed"),
            self._item("建议确认", source="seed"),
        ]

        stats = review.build_review_queue_stats(items)

        self.assertEqual(3, stats["pending"])
        self.assertEqual(1, stats["confirm"])
        self.assertEqual(1, stats["review"])
        self.assertEqual(1, stats["reject"])
        self.assertEqual(1, stats["confirmed"])

    def test_queue_filter_and_bulk_eligibility(self):
        confirm_item = self._item("建议确认")
        review_item = self._item("建议复核")
        confirmed_item = self._item("建议确认", status="confirmed")
        seed_item = self._item("建议确认", source="seed")
        items = [confirm_item, review_item, confirmed_item, seed_item]

        self.assertEqual("待确认", review.REVIEW_FILTER_OPTIONS[0])
        self.assertEqual([confirm_item, review_item], review.filter_review_queue_items(items, "待确认"))
        self.assertEqual([confirm_item], review.filter_review_queue_items(items, "建议确认"))
        self.assertEqual([confirmed_item], review.filter_review_queue_items(items, "已确认"))
        self.assertTrue(review.is_bulk_confirm_eligible(confirm_item))
        self.assertFalse(review.is_bulk_confirm_eligible(review_item))
        self.assertFalse(review.is_bulk_confirm_eligible(confirmed_item))
        self.assertFalse(review.is_bulk_confirm_eligible(seed_item))

    def test_queue_row_marks_bulk_eligibility(self):
        confirm_item = self._item("建议确认")
        review_item = self._item("建议复核")
        confirmed_item = self._item("建议确认", status="confirmed")

        self.assertEqual("是", review.review_queue_row(confirm_item)["可批量确认"])
        self.assertEqual("否", review.review_queue_row(review_item)["可批量确认"])
        self.assertEqual("否", review.review_queue_row(confirmed_item)["可批量确认"])

    def test_bulk_message_survives_rerun_payload(self):
        message = review.build_bulk_review_message(confirmed_count=3, failed_count=2, blocked_count=1)

        self.assertIn("已确认 3 条评分，已纳入正式结论。", message["success"])
        self.assertIn("2 条评分未确认", message["warning"])
        self.assertIn("仅“建议确认”且状态为“待确认”的评分支持批量确认", message["warning"])

    def test_bulk_confirm_result_counts_failures_and_ids(self):
        result = review.summarize_bulk_confirm_result([10, 11, 12], {"confirmed_ids": [10, 12], "failed_ids": [11]})

        self.assertEqual(2, result["confirmed_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual([10, 12], result["confirmed_ids"])
        self.assertEqual([11], result["failed_ids"])

    def test_action_message_payload_persists_after_rerun(self):
        payload = review.build_review_action_result("confirm", 42)

        self.assertEqual("success", payload["level"])
        self.assertEqual(42, payload["row_id"])
        self.assertEqual("confirm", payload["action_type"])
        self.assertEqual("已确认生效，该评分已纳入正式结论。", payload["message"])
        self.assertTrue(payload["show_conclusions_link"])

    def test_revision_and_skip_action_messages_are_specific(self):
        revision = review.build_review_action_result("revision", 43)
        skipped = review.build_review_action_result("skip", 44)

        self.assertEqual("已修订并确认，该评分已纳入正式结论。", revision["message"])
        self.assertEqual("已暂不采用，该评分未纳入正式结论。", skipped["message"])

    def test_next_review_index_skips_handled_row_and_prefers_pending(self):
        handled = self._item("建议确认", status="confirmed")
        handled["score_row_id"] = 1
        next_item = self._item("建议复核")
        next_item["score_row_id"] = 2

        self.assertEqual(1, review.select_next_review_index([handled, next_item], handled_row_id=1))
        self.assertEqual(0, review.select_next_review_index([next_item], handled_row_id=1))
        self.assertIsNone(review.select_next_review_index([], handled_row_id=1))

    def test_pending_queue_helpers_drive_empty_state(self):
        confirmed_item = self._item("建议确认", status="confirmed")
        skipped_item = self._item("不建议采用", status="skipped")
        pending_item = self._item("建议复核")

        self.assertFalse(review.has_pending_review_items([confirmed_item, skipped_item]))
        self.assertTrue(review.has_pending_review_items([confirmed_item, pending_item]))
        self.assertEqual("当前批次暂无待确认评分。", review.review_empty_message([confirmed_item, skipped_item]))
        self.assertEqual("当前筛选条件下暂无评分记录。", review.review_empty_message([confirmed_item, pending_item]))
        self.assertTrue(review.should_show_no_pending_after_action([confirmed_item, skipped_item], True))
        self.assertFalse(review.should_show_no_pending_after_action([confirmed_item, pending_item], True))


class ErrorAttributionTests(unittest.TestCase):
    def test_error_attribution_rows_include_fix_and_data_action(self):
        errors = _errors(
            {
                "output_id": "OUT-1",
                "case_id": "CASE-1",
                "model_name": "model-x",
                "error_type": "风险遗漏",
                "severity": "高",
                "error_description": "未覆盖关键风险",
                "correction": "补充风险判断",
                "optimization_action": "",
            }
        )
        optimizations = pd.DataFrame(
            [
                {
                    "frequent_error": "风险遗漏",
                    "likely_cause": "样本缺少风险计算示例",
                    "optimization_action": "增加风险覆盖样本",
                }
            ]
        )

        rows = review.build_error_attribution_rows(errors, optimizations, "OUT-1")

        self.assertEqual("风险遗漏", rows[0]["错误类型"])
        self.assertEqual("高", rows[0]["严重程度"])
        self.assertEqual("未覆盖关键风险", rows[0]["错误表现"])
        self.assertEqual("补充风险判断", rows[0]["修正方向"])
        self.assertEqual("增加风险覆盖样本", rows[0]["数据优化建议"])

    def test_empty_error_attribution_has_no_rows(self):
        self.assertEqual([], review.build_error_attribution_rows(pd.DataFrame(), pd.DataFrame(), "OUT-1"))


class RedlineAndCopyTests(unittest.TestCase):
    def test_redline_blocks_tolerate_empty_inputs(self):
        blocks = review.build_redline_blocks(
            verdict={"redline_hits": []},
            gold={},
            output_row=_score_row(accuracy_score=30, coverage_score=20),
            errors_df=pd.DataFrame(),
            task_info=pd.Series({"risk_level": ""}),
        )

        self.assertEqual([], blocks)

    def test_review_verdict_copy_uses_reference_boundary_labels(self):
        verdict = review.build_case_verdict(
            _score_row(accuracy_score=30, coverage_score=20, total_score=92),
            pd.DataFrame(),
            {},
            pd.Series({"risk_level": "中"}),
        )

        self.assertEqual("可作为初稿参考", verdict["title"])
        self.assertNotEqual("可直接使用", verdict["title"])

    def test_current_review_and_conclusion_pages_do_not_use_old_direct_copy(self):
        for file_path in ["src/ui/review.py", "src/ui/conclusions.py"]:
            source = Path(file_path).read_text(encoding="utf-8")
            self.assertNotIn("可直接使用", source)
            self.assertNotIn("不可直接使用", source)


class TagStyleTests(unittest.TestCase):
    def test_status_badge_palette_is_semantic_and_restrained(self):
        css = components.STYLE_CSS
        for token in ["status-neutral", "status-success", "status-warning", "status-danger", "status-muted"]:
            self.assertIn(token, css)
        self.assertIn("--fde-status-danger-bg", css)
        self.assertIn(".review-risk-note", css)
        risk_css = css.split(".review-risk-note {", 1)[1].split(".text-block-label", 1)[0]
        self.assertNotIn("border-left", risk_css)


if __name__ == "__main__":
    unittest.main()
