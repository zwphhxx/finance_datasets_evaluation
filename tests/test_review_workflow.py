"""review page emphasizes matrix, attribution, redlines and restrained tags."""

import unittest
from pathlib import Path

import pandas as pd

from src.ui import components
from src.ui import review
from src.ui import review_materials
from src.ui import review_queue
from src.ui import review_scoring


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
                "待处理评分",
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
        source = Path("src/ui/review_actions.py").read_text(encoding="utf-8")
        self.assertIn('@st.dialog("确认生效"', source)
        self.assertIn('@st.dialog("修订后确认"', source)
        self.assertIn('@st.dialog("暂不采用"', source)
        actions_source = source.split("def render_confirmation_actions", 1)[1].split('@st.dialog("确认生效"', 1)[0]
        self.assertNotIn("number_input", actions_source)
        self.assertNotIn("text_area", actions_source)

    def test_confirmation_actions_clear_stale_session_score_and_show_update_failure(self):
        source = Path("src/ui/review_actions.py").read_text(encoding="utf-8")
        self.assertIn("eval_state.clear_last_score()", source)
        self.assertIn("确认失败：评分记录未更新，请刷新页面后重试。", source)
        self.assertIn("暂不采用失败：评分记录未更新，请刷新页面后重试。", source)

    def test_review_page_does_not_use_risk_note_cards(self):
        combined = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in ["src/ui/review.py", "src/ui/review_materials.py", "src/ui/review_scoring.py"]
        )
        self.assertNotIn("review-risk-note", combined)
        self.assertNotIn('st.markdown("### 命中红线")', combined)
        self.assertNotIn('st.markdown("### 关键维度低分")', combined)
        materials_source = Path("src/ui/review_materials.py").read_text(encoding="utf-8")
        self.assertIn('@st.dialog("评分材料"', materials_source)
        self.assertIn('"查看评分材料"', materials_source)

    def test_current_score_summary_uses_detail_panel_with_materials_action(self):
        materials_source = Path("src/ui/review_materials.py").read_text(encoding="utf-8")
        components_source = Path("src/ui/components.py").read_text(encoding="utf-8")
        summary_source = materials_source.split("def render_score_summary", 1)[1].split("@st.dialog", 1)[0]

        self.assertIn("build_score_summary_panel", materials_source)
        self.assertIn("render_detail_panel_with_action", summary_source)
        self.assertIn("detail-panel-toolbar-title", components_source)
        self.assertIn("review-summary-panel-body", summary_source)
        self.assertIn('"查看评分材料"', summary_source)
        self.assertIn('action_type="secondary"', summary_source)
        self.assertIn("主要原因", summary_source)
        self.assertIn("需要关注", summary_source)
        self.assertNotIn("render_inline_status(summary_rows)", summary_source)

    def test_score_summary_panel_separates_compact_fields_and_long_text(self):
        item = {
            "case_id": "CASE-1",
            "display_model": "model-x",
            "model_name": "provider/model-x",
            "gold": {},
            "task_info": {"risk_level": "高"},
            "rubric_rows": [],
            "output_row": _score_row(
                judge_model="judge/model-y",
                review_note="复核提示需要单独展示",
                answer_text="回答内容",
                judge_status="success",
            ),
            "recommendation": {
                "recommendation": "建议复核",
                "reasons": ["总分处于中间区间", "任务风险等级较高"],
            },
        }

        panel = review_materials.build_score_summary_panel(item, pd.DataFrame())

        self.assertEqual("CASE-1｜model-x", panel["title"])
        self.assertIn("总分 55 / 100", panel["meta"])
        self.assertIn("建议处理：建议复核", panel["meta"])
        self.assertIn("裁判模型：model-y", panel["meta"])
        self.assertEqual("provider/model-x", panel["model_id"])
        self.assertEqual("总分处于中间区间；任务风险等级较高", panel["reason"])
        self.assertEqual("复核提示需要单独展示", panel["review_note"])
        self.assertTrue(any("任务风险等级较高" in item for item in panel["attention"]))


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
        self.assertEqual("结论准确且依据充分", rows[0]["标准答案要求"])
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
        self.assertEqual("待补充", rows[0]["标准答案要求"])
        self.assertEqual("暂无错误标签", rows[0]["对应错误标签"])


class ScoringStandardMaterialDisplayTests(unittest.TestCase):
    def test_incomplete_rubric_material_shows_dimension_config(self):
        state = review_scoring.build_rubric_material_display([
            {"field": "accuracy_score", "name": "准确性", "full_mark": 30}
        ])

        self.assertFalse(state["complete"])
        self.assertEqual("评分维度配置", state["title"])
        self.assertIn("尚未完整维护满分标准与扣分规则", state["note"])
        self.assertEqual(["维度", "满分", "缺失项"], list(state["rows"][0].keys()))
        self.assertEqual("缺少满分标准；缺少扣分规则", state["rows"][0]["缺失项"])
        self.assertNotIn("待补充", str(state["rows"]))
        self.assertNotIn("暂无规则", str(state["rows"]))

    def test_complete_rubric_material_shows_scoring_standard(self):
        state = review_scoring.build_rubric_material_display([
            {
                "field": "accuracy_score",
                "name": "准确性",
                "full_mark": 30,
                "full_mark_standard": "结论准确且依据充分。",
                "deduction_rules": "事实错误扣分。",
            }
        ])

        self.assertTrue(state["complete"])
        self.assertEqual("评分标准", state["title"])
        self.assertEqual(["维度", "满分", "满分标准", "扣分规则"], list(state["rows"][0].keys()))
        self.assertEqual("结论准确且依据充分。", state["rows"][0]["满分标准"])


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

    def test_redline_or_low_score_is_not_recommended_for_adoption(self):
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

    def test_queue_stats_separate_pending_and_processed(self):
        items = [
            self._item("建议确认"),
            self._item("建议复核"),
            self._item("不建议采用"),
            self._item("建议确认", status="confirmed"),
            self._item("不建议采用", status="skipped"),
            self._item("建议确认", source="seed"),
        ]

        stats = review.build_review_queue_stats(items)

        self.assertEqual(3, stats["pending"])
        self.assertEqual(2, stats["processed"])

    def test_queue_filter_is_reduced_to_pending_and_processed(self):
        confirm_item = self._item("建议确认")
        review_item = self._item("建议复核")
        confirmed_item = self._item("建议确认", status="confirmed")
        skipped_item = self._item("不建议采用", status="skipped")
        seed_item = self._item("建议确认", source="seed")
        items = [confirm_item, review_item, confirmed_item, skipped_item, seed_item]

        self.assertEqual(["待处理", "已处理"], review.REVIEW_FILTER_OPTIONS)
        self.assertEqual([confirm_item, review_item], review.filter_review_queue_items(items, "待处理"))
        self.assertEqual([confirmed_item, skipped_item], review.filter_review_queue_items(items, "已处理"))

    def test_queue_row_is_single_select_index_row_without_bulk_columns(self):
        confirm_item = self._item("建议确认")
        row = review.review_queue_row(confirm_item)

        self.assertEqual(
            ["样本编号", "模型", "总分", "建议处理", "状态", "生成时间"],
            list(row.keys()),
        )
        self.assertNotIn("选择", row)
        self.assertNotIn("可批量确认", row)

    def test_table_selection_defaults_to_first_pending_row(self):
        first = self._item("建议确认")
        first["score_row_id"] = 10
        second = self._item("建议复核")
        second["score_row_id"] = 11

        self.assertEqual(0, review.selected_review_table_index(None, [first, second]))
        self.assertEqual(1, review.selected_review_table_index({"selection": {"rows": [1]}}, [first, second]))
        self.assertEqual(0, review.selected_review_table_index({"selection": {"rows": [99]}}, [first, second]))

    def test_review_page_no_longer_exposes_dropdown_or_bulk_confirm(self):
        page_source = Path("src/ui/review.py").read_text(encoding="utf-8")
        queue_source = Path("src/ui/review_queue.py").read_text(encoding="utf-8")
        combined = page_source + "\n" + queue_source

        self.assertNotIn('st.selectbox(\n        "当前评分"', combined)
        self.assertIn("selection_mode=\"single-row\"", queue_source)
        self.assertIn("on_select=\"rerun\"", queue_source)
        self.assertNotIn('"选择评分草稿"', queue_source)
        self.assertNotIn("批量" + "确认生效", combined)
        self.assertNotIn("CheckboxColumn", combined)

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
        self.assertEqual(
            "暂无待处理评分草稿。若发起评测页存在评分失败，请先重试评分。",
            review.review_empty_message([confirmed_item, skipped_item]),
        )
        self.assertEqual("当前筛选条件下暂无评分记录。", review.review_empty_message([confirmed_item, pending_item]))
        self.assertTrue(review.should_show_no_pending_after_action([confirmed_item, skipped_item], True))
        self.assertFalse(review.should_show_no_pending_after_action([confirmed_item, pending_item], True))

    def test_failed_judge_scores_do_not_enter_review_queue(self):
        scores = pd.DataFrame([
            {
                "id": 1,
                "score_run_id": "S1",
                "case_id": "C1",
                "eval_model": "vendor/model-ok",
                "judge_status": "success",
                "review_status": "pending",
                "status": "active",
            },
            {
                "id": 2,
                "score_run_id": "S1",
                "case_id": "C2",
                "eval_model": "vendor/model-failed",
                "judge_status": "failed",
                "review_status": "pending",
                "status": "active",
            },
        ])

        filtered = review_queue.filter_live_score_frame(scores)

        self.assertEqual(["vendor/model-ok"], filtered["eval_model"].tolist())

    def test_score_run_summary_counts_status_models_and_cases(self):
        scores = pd.DataFrame(
            [
                {
                    "score_run_id": "SCORE-OLD",
                    "case_id": "CM-001",
                    "eval_model": "provider/Model-A",
                    "review_status": "confirmed",
                    "created_at": "2026-07-06 09:45:00",
                    "id": 1,
                },
                {
                    "score_run_id": "SCORE-NEW",
                    "case_id": "CM-001",
                    "eval_model": "provider/Model-A",
                    "review_status": "pending",
                    "created_at": "2026-07-06 10:30:00",
                    "id": 2,
                },
                {
                    "score_run_id": "SCORE-NEW",
                    "case_id": "LD-001",
                    "eval_model": "vendor/Model-B",
                    "review_status": "skipped",
                    "created_at": "2026-07-06 10:31:00",
                    "id": 3,
                },
            ]
        )

        summary = review.build_score_run_summary(scores, "SCORE-NEW")

        self.assertEqual("2026-07-06 10:31", summary["created_at"])
        self.assertEqual(2, summary["total"])
        self.assertEqual(1, summary["pending"])
        self.assertEqual(0, summary["confirmed"])
        self.assertEqual(1, summary["skipped"])
        self.assertEqual(2, summary["model_count"])
        self.assertEqual(2, summary["case_count"])
        self.assertEqual(["Model-A", "Model-B"], summary["models"])

    def test_score_run_option_label_hides_technical_id(self):
        scores = pd.DataFrame(
            [
                {
                    "score_run_id": "SCORE-OLD",
                    "case_id": "CM-001",
                    "eval_model": "provider/Model-A",
                    "review_status": "confirmed",
                    "created_at": "2026-07-06 09:45:00",
                    "id": 1,
                },
                {
                    "score_run_id": "SCORE-NEW",
                    "case_id": "LD-001",
                    "eval_model": "vendor/Model-B",
                    "review_status": "pending",
                    "created_at": "2026-07-06 10:30:00",
                    "id": 2,
                },
            ]
        )

        latest_label = review.score_run_option_label(scores, "SCORE-NEW")
        old_label = review.score_run_option_label(scores, "SCORE-OLD")

        self.assertTrue(latest_label.startswith("最新批次｜2026-07-06 10:30｜1 条待处理"))
        self.assertTrue(old_label.startswith("历史批次｜2026-07-06 09:45｜已处理 1 条"))
        self.assertNotIn("SCORE-NEW", latest_label)
        self.assertNotIn("SCORE-OLD", old_label)

    def test_default_score_run_prefers_current_pending_then_latest_pending(self):
        scores = pd.DataFrame(
            [
                {
                    "score_run_id": "SCORE-OLD",
                    "case_id": "CM-001",
                    "eval_model": "provider/Model-A",
                    "review_status": "pending",
                    "created_at": "2026-07-06 09:45:00",
                    "id": 1,
                },
                {
                    "score_run_id": "SCORE-NEW",
                    "case_id": "LD-001",
                    "eval_model": "vendor/Model-B",
                    "review_status": "pending",
                    "created_at": "2026-07-06 10:30:00",
                    "id": 2,
                },
            ]
        )

        self.assertEqual(
            "SCORE-OLD",
            review.default_score_run_id(scores, {"score_run_id": "SCORE-OLD"}),
        )

        processed_preferred = scores.copy()
        processed_preferred.loc[processed_preferred["score_run_id"] == "SCORE-OLD", "review_status"] = "confirmed"
        self.assertEqual(
            "SCORE-NEW",
            review.default_score_run_id(processed_preferred, {"score_run_id": "SCORE-OLD"}),
        )

        all_processed = processed_preferred.copy()
        all_processed["review_status"] = "confirmed"
        self.assertEqual("SCORE-NEW", review.default_score_run_id(all_processed, {}))


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
    def test_status_palette_is_semantic_and_restrained(self):
        css = components.STYLE_CSS
        for token in ["--fde-success-bg", "--fde-warning-bg", "--fde-danger-bg"]:
            self.assertIn(token, css)
        self.assertIn(".inline-pill", css)
        self.assertNotIn(".review-risk-note", css)
        self.assertNotIn(".status-badge", css)
        self.assertNotIn(".score-badge", css)


if __name__ == "__main__":
    unittest.main()
