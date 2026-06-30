"""PR-UI tests: 整体 UI 改为 Portfolio Case Study 风格。

覆盖：
  - 新增的作品集组件函数存在且能渲染（render_hero / render_section_block /
    render_feature_card / render_case_study_card / render_status_pill / render_cta_group）；
  - 对应的 design token / CSS 类已写入全局样式；
  - 首屏 Hero 的动态数字来自数据，不写死；空数据时安全回退；
  - 导航改为作品集目录：分组覆盖全部页面、数据集分区排在最后；
  - 三个页面标题已按目录重命名（样本库 / 可复现实验 / 数据集质量）。

不执行任何真实外呼；不回写 data/ 下 seed 文件。
"""

import types
import unittest
import warnings

import pandas as pd

import src.ui.components as components
from src.metrics import SCORE_DIMENSIONS
from src.ui.navigation import PAGES, _NAV_GROUPS
from src.ui.page_config import PAGE_CONFIG_BY_KEY
from src.ui.project_methodology import build_hero_stats


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
            [("查看评测结论 →", "evaluation_conclusions"), ("红线评测台 →", "overview")],
            note="说明",
        )

    def test_empty_actions_is_noop(self):
        components.render_cta_group([])  # 不应抛错


class HeroStatsDynamicTests(unittest.TestCase):
    def test_stats_track_data(self):
        stub = types.SimpleNamespace(
            tasks=pd.DataFrame({"domain": ["a", "b"]}),
            gold_answer_map={},
            scores=pd.DataFrame(),
        )
        stats = build_hero_stats(stub)
        values = {label: value for value, label in stats}
        self.assertEqual("2", values["尽调任务样本"])
        self.assertEqual("2", values["专业领域"])
        # 维度数取自 Rubric 配置而非写死。
        self.assertEqual(str(len(SCORE_DIMENSIONS)), values["Rubric 评分维度"])

    def test_stats_handle_empty_data(self):
        stub = types.SimpleNamespace(
            tasks=pd.DataFrame(), gold_answer_map={}, scores=pd.DataFrame()
        )
        stats = build_hero_stats(stub)
        self.assertEqual(3, len(stats))
        values = {label: value for value, label in stats}
        self.assertEqual("0", values["尽调任务样本"])
        self.assertEqual("0", values["专业领域"])


class PortfolioNavTests(unittest.TestCase):
    def test_nav_groups_cover_every_page(self):
        group_keys = [key for _, keys in _NAV_GROUPS for key in keys]
        self.assertEqual(sorted(group_keys), sorted(PAGES.keys()))
        # 目录无重复。
        self.assertEqual(len(group_keys), len(set(group_keys)))

    def test_methodology_is_first_dataset_group_is_last(self):
        self.assertIn("project_methodology", _NAV_GROUPS[0][1])
        self.assertEqual(["dataset_quality", "dataset_admin"], _NAV_GROUPS[-1][1])

    def test_renamed_titles(self):
        self.assertEqual("样本库", PAGE_CONFIG_BY_KEY["tasks"].title)
        self.assertEqual("可复现实验", PAGE_CONFIG_BY_KEY["eval_run"].title)
        self.assertEqual("数据集质量", PAGE_CONFIG_BY_KEY["dataset_quality"].title)


if __name__ == "__main__":
    unittest.main()
