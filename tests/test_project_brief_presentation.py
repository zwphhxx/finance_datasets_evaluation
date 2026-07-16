"""project-intro numbers stay dynamic and task fields are
presented in business Chinese without leaking raw English field values.
"""

import unittest
from pathlib import Path

from src.data_service import load_all_data
from src.ui import labels


class CaseStudyPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = load_all_data()

    def test_case_study_source_keeps_three_main_sections(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        for section in ("项目定位", "评测流程", "数据边界"):
            self.assertIn(section, source)
        self.assertNotIn("04\", \"进入操作", source)

    def test_case_study_intro_restores_title_without_subtitle_or_stats(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertIn("render_brief_intro(", source)
        self.assertIn("PROJECT_DISPLAY_NAME", source)
        self.assertIn("专业任务中的回答质量", source)
        self.assertIn("识别模型的主要问题和使用边界", source)
        self.assertNotIn("subtitle=", source)
        self.assertNotIn("stats=", source)
        self.assertNotIn("_build_home_stats", source)
        self.assertNotIn("当前样本 13 个", source)
        self.assertNotIn("覆盖专业场景", source)

    def test_case_study_reads_as_professional_brief(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertNotIn("本项目不判断哪个模型最好", source)
        self.assertIn("本项目评估大模型在财务、法律、投行等专业任务中的回答质量", source)
        self.assertIn("财务核查、法律合规、投行尽调", source)
        self.assertIn("当前样本库包含 13 条人工整理的专业任务样本及专业标准答案", source)
        self.assertIn("主要问题", source)
        self.assertIn("使用边界", source)
        self.assertIn("被测模型只看到任务题、业务背景和输出要求", source)
        self.assertIn("被测模型不会看到专业标准答案、必须覆盖点、不可接受错误或评分标准", source)
        self.assertIn("失败评分、模拟回退或示例评价均不进入评测结论", source)
        self.assertNotIn("维护样本", source)
        self.assertNotIn("确认可测", source)
        self.assertNotIn("render_inline_status", source)
        self.assertNotIn('st.markdown("**评分依据**")', source)

    def test_case_study_sections_have_number_title_lead_and_body(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertIn("render_home_section", source)
        for number, title, lead in [
            ("01", "项目定位", "评估模型在财务、法律、投行场景中的回答质量。"),
            ("02", "评测流程", "从专业样本到 AI 评分后的评测结论。"),
            ("03", "数据边界", "结论只代表当前样本范围，不做脱离样本的泛化排名。"),
        ]:
            self.assertIn(f'number="{number}"', source)
            self.assertIn(f'title="{title}"', source)
            self.assertIn(f'lead="{lead}"', source)
        self.assertNotIn("render_numbered_section", source)
        self.assertIn("first=True", source)

    def test_case_study_keeps_process_line_only_in_flow_section(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertNotIn("PROCESS_TEXT", source)
        self.assertNotIn("process_text=", source)
        self.assertNotIn("render_process_line(PROCESS_STEPS)", source)
        self.assertEqual(1, source.count("process_steps=PROCESS_STEPS"))
        self.assertIn(
            'PROCESS_STEPS = ["人工录入样本库", "发起模型评测", "生成 AI 评分", "进入评测结论"]',
            source,
        )
        self.assertIn('title="评测流程"', source)
        self.assertLess(source.index('title="评测流程"'), source.index("process_steps=PROCESS_STEPS"))

    def test_brief_and_section_title_styles_are_stronger(self):
        css = Path("src/ui/components.py").read_text(encoding="utf-8")
        for snippet in [
            "letter-spacing: 0;",
            ".brief-title",
            "font-size: 2.35rem;",
            "border-left: 2px solid var(--fde-accent);",
            ".home-section-first",
            "border-top: 0;",
            ".section-heading {",
            ".section-heading-home",
            ".section-heading-page",
            "grid-template-columns: 4.8rem minmax(0, 1fr);",
            "align-items: baseline;",
            "margin-left: 6.05rem;",
            "font-size: 2.05rem;",
            "font-size: 1.62rem;",
            "grid-template-columns: 3.4rem minmax(0, 1fr);",
            "font-size: 1.28rem;",
        ]:
            self.assertIn(snippet, css)
        self.assertNotIn(".brief-subtitle", css)
        self.assertNotIn(".brief-meta", css)

    def test_brief_intro_outputs_title_and_note_without_subtitle_or_stats(self):
        import src.ui.components as components

        captured = []
        original = components.render_html
        try:
            components.render_html = lambda html, container=None: captured.append(str(html))
            components.render_brief_intro(
                title=components.PROJECT_DISPLAY_NAME,
                note=(
                    "本项目评估大模型在财务、法律、投行等专业任务中的回答质量，"
                    "并在当前样本范围内识别模型的主要问题和使用边界。"
                )
            )
        finally:
            components.render_html = original

        html = "".join(captured)
        self.assertIn("brief-intro", html)
        self.assertIn("<h1", html)
        self.assertIn(components.PROJECT_DISPLAY_NAME, html)
        self.assertIn("brief-note", html)
        self.assertNotIn("brief-subtitle", html)
        self.assertNotIn("brief-meta", html)

    def test_home_section_html_groups_number_title_lead_and_body(self):
        import src.ui.components as components

        captured = []
        original = components.render_html
        try:
            components.render_html = lambda html, container=None: captured.append(str(html))
            components.render_home_section(
                number="01",
                title="项目定位",
                lead="评估模型在财务、法律、投行场景中的回答质量。",
                body=["正文"],
                first=True,
            )
        finally:
            components.render_html = original

        html = "".join(captured)
        self.assertIn('class="home-section home-section-first"', html)
        self.assertIn('class="section-heading section-heading-home"', html)
        self.assertIn("section-heading-main", html)
        self.assertIn('<span class="section-heading-number">01</span>', html)
        self.assertNotIn("home-section-heading", html)
        self.assertIn("home-section-body", html)
        self.assertLess(html.index("section-heading"), html.index("home-section-body"))

    def test_home_section_process_line_is_inside_body_column(self):
        import src.ui.components as components

        captured = []
        original = components.render_html
        try:
            components.render_html = lambda html, container=None: captured.append(str(html))
            components.render_home_section(
                number="02",
                title="评测流程",
                lead="从专业样本到 AI 评分后的评测结论。",
                body=["正文"],
                process_steps=["人工录入样本库", "发起模型评测"],
            )
        finally:
            components.render_html = original

        html = "".join(captured)
        body_start = html.index('<div class="home-section-body">')
        body_end = html.index("</div>", body_start)
        process_index = html.index('class="process-line"')
        self.assertGreater(process_index, body_start)
        self.assertLess(process_index, body_end)

    def test_section_heading_renders_home_and_page_variants(self):
        import src.ui.components as components

        captured = []
        original = components.render_html
        try:
            components.render_html = lambda html, container=None: captured.append(str(html))
            components.render_section_heading("01", "项目定位", "评估模型回答质量。", variant="home")
            components.render_section_heading("02", "样本列表", "展示当前查询结果。", variant="page")
        finally:
            components.render_html = original

        html = "".join(captured)
        self.assertIn('class="section-heading section-heading-home"', html)
        self.assertIn('class="section-heading section-heading-page"', html)
        self.assertIn("section-heading-number", html)
        self.assertIn("section-heading-title", html)
        self.assertIn("section-heading-lead", html)

    def test_numbered_section_uses_unified_heading_structure(self):
        import src.ui.components as components

        captured = []
        original = components.render_html
        try:
            components.render_html = lambda html, container=None: captured.append(str(html))
            components.render_numbered_section("02", "样本列表", "展示当前查询结果。")
        finally:
            components.render_html = original

        html = "".join(captured)
        self.assertIn('class="section-heading section-heading-page"', html)
        self.assertIn('<span class="section-heading-number">02</span>', html)
        self.assertIn("样本列表", html)
        self.assertIn("展示当前查询结果", html)
        self.assertNotIn("numbered-section-index", html)


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
        self.assertEqual("投行场景", sample["domain_label"])
        self.assertEqual("投行专业判断", sample["task_type_label"])
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
            ["案例编号", "专业场景", "任务类型", "难度", "风险等级", "考察能力", "任务摘要"],
            list(self.table.columns),
        )

    def test_table_does_not_leak_raw_english_field_values(self):
        flattened = self.table.astype(str).values.ravel().tolist()
        for raw in ("Capital Markets", "Regulatory Analysis", "Hard", "Medium"):
            self.assertNotIn(raw, flattened)


if __name__ == "__main__":
    unittest.main()
