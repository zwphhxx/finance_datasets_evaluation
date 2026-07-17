import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESPONSIVE_PATH = PROJECT_ROOT / "src" / "ui" / "responsive.py"
COMPONENTS_PATH = PROJECT_ROOT / "src" / "ui" / "components.py"
TEST_RUN_PATH = PROJECT_ROOT / "src" / "ui" / "test_run.py"


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

        self.assertIn(".st-key-test_run_run", css)
        self.assertEqual(1, len(re.findall(r"position\s*:\s*fixed\b", css)))
        self.assertRegex(
            css,
            re.compile(
                r'\.stApp:has\(\[data-testid="stDialog"\]\)'
                r"\s+\.st-key-test_run_run\s*\{[^}]*display\s*:\s*none",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            css,
            re.compile(
                r"\.stApp:has\(input:focus\)"
                r"\s+\.st-key-test_run_run\s*\{[^}]*position\s*:\s*static",
                re.DOTALL,
            ),
        )

    def test_sample_table_has_a_stable_key_and_mobile_minimum_width(self):
        test_run_source = TEST_RUN_PATH.read_text(encoding="utf-8")

        self.assertTrue(
            'key="test_run_sample_table"' in test_run_source,
            "src/ui/test_run.py must give the sample dataframe a stable key",
        )
        css = self._responsive_css()
        self.assertIn(".st-key-test_run_sample_table", css)
        self.assertIn("min-width: 44rem", css)

    def test_components_load_responsive_css_and_wrap_markdown_tables(self):
        components_source = COMPONENTS_PATH.read_text(encoding="utf-8")

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
