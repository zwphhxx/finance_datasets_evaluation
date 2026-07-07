"""the test-run page behaves like an evaluation execution flow."""

import unittest
from pathlib import Path

from app.models.base import ModelInfo
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.services import scorer as sc
from src.ui import components as ui_components
from src.ui.test_run import (
    _EVAL_MAX_TOKENS,
    _EVAL_MAX_TOKENS_DEFAULT,
    _EVAL_MAX_TOKENS_LIMIT,
    batch_run_notice,
    build_outcome_view_options,
    build_model_selection_options,
    build_remaining_queue_items,
    build_failed_run_queue_items,
    build_run_plan_summary,
    build_run_queue_items,
    build_score_plan_summary,
    build_score_queue_items,
    build_score_draft_detail_panel,
    build_score_result_index_rows,
    build_sample_options,
    build_sample_selection_rows,
    build_score_view_options,
    build_score_summary_rows,
    default_outcome_view_index,
    default_score_view_index,
    filter_sample_selection_options,
    get_advanced_setting_items,
    get_test_run_steps,
    has_confirmable_score_drafts,
    merge_sample_checkbox_selection,
    prompt_preview_task_for_case,
    requires_large_run_confirmation,
    resolve_eval_max_tokens,
    sample_checkbox_key,
    slow_model_notice,
    _model_short_name,
    _siliconflow_balance_text,
)


class TestRunFlowStructureTests(unittest.TestCase):
    def test_main_steps_are_execution_flow(self):
        self.assertEqual(
            ["评测配置", "模型回答", "评分草稿"],
            get_test_run_steps(),
        )

    def test_advanced_settings_keep_technical_controls_collapsed(self):
        self.assertEqual([], get_advanced_setting_items())

    def test_eval_max_tokens_default_and_env_override_are_bounded(self):
        self.assertEqual(4096, _EVAL_MAX_TOKENS_DEFAULT)
        self.assertLessEqual(_EVAL_MAX_TOKENS, _EVAL_MAX_TOKENS_LIMIT)
        self.assertEqual(4096, resolve_eval_max_tokens(""))
        self.assertEqual(6000, resolve_eval_max_tokens("6000"))
        self.assertEqual(_EVAL_MAX_TOKENS_LIMIT, resolve_eval_max_tokens("999999"))
        self.assertEqual(4096, resolve_eval_max_tokens("not-a-number"))

    def test_batch_run_notice_thresholds_and_confirmation(self):
        self.assertIsNone(batch_run_notice({"planned_responses": 20}))
        self.assertIn("建议分批运行", batch_run_notice({"planned_responses": 21}) or "")
        self.assertIn("二次确认", batch_run_notice({"planned_responses": 51}) or "")
        self.assertFalse(requires_large_run_confirmation({"planned_responses": 50}))
        self.assertTrue(requires_large_run_confirmation({"planned_responses": 51}))

    def test_slow_model_notice_uses_soft_keywords(self):
        notice = slow_model_notice(["vendor/LongCat-2.0", "deepseek-r1", "fast/model"])

        self.assertIn("响应可能较慢", notice or "")
        self.assertIn("LongCat-2.0", notice or "")
        self.assertIn("deepseek-r1", notice or "")

    def test_selection_controls_are_dialog_driven(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

        self.assertIn('@st.dialog("选择样本"', source)
        self.assertIn('@st.dialog("选择模型"', source)
        self.assertIn("st.checkbox", source)
        self.assertIn("test_run_case_checkbox_", source)
        self.assertIn("关键词搜索", source)
        self.assertIn("当前没有符合条件的可测样本", source)
        self.assertIn("模型服务：", source)
        self.assertIn("硅基流动", source)
        self.assertIn('st.text_input(\n            "搜索模型"', source)
        self.assertIn("输入模型名称、厂商或关键词", source)
        self.assertIn('st.selectbox("模型"', source)
        self.assertIn("添加到对比列表", source)
        self.assertIn("test_run_model_dialog_selected", source)
        self.assertIn("移除", source)
        self.assertIn("test_run_selected_cases", source)
        self.assertIn("test_run_selected_models", source)
        self.assertIn("test_run_cases_dialog_selected", source)
        self.assertNotIn('render_numbered_section("04"', source)
        self.assertNotIn("st.multiselect(", source)
        self.assertNotIn('st.multiselect(\n        "选择样本"', source)
        self.assertNotIn('st.multiselect("选择对比模型"', source)
        self.assertNotIn("st.data_editor", source)
        self.assertNotIn("CheckboxColumn", source)
        self.assertNotIn("test_run_cases_editor", source)
        self.assertNotIn("test_run_model_check_", source)
        self.assertNotIn("模型服务 provider", source)
        self.assertNotIn('st.expander("高级设置"', source)
        self.assertNotIn("加载 / 刷新模型列表", source)
        self.assertNotIn("手动追加模型 ID", source)
        self.assertNotIn('st.slider("temperature"', source)
        self.assertNotIn('number_input(\n            "max_tokens"', source)
        self.assertNotIn("账户余额：未获取", source)

    def test_run_execution_streams_queue_items_in_page(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        panel_source = source[
            source.index("def _render_configuration_panel"):
            source.index("def _open_sample_dialog")
        ]
        run_button_source = source[
            source.index("def _render_run_button"):
            source.index("def _render_live_run_queue")
        ]

        self.assertIn("运行队列", source)
        self.assertIn("已完成结果", source)
        self.assertIn("等待中", source)
        self.assertIn("已完成回答已保留", source)
        self.assertIn("继续未完成项", source)
        self.assertIn("放弃本次运行", source)
        self.assertIn("er.run_single", source)
        self.assertIn("retry_max_tokens=_EVAL_MAX_TOKENS_LIMIT", source)
        self.assertIn("er.CompareRunResult", source)
        self.assertIn("现场演示建议最多 2-3 个模型", source)
        self.assertIn("当前预计生成回答较多，运行时间可能较长，部分模型可能超时。建议分批运行。", source)
        self.assertIn("确认按批处理运行", source)
        self.assertIn("查看全文", source)
        self.assertIn('@st.dialog("模型回答全文"', source)
        self.assertIn("查看技术明细", source)
        self.assertIn('@st.dialog("技术明细"', source)
        self.assertIn("仅对已完成回答生成评分草稿", source)
        self.assertIn("start_run = _render_run_button(", panel_source)
        self.assertIn("if start_run:", panel_source)
        self.assertLess(panel_source.index("with col3:"), panel_source.index("if start_run:"))
        self.assertLess(panel_source.index("if start_run:"), panel_source.index("_execute_run_queue("))
        self.assertNotIn("_execute_run_queue(", run_button_source)
        self.assertNotIn("progress_callback=_on_progress", source)
        self.assertNotIn('st.expander("查看回答"', source)
        self.assertNotIn('st.expander("查看全部回答"', source)

    def test_configuration_panel_exposes_model_prompt_preview_without_answer_fields(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

        self.assertIn("查看本题发送给被测模型的提示词", source)
        self.assertIn('@st.dialog("发送给被测模型的提示词"', source)
        self.assertIn("er.build_messages", source)
        self.assertIn("系统提示词", source)
        self.assertIn("用户提示词", source)
        self.assertIn("不包含专业标准答案、必须覆盖点、不可接受错误或评分标准", source)
        self.assertIn("请以本弹窗内容为准判断被测模型实际收到的信息", source)
        self.assertNotIn("core_conclusion", source[source.index("def _render_prompt_preview_dialog"):])

    def test_prompt_preview_uses_same_task_as_run_queue(self):
        task = {
            "case_id": "FD-001",
            "scenario": "财务场景",
            "question": "请判断收入质量。",
            "context": "2025 年收入 12,000 万元，应收账款 5,400 万元。",
            "expected_capability": "请基于已提供模拟数据先形成初步判断。",
            "standard_conclusion": "不应进入被测模型 prompt",
            "must_have_points": ["不应进入被测模型 prompt"],
            "unacceptable_errors": ["不应进入被测模型 prompt"],
            "scoring_focus": "不应进入被测模型 prompt",
        }
        sample_options = [{
            "case_id": "FD-001",
            "title": "收入质量",
            "task": task,
        }]
        selected_tasks = [sample_options[0]]

        preview_task = prompt_preview_task_for_case(sample_options, ["FD-001"], "FD-001")
        queue_task = build_run_queue_items(["vendor/model"], selected_tasks)[0]["task"]

        self.assertIs(preview_task, queue_task)
        prompt = "\n".join(message["content"] for message in er.build_messages(preview_task))
        self.assertIn("2025 年收入 12,000 万元", prompt)
        self.assertIn("请基于已提供模拟数据先形成初步判断", prompt)
        for leak in ["standard_conclusion", "must_have_points", "unacceptable_errors", "scoring_focus", "不应进入被测模型 prompt"]:
            self.assertNotIn(leak, prompt)

    def test_page_wires_recoverable_run_and_score_queues(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

        self.assertIn("er.initialize_run_queue", source)
        self.assertIn("er.mark_run_queue_item_running", source)
        self.assertIn("er.persist_run_outcome", source)
        self.assertIn("er.restore_compare_result_from_db", source)
        self.assertIn("sc.initialize_score_queue", source)
        self.assertIn("sc.mark_score_queue_item_running", source)
        self.assertIn("sc.restore_score_result_from_db", source)
        self.assertIn("当前任务在页面内执行", source)
        self.assertIn("已完成结果会保留，未完成项可稍后继续", source)

    def test_run_results_use_selector_for_answer_review(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        results_source = source[
            source.index("def _render_results"):
            source.index("def _render_unfinished_run_without_result")
        ]

        self.assertIn("build_outcome_view_options", source)
        self.assertIn("default_outcome_view_index", source)
        self.assertIn("render_model_answer_detail", source)
        self.assertIn("render_markdown_detail_panel", source)
        self.assertIn("action_label=\"查看技术明细\"", source)
        self.assertIn("action_type=\"secondary\"", source)
        self.assertIn("_model_short_name", source)
        self.assertIn("_task_lookup_for_result", source)
        self.assertIn("markdown-detail-heading", Path("src/ui/components.py").read_text(encoding="utf-8"))
        self.assertIn('st.selectbox(\n        "查看回答"', source)
        self.assertIn("_render_selected_outcome_detail", source)
        self.assertIn("失败项不会进入评分草稿", source)
        self.assertIn("默认展示第一条失败原因", source)
        self.assertIn("回答不完整", source)
        self.assertIn("响应超时", source)
        self.assertIn("触发限流", source)
        self.assertIn("权限异常", source)
        self.assertIn("空回答", source)
        self.assertIn("原因：", source)
        self.assertIn("已自动重试", source)
        self.assertIn("处理：不会进入评分草稿，可重试失败项或更换模型。", source)
        for column in ("finish_reason", "incomplete_reason", "retry_count", "输出tokens", "trace_id"):
            self.assertIn(column, source[source.index("def _render_results_table"):])
        self.assertNotIn("render_aux_action_bar", results_source)
        self.assertNotIn("test_run_technical_details", results_source)
        self.assertNotIn("for index, outcome in enumerate(result.outcomes", results_source)
        self.assertNotIn("_render_run_outcome_card(outcome, index)", results_source)
        self.assertNotIn("st.markdown(normalize_answer_markdown(_answer_preview(answer)))", source)
        self.assertNotIn("st.markdown(normalize_answer_markdown(outcome.answer_text or \"—\"))", source)

    def test_score_draft_streams_and_shows_rationale_by_default(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        score_source = source[
            source.index("def _render_scoring"):
            source.index("def _render_score_compare_table")
        ]

        self.assertIn("评分队列", source)
        self.assertIn("正在评分", source)
        self.assertIn("已生成评分", source)
        self.assertIn("跳过失败回答", source)
        self.assertIn("build_score_queue_items", source)
        self.assertIn("build_score_view_options", source)
        self.assertIn("default_score_view_index", source)
        self.assertIn("sc.score_single", source)
        self.assertIn("复核提示", source)
        self.assertIn("维度评分", source)
        self.assertIn("评分依据", source)
        self.assertIn("未返回明确依据", source)
        self.assertIn("查看评分对比表", source)
        self.assertIn("action_label=\"查看评分对比表\"", score_source)
        self.assertIn("action_type=\"secondary\"", score_source)
        self.assertNotIn("render_aux_action_bar", score_source)
        self.assertNotIn('"辅助查看"', score_source)
        self.assertNotIn("st.spinner", score_source)
        self.assertNotIn("sc.score_compare(", score_source)
        self.assertNotIn('st.expander("评分对比表"', source)

    def test_score_failure_copy_and_retry_entry_are_visible(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")

        self.assertIn("模型回答已生成，裁判评分失败。", source)
        self.assertIn("重试失败评分", source)
        self.assertIn("SILICONFLOW_TIMEOUT_SECONDS", source)
        self.assertIn("_execute_retry_score_queue", source)

    def test_model_selection_options_are_bounded_and_searchable(self):
        models = [
            ModelInfo(
                id=f"Vendor/Model-{idx}",
                provider="siliconflow",
                object="model",
                owned_by="Vendor",
                raw={"display_name": f"Finance Model {idx}"},
            )
            for idx in range(35)
        ]
        options, matched_count = build_model_selection_options(models, "")

        self.assertEqual(30, len(options))
        self.assertEqual(35, matched_count)
        self.assertEqual("Vendor/Model-0", options[0])

    def test_model_selection_search_uses_id_name_and_owner_case_insensitively(self):
        models = [
            ModelInfo(
                id="Alpha/General",
                provider="siliconflow",
                object="model",
                owned_by="Alpha",
                raw={"display_name": "General Chat"},
            ),
            ModelInfo(
                id="Beta/Risk",
                provider="siliconflow",
                object="model",
                owned_by="BetaLab",
                raw={"display_name": "Finance Risk"},
            ),
        ]

        self.assertEqual(["Beta/Risk"], build_model_selection_options(models, "finance")[0])
        self.assertEqual(["Beta/Risk"], build_model_selection_options(models, "betalab")[0])
        self.assertEqual(["Alpha/General"], build_model_selection_options(models, "alpha/general")[0])

    def test_balance_text_is_optional(self):
        class _NoBalanceProvider:
            def get_balance(self):
                return None

        class _NumericBalanceProvider:
            def get_balance(self):
                return 12.345

        class _EmptyBalanceProvider:
            def get_balance(self):
                return " "

        self.assertIsNone(_siliconflow_balance_text(_NoBalanceProvider()))
        self.assertIsNone(_siliconflow_balance_text(_EmptyBalanceProvider()))
        self.assertEqual("¥12.35", _siliconflow_balance_text(_NumericBalanceProvider()))

    def test_outcome_view_options_prefer_first_success(self):
        outcomes = [
            er.RunOutcome(
                case_id="A",
                task_type="analysis",
                provider="siliconflow",
                model_id="Model-Failed",
                run_status="failed",
                success=False,
                error_code="timeout",
                error_message="timeout",
            ),
            er.RunOutcome(
                case_id="B",
                task_type="analysis",
                provider="siliconflow",
                model_id="Model-Success",
                run_status="success",
                success=True,
                answer_text="ok",
            ),
        ]

        task_lookup = {
            "A": {"question": "这是一段用于识别资金占用风险的任务题，需要判断相关方往来是否异常。"},
            "B": {"expected_capability": "重大资产重组判断"},
        }
        options = build_outcome_view_options(outcomes, task_lookup)

        self.assertEqual(1, default_outcome_view_index(outcomes))
        self.assertEqual("A｜这是一段用于识别资金占用风险的任务题，需要判…｜Model-Failed｜响应超时", options[0]["label"])
        self.assertEqual("B｜重大资产重组判断｜Model-Success｜已完成", options[1]["label"])

    def test_outcome_view_defaults_to_first_failure_when_no_success(self):
        outcomes = [
            er.RunOutcome(
                case_id="A",
                task_type="analysis",
                provider="siliconflow",
                model_id="Model-Failed",
                run_status="failed",
                success=False,
            )
        ]

        self.assertEqual(0, default_outcome_view_index(outcomes))

    def test_model_short_name_uses_last_path_segment(self):
        self.assertEqual("LongCat-2.0", _model_short_name("meituan-longcat/LongCat-2.0"))
        self.assertEqual("DeepSeek-V4-Pro", _model_short_name("deepseek-ai/DeepSeek-V4-Pro"))
        self.assertEqual("plain-model", _model_short_name("plain-model"))

    def test_answer_markdown_headings_render_as_detail_panel_subtitles(self):
        self.assertTrue(hasattr(ui_components, "markdown_detail_html"))

        text = "# 一级\n## 二级\n### 三级\n- 列表\n```python\n# keep\n```"
        html = ui_components.markdown_detail_html(text)

        self.assertIn('class="markdown-detail-heading"', html)
        self.assertIn("一级", html)
        self.assertIn("二级", html)
        self.assertIn("三级", html)
        self.assertIn("<li>列表</li>", html)
        self.assertIn("# keep", html)
        self.assertNotIn("<h1", html)
        self.assertNotIn("<h2", html)
        self.assertNotIn("#### 一级", html)

        table_html = ui_components.markdown_detail_html(
            "| 维度 | 得分 |\n| --- | ---: |\n| **准确性** | `18/20` |"
        )
        self.assertIn('class="markdown-detail-table"', table_html)
        self.assertIn("<strong>准确性</strong>", table_html)
        self.assertIn('class="markdown-detail-inline-code"', table_html)

    def test_answer_markdown_bold_only_lines_render_as_detail_panel_subtitles(self):
        html = ui_components.markdown_detail_html("**复核提示**\n\n需人工确认评分依据。")

        self.assertIn('<div class="markdown-detail-heading">复核提示</div>', html)
        self.assertIn("<p>需人工确认评分依据。</p>", html)

    def test_answer_markdown_section_numbers_render_as_subtitles(self):
        html = ui_components.markdown_detail_html(
            "1. 结论\n\n"
            "模型回答正文。\n\n"
            "2. 主要依据\n\n"
            "结合题目材料判断。\n\n"
            "3. 风险与核查边界\n\n"
            "仍需核查底稿。"
        )

        self.assertEqual(3, html.count('class="markdown-detail-heading"'))
        self.assertIn("1. 结论", html)
        self.assertIn("2. 主要依据", html)
        self.assertIn("3. 风险与核查边界", html)
        self.assertNotIn("<ol", html)

    def test_answer_markdown_chinese_section_numbers_render_as_subtitles(self):
        html = ui_components.markdown_detail_html("一、结论\n\n正文\n\n二、主要依据\n\n正文")

        self.assertEqual(2, html.count('class="markdown-detail-heading"'))
        self.assertIn("一、结论", html)
        self.assertIn("二、主要依据", html)
        self.assertNotIn("<ol", html)

    def test_answer_markdown_parenthesized_section_numbers_render_as_subtitles(self):
        html = ui_components.markdown_detail_html("（一）结论\n\n正文\n\n（二）主要依据\n\n正文")

        self.assertEqual(2, html.count('class="markdown-detail-heading"'))
        self.assertIn("（一）结论", html)
        self.assertIn("（二）主要依据", html)
        self.assertNotIn("<ol", html)

    def test_answer_markdown_arabic_parenthesized_sections_render_as_subtitles(self):
        html = ui_components.markdown_detail_html("1）结论\n\n正文\n\n2) 主要依据\n\n正文")

        self.assertEqual(2, html.count('class="markdown-detail-heading"'))
        self.assertIn("1）结论", html)
        self.assertIn("2) 主要依据", html)
        self.assertNotIn("<ol", html)

    def test_answer_markdown_keeps_true_ordered_lists(self):
        html = ui_components.markdown_detail_html("1. 核查交易协议\n2. 核查审计报告\n3. 核查评估报告")

        self.assertIn('<ol class="markdown-detail-list">', html)
        self.assertIn("<li>核查交易协议</li>", html)
        self.assertIn("<li>核查审计报告</li>", html)
        self.assertIn("<li>核查评估报告</li>", html)
        self.assertNotIn('class="markdown-detail-heading"', html)

    def test_answer_markdown_preserves_ordered_list_start_number(self):
        html = ui_components.markdown_detail_html("2. 第二项\n3. 第三项")

        self.assertIn('<ol class="markdown-detail-list" start="2">', html)
        self.assertIn("<li>第二项</li>", html)
        self.assertIn("<li>第三项</li>", html)
        self.assertNotIn('class="markdown-detail-heading"', html)

    def test_answer_markdown_keeps_numbered_lines_inside_code_blocks(self):
        html = ui_components.markdown_detail_html("```text\n1. code\n2. code\n```")

        self.assertIn('<pre class="markdown-detail-code"><code>1. code\n2. code</code></pre>', html)
        self.assertNotIn("<ol", html)
        self.assertNotIn('class="markdown-detail-heading"', html)


class SampleSelectionTests(unittest.TestCase):
    def test_sample_options_use_unified_readiness_and_compact_labels(self):
        tasks = [
            {
                "case_id": "A",
                "status": ds.ACTIVE_STATUS,
                "question": "这是一段较长的任务题干" * 8,
                "context": "背景",
                "scenario": "财务尽调",
                "task_type": "risk_identification",
            },
            {
                "case_id": "B",
                "status": ds.DRAFT_STATUS,
                "question": "题干",
                "context": "背景",
                "scenario": "法律尽调",
                "task_type": "analysis",
            },
        ]
        gold_map = {
            "A": {
                "core_conclusion": "结论",
                "must_have_points": ["覆盖点"],
                "unacceptable_errors": ["错误"],
            },
            "B": {
                "core_conclusion": "结论",
                "must_have_points": ["覆盖点"],
                "unacceptable_errors": ["错误"],
            },
        }
        dimensions = [
            {
                "field": "accuracy_score",
                "name": "准确性",
                "full_mark": 30,
                "full_mark_standard": "回答完整准确覆盖标准。",
                "deduction_rules": "缺少关键判断或依据时扣分。",
            }
        ]

        options = build_sample_options(tasks, gold_map, dimensions)

        self.assertEqual(["A"], [item["case_id"] for item in options])
        self.assertIn("A", options[0]["label"])
        self.assertIn("财务尽调", options[0]["label"])
        self.assertLessEqual(len(options[0]["label"]), 90)
        self.assertNotIn("Gold", options[0]["label"])
        self.assertNotIn("Rub" + "ric", options[0]["label"])

    def test_sample_dialog_filters_use_search_scene_and_difficulty(self):
        sample_options = [
            {
                "case_id": "A",
                "title": "收入确认风险",
                "scenario": "财务尽调",
                "difficulty": "中等",
                "task": {"question": "识别收入确认问题", "context": "合同背景"},
            },
            {
                "case_id": "B",
                "title": "诉讼风险",
                "scenario": "法律审核",
                "difficulty": "困难",
                "task": {"question": "核查重大诉讼", "context": "法律背景"},
            },
        ]

        self.assertEqual(["A"], [
            item["case_id"]
            for item in filter_sample_selection_options(sample_options, "合同", "全部", "全部")
        ])
        self.assertEqual(["B"], [
            item["case_id"]
            for item in filter_sample_selection_options(sample_options, "", "法律审核", "困难")
        ])
        self.assertEqual([], filter_sample_selection_options(sample_options, "不存在", "全部", "全部"))

    def test_sample_selection_rows_are_compact_and_mark_selected(self):
        sample_options = [
            {
                "case_id": "A",
                "title": "收入确认风险",
                "scenario": "财务尽调",
                "difficulty": "中等",
                "task": {"question": "不应展示完整题干"},
            },
            {
                "case_id": "B",
                "title": "诉讼风险",
                "scenario": "法律审核",
                "difficulty": "困难",
                "task": {"question": "不应展示完整题干"},
            },
        ]

        rows = build_sample_selection_rows(sample_options, ["B"])

        self.assertEqual(["选择", "样本编号", "任务标题", "场景", "难度", "测试状态"], list(rows[0].keys()))
        self.assertFalse(rows[0]["选择"])
        self.assertTrue(rows[1]["选择"])
        self.assertEqual("可测试", rows[0]["测试状态"])
        self.assertNotIn("不应展示完整题干", str(rows))

    def test_sample_checkbox_key_is_stable_per_case(self):
        self.assertEqual("test_run_case_checkbox_FD-001", sample_checkbox_key("FD-001"))

    def test_sample_checkbox_selection_keeps_hidden_selected_and_updates_visible(self):
        filtered_options = [{"case_id": "A"}, {"case_id": "B"}]
        checkbox_values = {"A": False, "B": True}

        selected = merge_sample_checkbox_selection(
            ["A", "C"],
            filtered_options,
            checkbox_values,
            {"A", "B", "C"},
        )

        self.assertEqual(["C", "B"], selected)

    def test_sample_checkbox_selection_preserves_hidden_when_filter_changes(self):
        filtered_options = [{"case_id": "A"}, {"case_id": "B"}]
        checkbox_values = {"A": True, "B": False}

        selected = merge_sample_checkbox_selection(
            ["C"],
            filtered_options,
            checkbox_values,
            {"A", "B", "C"},
        )

        self.assertEqual(["C", "A"], selected)

    def test_sample_dialog_cleans_checkbox_state_without_touching_confirmed_selection(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        clear_source = source[
            source.index("def _clear_dialog_state"):
            source.index("@st.dialog(\"发送给被测模型的提示词\"")
        ]

        self.assertIn("test_run_cases_dialog_selected", clear_source)
        self.assertIn("SAMPLE_CHECKBOX_KEY_PREFIX", clear_source)
        self.assertNotIn("test_run_selected_cases", clear_source)

    def test_sample_dialog_opens_from_confirmed_selection_and_clears_checkbox_keys(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        open_source = source[
            source.index("def _open_sample_dialog"):
            source.index("def _open_model_dialog")
        ]

        self.assertIn('st.session_state.get("test_run_selected_cases"', open_source)
        self.assertIn('st.session_state["test_run_cases_dialog_selected"] = current', open_source)
        self.assertIn("_clear_session_state_prefix(SAMPLE_CHECKBOX_KEY_PREFIX)", open_source)

    def test_sample_dialog_confirm_is_only_path_that_writes_confirmed_selection(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        dialog_source = source[
            source.index("def _render_sample_selection_dialog"):
            source.index("def _render_sample_checkbox_table")
        ]
        cancel_source = dialog_source[dialog_source.index('key="test_run_sample_dialog_cancel"'):]

        self.assertIn('st.session_state["test_run_selected_cases"] = selected_cases', dialog_source)
        self.assertNotIn('st.session_state["test_run_selected_cases"]', cancel_source)

    def test_sample_checkbox_table_keeps_fixed_scrollable_table_shape(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        table_source = source[
            source.index("def _render_sample_checkbox_table"):
            source.index("@st.dialog(\"选择模型\"")
        ]

        self.assertIn("SAMPLE_TABLE_COLUMN_WIDTHS", table_source)
        self.assertIn("SAMPLE_TABLE_HEADERS", table_source)
        self.assertIn("st.container(height=SAMPLE_TABLE_HEIGHT, border=True)", table_source)
        self.assertIn('st.markdown(f"**{header}**")', table_source)
        self.assertIn("st.checkbox(", table_source)
        self.assertNotIn("st.data_editor", table_source)


class RunPlanTests(unittest.TestCase):
    def test_run_plan_summary_disables_without_samples_or_models(self):
        self.assertFalse(build_run_plan_summary([], [{"case_id": "A"}])["can_run"])
        self.assertFalse(build_run_plan_summary(["m1"], [])["can_run"])

    def test_run_plan_summary_counts_expected_responses(self):
        summary = build_run_plan_summary(["m1", "m2"], [{"case_id": "A"}, {"case_id": "B"}])

        self.assertEqual(2, summary["model_count"])
        self.assertEqual(2, summary["sample_count"])
        self.assertEqual(4, summary["planned_responses"])
        self.assertTrue(summary["can_run"])

    def test_run_queue_items_dedupe_models_and_preserve_order(self):
        queue = build_run_queue_items(
            ["m1", "m1", "m2"],
            [{"case_id": "A"}, {"case_id": "B"}],
        )

        self.assertEqual(
            [("m1", "A"), ("m1", "B"), ("m2", "A"), ("m2", "B")],
            [(item["model_id"], item["case_id"]) for item in queue],
        )

    def test_remaining_queue_items_use_completed_model_case_pairs(self):
        queue = build_run_queue_items(["m1", "m2"], [{"case_id": "A"}, {"case_id": "B"}])
        outcomes = [
            er.RunOutcome("A", "", "mock", "m1", "mock", True, answer_text="ok"),
            er.RunOutcome("B", "", "mock", "m2", "failed", False, error_code="timeout"),
        ]

        remaining = build_remaining_queue_items(queue, outcomes)

        self.assertEqual(
            [("m1", "B"), ("m2", "A")],
            [(item["model_id"], item["case_id"]) for item in remaining],
        )

    def test_incomplete_response_is_retryable_failed_queue_item(self):
        queue = build_run_queue_items(["m1"], [{"case_id": "A"}])
        outcomes = [
            er.RunOutcome(
                "A",
                "",
                "siliconflow",
                "m1",
                "failed",
                False,
                answer_text="初步结论：存在风险。具体测算",
                error_code="incomplete_response",
                finish_reason="length",
                incomplete_reason="模型回答因长度限制中断。",
            )
        ]

        failed_items = build_failed_run_queue_items(queue, outcomes)

        self.assertEqual([("m1", "A")], [(item["model_id"], item["case_id"]) for item in failed_items])

    def test_timeout_is_retryable_failed_queue_item_without_success_pairs(self):
        queue = build_run_queue_items(["m1", "m2"], [{"case_id": "A"}, {"case_id": "B"}])
        outcomes = [
            er.RunOutcome("A", "", "siliconflow", "m1", "success", True, answer_text="ok"),
            er.RunOutcome("B", "", "siliconflow", "m2", "failed", False, error_code="timeout"),
        ]

        failed_items = build_failed_run_queue_items(queue, outcomes)

        self.assertEqual([("m2", "B")], [(item["model_id"], item["case_id"]) for item in failed_items])


class ScoreDraftTests(unittest.TestCase):
    def test_score_queue_and_plan_skip_failed_model_answers(self):
        compare = er.CompareRunResult(
            run_id="R1",
            provider="mock",
            model_ids=("m1", "m2"),
            mode="mock",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                er.RunOutcome("A", "analysis", "mock", "m1", "success", True, answer_text="回答"),
                er.RunOutcome("A", "analysis", "mock", "m2", "failed", False, error_message="失败"),
            ),
        )

        queue = build_score_queue_items(compare)
        plan = build_score_plan_summary(compare)

        self.assertEqual([("A", "m1")], [(item.case_id, item.model_id) for item in queue])
        self.assertEqual(2, plan["total"])
        self.assertEqual(1, plan["scoreable"])
        self.assertEqual(1, plan["skipped"])
        self.assertTrue(plan["can_score"])

    def test_incomplete_response_does_not_enter_score_queue(self):
        compare = er.CompareRunResult(
            run_id="R1",
            provider="siliconflow",
            model_ids=("m1",),
            mode="live",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                er.RunOutcome(
                    "CM-001",
                    "analysis",
                    "siliconflow",
                    "m1",
                    "failed",
                    False,
                    answer_text="初步结论：可能构成重大资产重组。具体测算",
                    error_code="incomplete_response",
                    finish_reason="length",
                    incomplete_reason="模型回答因长度限制中断。",
                ),
            ),
        )

        self.assertEqual([], build_score_queue_items(compare))
        self.assertEqual(0, build_score_plan_summary(compare)["scoreable"])

    def test_score_view_options_prefer_first_success(self):
        outcomes = [
            sc.ScoreOutcome(
                case_id="A",
                task_type="analysis",
                eval_model="vendor/model-failed",
                judge_provider="judge",
                judge_model="judge/model",
                judge_status="failed",
                scores={},
                total_score=None,
                error_code="judge_parse_error",
            ),
            sc.ScoreOutcome(
                case_id="B",
                task_type="analysis",
                eval_model="vendor/model-ok",
                judge_provider="judge",
                judge_model="judge/model",
                judge_status="success",
                scores={"accuracy_score": 20},
                total_score=78,
                review_status="pending",
            ),
        ]

        options = build_score_view_options(outcomes)

        self.assertEqual(1, default_score_view_index(outcomes))
        self.assertEqual("A｜model-failed｜未评分｜失败", options[0]["label"])
        self.assertEqual("B｜model-ok｜78分｜待确认", options[1]["label"])

    def test_score_summary_rows_use_dynamic_dimensions_and_pending_review(self):
        dimensions = [
            {"field": "accuracy_score", "name": "准确性", "full_mark": 30},
            {"field": "coverage_score", "name": "覆盖度", "full_mark": 20},
        ]
        result = sc.ScoreResult(
            score_run_id="S1",
            run_id="R1",
            judge_provider="mock",
            judge_model="judge",
            mode="mock",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="A",
                    task_type="analysis",
                    eval_model="m1",
                    judge_provider="mock",
                    judge_model="judge",
                    judge_status="success",
                    scores={"accuracy_score": 20, "coverage_score": 10},
                    total_score=30,
                ),
            ),
        )

        rows = build_score_summary_rows(result, dimensions)

        self.assertEqual("m1", rows[0]["模型"])
        self.assertEqual("A", rows[0]["样本"])
        self.assertEqual("20", rows[0]["准确性"])
        self.assertEqual("10", rows[0]["覆盖度"])
        self.assertEqual("30", rows[0]["总分"])
        self.assertEqual("待确认", rows[0]["裁判状态"])

    def test_score_result_index_rows_only_keep_summary_fields(self):
        result = sc.ScoreResult(
            score_run_id="S1",
            run_id="R1",
            judge_provider="siliconflow",
            judge_model="judge/model",
            mode="live",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="CM-001",
                    task_type="analysis",
                    eval_model="vendor/model-a",
                    judge_provider="siliconflow",
                    judge_model="judge/model",
                    judge_status="success",
                    scores={"accuracy_score": 22},
                    total_score=85,
                    review_status="pending",
                    review_note="复核提示不应出现在索引表",
                ),
            ),
        )

        rows = build_score_result_index_rows(result, [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}])

        self.assertEqual([{"模型": "model-a", "样本": "CM-001", "总分": "85 / 30", "状态": "待确认"}], rows)
        self.assertNotIn("模型ID", rows[0])
        self.assertNotIn("复核提示", rows[0])
        self.assertNotIn("评分依据", rows[0])

    def test_success_score_draft_detail_uses_markdown_panel_content(self):
        dimensions = [
            {"field": "accuracy_score", "name": "专业准确性", "full_mark": 30},
            {"field": "coverage_score", "name": "风险覆盖", "full_mark": 20},
        ]
        outcome = sc.ScoreOutcome(
            case_id="CM-001",
            task_type="analysis",
            eval_model="Pro/moonshotai/Kimi-K2.6",
            judge_provider="siliconflow",
            judge_model="deepseek-ai/DeepSeek-V4-Pro",
            judge_status="success",
            scores={"accuracy_score": 22, "coverage_score": 16},
            total_score=38,
            rationale={"accuracy_score": "判断标准准确。", "coverage_score": "覆盖主要风险。"},
            review_note="需人工确认评分依据。",
            review_status="pending",
        )

        panel = build_score_draft_detail_panel(outcome, dimensions)

        self.assertEqual("CM-001｜Kimi-K2.6｜38 / 50｜待确认", panel["title"])
        self.assertIn("裁判模型：DeepSeek-V4-Pro", panel["meta"])
        self.assertIn("模型 ID：Pro/moonshotai/Kimi-K2.6", panel["meta"])
        self.assertIn("**复核提示**", panel["markdown"])
        self.assertIn("需人工确认评分依据。", panel["markdown"])
        self.assertIn("**维度评分**", panel["markdown"])
        self.assertIn("**专业准确性：22 / 30**", panel["markdown"])
        self.assertIn("评分依据：判断标准准确。", panel["markdown"])

    def test_success_score_draft_detail_uses_fallback_review_note_and_rationale(self):
        outcome = sc.ScoreOutcome(
            case_id="CM-002",
            task_type="analysis",
            eval_model="vendor/model-a",
            judge_provider="siliconflow",
            judge_model="judge/model",
            judge_status="success",
            scores={"accuracy_score": 12},
            total_score=12,
            rationale={},
            review_note="",
        )

        panel = build_score_draft_detail_panel(outcome, [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}])

        self.assertIn("未返回明确复核提示。", panel["markdown"])
        self.assertIn("评分依据：未返回明确依据。", panel["markdown"])

    def test_failed_score_draft_detail_shows_failure_without_dimension_table(self):
        outcome = sc.ScoreOutcome(
            case_id="CM-003",
            task_type="analysis",
            eval_model="vendor/model-a",
            judge_provider="siliconflow",
            judge_model="judge/model",
            judge_status="failed",
            scores={},
            total_score=None,
            error_code="timeout",
            error_message="请求超时，请稍后重试或调大 SILICONFLOW_TIMEOUT_SECONDS。",
        )

        panel = build_score_draft_detail_panel(outcome, [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}])

        self.assertEqual("CM-003｜model-a｜未评分｜失败", panel["title"])
        self.assertIn("**评分失败**", panel["markdown"])
        self.assertIn("模型回答已生成，裁判评分失败。", panel["markdown"])
        self.assertIn("错误码：`timeout`", panel["markdown"])
        self.assertIn("错误信息：请求超时", panel["markdown"])
        self.assertIn("失败评分不会进入评分确认，也不会纳入正式结论。", panel["markdown"])
        self.assertNotIn("**维度评分**", panel["markdown"])

    def test_mock_score_draft_detail_is_marked_as_mock(self):
        outcome = sc.ScoreOutcome(
            case_id="CM-004",
            task_type="analysis",
            eval_model="vendor/model-a",
            judge_provider="mock",
            judge_model="judge/model",
            judge_status="mock",
            scores={},
            total_score=None,
            review_note="",
        )

        panel = build_score_draft_detail_panel(outcome, [])

        self.assertIn("**模拟评分**", panel["markdown"])
        self.assertIn("未配置真实模型服务，未产生真实评分。", panel["markdown"])
        self.assertIn("该结果仅用于链路调试，不进入正式结论。", panel["markdown"])

    def test_confirm_review_entry_only_shows_for_pending_success_scores(self):
        result = sc.ScoreResult(
            score_run_id="S1",
            run_id="R1",
            judge_provider="siliconflow",
            judge_model="judge/model",
            mode="live",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="CM-001",
                    task_type="analysis",
                    eval_model="vendor/model-a",
                    judge_provider="siliconflow",
                    judge_model="judge/model",
                    judge_status="success",
                    total_score=80,
                    review_status="pending",
                ),
            ),
        )
        self.assertTrue(has_confirmable_score_drafts(result))

        confirmed = sc.ScoreResult(
            score_run_id="S2",
            run_id="R1",
            judge_provider="siliconflow",
            judge_model="judge/model",
            mode="live",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="CM-001",
                    task_type="analysis",
                    eval_model="vendor/model-a",
                    judge_provider="siliconflow",
                    judge_model="judge/model",
                    judge_status="success",
                    total_score=80,
                    review_status="confirmed",
                ),
            ),
        )
        failed = sc.ScoreResult(
            score_run_id="S3",
            run_id="R1",
            judge_provider="siliconflow",
            judge_model="judge/model",
            mode="live",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="CM-001",
                    task_type="analysis",
                    eval_model="vendor/model-a",
                    judge_provider="siliconflow",
                    judge_model="judge/model",
                    judge_status="failed",
                    total_score=None,
                    review_status="pending",
                ),
            ),
        )
        mock = sc.ScoreResult(
            score_run_id="S4",
            run_id="R1",
            judge_provider="mock",
            judge_model="judge/model",
            mode="mock",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="CM-001",
                    task_type="analysis",
                    eval_model="vendor/model-a",
                    judge_provider="mock",
                    judge_model="judge/model",
                    judge_status="mock",
                    total_score=None,
                    review_status="pending",
                ),
            ),
        )
        self.assertFalse(has_confirmable_score_drafts(confirmed))
        self.assertFalse(has_confirmable_score_drafts(failed))
        self.assertFalse(has_confirmable_score_drafts(mock))

    def test_failed_score_retry_items_only_retry_failed_scores_with_successful_answers(self):
        import src.ui.test_run as tr

        compare = er.CompareRunResult(
            run_id="R1",
            provider="siliconflow",
            model_ids=("m1", "m2", "m3"),
            mode="live",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                er.RunOutcome("A", "analysis", "siliconflow", "m1", "success", True, answer_text="回答 A"),
                er.RunOutcome("A", "analysis", "siliconflow", "m2", "success", True, answer_text="回答 B"),
                er.RunOutcome("A", "analysis", "siliconflow", "m3", "failed", False, error_code="timeout"),
            ),
        )
        score_result = sc.ScoreResult(
            score_run_id="S1",
            run_id="R1",
            judge_provider="siliconflow",
            judge_model="judge",
            mode="live",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                sc.ScoreOutcome(
                    case_id="A",
                    task_type="analysis",
                    eval_model="m1",
                    judge_provider="siliconflow",
                    judge_model="judge",
                    judge_status="failed",
                    scores={},
                    total_score=None,
                    error_code="timeout",
                ),
                sc.ScoreOutcome(
                    case_id="A",
                    task_type="analysis",
                    eval_model="m2",
                    judge_provider="siliconflow",
                    judge_model="judge",
                    judge_status="success",
                    scores={"accuracy_score": 20},
                    total_score=80,
                ),
                sc.ScoreOutcome(
                    case_id="A",
                    task_type="analysis",
                    eval_model="m3",
                    judge_provider="siliconflow",
                    judge_model="judge",
                    judge_status="failed",
                    scores={},
                    total_score=None,
                    error_code="timeout",
                ),
            ),
        )

        self.assertTrue(hasattr(tr, "build_failed_score_retry_items"))
        retry_items = tr.build_failed_score_retry_items(score_result, compare)

        self.assertEqual([("A", "m1", "回答 A")], [
            (item.case_id, item.model_id, item.answer_text) for item in retry_items
        ])


class ScoringInputTests(unittest.TestCase):
    def test_score_compare_only_scores_successful_answers(self):
        compare = er.CompareRunResult(
            run_id="R1",
            provider="mock",
            model_ids=("m1", "m2"),
            mode="mock",
            created_at="2026-07-05T12:00:00",
            outcomes=(
                er.RunOutcome("A", "analysis", "mock", "m1", "mock", True, answer_text="回答"),
                er.RunOutcome("A", "analysis", "mock", "m2", "failed", False, error_message="失败"),
            ),
        )
        dimensions = [{"field": "accuracy_score", "name": "准确性", "full_mark": 30}]

        result = sc.score_compare(
            provider=_MockJudgeProvider(),
            compare_result=compare,
            gold_map={"A": {"core_conclusion": "结论"}},
            tasks_by_case={"A": {"case_id": "A", "question": "题干"}},
            dimensions=dimensions,
        )

        self.assertEqual(1, len(result.outcomes))
        self.assertEqual("m1", result.outcomes[0].eval_model)


class _MockJudgeProvider:
    name = "mock"

    def generate_response(self, *args, **kwargs):  # pragma: no cover - mock provider scoring does not call this.
        raise AssertionError("mock scorer should not call provider.generate_response")


if __name__ == "__main__":
    unittest.main()
