"""UI shell tests for the current four-page workflow."""

import unittest
import warnings

import src.ui.components as components
from src.ui.navigation import _TOP_NAV_ITEMS, PAGES
from src.ui.page_config import PAGE_CONFIG_BY_KEY


class ComponentRenderTests(unittest.TestCase):
    """Render helpers only emit compact HTML fragments."""

    def setUp(self):
        warnings.simplefilter("ignore")
        self._captured = []
        self._orig_html = components.render_html
        components.render_html = lambda html, container=None: self._captured.append(str(html))

    def tearDown(self):
        components.render_html = self._orig_html

    def test_page_heading_renders_title_and_copy(self):
        components.render_page_heading("样本库", "维护正式评测样本。")
        html = "".join(self._captured)
        self.assertIn("page-title-row", html)
        self.assertIn("样本库", html)
        self.assertIn("维护正式评测样本", html)

    def test_numbered_section_renders_index_and_caption(self):
        components.render_numbered_section("02", "样本列表", "展示当前查询结果。")
        html = "".join(self._captured)
        self.assertIn("section-heading-page", html)
        self.assertIn("section-heading-number", html)
        self.assertIn("02", html)
        self.assertIn("样本列表", html)

    def test_detail_panel_and_status_helpers_render(self):
        components.render_detail_panel("<p>正文</p>", title="CM-001", meta="可测试")
        components.render_inline_status([("模型", "LongCat"), ("状态", "已完成")])
        html = "".join(self._captured)
        self.assertIn("detail-panel", html)
        self.assertIn("inline-status", html)


class WorkflowNavTests(unittest.TestCase):
    def test_nav_items_cover_every_page(self):
        nav_keys = [page_key for _, page_key in _TOP_NAV_ITEMS]
        self.assertEqual(sorted(nav_keys), sorted(PAGES.keys()))
        self.assertEqual(len(nav_keys), len(set(nav_keys)))

    def test_current_pages_are_registered(self):
        self.assertEqual(["case_study", "samples", "test_run", "conclusions"], list(PAGES.keys()))
        self.assertEqual(
            ["case_study", "samples", "test_run", "conclusions"],
            [page_key for _, page_key in _TOP_NAV_ITEMS],
        )
        self.assertEqual("样本库", PAGE_CONFIG_BY_KEY["samples"].title)
        self.assertEqual("发起评测", PAGE_CONFIG_BY_KEY["test_run"].title)
        self.assertEqual("评测结论", PAGE_CONFIG_BY_KEY["conclusions"].title)

    def test_top_nav_has_four_items(self):
        self.assertEqual(4, len(_TOP_NAV_ITEMS))
        labels = [label for label, _ in _TOP_NAV_ITEMS]
        self.assertEqual(["项目说明", "样本库", "发起评测", "评测结论"], labels)


class PageRenderSmokeTests(unittest.TestCase):
    def test_all_pages_are_callable(self):
        for name, fn in PAGES.items():
            self.assertTrue(callable(fn), f"{name} should be callable")

    def test_page_render_functions_exist(self):
        from src.ui.case_study import render_case_study_page
        from src.ui.conclusions import render_conclusions_page
        from src.ui.samples import render_samples_page
        from src.ui.test_run import render_test_run_page

        for fn in [
            render_case_study_page,
            render_samples_page,
            render_test_run_page,
            render_conclusions_page,
        ]:
            self.assertTrue(callable(fn))


if __name__ == "__main__":
    unittest.main()
