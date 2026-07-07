import inspect
import unittest
from pathlib import Path

from src.ui.navigation import PAGES
from src.ui.page_config import PAGE_CONFIGS


EXPECTED_PAGE_ORDER = [
    "case_study",
    "samples",
    "test_run",
    "review",
    "conclusions",
]

BANNED_PHRASES = ["AI赋能", "智能洞察", "一键优化", "专家级", "秒级"]


class UIComponentsTests(unittest.TestCase):
    def test_components_module_exposes_current_lightweight_api(self):
        import src.ui.components as components

        expected_functions = [
            "apply_global_styles",
            "render_html",
            "render_page_heading",
            "render_numbered_section",
            "render_document_block",
            "render_field_section",
            "render_long_text_section",
            "render_markdown_block",
            "render_detail_panel",
            "render_kv_grid",
            "render_inline_status",
            "render_empty_state",
            "render_clean_list",
            "render_compact_hero",
            "render_status_pill",
        ]
        for name in expected_functions:
            self.assertTrue(hasattr(components, name), name)
            self.assertTrue(callable(getattr(components, name)), name)

    def test_components_do_not_export_legacy_card_api(self):
        import src.ui.components as components

        removed_functions = [
            "render_page_header",
            "render_page_shell",
            "render_boundary_bar",
            "render_metric_card",
            "render_info_panel",
            "render_context_grid",
            "render_context_summary",
            "render_warning_panel",
            "render_section_title",
            "render_fingerprint_cards",
            "render_redline_verdict",
            "render_flow_strip",
            "render_evidence_panel",
            "render_status_summary",
            "render_model_answer_card",
        ]
        for name in removed_functions:
            self.assertFalse(hasattr(components, name), name)

        for selector in [
            ".metric-card",
            ".score-badge",
            ".status-badge",
            ".fingerprint-card",
            ".boundary-card",
            ".verdict-card",
            ".review-risk-note",
            ".portfolio-hero",
        ]:
            self.assertNotIn(selector, components.STYLE_CSS)

    def test_navigation_uses_button_items_in_current_order(self):
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
            "src/ui/case_study.py",
            "src/ui/samples.py",
            "src/ui/test_run.py",
            "src/ui/review.py",
            "src/ui/conclusions.py",
        ]
        for file_path in page_files:
            source = Path(file_path).read_text(encoding="utf-8")
            self.assertIn("src.ui.components", source, file_path)
            for phrase in BANNED_PHRASES:
                self.assertNotIn(phrase, source, file_path)

    def test_component_signatures_match_current_contract(self):
        import src.ui.components as components

        signatures = {
            "render_page_heading": ["title", "description"],
            "render_numbered_section": ["index", "title", "caption"],
            "render_document_block": ["body_html", "title", "meta"],
            "render_field_section": ["label", "value", "fallback"],
            "render_long_text_section": ["label", "value", "fallback"],
            "render_markdown_block": ["markdown_text"],
            "render_detail_panel": ["body_html", "title", "meta"],
            "render_kv_grid": ["items"],
            "render_inline_status": ["items"],
            "render_empty_state": ["message"],
            "render_clean_list": ["items"],
            "render_compact_hero": ["eyebrow", "title", "question", "stats"],
            "render_status_pill": ["text", "level"],
        }
        for function_name, parameter_names in signatures.items():
            actual = inspect.signature(getattr(components, function_name))
            for parameter_name in parameter_names:
                self.assertIn(parameter_name, actual.parameters, function_name)

    def test_document_reading_components_use_shared_long_text_classes(self):
        import src.ui.components as components

        field_html = components.render_long_text_section("标准结论", "第一段\n\n第二段")
        list_html = components.render_field_section("必须覆盖点", ["覆盖点一", "覆盖点二"])
        markdown_html = components.render_markdown_block("**复核提示**\n\n需人工确认。")

        self.assertIn('class="document-field"', field_html)
        self.assertIn('class="document-field-title"', field_html)
        self.assertIn('class="document-text"', field_html)
        self.assertIn("<p>第一段</p>", field_html)
        self.assertIn("<p>第二段</p>", field_html)
        self.assertIn('class="document-list"', list_html)
        self.assertIn("<li>覆盖点一</li>", list_html)
        self.assertIn('class="markdown-detail-body document-markdown"', markdown_html)

        self.assertIn(".document-block", components.STYLE_CSS)
        self.assertIn("max-width: min(100%, 960px)", components.STYLE_CSS)
        self.assertIn(".document-field + .document-field", components.STYLE_CSS)
        self.assertIn(".document-list-risk", components.STYLE_CSS)
        self.assertIn(".markdown-detail-body", components.STYLE_CSS)
        self.assertIn("max-width: min(100%, 960px)", components.STYLE_CSS)


if __name__ == "__main__":
    unittest.main()
