import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESPONSIVE_PATH = PROJECT_ROOT / "src" / "ui" / "responsive.py"
COMPONENTS_PATH = PROJECT_ROOT / "src" / "ui" / "components.py"
TEST_RUN_PATH = PROJECT_ROOT / "src" / "ui" / "test_run.py"
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

    def test_top_navigation_is_sticky_and_horizontally_scrollable(self):
        css = self._responsive_css()

        for contract in [
            '[data-testid="stHorizontalBlock"]:has(.top-nav-brand)',
            "position: sticky",
            "overflow-x: auto",
            "grid-template-columns: repeat(4, max-content)",
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
            any(re.search(r"grid-template-columns\s*:\s*1fr 1fr", rule) for rule in scoped_rules),
            "the sample title actions stay side-by-side and compact on mobile",
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

    def test_run_action_is_the_only_fixed_element_and_yields_to_overlays(self):
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
        fixed_selectors, fixed_declarations = fixed_rules[0]
        self.assertIn(".st-key-test_run_run", fixed_selectors)
        self.assertRegex(fixed_declarations, r"position\s*:\s*fixed\b")

        dialog_selector = (
            'body:has([data-testid="stDialog"]) .st-key-test_run_run'
        )
        self.assertTrue(
            any(
                re.search(r"visibility\s*:\s*hidden\b", declarations)
                for declarations in _declarations_for_selector(
                    mobile_css,
                    dialog_selector,
                )
            )
        )
        old_dialog_selector = (
            '.stApp:has([data-testid="stDialog"]) .st-key-test_run_run'
        )
        self.assertEqual(
            [],
            _declarations_for_selector(css, old_dialog_selector),
        )

        for focus_selector in [
            ".stApp:has(input:focus) .st-key-test_run_run",
            ".stApp:has(textarea:focus) .st-key-test_run_run",
        ]:
            self.assertTrue(
                any(
                    re.search(r"position\s*:\s*static\b", declarations)
                    for declarations in _declarations_for_selector(
                        mobile_css,
                        focus_selector,
                    )
                ),
                focus_selector,
            )

        disabled_selector = ".st-key-test_run_run:has(button:disabled)"
        self.assertTrue(
            any(
                all(
                    re.search(contract, rule)
                    for contract in [
                        r"position\s*:\s*static\b",
                        r"width\s*:\s*100%\s*;",
                    ]
                )
                for rule in _declarations_for_selector(
                    mobile_css,
                    disabled_selector,
                )
            )
        )

        answer_viewer_selector = (
            ".stApp:has(.st-key-test_run_answer_viewer) .st-key-test_run_run"
        )
        self.assertTrue(
            any(
                re.search(r"position\s*:\s*static\b", declarations)
                for declarations in _declarations_for_selector(
                    mobile_css,
                    answer_viewer_selector,
                )
            )
        )

        run_button_wrapper = ".st-key-test_run_run .stButton"
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

        test_run_source = TEST_RUN_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'with st.container(key="test_run_answer_viewer"):',
            test_run_source,
        )

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

    def test_sample_table_has_a_stable_key_and_mobile_minimum_width(self):
        test_run_source = TEST_RUN_PATH.read_text(encoding="utf-8")

        self.assertTrue(
            'key="test_run_sample_table"' in test_run_source,
            "src/ui/test_run.py must give the sample selection table container a stable key",
        )
        css = self._responsive_css()
        self.assertIn(".st-key-test_run_sample_table", css)
        self.assertIn("min-width: 44rem", css)

    def test_run_action_is_rendered_outside_streamlit_columns(self):
        import inspect

        from src.ui.test_run import _render_configuration_panel

        source = inspect.getsource(_render_configuration_panel)
        self.assertIn('with st.container(key="test_run_actions"):', source)
        self.assertIn('with st.container(key="test_run_action_samples"):', source)
        self.assertIn('with st.container(key="test_run_action_models"):', source)
        self.assertIn('with st.container(key="test_run_action_primary"):', source)
        self.assertNotIn("st.columns(", source)

    def test_run_action_group_uses_desktop_grid_and_mobile_stack(self):
        css = self._responsive_css()
        desktop_css, mobile_and_below = css.split("@media (max-width: 760px)", 1)
        mobile_css = mobile_and_below.split("@media (max-width: 480px)", 1)[0]

        self.assertRegex(
            desktop_css,
            (
                r"\.st-key-test_run_actions\s*\{[^}]*"
                r"display\s*:\s*grid\s*;[^}]*"
                r"grid-template-columns\s*:\s*1fr\s+1fr\s+1\.2fr\s*;"
            ),
        )
        mobile_rules = _declarations_for_selector(
            mobile_css,
            ".st-key-test_run_actions",
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
