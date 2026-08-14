import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESPONSIVE_PATH = PROJECT_ROOT / "src" / "ui" / "responsive.py"
COMPONENTS_PATH = PROJECT_ROOT / "src" / "ui" / "components.py"
TEST_RUN_PATH = PROJECT_ROOT / "src" / "ui" / "test_run.py"
EVALUATION_CONFIG_PATH = PROJECT_ROOT / "src" / "ui" / "evaluation_config.py"
SAMPLES_PATH = PROJECT_ROOT / "src" / "ui" / "samples.py"


def _css_rules(css: str) -> list[tuple[set[str], str]]:
    return [
        (
            {selector.strip() for selector in selector_list.split(",")},
            declarations,
        )
        for selector_list, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        if not selector_list.lstrip().startswith("@")
    ]


def _declarations_for_selector(css: str, selector: str) -> list[str]:
    return [
        declarations
        for selectors, declarations in _css_rules(css)
        if selector in selectors
    ]


class MobileResponsiveUIContracts(unittest.TestCase):
    def _responsive_css(self) -> str:
        self.assertTrue(
            RESPONSIVE_PATH.exists(),
            "src/ui/responsive.py must define the shared mobile responsive CSS",
        )
        return RESPONSIVE_PATH.read_text(encoding="utf-8")

    def test_responsive_css_defines_breakpoints_safe_area_and_touch_targets(self):
        css = self._responsive_css()

        for contract in [
            "@media (min-width: 761px) and (max-width: 860px)",
            "@media (max-width: 760px)",
            "@media (max-width: 480px)",
            "env(safe-area-inset-bottom)",
            "min-height: 44px",
        ]:
            self.assertIn(contract, css)

    def test_report_primitives_reflow_without_a_second_mobile_data_structure(self):
        from src.ui.report_styles import REPORT_STYLE_CSS

        mobile_css = REPORT_STYLE_CSS.split("@media (max-width: 760px)", 1)[1]
        for selector in [
            ".report-ledger",
            ".report-section-heading",
            ".report-index-row--header",
            ".report-index-row",
            ".evidence-index-item",
        ]:
            self.assertIn(selector, mobile_css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", mobile_css)
        self.assertIn("display: none", mobile_css)
        self.assertIn("overflow-wrap: anywhere", mobile_css)
        self.assertIn("min-width: 0", mobile_css)
        self.assertIn("min-height: 44px", mobile_css)
        self.assertIn("max(5.5rem, env(safe-area-inset-bottom))", mobile_css)
        self.assertIn(
            "max-height: calc(100dvh - 5.5rem - env(safe-area-inset-bottom))",
            mobile_css,
        )
        self.assertIn("overflow-y: auto", mobile_css)

    def test_mobile_report_masthead_keeps_the_first_judgment_in_reach(self):
        from src.ui.report_styles import REPORT_STYLE_CSS

        mobile_css = REPORT_STYLE_CSS.split("@media (max-width: 760px)", 1)[1]
        masthead_rule = mobile_css.split(".report-masthead {", 1)[1].split("}", 1)[0]
        title_rule = mobile_css.split(
            '[data-testid="stMarkdownContainer"] .report-masthead-title {', 1
        )[1].split("}", 1)[0]

        self.assertIn("padding: 0.85rem 0 0.95rem", masthead_rule)
        self.assertIn("margin: 0.4rem 0 1rem", masthead_rule)
        self.assertIn("font-size: 1.8rem !important", title_rule)
        self.assertIn("padding: 0 !important", title_rule)

    def test_consulting_report_regions_adapt_on_mobile(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]

        for selector in [
            ".brief-facts",
            ".executive-takeaway",
            ".st-key-samples_filter_region",
            ".st-key-test_run_stage_configuration",
        ]:
            self.assertIn(selector, mobile_css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", mobile_css)

    def test_top_navigation_is_sticky_and_uses_equal_width_items(self):
        css = self._responsive_css()

        for contract in [
            '[data-testid="stHorizontalBlock"]:has(.top-nav-brand)',
            "position: sticky",
            "grid-template-columns: repeat(3, minmax(0, 1fr))",
        ]:
            self.assertIn(contract, css)

    def test_mobile_navigation_and_section_spacing_use_the_full_viewport(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]
        nav_selector = (
            '.block-container [data-testid="stHorizontalBlock"]:has(.top-nav-brand)'
        )
        nav_rules = _declarations_for_selector(mobile_css, nav_selector)
        self.assertTrue(
            any(re.search(r"width\s*:\s*100vw\s*;", rule) for rule in nav_rules)
        )
        self.assertTrue(
            any(re.search(r"max-width\s*:\s*none\s*;", rule) for rule in nav_rules)
        )
        self.assertTrue(
            any(re.search(r"margin\s*:\s*0\s+-0\.875rem\s*;", rule) for rule in nav_rules)
        )

        section_rules = _declarations_for_selector(mobile_css, ".section-heading-page")
        self.assertTrue(
            any(
                re.search(
                    r"grid-template-columns\s*:\s*2\.5rem\s+minmax\(0,\s*1fr\)\s*;",
                    rule,
                )
                for rule in section_rules
            )
        )

    def test_custom_headings_override_streamlit_native_spacing(self):
        from src.ui.components import STYLE_CSS

        for selector in [
            '[data-testid="stMarkdownContainer"] .page-title-heading',
            '[data-testid="stMarkdownContainer"] .brief-title',
            '[data-testid="stMarkdownContainer"] .section-heading-title',
        ]:
            declarations = _declarations_for_selector(STYLE_CSS, selector)
            self.assertTrue(declarations, selector)
            self.assertTrue(
                any(re.search(r"padding\s*:\s*0\s*;", rule) for rule in declarations),
                selector,
            )

        mobile_css = self._responsive_css().split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]
        expected_mobile_sizes = {
            '[data-testid="stMarkdownContainer"] .page-title-heading': "1.3rem",
            '[data-testid="stMarkdownContainer"] .brief-title': "1.78rem",
        }
        for selector, expected_size in expected_mobile_sizes.items():
            self.assertTrue(
                any(
                    re.search(
                        rf"font-size\s*:\s*{re.escape(expected_size)}\s*;",
                        rule,
                    )
                    for rule in _declarations_for_selector(mobile_css, selector)
                ),
                selector,
            )

    def test_mobile_home_page_uses_compact_section_rhythm(self):
        mobile_css = self._responsive_css().split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]

        self.assertTrue(
            any(
                re.search(r"margin-top\s*:\s*1\.75rem\s*;", rule)
                for rule in _declarations_for_selector(mobile_css, ".home-section")
            )
        )
        self.assertTrue(
            any(
                re.search(r"margin-top\s*:\s*1\.25rem\s*;", rule)
                for rule in _declarations_for_selector(mobile_css, ".home-section-first")
            )
        )

    def test_mobile_columns_dialogs_and_tables_fit_the_viewport(self):
        css = self._responsive_css()

        for contract in [
            ".st-key-samples_title_bar",
            '[data-testid="stDialog"] [role="dialog"]',
            '[data-testid="stDataFrame"]',
            ".markdown-detail-table-scroll",
            "overflow-wrap: anywhere",
        ]:
            self.assertIn(contract, css)

    def test_mobile_sample_selector_uses_card_grid_without_forced_width(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]
        source = EVALUATION_CONFIG_PATH.read_text(encoding="utf-8")

        self.assertNotIn("min-width: 44rem", mobile_css)
        self.assertIn("test_run_sample_table_header", source)
        self.assertIn("test_run_sample_row_", source)
        self.assertIn('.st-key-test_run_sample_table_header', mobile_css)
        self.assertIn('[class*="st-key-test_run_sample_row_"]', mobile_css)
        self.assertIn("grid-template-columns: 2.5rem minmax(0, 1fr) minmax(0, 1fr)", mobile_css)

    def test_mobile_dialogs_reserve_navigation_and_safe_area_with_pinned_actions(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]
        source = EVALUATION_CONFIG_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "max-height: calc(100dvh - 5.5rem - env(safe-area-inset-bottom))",
            mobile_css,
        )
        for key in [
            "test_run_sample_dialog_actions",
            "test_run_model_dialog_actions",
            "test_run_prompt_dialog_actions",
        ]:
            self.assertIn(key, source)
            self.assertIn(
                f'[data-testid="stDialog"] .st-key-{key}',
                mobile_css,
            )
        action_rules = _declarations_for_selector(
            mobile_css,
            '[data-testid="stDialog"] .st-key-test_run_sample_dialog_actions',
        )
        self.assertTrue(
            any(re.search(r"position\s*:\s*fixed\s*;", rule) for rule in action_rules),
            "the dialog scroll container cannot reveal a naturally offscreen sticky footer",
        )
        self.assertTrue(
            any(re.search(r"bottom\s*:\s*calc\(", rule) for rule in action_rules)
        )
        self.assertIn(
            '[data-testid="stDialog"] .st-key-test_run_sample_dialog_actions [data-testid="stHorizontalBlock"]',
            mobile_css,
            "keep descendant combinators on one line so Streamlit CSS minification preserves them",
        )
        self.assertTrue(
            any(re.search(r"box-sizing\s*:\s*border-box\s*;", rule) for rule in action_rules)
        )
        self.assertTrue(
            any(re.search(r"width\s*:\s*auto\s*!important\s*;", rule) for rule in action_rules),
            "Streamlit gives vertical blocks width:100%; fixed left/right require an auto width",
        )
        dialog_rules = _declarations_for_selector(
            mobile_css,
            '[data-testid="stDialog"] [role="dialog"]',
        )
        self.assertTrue(
            any(re.search(r"padding-bottom\s*:\s*calc\(", rule) for rule in dialog_rules)
        )
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", mobile_css)

    def test_mobile_model_index_reflows_the_same_semantic_rows(self):
        from src.ui.report_styles import REPORT_STYLE_CSS

        source = (PROJECT_ROOT / "src" / "ui" / "conclusions.py").read_text(encoding="utf-8")
        mobile_css = REPORT_STYLE_CSS.split("@media (max-width: 760px)", 1)[1]

        self.assertIn("report_index_row_html", source)
        self.assertNotIn("_render_mobile_model_cards", source)
        self.assertNotIn("mobile-select-card", source)
        self.assertIn(".conclusion-model-index .report-index-row", mobile_css)
        self.assertIn(".report-index-cell::before", mobile_css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", mobile_css)
        self.assertNotIn("min-width: 44rem", mobile_css)

    def test_mobile_model_evidence_actions_are_full_width_touch_targets(self):
        from src.ui.report_styles import REPORT_STYLE_CSS

        mobile_css = REPORT_STYLE_CSS.split("@media (max-width: 760px)", 1)[1]
        selector = (
            '.st-key-conclusion_model_index [class*="st-key-conclusion_model_action_"] '
            ".stButton > button"
        )
        self.assertIn(selector + " {", mobile_css)
        rule = mobile_css.split(selector + " {", 1)[1].split("}", 1)[0]

        self.assertIn("min-height: 44px", rule)
        self.assertIn("width: 100%", rule)
        self.assertIn("white-space: normal", rule)

    def test_mobile_popover_triggers_are_real_44px_touch_targets(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]

        for container in [
            ".st-key-samples_title_bar",
            ".st-key-conclusion_maintenance_entry",
            ".st-key-samples_detail_region",
        ]:
            self.assertIn(container, mobile_css)
        self.assertIn('[data-testid="stPopover"] button', mobile_css)
        self.assertRegex(mobile_css, r"min-height\s*:\s*44px\s*!important")

    def test_mobile_native_anchors_clear_sticky_navigation(self):
        mobile_css = self._responsive_css().split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]

        self.assertIn('[id^="fde-"]', mobile_css)
        self.assertIn("scroll-margin-top: 5.75rem", mobile_css)

    def test_blocking_dialog_preparation_has_explicit_loading_feedback(self):
        source = EVALUATION_CONFIG_PATH.read_text(encoding="utf-8")

        self.assertIn('st.spinner("正在获取模型列表…")', source)
        self.assertIn('st.spinner("正在准备提示词…")', source)

    def test_mobile_column_stacking_is_scoped_to_named_layouts(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]

        global_rules = _declarations_for_selector(
            mobile_css,
            '.block-container [data-testid="stHorizontalBlock"]',
        )
        self.assertFalse(
            any(re.search(r"flex-direction\s*:\s*column\b", rule) for rule in global_rules),
            "mobile stacking must be limited to named page regions",
        )
        scoped_rules = _declarations_for_selector(
            mobile_css,
            '.st-key-samples_title_bar [data-testid="stHorizontalBlock"]',
        )
        self.assertTrue(
            any(re.search(r"grid-template-columns\s*:\s*1fr\s*;", rule) for rule in scoped_rules),
            "the sample title and maintenance entry stack without squeezing the heading",
        )

    def test_sample_detail_tables_own_mobile_scroll_container(self):
        from src.ui.samples import _rubric_detail_html

        html = _rubric_detail_html(
            [
                {
                    "评分维度": "准确性",
                    "满分": "10",
                    "满分标准": "结论准确且有依据",
                    "扣分规则": "事实错误扣分",
                }
            ]
        )
        self.assertIn('<div class="sample-detail-table-wrap">', html)
        self.assertIn('<table class="sample-detail-table">', html)
        wrapper_open = html.index('<div class="sample-detail-table-wrap">')
        table_open = html.index('<table class="sample-detail-table">')
        table_close = html.index("</table>")
        wrapper_close = html.index("</div>", table_close)
        self.assertLess(wrapper_open, table_open)
        self.assertLess(table_close, wrapper_close)

        mobile_css = self._responsive_css().split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]
        declarations = _declarations_for_selector(
            mobile_css,
            ".sample-detail-table-wrap",
        )
        self.assertTrue(
            any(
                all(
                    re.search(contract, rule)
                    for contract in [
                        r"max-width\s*:\s*100%\s*;",
                        r"overflow-x\s*:\s*auto\s*;",
                    ]
                )
                for rule in declarations
            )
        )
        for rule in _declarations_for_selector(mobile_css, ".sample-detail-table"):
            self.assertNotRegex(rule, r"display\s*:")

    def test_fixed_actions_are_limited_to_dialog_controls(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]
        fixed_rules = [
            (selectors, declarations)
            for selectors, declarations in _css_rules(css)
            if re.search(r"position\s*:\s*fixed\b", declarations)
        ]

        self.assertEqual(1, len(fixed_rules))
        dialog_rule = next(
            item
            for item in fixed_rules
            if any(
                ".st-key-test_run_sample_dialog_actions" in selector
                for selector in item[0]
            )
        )
        for selector in [
            ".st-key-test_run_sample_dialog_actions",
            ".st-key-test_run_model_dialog_actions",
            ".st-key-test_run_prompt_dialog_actions",
        ]:
            matching_selectors = [
                item for item in dialog_rule[0] if selector in item
            ]
            self.assertEqual(1, len(matching_selectors))
            self.assertIn('[data-testid="stDialog"]', matching_selectors[0])

        self.assertEqual(
            [],
            _declarations_for_selector(
                mobile_css,
                ".st-key-test_run_sample_dialog_actions",
            ),
            "dialog action styles must not leak onto Streamlit's transient rerun DOM",
        )
        self.assertNotIn(".st-key-test_run_run", css)
        run_button_wrapper = ".st-key-test_run_primary_action .stButton"
        self.assertTrue(
            any(
                re.search(r"width\s*:\s*100%\s*;", declarations)
                for declarations in _declarations_for_selector(
                    mobile_css,
                    run_button_wrapper,
                )
            )
        )

    def test_answer_viewer_and_detail_toolbar_have_stable_mobile_spacing(self):
        from src.ui.components import STYLE_CSS

        results_source = Path("src/ui/evaluation_results.py").read_text(encoding="utf-8")
        self.assertIn("render_markdown_detail_panel(", results_source)

        normalized_css = re.sub(r"\s+", " ", STYLE_CSS)
        self.assertRegex(
            normalized_css,
            (
                r'\[data-testid="stMarkdownContainer"\]:has\('
                r'\.detail-panel-toolbar-title\)[^{]*\{[^}]*'
                r'margin-bottom\s*:\s*0\s*!important\s*;'
            ),
        )
        self.assertRegex(
            normalized_css,
            (
                r'\[data-testid="stVerticalBlock"\]:has\('
                r'\s*> \[data-testid="stLayoutWrapper"\] '
                r'> \[data-testid="stHorizontalBlock"\] '
                r'\.detail-panel-toolbar-title\s*\)[^{]*\{[^}]*'
                r'gap\s*:\s*0\.25rem\s*;'
            ),
        )

    def test_sample_table_has_stable_keys_without_mobile_minimum_width(self):
        test_run_source = EVALUATION_CONFIG_PATH.read_text(encoding="utf-8")

        self.assertTrue(
            'key="test_run_sample_table"' in test_run_source,
            "evaluation_config.py must give the sample selection table container a stable key",
        )
        css = self._responsive_css()
        self.assertIn(".st-key-test_run_sample_table", css)
        self.assertIn("test_run_sample_table_header", test_run_source)
        self.assertIn("test_run_sample_row_", test_run_source)
        self.assertNotIn("min-width: 44rem", css)

    def test_run_action_is_rendered_outside_streamlit_columns(self):
        import inspect

        from src.ui.evaluation_config import render_evaluation_scope

        source = inspect.getsource(render_evaluation_scope)
        self.assertIn('with st.container(key="test_run_scope_actions"):', source)
        self.assertIn('key="test_run_open_samples"', source)
        self.assertIn('key="test_run_open_models"', source)
        self.assertNotIn("st.columns(", source)

    def test_run_action_group_uses_desktop_grid_and_mobile_stack(self):
        css = self._responsive_css()
        desktop_css, mobile_and_below = css.split("@media (max-width: 760px)", 1)
        mobile_css = mobile_and_below.split("@media (max-width: 480px)", 1)[0]

        self.assertRegex(
            desktop_css,
            (
                r"\.st-key-test_run_scope_actions\s*\{[^}]*"
                r"display\s*:\s*grid\s*;[^}]*"
                r"grid-template-columns\s*:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)\s*;"
            ),
        )
        mobile_rules = _declarations_for_selector(
            mobile_css,
            ".st-key-test_run_scope_actions",
        )
        self.assertTrue(
            any(
                re.search(r"grid-template-columns\s*:\s*1fr\s*;", rule)
                for rule in mobile_rules
            )
        )

    def test_sample_title_actions_use_bottom_alignment_without_blank_rows(self):
        import inspect

        from src.ui.samples import _render_samples_title_bar

        source = inspect.getsource(_render_samples_title_bar)
        self.assertIn('with st.container(key="samples_title_bar"):', source)
        self.assertIn('vertical_alignment="bottom"', source)
        self.assertNotIn('st.write("")', source)

    def test_sample_title_actions_keep_mobile_touch_height(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]
        rules = _declarations_for_selector(
            mobile_css,
            ".st-key-samples_title_bar .stButton > button",
        )

        self.assertTrue(
            any(re.search(r"min-height\s*:\s*44px\s*;", rule) for rule in rules)
        )

    def test_mobile_notice_and_table_tools_keep_touch_height(self):
        css = self._responsive_css()
        mobile_css = css.split(
            "@media (max-width: 760px)",
            1,
        )[1].split("@media (max-width: 480px)", 1)[0]

        for selector in [
            ".st-key-conclusion_data_notice .stButton > button",
            'button[kind="elementToolbar"]',
        ]:
            rules = _declarations_for_selector(mobile_css, selector)
            self.assertTrue(
                any(re.search(r"min-height\s*:\s*44px\s*;", rule) for rule in rules),
                selector,
            )

    def test_components_load_responsive_css_and_wrap_markdown_tables(self):
        import src.ui.components as components
        from src.ui.responsive import MOBILE_RESPONSIVE_CSS

        components_source = COMPONENTS_PATH.read_text(encoding="utf-8")

        self.assertIn(MOBILE_RESPONSIVE_CSS, components.STYLE_CSS)
        self.assertIsNotNone(
            re.search(
                r"from\s+src\.ui\.responsive\s+import\s+MOBILE_RESPONSIVE_CSS",
                components_source,
            ),
            "src/ui/components.py must import MOBILE_RESPONSIVE_CSS",
        )
        self.assertTrue(
            'class="markdown-detail-table-scroll"' in components_source,
            "markdown detail tables must have a horizontal scroll wrapper",
        )


if __name__ == "__main__":
    unittest.main()
