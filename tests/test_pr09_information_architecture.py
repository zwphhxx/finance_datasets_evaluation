import unittest

from src.data_service import load_all_data
from src.ui.common import PAGE_CONTEXTS
from src.ui.navigation import PAGES
from src.ui.overview import get_overview_asset_cards


EXPECTED_PAGE_ORDER = [
    "FinDueEval 数据集概览",
    "任务样本",
    "样板题深度评测",
    "模型能力诊断",
    "模型边界报告",
    "错误归因与数据补强",
    "优化验证",
    "数据集质量与扩展框架",
    "数据集管理",
]

BANNED_PHRASES = ["AI赋能", "智能洞察", "一键优化", "专家级"]


class InformationArchitectureTests(unittest.TestCase):
    def test_navigation_follows_evaluation_loop_order(self):
        self.assertEqual(EXPECTED_PAGE_ORDER, list(PAGES.keys()))

    def test_each_page_has_standard_context_block_copy(self):
        self.assertEqual(EXPECTED_PAGE_ORDER, list(PAGE_CONTEXTS.keys()))
        for page_name, context in PAGE_CONTEXTS.items():
            self.assertIn("question", context, page_name)
            self.assertIn("boundary", context, page_name)
            self.assertIn("highlights", context, page_name)
            self.assertTrue(context["question"].strip(), page_name)
            self.assertTrue(context["boundary"].strip(), page_name)
            self.assertTrue(context["highlights"].strip(), page_name)
            combined = " ".join(context.values())
            for phrase in BANNED_PHRASES:
                self.assertNotIn(phrase, combined)

    def test_overview_asset_cards_cover_core_data_assets(self):
        data = load_all_data()
        cards = get_overview_asset_cards(data)
        labels = [card["label"] for card in cards]

        self.assertEqual(
            ["任务样本", "模型回答", "Gold Answer 覆盖", "错误标签", "Preference Pair", "优化动作"],
            labels,
        )
        for card in cards:
            self.assertIn("value", card)
            self.assertIn("note", card)


if __name__ == "__main__":
    unittest.main()
