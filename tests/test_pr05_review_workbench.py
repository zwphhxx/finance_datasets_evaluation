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
                "当前评分详情",
                "评分依据",
                "风险与红线",
                "确认处理",
            ],
            review.get_review_sections(),
        )

    def test_scoring_matrix_is_not_hidden_in_expander(self):
        source = Path("src/ui/review.py").read_text(encoding="utf-8")
        self.assertNotIn('with st.expander("评分矩阵"', source)
        self.assertIn('render_numbered_section("03", REVIEW_SECTIONS[2]', source)
        self.assertIn("build_review_recommendation", source)


class ReviewMatrixTests(unittest.TestCase):
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

        self.assertEqual("不建议归档", recommendation["recommendation"])
        self.assertTrue(any("高严重度错误" in reason for reason in recommendation["reasons"]))


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
        self.assertIn("border-left", css)


if __name__ == "__main__":
    unittest.main()
