"""PR-11 tests: the overview home is a "redline evaluation cockpit".

Covers the new cockpit pieces (verdict banner, usage-boundary cards, horizontal
flow) and asserts the page renders without crashing across three data states:
empty dataset, no real run, and a real run with scores. All boundary/risk numbers
must come from the data builders, never hardcoded.
"""

import dataclasses
import unittest
import warnings

import pandas as pd

from app.services.live_results import empty_results_evaluation_data
from src.data_service import load_all_data
from src.model_boundary import (
    TIER_ORDER,
    build_data_actions,
    build_frequent_risks,
    summarize_usage_tiers,
)
from src.ui import components, overview
from src.ui.page_config import get_page_config
from src.validators import validate_evaluation_data


def _empty_dataset(base):
    """A fully empty EvaluationData (no tasks) for the empty-state path."""
    empties = {}
    for field in dataclasses.fields(base):
        value = getattr(base, field.name)
        if isinstance(value, pd.DataFrame):
            empties[field.name] = value.iloc[0:0]
        elif isinstance(value, dict):
            empties[field.name] = {}
        elif isinstance(value, list):
            empties[field.name] = []
    return dataclasses.replace(base, **empties)


class RedlineHomeConfigTests(unittest.TestCase):
    def test_conclusions_title_and_subtitle(self):
        config = get_page_config("conclusions")
        self.assertIn("评测结论", config.title)
        # 评测结论页副标题包含结论汇总相关关键词
        for word in ["正式", "结论", "复核"]:
            self.assertIn(word, config.subtitle)
        self.assertNotIn("seed", config.subtitle.lower())

    def test_loop_steps_keep_closed_loop_with_revalidation(self):
        steps = overview.get_evaluation_loop_steps()
        self.assertEqual(
            ["专业任务", "Gold Answer", "模型回答", "Rubric 评分", "错误归因", "数据补强", "复测验证"],
            steps,
        )


class RedlineComponentTests(unittest.TestCase):
    def test_new_cockpit_components_and_styles_exist(self):
        self.assertTrue(hasattr(components, "render_redline_verdict"))
        self.assertTrue(hasattr(components, "render_flow_strip"))
        for token in [".redline-verdict", ".boundary-card", ".flow-strip", ".flow-arrow"]:
            self.assertIn(token, components.STYLE_CSS)


class UsageBoundaryDerivationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_usage_tiers_are_three_and_data_driven(self):
        summaries = summarize_usage_tiers(self.data)
        self.assertEqual([s["key"] for s in summaries], TIER_ORDER)
        # 各档任务数加总应等于任务总数（每道任务恰好归入一档）。
        total = sum(s["count"] for s in summaries)
        self.assertEqual(len(self.data.tasks), total)

    def test_risk_and_action_builders_tolerate_empty_errors(self):
        empty = self.data.errors.iloc[0:0]
        empty_data = dataclasses.replace(self.data, errors=empty)
        self.assertEqual([], build_frequent_risks(empty_data))
        self.assertEqual([], build_data_actions(empty_data))


class RedlineHomeRenderTests(unittest.TestCase):
    """The cockpit must render in bare mode across all three data states."""

    def setUp(self):
        warnings.simplefilter("ignore")
        self.base = load_all_data()
        self.validation = validate_evaluation_data(self.base)

    def _bundle(self, data, live, run_id=None):
        return {
            "data": data,
            "base": self.base,
            "validation_result": self.validation,
            "eval_status": {"live": live, "run_id": run_id},
        }

    def test_renders_with_real_run_and_scores(self):
        # base 自带种子评分，等价于"有真实运行"状态。
        overview.render_overview_page(self._bundle(self.base, True, "RUN-1"))

    def test_renders_without_run(self):
        empty_results = empty_results_evaluation_data(self.base)
        overview.render_overview_page(self._bundle(empty_results, False))

    def test_renders_with_empty_dataset(self):
        overview.render_overview_page(self._bundle(_empty_dataset(self.base), False))


if __name__ == "__main__":
    unittest.main()
