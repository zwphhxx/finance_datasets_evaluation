import unittest
from pathlib import Path


class UIUXAuditFixesTests(unittest.TestCase):
    def test_overview_has_evaluation_loop_rail_steps(self):
        from src.ui.overview import get_evaluation_loop_steps
        import src.ui.components as components

        expected = [
            "专业任务",
            "Gold Answer",
            "模型回答",
            "Rubric 评分",
            "错误归因",
            "数据补强",
            "复测验证",
        ]
        self.assertEqual(expected, get_evaluation_loop_steps())
        self.assertTrue(hasattr(components, "render_loop_rail"))
        self.assertIn(".loop-rail", components.STYLE_CSS)
        self.assertIn(".loop-step", components.STYLE_CSS)

        # 概览页用横向流程（flow-strip）呈现评测闭环；分步向导（loop-rail）仍在「发起评测」页。
        overview_source = Path("src/ui/overview.py").read_text(encoding="utf-8")
        self.assertNotIn("render_loop_rail", overview_source)
        self.assertIn("render_flow_strip", overview_source)
        eval_run_source = Path("src/ui/eval_run_page.py").read_text(encoding="utf-8")
        self.assertIn("loop-rail", eval_run_source)

    def test_pages_use_page_shell_and_context_grid(self):
        import src.ui.components as components

        self.assertTrue(hasattr(components, "render_page_shell"))
        self.assertTrue(hasattr(components, "render_context_grid"))
        self.assertIn(".context-grid", components.STYLE_CSS)
        self.assertIn(".context-item", components.STYLE_CSS)

        for file_path in [
            "src/ui/overview.py",
            "src/ui/tasks.py",
            "src/ui/eval_run_page.py",
            "src/ui/case_detail.py",
            "src/ui/model_diagnosis.py",
            "src/ui/error_analysis.py",
            "src/ui/optimization_compare.py",
        ]:
            source = Path(file_path).read_text(encoding="utf-8")
            self.assertIn("render_page_shell", source, file_path)

    def test_sidebar_navigation_has_active_state_and_groups(self):
        from src.ui.navigation import PAGES, _NAV_GROUPS
        import src.ui.components as components

        self.assertIn("overview", PAGES)
        self.assertIn("eval_run", PAGES)
        self.assertIn("dataset_admin", PAGES)

        group_keys = [key for _, keys in _NAV_GROUPS for key in keys]
        self.assertEqual(sorted(group_keys), sorted(PAGES.keys()))

        self.assertIn(".nav-brand", components.STYLE_CSS)
        navigation_source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
        self.assertIn("current_page", navigation_source)
        self.assertIn("_NAV_GROUPS", navigation_source)

    def test_case_detail_uses_review_workbench_components(self):
        import src.ui.components as components

        self.assertTrue(hasattr(components, "render_answer_boundary_panel"))
        self.assertTrue(hasattr(components, "render_preference_comparison"))
        self.assertIn(".answer-boundary-panel", components.STYLE_CSS)
        self.assertIn(".comparison-grid", components.STYLE_CSS)

        source = Path("src/ui/case_detail.py").read_text(encoding="utf-8")
        self.assertIn("render_answer_boundary_panel", source)
        self.assertIn("render_preference_comparison", source)
        self.assertNotIn("Preferred", source)
        self.assertNotIn("Rejected", source)

    def test_error_analysis_prioritizes_error_to_data_action_path(self):
        from src.data_service import load_all_data
        from src.metrics import get_error_attribution_actions
        from src.ui.error_analysis import build_error_action_path

        data = load_all_data()
        actions = get_error_attribution_actions(data.errors, data.optimizations)
        path_df = build_error_action_path(actions)

        self.assertFalse(path_df.empty)
        self.assertEqual(
            ["错误表现", "可能原因", "数据补强动作", "验证指标"],
            list(path_df.columns),
        )

        source = Path("src/ui/error_analysis.py").read_text(encoding="utf-8")
        self.assertIn("_show_error_action_path", source)
        self.assertIn("错误表现 → 可能原因 → 数据补强动作", source)
        self.assertIn("当前样本观察", source)


if __name__ == "__main__":
    unittest.main()
