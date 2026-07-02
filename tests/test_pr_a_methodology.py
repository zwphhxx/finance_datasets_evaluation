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
    build_hero_stats,
    get_dataset_snapshot_items,
    get_how_to_read_steps,
    get_methodology_items,
    get_project_brief_items,
    get_redline_triggers,
    get_rubric_framework_items,
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
        context = PAGE_CONTEXTS["Case Study"]
        for key in ("question", "boundary", "highlights"):
            self.assertTrue(context[key].strip(), key)
        combined = " ".join(context.values())
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, combined)

    def test_source_has_no_banned_phrases_and_uses_shared_components(self):
        source = Path("src/ui/project_methodology.py").read_text(encoding="utf-8")
        self.assertIn("src.ui.components", source)
        # 首屏改为作品集 Hero：方法论页以 render_hero 作为共享页头组件。
        self.assertIn("render_hero", source)
        # Portfolio case-study 结构：编号 section block + 卡片化叙事。
        self.assertIn("render_section_block", source)
        self.assertIn("render_feature_card", source)
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, source)

    def test_page_follows_portfolio_case_study_sections(self):
        source = Path("src/ui/project_methodology.py").read_text(encoding="utf-8")
        for section in ("Project Brief", "Methodology", "Dataset Snapshot", "How to Read"):
            self.assertIn(section, source, section)
        self.assertIn("不是模型排行榜", source)
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

    def test_project_brief_has_four_narrative_cards(self):
        items = get_project_brief_items()
        labels = [label for label, _ in items]
        self.assertEqual(["背景", "问题", "我的方法", "项目输出"], labels)
        for _, note in items:
            self.assertTrue(note.strip())

    def test_methodology_has_five_steps(self):
        items = get_methodology_items()
        labels = [label for label, _ in items]
        self.assertEqual(
            ["样本脱敏抽象", "Gold Answer", "Rubric 多维评分", "红线错误", "人工复核归档"],
            labels,
        )
        for _, note in items:
            self.assertTrue(note.strip())

    def test_dataset_snapshot_is_dynamic(self):
        items = dict(get_dataset_snapshot_items(self.data))
        task_count = len(self.data.tasks)
        domain_count = self.data.tasks["domain"].dropna().nunique()
        gold_count = len(self.data.gold_answer_map)
        output_count = len(self.data.model_outputs)
        scored = int(self.data.scores["total_score"].notna().sum())

        self.assertIn(str(task_count), items["任务样本"])
        self.assertIn(str(domain_count), items["覆盖领域"])
        self.assertIn(f"{gold_count}/{task_count}", items["Gold 覆盖"])
        self.assertIn(str(scored), items["评分记录"])
        self.assertIn(str(output_count), items["模型回答"])

    def test_dataset_snapshot_handles_empty_data(self):
        import types

        import pandas as pd

        stub = types.SimpleNamespace(
            tasks=pd.DataFrame(),
            gold_answer_map={},
            scores=pd.DataFrame(),
            model_outputs=pd.DataFrame(),
        )
        items = dict(get_dataset_snapshot_items(stub))
        self.assertEqual("0 道", items["任务样本"])
        self.assertEqual("0/0", items["Gold 覆盖"])
        self.assertEqual("0 条", items["评分记录"])
        self.assertEqual("0 条", items["模型回答"])

    def test_how_to_read_steps(self):
        steps = get_how_to_read_steps()
        self.assertEqual(
            ["先看已有评测结论", "再看典型样本拆解", "最后可现场发起可复现实验"],
            steps,
        )

    def test_hero_stats_are_dynamic(self):
        stats = {label: value for value, label in build_hero_stats(self.data)}
        task_count = len(self.data.tasks)
        domain_count = self.data.tasks["domain"].dropna().nunique()
        self.assertEqual(str(task_count), stats["尽调任务样本"])
        self.assertEqual(str(domain_count), stats["专业领域"])
        self.assertEqual(str(len(SCORE_DIMENSIONS)), stats["Rubric 评分维度"])

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
