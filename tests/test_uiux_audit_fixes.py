import re
import unittest
from pathlib import Path


class UIUXAuditFixesTests(unittest.TestCase):
    def test_legacy_ui_pages_are_removed_from_main_flow(self):
        import src.ui.components as components

        legacy_files = [
            "src/ui/overview.py",
            "src/ui/eval_run_page.py",
            "src/ui/model_diagnosis.py",
            "src/ui/model_boundary.py",
            "src/ui/dataset_quality.py",
            "src/ui/error_analysis.py",
            "src/ui/optimization_compare.py",
            "src/ui/case_detail.py",
            "src/ui/dataset_admin.py",
            "src/ui/evaluation_conclusions.py",
            "src/ui/project_methodology.py",
            "src/ui/tasks.py",
        ]
        for legacy_file in legacy_files:
            self.assertFalse(Path(legacy_file).exists(), legacy_file)

        test_run_source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        self.assertNotIn("loop-rail", test_run_source)
        self.assertFalse(hasattr(components, "render_flow_strip"))

    def test_pages_keep_shared_page_components_available(self):
        import src.ui.components as components

        self.assertTrue(hasattr(components, "render_compact_hero"))
        self.assertTrue(hasattr(components, "render_page_heading"))
        self.assertTrue(hasattr(components, "render_detail_panel"))
        self.assertTrue(hasattr(components, "render_kv_grid"))
        self.assertTrue(hasattr(components, "render_inline_status"))
        self.assertTrue(hasattr(components, "render_clean_list"))
        self.assertIn(".inline-status", components.STYLE_CSS)
        self.assertIn(".detail-panel", components.STYLE_CSS)

        samples_source = Path("src/ui/samples.py").read_text(encoding="utf-8")
        self.assertIn("_render_samples_title_bar", samples_source)
        self.assertNotIn("render_compact_hero", samples_source)
        case_study_source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertNotIn("render_mockup_stack", case_study_source, "src/ui/case_study.py")

    def test_legacy_component_exports_are_removed(self):
        import src.ui.components as components

        for name in [
            "render_page_shell",
            "render_context_grid",
            "render_metric_card",
            "render_status_badge",
            "render_score_badge",
            "render_evidence_panel",
            "render_action_cards",
        ]:
            self.assertFalse(hasattr(components, name), name)
        for selector in [".metric-card", ".status-badge", ".score-badge", ".review-risk-note"]:
            self.assertNotIn(selector, components.STYLE_CSS)

    def test_top_navigation_has_five_items_and_no_duplicate_html_buttons(self):
        from src.ui.navigation import PAGES, _TOP_NAV_ITEMS
        import src.ui.components as components

        self.assertEqual(5, len(_TOP_NAV_ITEMS))
        self.assertEqual(sorted([key for _, key in _TOP_NAV_ITEMS]), sorted(PAGES.keys()))
        self.assertIn(".top-nav-brand", components.STYLE_CSS)

        navigation_source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
        # 侧边栏不再渲染页面按钮，避免与顶部导航重复。
        self.assertNotIn("st.sidebar.button", navigation_source)
        self.assertIn("财务/法律/投行场景大模型对比评测", navigation_source)
        self.assertNotIn("尽调评测工作台", navigation_source)
        self.assertNotIn("样本库 > 测试", navigation_source)

    def test_top_navigation_is_lightweight_not_primary_cta(self):
        navigation_source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
        components_source = Path("src/ui/components.py").read_text(encoding="utf-8")

        self.assertIn("top-nav-brand", navigation_source)
        self.assertNotIn('type="primary" if current == page_key else "secondary"', navigation_source)
        self.assertIn('"tertiary"', navigation_source)
        self.assertIn('[data-testid="stHorizontalBlock"]:has(.top-nav-brand)', components_source)
        self.assertIn("border: 0;", components_source)
        self.assertIn('use_container_width=False', navigation_source)
        self.assertIn("background: transparent !important;", components_source)
        self.assertNotIn("position: sticky", components_source)
        self.assertNotIn("position: fixed", components_source)
        self.assertNotIn('left: calc(50% - 50vw)', components_source)
        self.assertNotIn(
            '[data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button[kind="secondary"] {\n'
            "    background: var(--fde-status-muted-bg)",
            components_source,
        )
        self.assertNotIn("border-bottom-color: var(--fde-ink)", components_source)

    def test_primary_buttons_are_not_used_for_navigation(self):
        navigation_source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
        self.assertNotIn('type="primary"', navigation_source)

        case_study_source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        self.assertEqual(0, case_study_source.count('type="primary"'))

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

    def test_case_study_has_no_duplicate_cta_buttons(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        buttons = re.findall(r"st\.button\(", source)
        self.assertEqual(0, len(buttons), "项目说明页不再重复顶部导航入口")
        self.assertNotIn('查看样本库', source)
        self.assertNotIn('case_study_samples', source)
        self.assertNotIn('case_study_try', source)
        self.assertNotIn('type="primary"', source)
        self.assertNotIn('type="secondary"', source)

    def test_case_study_does_not_duplicate_top_nav_actions(self):
        source = Path("src/ui/case_study.py").read_text(encoding="utf-8")
        button_labels = re.findall(r'st\.button\("([^"]+)"', source)

        self.assertEqual([], button_labels)
        for label in ["项目说明", "样本库", "发起评测", "评分确认", "评测结论"]:
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
        self.assertIn('"操作"', samples_source)
        self.assertIn('"查看"', samples_source)
        self.assertNotIn('"缺失项摘要"', samples_source)
        self.assertNotIn("sample-index-grid", samples_source)
        self.assertNotIn("samples_view_", samples_source)
        self.assertNotIn("for sample, row in zip", samples_source)
        self.assertIn("selection_mode=\"single-row\"", samples_source)
        self.assertIn("on_select=\"rerun\"", samples_source)
        self.assertNotIn("samples_index_dataframe", samples_source)
        self.assertIn("[data-testid=\"stDataFrame\"]", components_source)
        self.assertNotIn(".sample-operation-selected", components_source)

    def test_sample_library_uses_dialogs_and_selected_actions(self):
        samples_source = Path("src/ui/samples.py").read_text(encoding="utf-8")

        self.assertIn("@st.dialog(\"新增样本\"", samples_source)
        self.assertIn("@st.dialog(\"编辑样本\"", samples_source)
        self.assertIn("@st.dialog(\"确认移出测试\"", samples_source)
        self.assertIn("@st.dialog(\"导入 CSV\"", samples_source)
        self.assertIn("samples_create_open", samples_source)
        self.assertIn("samples_import_csv_open", samples_source)
        self.assertIn("samples_csv_template_download", samples_source)
        self.assertIn("samples_csv_upload", samples_source)
        self.assertIn("跳过重复样本", samples_source)
        self.assertIn("更新已有样本", samples_source)
        self.assertNotIn("samples_current_sample_select", samples_source)
        self.assertIn("当前样本", samples_source)
        self.assertIn("编辑样本", samples_source)
        self.assertIn("移出测试", samples_source)
        self.assertIn("历史记录仍保留", samples_source)
        self.assertNotIn("@st.dialog(\"更多操作\"", samples_source)
        self.assertNotIn("当前版本暂不支持删除样本", samples_source)
        self.assertNotIn("删除样本", samples_source)
        self.assertNotIn("更多操作", samples_source)
        self.assertNotIn("点击表格行可查看当前样本。", samples_source)
        self.assertNotIn("_render_sample_selectbox_fallback", samples_source)
        self.assertNotIn("samples_index_select_fallback", samples_source)
        self.assertNotIn('"选择样本"', samples_source)
        self.assertIn('"查看"', samples_source)
        self.assertNotIn('with st.expander("样本管理"', samples_source)
        self.assertNotIn("st.tabs([\"新增样本\", \"编辑样本\", \"状态管理\", \"导入导出\"])", samples_source)

    def test_sample_library_has_three_main_sections_and_detail_panel(self):
        samples_source = Path("src/ui/samples.py").read_text(encoding="utf-8")
        components_source = Path("src/ui/components.py").read_text(encoding="utf-8")
        page_config_source = Path("src/ui/page_config.py").read_text(encoding="utf-8")

        self.assertIn('render_numbered_section("01", "查询与筛选")', samples_source)
        self.assertIn('render_numbered_section("02", "样本列表", "展示当前查询结果。")', samples_source)
        self.assertIn('render_numbered_section("03", "当前样本", "选择一个样本，查看评测资产结构。")', samples_source)
        self.assertNotIn('render_numbered_section("04", "样本操作"', samples_source)
        self.assertIn("展示当前查询结果。", samples_source)
        self.assertIn("选择一个样本，查看评测资产结构。", samples_source)
        self.assertIn("render_sample_detail_panel", samples_source)
        self.assertIn("render_detail_panel(body)", samples_source)
        self.assertIn("sample-detail-toolbar-title", components_source)
        self.assertIn(".sample-detail-panel", components_source)
        self.assertIn("sample-detail-section-title", components_source)
        self.assertIn("_detail_section_html(\"任务场景\"", samples_source)
        self.assertIn("_detail_section_html(\"任务内容\"", samples_source)
        self.assertIn("_detail_section_html(\"理想回复标准 / Gold Answer\"", samples_source)
        self.assertIn("Rubric 评分标准", samples_source)
        self.assertIn("Rubric 维度配置", samples_source)
        self.assertIn("_detail_section_html(\"准入状态\"", samples_source)
        self.assertNotIn("当前样本：", samples_source)
        self.assertNotIn('st.expander("任务内容", expanded=False)', samples_source)
        self.assertNotIn(".current-sample-summary", components_source)
        self.assertIn("维护正式评测样本。完整且已入库的样本可以进入发起评测。", page_config_source)
        self.assertIn("查询与筛选、样本列表、当前样本。", page_config_source)
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

    def test_review_seed_mode_hides_direct_confirmation_for_examples(self):
        page_source = Path("src/ui/review.py").read_text(encoding="utf-8")
        actions_source = Path("src/ui/review_actions.py").read_text(encoding="utf-8")
        queue_source = Path("src/ui/review_queue.py").read_text(encoding="utf-8")
        self.assertIn("score_run_id", page_source)
        self.assertIn('"确认生效"', actions_source)
        self.assertIn('@st.dialog("确认生效"', actions_source)
        self.assertIn('@st.dialog("修订后确认"', actions_source)
        self.assertIn('@st.dialog("暂不采用"', actions_source)
        self.assertNotIn("def _render_case_review", page_source + actions_source + queue_source)

    def test_conclusions_does_not_render_card_classes(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        self.assertNotIn("fingerprint-card", source)
        self.assertNotIn("boundary-card", source)
        self.assertNotIn("render_action_cards", source)
        self.assertNotIn("status-badge", source)
        self.assertNotIn("review-risk-note", source)
        self.assertNotIn("render_evidence_panel", source)
        self.assertNotIn("st.expander", source)

    def test_review_uses_current_component_surface(self):
        import src.ui.components as components

        self.assertFalse(hasattr(components, "render_answer_boundary_panel"))
        self.assertFalse(hasattr(components, "render_preference_comparison"))
        self.assertNotIn(".answer-boundary-panel", components.STYLE_CSS)
        self.assertNotIn(".comparison-grid", components.STYLE_CSS)

        review_path = Path("src/ui/review.py")
        if review_path.exists():
            source = review_path.read_text(encoding="utf-8")
            self.assertNotIn("Preferred", source)
            self.assertNotIn("Rejected", source)


if __name__ == "__main__":
    unittest.main()
