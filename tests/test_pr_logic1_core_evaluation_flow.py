"""PR-LOGIC1 tests: Core evaluation workflow simplification.

Covers:
- Sample without judgment criteria cannot enter formal testing
- deepseek-ai/DeepSeek-V4-Pro is the default judge model
- Pending does not enter formal conclusions
- Confirmed enters formal conclusions
- Tested model prompt does not contain Gold Answer
- Main nav has only 5 primary entries
"""

import unittest

import pandas as pd

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import scorer as sc
from src.ui.navigation import get_primary_nav_items, _TOP_NAV_ITEMS


class SampleJudgmentCriteriaTests(unittest.TestCase):
    def test_has_judgment_criteria_requires_all_fields(self):
        """样本必须具备核心结论、必须覆盖点、不可接受错误才算有评判标准。"""
        self.assertFalse(ds.has_judgment_criteria(None))
        self.assertFalse(ds.has_judgment_criteria({}))
        self.assertFalse(ds.has_judgment_criteria({"core_conclusion": "有结论"}))
        self.assertFalse(ds.has_judgment_criteria({
            "core_conclusion": "有结论",
            "must_have_points": ["要点1"],
        }))
        self.assertTrue(ds.has_judgment_criteria({
            "core_conclusion": "有结论",
            "must_have_points": ["要点1"],
            "unacceptable_errors": ["错误1"],
        }))

    def test_draft_sample_cannot_enter_testing(self):
        """缺少评判标准的样本为 draft，不可进入正式测试。"""
        task = {"case_id": "T1", "status": "active"}
        gold_no_criteria = {"core_conclusion": "有结论"}  # 缺少 must_have_points 和 unacceptable_errors
        self.assertEqual(ds.get_sample_status(task, gold_no_criteria), ds.DRAFT_STATUS)
        self.assertFalse(ds.can_enter_formal_testing(task, gold_no_criteria))

    def test_complete_sample_can_enter_testing(self):
        """评判标准完整的样本为 active，可以进入正式测试。"""
        task = {"case_id": "T1", "status": "active"}
        gold_complete = {
            "core_conclusion": "有结论",
            "must_have_points": ["要点1"],
            "unacceptable_errors": ["错误1"],
        }
        self.assertEqual(ds.get_sample_status(task, gold_complete), ds.ACTIVE_STATUS)
        self.assertTrue(ds.can_enter_formal_testing(task, gold_complete))

    def test_task_draft_status_cannot_enter_testing_even_with_complete_gold(self):
        """任务层标记为 draft 时，即使评判标准完整，也不可进入测试。"""
        task = {"case_id": "T1", "status": "draft"}
        gold_complete = {
            "core_conclusion": "有结论",
            "must_have_points": ["要点1"],
            "unacceptable_errors": ["错误1"],
        }
        self.assertEqual(ds.get_sample_status(task, gold_complete), ds.DRAFT_STATUS)
        self.assertFalse(ds.can_enter_formal_testing(task, gold_complete))

    def test_inactive_sample_cannot_enter_testing(self):
        """已停用样本不可进入测试，无论评判标准是否完整。"""
        task = {"case_id": "T1", "status": "inactive"}
        gold_complete = {
            "core_conclusion": "有结论",
            "must_have_points": ["要点1"],
            "unacceptable_errors": ["错误1"],
        }
        self.assertEqual(ds.get_sample_status(task, gold_complete), ds.INACTIVE_STATUS)
        self.assertFalse(ds.can_enter_formal_testing(task, gold_complete))


class FixedJudgeModelTests(unittest.TestCase):
    def test_default_judge_model_is_deepseek_v4_pro(self):
        """固定裁判模型为 deepseek-ai/DeepSeek-V4-Pro。"""
        self.assertEqual(sc.DEFAULT_JUDGE_MODEL, "deepseek-ai/DeepSeek-V4-Pro")

    def test_score_compare_uses_default_judge_when_not_specified(self):
        """score_compare 在不指定 judge_model_id 时使用默认裁判模型。"""
        # score_compare 的 judge_model_id 参数默认为 None，内部使用 DEFAULT_JUDGE_MODEL
        import inspect
        sig = inspect.signature(sc.score_compare)
        params = list(sig.parameters.keys())
        self.assertIn("judge_model_id", params)
        judge_param = sig.parameters["judge_model_id"]
        self.assertIsNone(judge_param.default)


class ReviewStatusConclusionsTests(unittest.TestCase):
    def test_pending_does_not_enter_formal_conclusions(self):
        """pending 状态的评分不进入正式结论。"""
        seed = pd.DataFrame(
            [{"model_name": "seed_m", "case_id": "C1", "total_score": 80, "accuracy_score": 24,
              "reasoning_score": 16, "coverage_score": 16, "evidence_score": 12,
              "expression_score": 12, "review_note": ""}]
        )
        live = pd.DataFrame([
            {"id": 1, "run_id": "R", "case_id": "C1", "eval_model": "live_m", "judge_status": "success",
             "review_status": "pending", "status": "active", "total_score": 30,
             "accuracy_score": 9, "reasoning_score": 6, "coverage_score": 6,
             "evidence_score": 4, "expression_score": 5, "review_note": ""},
        ])
        confirmed, pending = cc.split_live_scores(live)
        self.assertEqual(1, len(pending))
        self.assertEqual(0, len(confirmed))

        formal = cc.build_formal_conclusions(seed, confirmed)
        # pending 不进入正式结论，只有 seed 数据
        models = {item["model_name"] for item in formal}
        self.assertNotIn("live_m", models)
        self.assertIn("seed_m", models)

    def test_confirmed_enters_formal_conclusions(self):
        """confirmed 状态的评分进入正式结论。"""
        seed = pd.DataFrame(
            [{"model_name": "seed_m", "case_id": "C1", "total_score": 80, "accuracy_score": 24,
              "reasoning_score": 16, "coverage_score": 16, "evidence_score": 12,
              "expression_score": 12, "review_note": ""}]
        )
        live = pd.DataFrame([
            {"id": 2, "run_id": "R", "case_id": "C2", "eval_model": "live_m", "judge_status": "success",
             "review_status": "confirmed", "status": "active", "total_score": 88,
             "accuracy_score": 26, "reasoning_score": 18, "coverage_score": 18,
             "evidence_score": 13, "expression_score": 13, "review_note": ""},
        ])
        confirmed, pending = cc.split_live_scores(live)
        self.assertEqual(0, len(pending))
        self.assertEqual(1, len(confirmed))

        formal = cc.build_formal_conclusions(seed, confirmed)
        models = {item["model_name"] for item in formal}
        self.assertIn("live_m", models)
        self.assertIn("seed_m", models)

        summary = cc.summarize_formal(seed, confirmed)
        self.assertEqual(1, summary["confirmed_rows"])
        self.assertEqual(len(seed) + 1, summary["total_rows"])


class PromptBoundaryTests(unittest.TestCase):
    def test_eval_prompt_never_contains_gold_answer(self):
        """被评测模型的 prompt 绝不可包含 Gold Answer 内容。"""
        task = {
            "case_id": "X-1",
            "task_type": "Revenue Verification",
            "scenario": "某公司收购尽调",
            "question": "请评估收入确认的合规性。",
            "context": "提供了近三年财报。",
            "core_conclusion": "GOLD-结论-不应外泄",
            "must_have_points": ["GOLD要点A", "GOLD要点B"],
            "unacceptable_errors": ["GOLD红线"],
            "key_evidence": "GOLD依据",
        }
        messages = er.build_messages(task)
        joined = " ".join(m["content"] for m in messages)
        for leak in ["GOLD-结论-不应外泄", "GOLD要点A", "GOLD红线", "GOLD依据"]:
            self.assertNotIn(leak, joined)
        # 任务可见字段应在 prompt 中
        self.assertIn("某公司收购尽调", joined)
        self.assertIn("请评估收入确认的合规性。", joined)


class NavigationTests(unittest.TestCase):
    def test_main_nav_has_exactly_five_items(self):
        """主导航必须恰好有 5 个条目。"""
        items = get_primary_nav_items()
        self.assertEqual(5, len(items))

    def test_top_nav_items_are_core_workflow(self):
        """主导航条目对应核心评测流程。"""
        labels = [label for label, _ in _TOP_NAV_ITEMS]
        expected = ["项目说明", "样本库", "发起测试", "评测复核", "评测结论"]
        self.assertEqual(labels, expected)


if __name__ == "__main__":
    unittest.main()
