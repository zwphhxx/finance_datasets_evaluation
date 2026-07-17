import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESPONSIVE_PATH = PROJECT_ROOT / "src" / "ui" / "responsive.py"
COMPONENTS_PATH = PROJECT_ROOT / "src" / "ui" / "components.py"
TEST_RUN_PATH = PROJECT_ROOT / "src" / "ui" / "test_run.py"


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

    def test_mobile_columns_dialogs_and_tables_fit_the_viewport(self):
        css = self._responsive_css()

        for contract in [
            '.block-container [data-testid="stHorizontalBlock"]',
            '[data-testid="stDialog"] [role="dialog"]',
            '[data-testid="stDataFrame"]',
            ".markdown-detail-table-scroll",
            "overflow-wrap: anywhere",
        ]:
            self.assertIn(contract, css)

    def test_run_action_is_the_only_fixed_element_and_yields_to_overlays(self):
        css = self._responsive_css()
        rules = _css_rules(css)
        fixed_rules = [
            (selectors, declarations)
            for selectors, declarations in rules
            if re.search(r"position\s*:\s*fixed\b", declarations)
        ]

        self.assertEqual(1, len(fixed_rules))
        fixed_selectors, fixed_declarations = fixed_rules[0]
        self.assertIn(".st-key-test_run_run", fixed_selectors)
        self.assertRegex(fixed_declarations, r"position\s*:\s*fixed\b")

        dialog_selector = (
            '.stApp:has([data-testid="stDialog"]) .st-key-test_run_run'
        )
        self.assertTrue(
            any(
                re.search(r"visibility\s*:\s*hidden\b", declarations)
                for declarations in _declarations_for_selector(css, dialog_selector)
            )
        )

        for focus_selector in [
            ".stApp:has(input:focus) .st-key-test_run_run",
            ".stApp:has(textarea:focus) .st-key-test_run_run",
        ]:
            self.assertTrue(
                any(
                    re.search(r"position\s*:\s*static\b", declarations)
                    for declarations in _declarations_for_selector(css, focus_selector)
                ),
                focus_selector,
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
