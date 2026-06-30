"""PR-A tests: 项目介绍 / 方法论页面。

校验新页面已注册为导航第一项、可正常渲染，且样本统计均从 tasks / gold / 评分维度
动态计算（不写死数量），并带有明确的“可用边界评测、非排行榜”定位。
"""

import unittest
from pathlib import Path

from src.data_service import load_all_data
from src.metrics import SCORE_DIMENSIONS
from src.ui.navigation import PAGES, _NAV_GROUPS
from src.ui.page_config import DEFAULT_PAGE_KEY, PAGE_CONFIG_BY_KEY, PAGE_CONTEXTS
from src.ui.project_methodology import (
    build_dataset_summary_items,
    get_rubric_framework_items,
    get_redline_triggers,
    get_sample_structure_items,
    scored_case_count,
)

BANNED_PHRASES = ["AI赋能", "智能洞察", "一键优化", "专家级", "秒级"]


class RegistrationTests(unittest.TestCase):
    def test_page_is_registered_and_first(self):
        self.assertIn("project_methodology", PAGES)
        self.assertEqual("project_methodology", list(PAGES.keys())[0])
        self.assertIn("project_methodology", PAGE_CONFIG_BY_KEY)

    def test_methodology_is_default_landing_page(self):
        self.assertEqual("project_methodology", DEFAULT_PAGE_KEY)

    def test_first_nav_group_contains_methodology(self):
        first_group_keys = _NAV_GROUPS[0][1]
        self.assertIn("project_methodology", first_group_keys)

    def test_page_context_is_complete_and_clean(self):
        context = PAGE_CONTEXTS["项目介绍"]
        for key in ("question", "boundary", "highlights"):
            self.assertTrue(context[key].strip(), key)
        combined = " ".join(context.values())
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, combined)

    def test_source_has_no_banned_phrases_and_uses_shared_components(self):
        source = Path("src/ui/project_methodology.py").read_text(encoding="utf-8")
        self.assertIn("src.ui.components", source)
        self.assertIn("render_page_shell", source)
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, source)

    def test_positioning_states_not_a_leaderboard(self):
        source = Path("src/ui/project_methodology.py").read_text(encoding="utf-8")
        self.assertIn("不是", source)
        self.assertIn("排行榜", source)
        self.assertIn("可用边界", source)


class DynamicStatsTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_dataset_summary_counts_match_live_data(self):
        items = dict(build_dataset_summary_items(self.data))
        task_count = len(self.data.tasks)
        domain_count = self.data.tasks["domain"].dropna().nunique()
        gold_count = len(self.data.gold_answer_map)

        self.assertIn(str(task_count), items["任务样本"])
        self.assertIn(str(domain_count), items["覆盖领域"])
        self.assertIn(f"{gold_count}/{task_count}", items["Gold Answer"])
        # 维度数取自 Rubric 配置，而非写死。
        self.assertIn(str(len(SCORE_DIMENSIONS)), items["评价维度"])

    def test_dataset_summary_tracks_data_changes(self):
        # 用一个小型替身验证数字随数据变化，避免改动共享缓存对象。
        import types

        import pandas as pd

        stub = types.SimpleNamespace(
            tasks=pd.DataFrame({"domain": ["a", "b"], "task_type": ["x", "x"]}),
            gold_answer_map={"C1": {}},
            scores=pd.DataFrame(),
        )
        items = dict(build_dataset_summary_items(stub))
        self.assertIn("2", items["任务样本"])
        self.assertIn("2", items["覆盖领域"])
        self.assertIn("1/2", items["Gold Answer"])

    def test_rubric_items_cover_all_dimensions_plus_boundary(self):
        items = get_rubric_framework_items()
        labels = [label for label, _ in items]
        for _, label in SCORE_DIMENSIONS:
            self.assertIn(label, labels)
        self.assertIn("边界意识", labels)
        for _, note in items:
            self.assertTrue(note.strip())

    def test_structure_and_redline_items_present(self):
        structure_labels = [label for label, _ in get_sample_structure_items()]
        for expected in ("Gold Answer", "必须覆盖点", "不可接受错误"):
            self.assertIn(expected, structure_labels)
        self.assertEqual(3, len(get_redline_triggers()))

    def test_scored_case_count_handles_empty_and_counts_scores(self):
        import pandas as pd

        self.assertEqual(0, scored_case_count(None))
        self.assertEqual(0, scored_case_count(pd.DataFrame()))
        # seed 数据带评分，计数应等于 total_score 非空行数。
        expected = int(self.data.scores["total_score"].notna().sum())
        self.assertEqual(expected, scored_case_count(self.data.scores))


class RenderTests(unittest.TestCase):
    def test_page_renders_without_exception(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        at.session_state["current_page"] = "project_methodology"
        at.run()
        self.assertEqual(list(at.exception), [])


if __name__ == "__main__":
    unittest.main()
