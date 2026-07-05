import re
import unittest
from pathlib import Path


class UIUXAuditFixesTests(unittest.TestCase):
    def test_overview_uses_flow_strip_not_loop_rail(self):
        from src.ui.overview import get_evaluation_loop_steps
        import src.ui.components as components

        expected = [
            "专业任务",
            "Gold Answer",
            "模型回答",
            "Rubric 评分",
            "错误归因",
            "数据补强",
            "复测验证",
        ]
        self.assertEqual(expected, get_evaluation_loop_steps())
        self.assertTrue(hasattr(components, "render_flow_strip"))
        self.assertIn(".flow-strip", components.STYLE_CSS)

        overview_source = Path("src/ui/overview.py").read_text(encoding="utf-8")
        self.assertNotIn("render_loop_rail", overview_source)
        self.assertIn("render_flow_strip", overview_source)

        test_run_source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        self.assertNotIn("loop-rail", test_run_source)

    def test_pages_use_compact_hero(self):
        import src.ui.components as components

        self.assertTrue(hasattr(components, "render_compact_hero"))
        self.assertTrue(hasattr(components, "render_context_grid"))
        self.assertIn(".context-grid", components.STYLE_CSS)
        self.assertIn(".context-item", components.STYLE_CSS)

        for file_path in [
            "src/ui/case_study.py",
            "src/ui/samples.py",
            "src/ui/test_run.py",
            "src/ui/review.py",
            "src/ui/conclusions.py",
        ]:
            source = Path(file_path).read_text(encoding="utf-8")
            self.assertIn("render_compact_hero", source, file_path)
        case_study_source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertNotIn("render_mockup_stack", case_study_source, "src/ui/case_study.py")

    def test_pages_still_export_render_page_shell_for_backward_compat(self):
        import src.ui.components as components

        self.assertTrue(hasattr(components, "render_page_shell"))
        self.assertIn(".context-grid", components.STYLE_CSS)
        self.assertIn(".context-item", components.STYLE_CSS)

    def test_top_navigation_has_five_items_and_no_duplicate_html_buttons(self):
        from src.ui.navigation import PAGES, _TOP_NAV_ITEMS
        import src.ui.components as components

        self.assertEqual(5, len(_TOP_NAV_ITEMS))
        self.assertEqual(sorted([key for _, key in _TOP_NAV_ITEMS]), sorted(PAGES.keys()))
        self.assertIn(".top-nav", components.STYLE_CSS)

        navigation_source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
        # 侧边栏不再渲染页面按钮，避免与顶部导航重复。
        self.assertNotIn("st.sidebar.button", navigation_source)

    def test_top_navigation_is_lightweight_not_primary_cta(self):
        navigation_source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
        components_source = Path("src/ui/components.py").read_text(encoding="utf-8")

        self.assertNotIn("top-nav-brand", navigation_source)
        self.assertNotIn('type="primary" if current == page_key else "secondary"', navigation_source)
        self.assertIn('"tertiary"', navigation_source)
        self.assertIn(".top-nav .stButton > button", components_source)
        self.assertIn("border-bottom: 2px solid var(--fde-ink)", components_source)

    def test_primary_buttons_are_not_used_for_navigation(self):
        navigation_source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
        self.assertNotIn('type="primary"', navigation_source)

        case_study_source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertEqual(1, case_study_source.count('type="primary"'))

    def test_main_pages_do_not_repeat_brand_eyebrow(self):
        for file_path in [
            "src/ui/case_study.py",
            "src/ui/samples.py",
            "src/ui/test_run.py",
            "src/ui/review.py",
            "src/ui/conclusions.py",
        ]:
            source = Path(file_path).read_text(encoding="utf-8")
            self.assertNotIn('eyebrow="FinDueEval"', source, file_path)

    def test_current_pages_avoid_overpromising_copy(self):
        banned = [
            "可直接使用",
            "赋能",
            "智能",
            "一键",
            "自动洞察",
            "深度解析",
            "精准判断",
            "模型能力全景",
            "革命性",
            "草稿发布",
        ]
        for file_path in [
            "src/ui/page_config.py",
            "src/ui/case_study.py",
            "src/ui/samples.py",
            "src/ui/test_run.py",
            "src/ui/review.py",
            "src/ui/conclusions.py",
            "README.md",
        ]:
            source = Path(file_path).read_text(encoding="utf-8")
            for word in banned:
                self.assertNotIn(word, source, f"{file_path} contains {word}")

    def test_no_emoji_in_checklist(self):
        components_source = Path("src/ui/components.py").read_text(encoding="utf-8")
        self.assertNotIn("✅", components_source)
        case_study_source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertNotIn("✅", case_study_source)

    def test_case_study_has_single_primary_cta(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        buttons = re.findall(r"st\.button\(", source)
        self.assertEqual(2, len(buttons), "项目说明页应提供样本库与发起评测两个入口")
        self.assertIn('查看样本库', source)
        self.assertIn('发起评测', source)
        self.assertEqual(1, source.count('type="primary"'))
        self.assertIn('type="secondary"', source)

    def test_case_study_does_not_duplicate_top_nav_actions(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        button_labels = re.findall(r'st\.button\("([^"]+)"', source)

        self.assertEqual(["查看样本库", "发起评测"], button_labels)
        for label in ["项目说明", "评分确认", "评测结论"]:
            self.assertNotIn(label, button_labels)

    def test_case_study_does_not_render_status_or_domain_pills(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")

        self.assertNotIn("render_tag_cloud", source)
        self.assertNotIn("render_status_summary", source)
        for label in ["待复核样本", "已入库样本", "需优化样本", "已复核评分"]:
            self.assertNotIn(label, source)
        self.assertIn("_build_sample_scope_text", source)
        self.assertIn("已脱敏抽象为可评测任务", source)

    def test_sample_index_table_is_compact(self):
        samples_source = Path("src/ui/samples.py").read_text(encoding="utf-8")
        components_source = Path("src/ui/components.py").read_text(encoding="utf-8")

        self.assertIn("st.dataframe", samples_source)
        self.assertIn('"测试状态"', samples_source)
        self.assertNotIn('"操作"', samples_source)
        self.assertNotIn('"缺失项摘要"', samples_source)
        self.assertNotIn("sample-index-grid", samples_source)
        self.assertNotIn("samples_view_", samples_source)
        self.assertNotIn("for sample, row in zip", samples_source)
        self.assertNotIn("selection_mode=", samples_source)
        self.assertNotIn("on_select=", samples_source)
        self.assertNotIn("samples_index_dataframe", samples_source)
        self.assertIn("[data-testid=\"stDataFrame\"]", components_source)
        self.assertNotIn(".sample-operation-selected", components_source)

    def test_sample_library_uses_dialogs_and_selected_actions(self):
        samples_source = Path("src/ui/samples.py").read_text(encoding="utf-8")

        self.assertIn("@st.dialog(\"新增样本\"", samples_source)
        self.assertIn("@st.dialog(\"编辑样本\"", samples_source)
        self.assertIn("@st.dialog(\"确认移出测试\"", samples_source)
        self.assertIn("samples_create_open", samples_source)
        self.assertIn("samples_current_sample_select", samples_source)
        self.assertIn("当前样本", samples_source)
        self.assertIn("编辑当前样本", samples_source)
        self.assertIn("移出测试", samples_source)
        self.assertIn("移出测试是软删除", samples_source)
        self.assertIn("移出测试是软删除", samples_source)
        self.assertNotIn("点击表格行可查看当前样本。", samples_source)
        self.assertNotIn("_render_sample_selectbox_fallback", samples_source)
        self.assertNotIn("samples_index_select_fallback", samples_source)
        self.assertNotIn('"选择样本"', samples_source)
        self.assertNotIn('"查看"', samples_source)
        self.assertNotIn('with st.expander("样本管理"', samples_source)
        self.assertNotIn("st.tabs([\"新增样本\", \"编辑样本\", \"状态管理\", \"导入导出\"])", samples_source)

    def test_sample_library_has_three_main_sections_and_collapsed_detail(self):
        samples_source = Path("src/ui/samples.py").read_text(encoding="utf-8")
        page_config_source = Path("src/ui/page_config.py").read_text(encoding="utf-8")

        self.assertIn('render_numbered_section("01", "查询样本")', samples_source)
        self.assertIn('render_numbered_section("02", "样本列表", "展示当前查询结果。")', samples_source)
        self.assertIn('render_numbered_section("03", "当前样本", "选择、查看和维护一个样本。")', samples_source)
        self.assertIn("展示当前查询结果。", samples_source)
        self.assertIn("选择、查看和维护一个样本。", samples_source)
        self.assertIn("#### 任务内容", samples_source)
        self.assertIn("#### 理想回复标准 / Gold Answer", samples_source)
        self.assertIn('st.markdown("#### Rubric 评分标准")', samples_source)
        self.assertIn("#### 完整度检查", samples_source)
        self.assertNotIn('st.expander("任务内容", expanded=False)', samples_source)
        self.assertNotIn(".current-sample-summary", Path("src/ui/components.py").read_text(encoding="utf-8"))
        self.assertIn("维护正式评测样本。完整且已入库的样本可以进入发起评测。", page_config_source)
        self.assertIn("查询样本、样本列表、当前样本。", page_config_source)
        self.assertNotIn("新增和编辑会同步任务题", samples_source)

    def test_test_run_keeps_primary_buttons_for_confirmation_and_execution(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        primary_buttons = re.findall(r'type\s*=\s*"primary"', source)
        self.assertEqual(4, len(primary_buttons), "样本确认、模型确认、运行和评分可使用 Primary")
        self.assertIn('"运行模型回答", type="primary"', source)
        self.assertIn('button_label = "仅对已完成回答生成评分草稿" if partial_run else "生成评分草稿"', source)
        self.assertIn('button_label, type="primary"', source)
        self.assertIn('"确认选择"', source)
        self.assertIn('key="test_run_sample_dialog_confirm"', source)
        self.assertIn('key="test_run_model_dialog_confirm"', source)
        self.assertIn('disabled=not selected_cases', source)
        self.assertIn('disabled=not chosen_models', source)

    def test_review_seed_mode_hides_confirm_archive(self):
        source = Path("src/ui/review.py").read_text(encoding="utf-8")
        self.assertIn("score_run_id", source)
        self.assertIn('"确认生效"', source)
        self.assertIn('@st.dialog("确认生效"', source)
        self.assertIn('@st.dialog("修订后确认"', source)
        self.assertIn('@st.dialog("暂不采用"', source)
        self.assertNotIn("def _render_case_review", source)

    def test_conclusions_does_not_render_card_classes(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        self.assertNotIn("fingerprint-card", source)
        self.assertNotIn("boundary-card", source)
        self.assertNotIn("render_action_cards", source)
        self.assertNotIn("status-badge", source)
        self.assertNotIn("review-risk-note", source)
        self.assertNotIn("render_evidence_panel", source)
        self.assertNotIn("st.expander", source)

    def test_case_detail_uses_review_workbench_components(self):
        import src.ui.components as components

        self.assertTrue(hasattr(components, "render_answer_boundary_panel"))
        self.assertTrue(hasattr(components, "render_preference_comparison"))
        self.assertIn(".answer-boundary-panel", components.STYLE_CSS)
        self.assertIn(".comparison-grid", components.STYLE_CSS)

        review_path = Path("src/ui/review.py")
        if review_path.exists():
            source = review_path.read_text(encoding="utf-8")
            self.assertNotIn("Preferred", source)
            self.assertNotIn("Rejected", source)

    def test_error_analysis_prioritizes_error_to_data_action_path(self):
        from src.data_service import load_all_data
        from src.metrics import get_error_attribution_actions
        from src.ui.error_analysis import build_error_action_path

        data = load_all_data()
        actions = get_error_attribution_actions(data.errors, data.optimizations)
        path_df = build_error_action_path(actions)

        self.assertFalse(path_df.empty)
        self.assertEqual(
            ["错误表现", "可能原因", "数据补强动作", "验证指标"],
            list(path_df.columns),
        )

        source = Path("src/ui/error_analysis.py").read_text(encoding="utf-8")
        self.assertIn("_show_error_action_path", source)
        self.assertIn("错误表现 → 可能原因 → 数据补强动作", source)
        self.assertIn("当前样本观察", source)


if __name__ == "__main__":
    unittest.main()
