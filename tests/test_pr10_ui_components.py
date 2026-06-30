import inspect
import unittest
from pathlib import Path

from src.ui.navigation import PAGES
from src.ui.page_config import PAGE_CONFIGS


EXPECTED_PAGE_ORDER = [
    "project_methodology",
    "overview",
    "tasks",
    "eval_run",
    "case_detail",
    "model_diagnosis",
    "model_boundary",
    "evaluation_conclusions",
    "dataset_quality",
    "dataset_admin",
]

BANNED_PHRASES = ["AI赋能", "智能洞察", "一键优化", "专家级", "秒级"]


class UIComponentsTests(unittest.TestCase):
    def test_components_module_exposes_reusable_api_and_css_tokens(self):
        import src.ui.components as components

        expected_functions = [
            "render_page_header",
            "render_metric_card",
            "render_info_panel",
            "render_warning_panel",
            "render_empty_state",
            "render_score_badge",
            "render_status_badge",
            "render_section_title",
            "render_model_answer_card",
        ]
        for name in expected_functions:
            self.assertTrue(hasattr(components, name), name)
            self.assertTrue(callable(getattr(components, name)), name)

        self.assertIn(".metric-card", components.STYLE_CSS)
        self.assertIn(".score-badge", components.STYLE_CSS)
        self.assertIn(".status-badge", components.STYLE_CSS)
        self.assertIn(".empty-state", components.STYLE_CSS)
        self.assertIn("--fde-blue", components.STYLE_CSS)

    def test_navigation_uses_button_items_in_pr09_order(self):
        self.assertEqual(EXPECTED_PAGE_ORDER, [config.page_key for config in PAGE_CONFIGS])
        self.assertEqual(EXPECTED_PAGE_ORDER, list(PAGES.keys()))
        for config in PAGE_CONFIGS:
            self.assertTrue(config.title.strip())
            self.assertTrue(config.nav_summary.strip())
            self.assertTrue(callable(PAGES[config.page_key]))

    def test_app_routes_through_navigation_without_radio(self):
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("render_sidebar_navigation", app_source)
        self.assertNotIn("st.sidebar.radio", app_source)
        self.assertLessEqual(app_source.count("st.sidebar"), 1)

    def test_pages_import_shared_components(self):
        page_files = [
            "src/ui/overview.py",
            "src/ui/tasks.py",
            "src/ui/eval_run_page.py",
            "src/ui/case_detail.py",
            "src/ui/model_diagnosis.py",
            "src/ui/error_analysis.py",
            "src/ui/optimization_compare.py",
        ]
        for file_path in page_files:
            source = Path(file_path).read_text(encoding="utf-8")
            self.assertIn("src.ui.components", source, file_path)
            for phrase in BANNED_PHRASES:
                self.assertNotIn(phrase, source, file_path)

    def test_component_signatures_match_pr10_contract(self):
        import src.ui.components as components

        signatures = {
            "render_page_header": ["title", "subtitle", "boundary_note"],
            "render_metric_card": ["label", "value", "help_text"],
            "render_info_panel": ["title", "content"],
            "render_warning_panel": ["content"],
            "render_empty_state": ["message"],
            "render_score_badge": ["score"],
            "render_status_badge": ["text", "level"],
            "render_section_title": ["title", "caption"],
        }
        for function_name, parameter_names in signatures.items():
            actual = inspect.signature(getattr(components, function_name))
            for parameter_name in parameter_names:
                self.assertIn(parameter_name, actual.parameters, function_name)


if __name__ == "__main__":
    unittest.main()
