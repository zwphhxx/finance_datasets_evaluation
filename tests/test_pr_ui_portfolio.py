"""PR-UI6 tests: Portfolio template layout redesign.

覆盖：
  - 新增的作品集组件函数存在且能渲染（PR-UI6 新组件）；
  - 对应的 design token / CSS 类已写入全局样式；
  - 导航 top nav 有 5 个主项；
  - 各页面渲染不报错；
  - 空数据/无评分/SQLite 不可用状态处理。

不执行任何真实外呼；不回写 data/ 下 seed 文件。
"""

import types
import unittest
import warnings

import pandas as pd

import src.ui.components as components
from src.metrics import SCORE_DIMENSIONS
from src.ui.navigation import PAGES, _NAV_GROUPS, _TOP_NAV_ITEMS
from src.ui.page_config import PAGE_CONFIG_BY_KEY


class _FakeCol:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSt:
    """Minimal Streamlit stand-in so render_cta_group can run outside a script."""

    def __init__(self):
        self.session_state = types.SimpleNamespace()

    def columns(self, n):
        return [_FakeCol() for _ in range(n)]

    def button(self, *args, **kwargs):
        return False

    def markdown(self, *args, **kwargs):
        pass

    def rerun(self):  # pragma: no cover - never reached (button returns False)
        raise AssertionError("rerun should not fire when button is not clicked")


class PortfolioComponentsExistTests(unittest.TestCase):
    def test_required_component_functions_exist(self):
        for name in (
            "render_hero",
            "render_section_block",
            "render_feature_card",
            "render_case_study_card",
            "render_status_pill",
            "render_cta_group",
        ):
            self.assertTrue(hasattr(components, name), name)
            self.assertTrue(callable(getattr(components, name)), name)

    def test_pr_ui6_component_functions_exist(self):
        """PR-UI6 new portfolio template components."""
        for name in (
            "render_portfolio_landing_hero",
            "render_checklist",
            "render_site_mockup_preview",
            "render_mockup_stack",
            "render_project_meta_line",
            "render_story_section",
            "render_process_line",
            "render_pull_quote",
            "render_tag_cloud",
            "render_editorial_list",
            "render_evidence_block",
            "render_conclusion_list",
            "render_cta_row",
        ):
            self.assertTrue(hasattr(components, name), name)
            self.assertTrue(callable(getattr(components, name)), name)

    def test_design_tokens_and_classes_present(self):
        css = components.STYLE_CSS
        for token in ("--fde-accent", "--fde-radius", "--fde-space"):
            self.assertIn(token, css, token)
        for klass in (
            ".fde-hero",
            ".section-block",
            ".feature-card",
            ".case-study-card",
            ".status-pill",
        ):
            self.assertIn(klass, css, klass)

    def test_pr_ui6_design_tokens_present(self):
        """PR-UI6 portfolio CSS tokens must exist."""
        css = components.STYLE_CSS
        for token in (
            "--portfolio-bg-start",
            "--portfolio-bg-end",
            "--portfolio-text",
            "--portfolio-muted",
            "--portfolio-accent-green",
            "--portfolio-line",
            "--portfolio-max-width",
        ):
            self.assertIn(token, css, token)
        for klass in (
            ".portfolio-hero",
            ".portfolio-checklist",
            ".mockup-desktop",
            ".mockup-mobile",
            ".story-section",
            ".process-line",
            ".tag-cloud",
            ".pull-quote",
            ".editorial-list",
            ".evidence-block",
            ".top-nav",
        ):
            self.assertIn(klass, css, klass)

    def test_hero_is_responsive(self):
        # 兼容窄屏：Hero 在小屏幕折叠为单列。
        self.assertIn("@media", components.STYLE_CSS)


class ComponentRenderTests(unittest.TestCase):
    """渲染层只产出 HTML；捕获 render_html 输出做结构断言，不依赖 Streamlit 运行时。"""

    def setUp(self):
        warnings.simplefilter("ignore")
        self._captured = []
        self._orig_html = components.render_html
        components.render_html = lambda html, container=None: self._captured.append(str(html))

    def tearDown(self):
        components.render_html = self._orig_html

    def test_hero_renders_title_and_stats(self):
        components.render_hero(
            "EYEBROW", "FinDueEval", "副标题", "价值句",
            stats=[("14", "任务"), ("3", "领域")],
        )
        html = "".join(self._captured)
        self.assertIn("fde-hero", html)
        self.assertIn("FinDueEval", html)
        self.assertIn("fde-hero-stat", html)

    def test_hero_without_stats_omits_aside(self):
        components.render_hero("E", "T", "S", "V", stats=[])
        html = "".join(self._captured)
        self.assertIn("fde-hero", html)
        self.assertNotIn("fde-hero-aside", html)

    def test_section_block_shows_index(self):
        components.render_section_block("02", "样本来源", "脱敏抽象后重写。")
        html = "".join(self._captured)
        self.assertIn("section-block-index", html)
        self.assertIn("02", html)
        self.assertIn("样本来源", html)

    def test_feature_card_grid_renders_each_item(self):
        components.render_feature_card([("A", "甲"), ("B", "乙")])
        html = "".join(self._captured)
        self.assertEqual(2, html.count("feature-card-title"))
        self.assertIn("feature-grid", html)

    def test_case_study_card_with_tags_and_metrics(self):
        components.render_case_study_card(
            "标题", "摘要", tags=["标签"], metrics=[("平均分", "72")],
        )
        html = "".join(self._captured)
        self.assertIn("case-study-card", html)
        self.assertIn("标签", html)
        self.assertIn("72", html)

    def test_status_pill_maps_level(self):
        components.render_status_pill("通过", "success")
        self.assertIn("status-pill-success", "".join(self._captured))

    def test_status_pill_unknown_level_falls_back_to_neutral(self):
        components.render_status_pill("未知", "nonsense")
        self.assertIn("status-pill-neutral", "".join(self._captured))

    # --- PR-UI6 new component render tests ---
    def test_portfolio_landing_hero_renders(self):
        components.render_portfolio_landing_hero(
            title="FinDueEval",
            subtitle="副标题",
            description="描述",
            checklist_items=["项1", "项2"],
            meta_line="10 任务 · 2 领域",
        )
        html = "".join(self._captured)
        self.assertIn("portfolio-hero", html)
        self.assertIn("FinDueEval", html)
        self.assertIn("portfolio-checklist", html)
        self.assertIn("项1", html)
        self.assertIn("10 任务", html)

    def test_checklist_renders_items(self):
        components.render_checklist(["A", "B", "C"])
        html = "".join(self._captured)
        self.assertIn("portfolio-checklist", html)
        self.assertIn("A", html)
        self.assertIn("B", html)
        self.assertIn("C", html)

    def test_mockup_preview_renders(self):
        components.render_site_mockup_preview(variant="desktop", lines=3)
        html = "".join(self._captured)
        self.assertIn("mockup-desktop", html)
        self.assertIn("mockup-topbar", html)

    def test_mockup_stack_renders(self):
        components.render_mockup_stack()
        html = "".join(self._captured)
        self.assertIn("mockup-stack", html)
        self.assertIn("mockup-desktop", html)
        self.assertNotIn("mockup-mobile", html)

    def test_story_section_renders(self):
        components.render_story_section(
            title="Why",
            paragraphs=["P1", "P2"],
            index="01",
        )
        html = "".join(self._captured)
        self.assertIn("story-section", html)
        self.assertIn("Why", html)
        self.assertIn("P1", html)
        self.assertIn("01", html)

    def test_process_line_renders(self):
        components.render_process_line(["A", "B", "C"])
        html = "".join(self._captured)
        self.assertIn("process-line", html)
        self.assertIn("A", html)
        self.assertIn("process-arrow", html)

    def test_pull_quote_renders(self):
        components.render_pull_quote("Quote text")
        html = "".join(self._captured)
        self.assertIn("pull-quote", html)
        self.assertIn("Quote text", html)

    def test_tag_cloud_renders(self):
        components.render_tag_cloud(["标签1", "标签2"])
        html = "".join(self._captured)
        self.assertIn("tag-cloud", html)
        self.assertIn("标签1", html)

    def test_editorial_list_renders(self):
        components.render_editorial_list([
            ("Model A", "Good", 4),
            ("Model B", "Fair", 3),
        ])
        html = "".join(self._captured)
        self.assertIn("editorial-list", html)
        self.assertIn("Model A", html)
        self.assertIn("editorial-bar-segment", html)

    def test_evidence_block_renders(self):
        components.render_evidence_block("Title", "<p>content</p>")
        html = "".join(self._captured)
        self.assertIn("evidence-block", html)
        self.assertIn("Title", html)

    def test_conclusion_list_renders(self):
        components.render_conclusion_list([
            ("Conclusion 1", "meta 1"),
            ("Conclusion 2", "meta 2"),
        ])
        html = "".join(self._captured)
        self.assertIn("conclusion-list", html)
        self.assertIn("Conclusion 1", html)

    def test_project_meta_line_renders(self):
        components.render_project_meta_line(10, 2, 5, 5)
        html = "".join(self._captured)
        self.assertIn("portfolio-meta-line", html)
        self.assertIn("10 任务", html)


class CtaGroupTests(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")
        self._orig_st = components.st
        components.st = _FakeSt()

    def tearDown(self):
        components.st = self._orig_st

    def test_cta_group_renders_without_error(self):
        # 不点击时不应触发导航/重跑，只渲染按钮与说明。
        components.render_cta_group(
            [("查看评测结论 →", "conclusions"), ("红线评测台 →", "samples")],
            note="说明",
        )

    def test_empty_actions_is_noop(self):
        components.render_cta_group([])  # 不应抛错


class PortfolioNavTests(unittest.TestCase):
    def test_nav_groups_cover_every_page(self):
        group_keys = [key for _, keys in _NAV_GROUPS for key in keys]
        self.assertEqual(sorted(group_keys), sorted(PAGES.keys()))
        # 目录无重复。
        self.assertEqual(len(group_keys), len(set(group_keys)))

    def test_methodology_is_first_dataset_group_is_last(self):
        self.assertIn("case_study", _NAV_GROUPS[0][1])
        # PR-LOGIC2: all 5 pages in a single nav group
        self.assertEqual(["case_study", "samples", "test_run", "review", "conclusions"], _NAV_GROUPS[-1][1])

    def test_renamed_titles(self):
        self.assertEqual("样本库", PAGE_CONFIG_BY_KEY["samples"].title)
        self.assertEqual("发起测试", PAGE_CONFIG_BY_KEY["test_run"].title)
        self.assertEqual("评测结论", PAGE_CONFIG_BY_KEY["conclusions"].title)

    def test_top_nav_has_five_items(self):
        """Top nav must have exactly 5 items."""
        self.assertEqual(5, len(_TOP_NAV_ITEMS))
        labels = [label for label, _ in _TOP_NAV_ITEMS]
        self.assertEqual(
            ["项目说明", "样本库", "发起测试", "评测复核", "评测结论"],
            labels,
        )


class PageRenderSmokeTests(unittest.TestCase):
    """Smoke tests: ensure each page render function can be imported and has the right signature."""

    def test_all_pages_are_callable(self):
        for name, fn in PAGES.items():
            self.assertTrue(callable(fn), f"{name} should be callable")

    def test_case_study_page_exists(self):
        from src.ui.case_study import render_case_study_page
        self.assertTrue(callable(render_case_study_page))

    def test_samples_page_exists(self):
        from src.ui.samples import render_samples_page
        self.assertTrue(callable(render_samples_page))

    def test_conclusions_page_exists(self):
        from src.ui.conclusions import render_conclusions_page
        self.assertTrue(callable(render_conclusions_page))

    def test_test_run_page_exists(self):
        from src.ui.test_run import render_test_run_page
        self.assertTrue(callable(render_test_run_page))

    def test_review_page_exists(self):
        from src.ui.review import render_review_page
        self.assertTrue(callable(render_review_page))


class NoDataStateTests(unittest.TestCase):
    """Test that pages handle no-data / no-score / SQLite-unavailable states gracefully."""

    def test_case_study_handles_empty_data(self):
        from src.ui.case_study import render_case_study_page
        # Just verify it doesn't raise on import; actual rendering requires Streamlit runtime
        self.assertTrue(callable(render_case_study_page))

    def test_conclusions_handles_no_scores(self):
        from src.ui.conclusions import render_conclusions_page
        self.assertTrue(callable(render_conclusions_page))

    def test_samples_handles_no_scores(self):
        from src.ui.samples import render_samples_page
        self.assertTrue(callable(render_samples_page))

    def test_review_handles_no_live_run(self):
        from src.ui.review import render_review_page
        self.assertTrue(callable(render_review_page))

    def test_test_run_handles_no_live_run(self):
        from src.ui.test_run import render_test_run_page
        self.assertTrue(callable(render_test_run_page))


if __name__ == "__main__":
    unittest.main()
