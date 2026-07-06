"""PR-13 tests: project-intro numbers stay dynamic and task fields are
presented in business Chinese without leaking raw English field values.
"""

import unittest
from pathlib import Path

from src.data_service import load_all_data
from src.ui import case_study, labels


class CaseStudyPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_home_stats_cover_core_assets_with_live_counts(self):
        stats = {label: value for value, label in case_study._build_home_stats(self.data, {})}
        self.assertIn("当前样本", stats)
        self.assertIn("覆盖领域", stats)
        self.assertIn(str(len(self.data.tasks)), stats["当前样本"])

    def test_case_study_source_keeps_three_main_sections(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        for section in ("项目定位", "评测流程", "数据边界"):
            self.assertIn(section, source)
        self.assertNotIn("04\", \"进入操作", source)

    def test_case_study_reads_as_professional_brief(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertNotIn("本项目不判断哪个模型最好", source)
        self.assertIn("本项目评估大模型在财务、法律、投行等专业场景中的回答质量", source)
        self.assertIn("主要问题", source)
        self.assertIn("使用边界", source)
        self.assertIn("被测模型不会看到 Gold Answer、必须覆盖点、不可接受错误或 Rubric", source)
        self.assertIn("待确认、暂不采用、评分失败或示例评价均不进入正式结论", source)
        self.assertNotIn("维护样本", source)
        self.assertNotIn("确认可测", source)
        self.assertNotIn("render_inline_status", source)
        self.assertNotIn('st.markdown("**评分依据**")', source)

    def test_case_study_sections_have_number_title_lead_and_body(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertIn("render_home_section", source)
        for number, title, lead in [
            ("01", "项目定位", "评估模型在财务、法律、投行场景中的回答质量。"),
            ("02", "评测流程", "从专业样本到人工确认，形成可追溯的评分闭环。"),
            ("03", "数据边界", "结论只代表当前已确认样本，不做脱离样本的泛化排名。"),
        ]:
            self.assertIn(f'number="{number}"', source)
            self.assertIn(f'title="{title}"', source)
            self.assertIn(f'lead="{lead}"', source)
        self.assertNotIn("render_numbered_section", source)

    def test_case_study_keeps_process_line_only_in_flow_section(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertNotIn("PROCESS_TEXT", source)
        self.assertNotIn("process_text=", source)
        self.assertEqual(1, source.count("render_process_line(PROCESS_STEPS)"))
        self.assertIn('title="评测流程"', source)
        self.assertLess(source.index('title="评测流程"'), source.index("render_process_line(PROCESS_STEPS)"))

    def test_brief_and_section_title_styles_are_stronger(self):
        css = Path("src/ui/components.py").read_text(encoding="utf-8")
        for snippet in [
            "font-size: 2.35rem;",
            "font-weight: 820;",
            "letter-spacing: 0;",
            "border-left: 2px solid var(--fde-accent);",
            "grid-template-columns: 5.4rem minmax(0, 1fr);",
            "font-size: 2.45rem;",
            "font-size: 1.55rem;",
            "grid-template-columns: 3.1rem minmax(0, 1fr);",
            "font-size: 1.22rem;",
        ]:
            self.assertIn(snippet, css)


class TaskPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()
        self.records = labels.build_task_records(self.data.tasks)
        self.table = labels.build_task_table(self.data.tasks)

    def test_records_match_row_count(self):
        self.assertEqual(len(self.data.tasks), len(self.records))

    def test_known_field_values_are_translated_to_chinese(self):
        record_by_case = {r["case_id"]: r for r in self.records}
        sample = record_by_case["CM-001"]
        self.assertEqual("资本市场", sample["domain_label"])
        self.assertEqual("监管合规分析", sample["task_type_label"])
        self.assertEqual("高难度", sample["difficulty_label"])
        self.assertEqual("高风险", sample["risk_label"])
        self.assertEqual("high", sample["difficulty_badge"])
        self.assertEqual("high", sample["risk_badge"])

    def test_unmapped_values_fall_back_to_raw(self):
        self.assertEqual("Unknown Domain", labels.display_label("Unknown Domain", labels.DOMAIN_LABELS))
        self.assertEqual("未标注", labels.display_label("", labels.DOMAIN_LABELS))

    def test_long_text_is_summarized(self):
        long_text = "甲" * 400
        summary = labels.summarize_text(long_text)
        self.assertLessEqual(len(summary), labels.SUMMARY_LIMIT + 1)
        self.assertTrue(summary.endswith("…"))

    def test_table_uses_business_chinese_headers_in_order(self):
        self.assertEqual(
            ["案例编号", "领域", "任务类型", "难度", "风险等级", "考察能力", "任务摘要"],
            list(self.table.columns),
        )

    def test_table_does_not_leak_raw_english_field_values(self):
        flattened = self.table.astype(str).values.ravel().tolist()
        for raw in ("Capital Markets", "Regulatory Analysis", "Hard", "Medium"):
            self.assertNotIn(raw, flattened)


if __name__ == "__main__":
    unittest.main()
