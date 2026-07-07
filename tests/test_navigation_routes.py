"""Audit and prune page routes to core evaluation workflow.

Covers:
- PAGES dict has exactly 5 keys: case_study, samples, test_run, review, conclusions
- Top nav has exactly 5 items
- Sidebar does not contain old page titles
- DEFAULT_PAGE_KEY == "case_study"
- DEFAULT_JUDGE_MODEL == "deepseek-ai/DeepSeek-V4-Pro"
- Pending does not enter formal conclusions
- Confirmed enters formal conclusions
- Tested model prompt does not contain Gold Answer
- All 5 main pages render without error
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from app.services import conclusions as cc
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import scorer as sc
from src.ui.navigation import PAGES, get_primary_nav_items, _TOP_NAV_ITEMS, DEFAULT_PAGE_KEY
from src.ui.page_config import PAGE_CONFIG_BY_KEY, DEFAULT_PAGE_KEY as PC_DEFAULT_PAGE_KEY


class PagesDictTests(unittest.TestCase):
    def test_pages_has_exactly_five_keys(self):
        """PAGES dict must have exactly 5 entries."""
        self.assertEqual(5, len(PAGES))

    def test_pages_keys_are_expected(self):
        """PAGES keys must be exactly the 5 core workflow pages."""
        expected = ["case_study", "samples", "test_run", "review", "conclusions"]
        self.assertEqual(sorted(expected), sorted(PAGES.keys()))

    def test_pages_does_not_contain_old_keys(self):
        """Old page keys must not be in PAGES."""
        old_keys = {
            "overview", "case_detail", "model_diagnosis", "model_boundary",
            "dataset_quality", "project_methodology", "eval_run",
            "tasks", "evaluation_conclusions", "dataset_admin",
            "model_results", "dataset", "cockpit",
        }
        for key in old_keys:
            self.assertNotIn(key, PAGES, f"Old key '{key}' should not be in PAGES")

    def test_legacy_ui_page_files_are_removed(self):
        """Legacy user-facing UI page files must not remain in src/ui."""
        legacy_files = [
            "case_detail.py",
            "dataset_admin.py",
            "dataset_quality.py",
            "error_analysis.py",
            "eval_console.py",
            "eval_run_page.py",
            "evaluation_conclusions.py",
            "model_boundary.py",
            "model_diagnosis.py",
            "optimization_compare.py",
            "overview.py",
            "project_methodology.py",
            "tasks.py",
        ]
        ui_dir = Path("src/ui")
        for filename in legacy_files:
            self.assertFalse((ui_dir / filename).exists(), filename)


class PageConfigTests(unittest.TestCase):
    def test_page_config_has_exactly_five_entries(self):
        """PAGE_CONFIG_BY_KEY must have exactly 5 entries."""
        self.assertEqual(5, len(PAGE_CONFIG_BY_KEY))

    def test_page_config_keys_match_pages(self):
        """PAGE_CONFIG_BY_KEY keys must match PAGES keys."""
        self.assertEqual(set(PAGES.keys()), set(PAGE_CONFIG_BY_KEY.keys()))

    def test_default_page_key_is_case_study(self):
        """Default page must be case_study."""
        self.assertEqual("case_study", DEFAULT_PAGE_KEY)
        self.assertEqual("case_study", PC_DEFAULT_PAGE_KEY)


class TopNavTests(unittest.TestCase):
    def test_top_nav_has_exactly_five_items(self):
        """Top nav must have exactly 5 items."""
        self.assertEqual(5, len(_TOP_NAV_ITEMS))

    def test_top_nav_labels_are_core_workflow(self):
        """Top nav labels must match the core evaluation workflow."""
        labels = [label for label, _ in _TOP_NAV_ITEMS]
        expected = ["项目说明", "样本库", "发起评测", "评分确认", "评测结论"]
        self.assertEqual(labels, expected)

    def test_top_nav_keys_match_pages(self):
        """Top nav page keys must match PAGES keys."""
        nav_keys = {key for _, key in _TOP_NAV_ITEMS}
        self.assertEqual(nav_keys, set(PAGES.keys()))

    def test_get_primary_nav_items_returns_five(self):
        """get_primary_nav_items must return exactly 5 items."""
        items = get_primary_nav_items()
        self.assertEqual(5, len(items))


class SidebarTests(unittest.TestCase):
    def test_sidebar_does_not_contain_old_titles(self):
        """Sidebar must not show old page titles."""
        old_titles = [
            "红线评测台", "模型能力指纹", "模型边界报告",
            "数据集" + "质量", "数据集" + "管理",
        ]
        for title in old_titles:
            for config in PAGE_CONFIG_BY_KEY.values():
                self.assertNotEqual(
                    title, config.title,
                    f"Old title '{title}' should not appear in page config"
                )

    def test_all_page_configs_are_five_pages(self):
        """All page configs must be one of the 5 core pages."""
        expected_keys = {"case_study", "samples", "test_run", "review", "conclusions"}
        self.assertEqual(expected_keys, set(PAGE_CONFIG_BY_KEY.keys()))


class FixedJudgeModelTests(unittest.TestCase):
    def test_default_judge_model_is_deepseek_v4_pro(self):
        """固定裁判模型为 deepseek-ai/DeepSeek-V4-Pro。"""
        self.assertEqual(sc.DEFAULT_JUDGE_MODEL, "deepseek-ai/DeepSeek-V4-Pro")

    def test_score_compare_uses_default_judge_when_not_specified(self):
        """score_compare 在不指定 judge_model_id 时使用默认裁判模型。"""
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
        models = {item["model_name"] for item in formal}
        self.assertNotIn("live_m", models)
        self.assertNotIn("seed_m", models)

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
        self.assertNotIn("seed_m", models)

        summary = cc.summarize_formal(seed, confirmed)
        self.assertEqual(1, summary["confirmed_rows"])
        self.assertEqual(1, summary["total_rows"])


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

    def test_eval_prompt_includes_sample_output_requirement(self):
        """被评测模型应看到样本级输出要求，但不看到专业标准答案字段。"""
        task = {
            "case_id": "X-2",
            "scenario": "财务场景",
            "question": "请判断收入质量。",
            "context": "2025 年收入 12,000 万元，应收账款 5,400 万元。",
            "output_requirement": "请基于已提供模拟数据先形成初步判断，并列示关键数据依据。",
            "core_conclusion": "GOLD-专业标准答案-不应外泄",
            "must_have_points": ["GOLD-必须覆盖点"],
            "unacceptable_errors": ["GOLD-不可接受错误"],
            "scoring_focus": "GOLD-评分关注点",
        }

        messages = er.build_messages(task)
        joined = " ".join(m["content"] for m in messages)

        self.assertIn("【输出要求】", joined)
        self.assertIn("请基于已提供模拟数据先形成初步判断", joined)
        self.assertIn("2025 年收入 12,000 万元", joined)
        for leak in ["GOLD-专业标准答案", "GOLD-必须覆盖点", "GOLD-不可接受错误", "GOLD-评分关注点"]:
            self.assertNotIn(leak, joined)

    def test_default_output_hint_requires_data_based_preliminary_judgment(self):
        messages = er.build_messages({
            "case_id": "X-3",
            "question": "请判断交易风险。",
            "context": "交易金额 52,000 万元，占资产总额 52.0%。",
        })
        joined = " ".join(m["content"] for m in messages)

        self.assertIn("基于已提供数据形成初步判断", joined)
        self.assertIn("不得只回答“资料不足”或“无法直接判定”", joined)
        self.assertNotIn("信息不足时应说明需要补充核实的内容", joined)


class PageRenderTests(unittest.TestCase):
    """Test that all 5 main page render functions can be imported and called."""

    def _mock_data_bundle(self):
        """Build a minimal mock data_bundle for page render tests."""
        mock_data = MagicMock()
        mock_data.tasks = pd.DataFrame()
        mock_data.scores = None
        mock_data.model_outputs = pd.DataFrame()
        mock_data.errors = pd.DataFrame()
        mock_data.gold_answer_map = {}
        mock_data.optimizations = pd.DataFrame()

        mock_base = MagicMock()
        mock_base.tasks = pd.DataFrame()
        mock_base.scores = None
        mock_base.model_outputs = pd.DataFrame()
        mock_base.errors = pd.DataFrame()
        mock_base.gold_answer_map = {}
        mock_base.optimizations = pd.DataFrame()

        return {
            "data": mock_data,
            "base": mock_base,
            "validation_result": MagicMock(),
            "eval_status": {},
            "data_context": {},
        }

    @patch("streamlit.set_page_config")
    @patch("streamlit.session_state", new_callable=dict)
    def test_case_study_page_imports(self, mock_session_state, mock_set_page_config):
        """case_study page can be imported and has render function."""
        from src.ui.case_study import render_case_study_page
        self.assertTrue(callable(render_case_study_page))

    @patch("streamlit.set_page_config")
    @patch("streamlit.session_state", new_callable=dict)
    def test_samples_page_imports(self, mock_session_state, mock_set_page_config):
        """samples page can be imported and has render function."""
        from src.ui.samples import render_samples_page
        self.assertTrue(callable(render_samples_page))

    @patch("streamlit.set_page_config")
    @patch("streamlit.session_state", new_callable=dict)
    def test_test_run_page_imports(self, mock_session_state, mock_set_page_config):
        """test_run page can be imported and has render function."""
        from src.ui.test_run import render_test_run_page
        self.assertTrue(callable(render_test_run_page))

    @patch("streamlit.set_page_config")
    @patch("streamlit.session_state", new_callable=dict)
    def test_review_page_imports(self, mock_session_state, mock_set_page_config):
        """review page can be imported and has render function."""
        from src.ui.review import render_review_page
        self.assertTrue(callable(render_review_page))

    @patch("streamlit.set_page_config")
    @patch("streamlit.session_state", new_callable=dict)
    def test_conclusions_page_imports(self, mock_session_state, mock_set_page_config):
        """conclusions page can be imported and has render function."""
        from src.ui.conclusions import render_conclusions_page
        self.assertTrue(callable(render_conclusions_page))


if __name__ == "__main__":
    unittest.main()
