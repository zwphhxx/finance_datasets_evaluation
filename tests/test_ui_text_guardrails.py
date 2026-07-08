from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import pandas as pd

from app.services import conclusions as cc
from src.ui import samples
from src.ui.components import PROJECT_DISPLAY_NAME as COMPONENT_PROJECT_NAME
from src.ui.navigation import PAGES, PROJECT_DISPLAY_NAME as NAV_PROJECT_NAME, _TOP_NAV_ITEMS
from src.ui.page_config import PAGE_CONFIGS, PAGE_CONFIG_BY_KEY


PROJECT_NAME = "财务/法律/投行场景大模型对比评测"
MAIN_PAGE_KEYS = ["case_study", "samples", "test_run", "conclusions"]
MAIN_NAV_LABELS = ["项目说明", "样本库", "发起评测", "评测结论"]
VISIBLE_UI_FILES = [
    Path("src/ui/case_study.py"),
    Path("src/ui/samples.py"),
    Path("src/ui/test_run.py"),
    Path("src/ui/conclusions.py"),
    Path("src/ui/navigation.py"),
    Path("src/ui/page_config.py"),
    Path("src/ui/components.py"),
]


class ReadmeCurrentFlowTests(unittest.TestCase):
    def test_readme_documents_current_main_flow_and_boundaries(self):
        text = Path("README.md").read_text(encoding="utf-8")

        self.assertIn(f"# {PROJECT_NAME}", text)
        self.assertIn("## 主流程", text)
        for line in [
            "1. **样本库**",
            "2. **发起评测**",
            "3. **评测结论**",
        ]:
            self.assertIn(line, text)

        required_boundaries = [
            "被测模型不看到专业标准答案",
            "AI 评分完成后直接形成评测结论",
            "结论基于当前样本、模型回答和 AI 评分生成",
            "失败评分和示例评价不进入评测结论",
            "本地 SQLite 数据库属于运行期产物",
            "导出 / 导入",
        ]
        for phrase in required_boundaries:
            self.assertIn(phrase, text)

        retired_page_phrases = [
            "模型" + "边界页",
            "模型" + "诊断页",
            "数据" + "质量页",
            "cockpit",
            "dashboard",
        ]
        for phrase in retired_page_phrases:
            self.assertNotIn(phrase, text)

    def test_readme_keeps_runtime_configuration_and_recovery_concise(self):
        text = Path("README.md").read_text(encoding="utf-8")

        for phrase in [
            "## 模型服务配置",
            "SILICONFLOW_API_KEY",
            "SILICONFLOW_TIMEOUT_SECONDS",
            "FINDUEVAL_EVAL_MAX_TOKENS",
            "FINDUEVAL_EVAL_TEMPERATURE",
            "## 演示与恢复",
            "外部模型服务可能受网络、限流、模型响应时间和输出长度影响",
            "未完成项可继续运行",
            "失败项可单独重试",
        ]:
            self.assertIn(phrase, text)
        for phrase in ["建议分批运行", "超过 50 条回答需要确认后再运行", "## 运行稳定性与失败恢复"]:
            self.assertNotIn(phrase, text)


class NavigationAndPageConfigGuardrailTests(unittest.TestCase):
    def test_navigation_only_exposes_current_four_pages(self):
        self.assertEqual(MAIN_PAGE_KEYS, list(PAGES.keys()))
        self.assertEqual(list(zip(MAIN_NAV_LABELS, MAIN_PAGE_KEYS)), _TOP_NAV_ITEMS)

    def test_page_config_only_contains_current_four_pages(self):
        self.assertEqual(MAIN_PAGE_KEYS, [config.page_key for config in PAGE_CONFIGS])
        self.assertEqual(set(MAIN_PAGE_KEYS), set(PAGE_CONFIG_BY_KEY.keys()))

    def test_visible_project_name_is_current_chinese_name(self):
        self.assertEqual(PROJECT_NAME, COMPONENT_PROJECT_NAME)
        self.assertEqual(PROJECT_NAME, NAV_PROJECT_NAME)


class VisibleTextGuardrailTests(unittest.TestCase):
    def test_visible_ui_and_readme_text_do_not_use_retired_or_promotional_terms(self):
        paths = [Path("README.md"), *VISIBLE_UI_FILES]
        banned_terms = [
            "Fin" + "DueEval",
            "Fin" + "DueEval " + "M" + "VP",
            "尽调评测工作台",
            "工作台",
            "归" + "档",
            "一键",
            "智能",
            "深度",
            "赋能",
            "自动洞察",
            "精准判断",
            "模型能力全景",
            "可直接使用",
            "最优模型",
            "排行榜",
        ]

        for path in paths:
            text = path.read_text(encoding="utf-8")
            for term in banned_terms:
                self.assertNotIn(term, text, f"{path} contains retired visible term: {term}")

    def test_user_facing_docs_and_ui_do_not_show_english_scoring_labels(self):
        paths = [
            Path("README.md"),
            *sorted(Path("docs").glob("*.md")),
            *VISIBLE_UI_FILES,
        ]
        banned_labels = [
            "Gold Answer",
            "Gold 要求",
            "Rub" + "ric",
            "full mark standard",
            "deduction rules",
        ]

        for path in paths:
            text = path.read_text(encoding="utf-8")
            for label in banned_labels:
                self.assertNotIn(label, text, f"{path} contains user-facing English label: {label}")

    def test_primary_flow_text_does_not_expose_manual_review_concepts(self):
        paths = [
            Path("README.md"),
            Path("docs/project_note.md"),
            Path("src/ui/case_study.py"),
            Path("src/ui/test_run.py"),
            Path("src/ui/conclusions.py"),
            Path("src/ui/navigation.py"),
            Path("src/ui/page_config.py"),
        ]
        banned_phrases = [
            "评分" + "确认",
            "人工" + "复" + "核",
            "人工" + "确认",
            "评分" + "草稿",
            "待" + "确认",
            "确认" + "生效",
            "修订后" + "确认",
            "暂不" + "采用",
            "已确认" + "结论",
        ]

        for path in paths:
            text = path.read_text(encoding="utf-8")
            for phrase in banned_phrases:
                self.assertNotIn(phrase, text, f"{path} exposes manual review phrase: {phrase}")


class FormalConclusionStatusGuardrailTests(unittest.TestCase):
    def test_successful_ai_scores_enter_conclusions_without_manual_confirmation(self):
        seed_scores = pd.DataFrame([
            {
                "model_name": "Model_A_baseline",
                "case_id": "SEED-1",
                "total_score": 99,
                "accuracy_score": 30,
                "reasoning_score": 20,
                "coverage_score": 20,
                "evidence_score": 15,
                "expression_score": 14,
                "review_note": "seed 示例不进入正式结论",
            }
        ])
        live_scores = pd.DataFrame([
            {
                "id": 1,
                "run_id": "R1",
                "case_id": "LIVE-OK",
                "eval_model": "vendor/live-ai-final",
                "judge_status": "success",
                "review_status": "ai_final",
                "status": "active",
                "total_score": 88,
                "accuracy_score": 26,
                "reasoning_score": 18,
                "coverage_score": 18,
                "evidence_score": 13,
                "expression_score": 13,
                "review_note": "AI 评分完成",
            },
            {
                "id": 2,
                "run_id": "R1",
                "case_id": "LIVE-FAILED",
                "eval_model": "vendor/live-failed",
                "judge_status": "failed",
                "review_status": "ai_final",
                "status": "active",
                "total_score": None,
                "accuracy_score": None,
                "reasoning_score": None,
                "coverage_score": None,
                "evidence_score": None,
                "expression_score": None,
                "review_note": "评分失败",
            },
            {
                "id": 4,
                "run_id": "R1",
                "case_id": "SEED-LIVE",
                "eval_model": "Model_A_baseline",
                "judge_status": "success",
                "review_status": "ai_final",
                "status": "active",
                "total_score": 100,
                "accuracy_score": 30,
                "reasoning_score": 20,
                "coverage_score": 20,
                "evidence_score": 15,
                "expression_score": 15,
                "review_note": "seed 名称不进入正式结论",
            },
        ])

        ai_scores, excluded = cc.split_live_scores(live_scores)
        self.assertEqual(["vendor/live-ai-final"], ai_scores["eval_model"].tolist())
        self.assertEqual(["vendor/live-failed"], excluded["eval_model"].tolist())

        formal = cc.build_formal_conclusions(seed_scores, ai_scores)
        self.assertEqual(["vendor/live-ai-final"], [item["model_name"] for item in formal])

    def test_conclusion_page_has_clear_empty_state_copy(self):
        text = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        for phrase in [
            "暂无 AI 评分结果",
            "发起评测",
        ]:
            self.assertIn(phrase, text)


class SampleLibraryGuardrailTests(unittest.TestCase):
    def test_sample_table_contract_and_current_sample_actions(self):
        self.assertEqual(
            ["样本编号", "任务标题", "专业场景", "测试状态", "完整度", "更新时间", "操作"],
            samples._SAMPLE_TABLE_COLUMNS,
        )

        table_source = inspect.getsource(samples.build_sample_table_rows)
        self.assertIn('"操作": "查看"', table_source)
        self.assertNotIn("删除", table_source)
        self.assertNotIn("编辑", table_source)
        self.assertNotIn("移出测试", table_source)

        toolbar_source = inspect.getsource(samples._render_sample_detail_toolbar)
        self.assertIn('"编辑样本"', toolbar_source)
        self.assertIn('"移出测试"', toolbar_source)
        self.assertNotIn('"更多"', toolbar_source)
        self.assertNotIn("删除样本", toolbar_source)

    def test_sample_library_top_level_actions_are_visible(self):
        source = Path("src/ui/samples.py").read_text(encoding="utf-8")
        self.assertIn('"新增样本"', source)
        self.assertIn('"导入 CSV"', source)
        self.assertIn('selection_mode="single-row"', source)
        self.assertIn('on_select="rerun"', source)
        self.assertNotIn('"查看样本"', source)
        self.assertNotIn("查看样本详情", source)
        self.assertNotIn("删除样本", source)
        self.assertNotIn('"更多"', source)
