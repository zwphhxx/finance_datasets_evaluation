"""项目说明页注册、结构和数据边界测试。"""

import unittest
import types
from pathlib import Path

import pandas as pd

from src.data_service import load_all_data
from src.ui.case_study import _build_sample_scope_text, scored_case_count
from src.ui.navigation import PAGES, _NAV_GROUPS
from src.ui.page_config import DEFAULT_PAGE_KEY, PAGE_CONFIG_BY_KEY, PAGE_CONTEXTS


BANNED_PHRASES = ["AI赋能", "智能洞察", "一键优化", "专家级", "秒级"]


class RegistrationTests(unittest.TestCase):
    def test_page_is_registered_and_first(self):
        self.assertIn("case_study", PAGES)
        self.assertEqual("case_study", list(PAGES.keys())[0])
        self.assertIn("case_study", PAGE_CONFIG_BY_KEY)

    def test_methodology_is_default_landing_page(self):
        self.assertEqual("case_study", DEFAULT_PAGE_KEY)

    def test_first_nav_group_contains_methodology(self):
        first_group_keys = _NAV_GROUPS[0][1]
        self.assertIn("case_study", first_group_keys)

    def test_page_context_is_complete_and_clean(self):
        context = PAGE_CONTEXTS["项目说明"]
        for key in ("question", "boundary", "highlights"):
            self.assertTrue(context[key].strip(), key)
        combined = " ".join(context.values())
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, combined)

    def test_source_uses_current_shared_components_only(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertIn("render_brief_intro", source)
        self.assertIn("render_home_section", source)
        self.assertIn("process_steps=PROCESS_STEPS", source)
        for legacy_name in (
            "render_mockup_stack",
            "render_story_section",
            "render_tag_cloud",
            "build_dataset_summary_items",
            "get_methodology_items",
            "get_rubric_framework_items",
        ):
            self.assertNotIn(legacy_name, source)
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, source)

    def test_page_follows_project_explanation_sections(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        for section in ("项目定位", "评测流程", "数据边界"):
            self.assertIn(section, source, section)
        self.assertNotIn('render_numbered_section("04", "进入操作")', source)
        self.assertNotIn("查看样本库", source)
        self.assertIn("当前样本范围", source)
        self.assertIn("使用边界", source)
        self.assertIn("回答质量", source)
        self.assertIn("主要问题", source)
        self.assertNotIn("本项目不判断哪个模型最好", source)
        self.assertIn("被测模型不会看到专业标准答案、必须覆盖点、不可接受错误或评分标准", source)
        self.assertIn("待确认、暂不采用、评分失败或示例评价均不进入正式结论", source)


class DynamicStatsTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_sample_scope_text_uses_domain_labels(self):
        text = _build_sample_scope_text(self.data)
        self.assertIn("样本来自", text)
        self.assertIn("财务场景、法律场景和投行场景", text)
        self.assertIn("不包含真实公司、真实交易或敏感数据", text)

    def test_sample_scope_text_handles_empty_data(self):
        stub = types.SimpleNamespace(tasks=pd.DataFrame())
        self.assertEqual(
            "样本来自财务场景、法律场景和投行场景，不包含真实公司、真实交易或敏感数据。",
            _build_sample_scope_text(stub),
        )

    def test_scored_case_count_handles_empty_and_counts_scores(self):
        self.assertEqual(0, scored_case_count(None))
        self.assertEqual(0, scored_case_count(pd.DataFrame()))
        expected = int(self.data.scores["total_score"].notna().sum())
        self.assertEqual(expected, scored_case_count(self.data.scores))


class RenderTests(unittest.TestCase):
    def test_page_renders_without_exception(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        at.session_state["current_page"] = "case_study"
        at.run()
        self.assertEqual(list(at.exception), [])


if __name__ == "__main__":
    unittest.main()
