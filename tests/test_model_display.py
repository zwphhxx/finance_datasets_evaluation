import unittest
from pathlib import Path

import pandas as pd

from app.services import conclusions as cc
from app.services import model_display as md


class ModelDisplayTests(unittest.TestCase):
    def test_live_model_uses_short_name_without_hardcoding(self):
        self.assertEqual("DeepSeek-V4-Pro", md.display_model_name("deepseek-ai/DeepSeek-V4-Pro"))
        self.assertEqual("Qwen3-235B-A22B", md.display_model_name("Qwen/Qwen3-235B-A22B"))
        self.assertEqual("LongCat-2.0", md.display_model_name("meituan-longcat/LongCat-2.0"))

    def test_seed_models_are_displayed_as_examples(self):
        self.assertEqual("示例基线回答", md.display_model_name("Model_A_baseline"))
        self.assertEqual("示例检索增强回答", md.display_model_name("Model_B_rag"))
        self.assertEqual("示例提示词优化回答", md.display_model_name("Model_C_prompt_v2"))

    def test_unknown_seed_source_is_still_marked_as_historical_example(self):
        self.assertEqual("示例历史评价：seed_m", md.display_model_name("seed_m", source="seed"))
        self.assertEqual("示例历史评价", md.source_label("seed"))
        self.assertEqual("本次运行结果", md.source_label("live"))
        self.assertEqual("AI 评分", md.source_label("confirmed" + "_live"))
        self.assertEqual("AI 评分", md.source_label("ai_score_live"))


class ConclusionSourceDisplayTests(unittest.TestCase):
    def test_seed_formal_conclusions_do_not_enter_current_formal_flow(self):
        seed = pd.DataFrame([
            {
                "model_name": "Model_A_baseline",
                "case_id": "C1",
                "total_score": 80,
                "accuracy_score": 24,
                "reasoning_score": 16,
                "coverage_score": 16,
                "evidence_score": 12,
                "expression_score": 12,
                "review_note": "",
            }
        ])
        rows = cc.build_formal_conclusions(seed, pd.DataFrame())

        self.assertEqual([], rows)

    def test_live_formal_conclusions_show_actual_selected_model_short_name(self):
        live = pd.DataFrame([
            {
                "id": 1,
                "run_id": "RUN-X",
                "case_id": "C1",
                "eval_model": "vendor/Actual-Model",
                "judge_status": "success",
                "review_status": "confirmed",
                "status": "active",
                "total_score": 88,
                "accuracy_score": 26,
                "reasoning_score": 18,
                "coverage_score": 18,
                "evidence_score": 13,
                "expression_score": 13,
                "review_note": "",
            }
        ])
        ai_scores, _ = cc.split_live_scores(live)
        rows = cc.build_formal_conclusions(pd.DataFrame(), ai_scores)

        self.assertEqual("vendor/Actual-Model", rows[0]["model_name"])
        self.assertEqual("Actual-Model", rows[0]["display_name"])
        self.assertEqual("ai_score_live", rows[0]["source"])
        self.assertEqual("AI 评分", rows[0]["source_label"])

    def test_conclusions_page_uses_current_ai_scores_only(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")

        self.assertIn("当前结论", source)
        self.assertIn("cc.build_model_issue_summaries(ai_scores", source)
        self.assertNotIn("Model_A_baseline", source)


if __name__ == "__main__":
    unittest.main()
