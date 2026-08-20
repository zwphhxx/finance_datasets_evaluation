from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

import pandas as pd

from app.services import conclusions as cc
from src.ui import samples
from src.ui.components import PROJECT_DISPLAY_NAME as COMPONENT_PROJECT_NAME
from src.ui.navigation import OPERATION_NAV_ITEM, PAGES, PRIMARY_NAV_ITEMS
from src.ui.navigation import PROJECT_DISPLAY_NAME as NAV_PROJECT_NAME
from src.ui.page_config import PAGE_CONFIG_BY_KEY, PAGE_CONFIGS

PROJECT_NAME = "财务/法律/投行场景大模型对比评测"
MAIN_PAGE_KEYS = ["case_study", "samples", "test_run", "conclusions"]
PAGE_CONFIG_KEYS = ["conclusions", "case_study", "samples", "test_run"]
MAIN_NAV_PAGE_KEYS = ["conclusions", "case_study", "samples"]
MAIN_NAV_LABELS = ["评测结论", "项目说明", "样本库"]
VISIBLE_UI_FILES = [
    Path("src/ui/case_study.py"),
    Path("src/ui/samples.py"),
    Path("src/ui/test_run.py"),
    Path("src/ui/conclusions.py"),
    Path("src/ui/navigation.py"),
    Path("src/ui/page_config.py"),
    Path("src/ui/components.py"),
    Path("src/ui/evaluation_config.py"),
    Path("src/ui/evaluation_results.py"),
]

_STREAMLIT_VISIBLE_METHODS = {
    "button",
    "caption",
    "checkbox",
    "dialog",
    "markdown",
    "write",
    "info",
    "warning",
    "error",
    "success",
    "toast",
    "download_button",
    "file_uploader",
    "form_submit_button",
    "text_input",
    "text_area",
    "radio",
    "selectbox",
    "slider",
    "spinner",
    "multiselect",
    "tabs",
    "popover",
    "expander",
    "header",
    "subheader",
    "title",
}
_CUSTOM_VISIBLE_FUNCTIONS = {
    "render_empty_state",
    "render_persistence_status",
    "render_inline_status",
    "render_page_heading",
    "render_numbered_section",
    "render_executive_takeaway",
    "render_report_masthead",
    "render_scope_ledger",
}
_KNOWN_CUSTOM_IMPORT_PATHS = {
    f"src.ui.components.{name}"
    for name in _CUSTOM_VISIBLE_FUNCTIONS
} | {
    f"src.ui.report_components.{name}"
    for name in _CUSTOM_VISIBLE_FUNCTIONS
}
_STREAMLIT_CONTAINER_FACTORIES = {
    "columns",
    "container",
    "dialog",
    "empty",
    "expander",
    "form",
    "popover",
    "status",
    "tabs",
}

_VISIBLE_POSITIONAL_LIMITS: dict[str, int | None] = {
    "write": None,
    "radio": 2,
    "selectbox": 2,
    "multiselect": 2,
    "render_page_heading": 2,
    "render_numbered_section": 3,
    "render_report_masthead": 2,
}
_VISIBLE_TEXT_KEYWORDS = {
    "body",
    "caption",
    "description",
    "help",
    "items",
    "label",
    "message",
    "options",
    "placeholder",
    "tabs",
    "text",
    "title",
    "value",
}


def _rendered_ui_text(path: Path) -> str:
    """Collect literal text passed to user-visible Streamlit/UI calls."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collector = _VisibleTextCollector()
    collector.visit(tree)
    return "\n".join(collector.fragments)


class _StaticScope:
    def __init__(self) -> None:
        self.bindings: dict[str, list[tuple[int, ast.AST | None]]] = {}
        self.streamlit_aliases: dict[str, list[int]] = {}
        self.imports: dict[str, str] = {}


def _attribute_parts(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return list(reversed(parts))
    return []


def _target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [name for element in node.elts for name in _target_names(element)]
    return []


def _is_static_text_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.FormattedValue):
        return _is_static_text_expression(node.value)
    if isinstance(node, ast.JoinedStr):
        return all(_is_static_text_expression(value) for value in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_static_text_expression(node.left) and _is_static_text_expression(node.right)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_static_text_expression(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_static_text_expression(value) for value in node.values)
    return False


class _ScopeBindingCollector(ast.NodeVisitor):
    def __init__(self, scope: _StaticScope, parent_scopes: list[_StaticScope]) -> None:
        self.scope = scope
        self.parent_scopes = parent_scopes

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            local_name = item.asname or item.name.split(".", 1)[0]
            self.scope.imports[local_name] = item.name if item.asname else local_name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = str(node.module or "")
        for item in node.names:
            local_name = item.asname or item.name
            self.scope.imports[local_name] = f"{module}.{item.name}".strip(".")

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_assignment(target, node.value)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record_assignment(node.target, node.value)
            self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_assignment(node.target, node.value)
        self.visit(node.value)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None and self._factory_method(item.context_expr):
                for name in _target_names(item.optional_vars):
                    self._record_binding(name, item.context_expr.lineno, None)
                    self._record_streamlit_alias(name, item.context_expr.lineno)
            self.visit(item.context_expr)
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def _record_assignment(self, target: ast.AST, value: ast.AST) -> None:
        names = _target_names(target)
        binding = value if _is_static_text_expression(value) else None
        for name in names:
            self._record_binding(name, value.lineno, binding)

        factory = self._factory_method(value)
        if factory in {"columns", "tabs"} and not isinstance(target, (ast.List, ast.Tuple)):
            return
        if factory:
            for name in names:
                self._record_streamlit_alias(name, value.lineno)

    def _factory_method(self, node: ast.AST) -> str:
        current = node
        while isinstance(current, ast.Subscript):
            current = current.value
        if not isinstance(current, ast.Call):
            return ""
        parts = _attribute_parts(current.func)
        if len(parts) < 2 or parts[-1] not in _STREAMLIT_CONTAINER_FACTORIES:
            return ""
        if parts[0] == "st" or _streamlit_alias_available(
            [*self.parent_scopes, self.scope],
            parts[0],
            current.lineno,
        ):
            return parts[-1]
        return ""

    def _record_binding(self, name: str, lineno: int, value: ast.AST | None) -> None:
        self.scope.bindings.setdefault(name, []).append((lineno, value))

    def _record_streamlit_alias(self, name: str, lineno: int) -> None:
        self.scope.streamlit_aliases.setdefault(name, []).append(lineno)


class _VisibleTextCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.fragments: list[str] = []
        self.scopes: list[_StaticScope] = []

    def visit_Module(self, node: ast.Module) -> None:
        self._visit_scope(node.body)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_scope(
            node.body,
            parameters=_parameter_names(node.args),
            start_lineno=node.lineno,
        )

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_scope(
            node.body,
            parameters=_parameter_names(node.args),
            start_lineno=node.lineno,
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_scope(node.body, start_lineno=node.lineno)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._visible_call_name(node.func)
        if call_name:
            limit = _VISIBLE_POSITIONAL_LIMITS.get(call_name, 1)
            positional = node.args if limit is None else node.args[:limit]
            visible_keywords = [
                item.value
                for item in node.keywords
                if item.arg in _VISIBLE_TEXT_KEYWORDS
            ]
            for argument in [*positional, *visible_keywords]:
                self.fragments.extend(
                    self._static_text_values(argument, node.lineno, set())
                )
        self.generic_visit(node)

    def _visit_scope(
        self,
        body: list[ast.stmt],
        parameters: list[str] | None = None,
        start_lineno: int = 0,
    ) -> None:
        scope = _StaticScope()
        for parameter in parameters or []:
            scope.bindings.setdefault(parameter, []).append((start_lineno, None))
        binding_collector = _ScopeBindingCollector(scope, list(self.scopes))
        for statement in body:
            binding_collector.visit(statement)
        self.scopes.append(scope)
        for statement in body:
            self.visit(statement)
        self.scopes.pop()

    def _visible_call_name(self, func: ast.AST) -> str:
        if isinstance(func, ast.Name):
            imported = self._lookup_import(func.id)
            if imported in _KNOWN_CUSTOM_IMPORT_PATHS:
                return imported.rsplit(".", 1)[-1]
            return func.id if func.id in _CUSTOM_VISIBLE_FUNCTIONS else ""

        parts = _attribute_parts(func)
        if len(parts) < 2:
            return ""
        method = parts[-1]
        if method in _STREAMLIT_VISIBLE_METHODS and (
            parts[0] == "st"
            or self._is_streamlit_alias(parts[0], getattr(func, "lineno", 0))
        ):
            return method
        imported_root = self._lookup_import(parts[0])
        if imported_root:
            qualified = ".".join([imported_root, *parts[1:]])
            if qualified in _KNOWN_CUSTOM_IMPORT_PATHS:
                return method
        return ""

    def _static_text_values(
        self,
        node: ast.AST,
        at_lineno: int,
        seen: set[str],
    ) -> list[str]:
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else []
        if isinstance(node, ast.Name):
            if node.id in seen:
                return []
            found, binding_lineno, binding = self._lookup_binding(node.id, at_lineno)
            return (
                []
                if not found or binding is None
                else self._static_text_values(
                    binding,
                    binding_lineno,
                    seen | {node.id},
                )
            )
        if isinstance(node, ast.FormattedValue):
            values = self._static_text_values(node.value, at_lineno, seen)
            return values or [""]
        if isinstance(node, ast.JoinedStr):
            return self._join_static_parts(node.values, at_lineno, seen)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self._join_static_parts([node.left, node.right], at_lineno, seen)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [
                value
                for element in node.elts
                for value in self._static_text_values(element, at_lineno, seen)
            ]
        if isinstance(node, ast.Dict):
            return [
                text
                for value in node.values
                for text in self._static_text_values(value, at_lineno, seen)
            ]
        return []

    def _join_static_parts(
        self,
        parts: list[ast.AST],
        at_lineno: int,
        seen: set[str],
    ) -> list[str]:
        combined = [""]
        for part in parts:
            values = self._static_text_values(part, at_lineno, seen) or [""]
            combined = [prefix + suffix for prefix in combined for suffix in values]
        return combined

    def _lookup_binding(
        self,
        name: str,
        at_lineno: int,
    ) -> tuple[bool, int, ast.AST | None]:
        for scope in reversed(self.scopes):
            if name in scope.bindings:
                prior = [
                    entry
                    for entry in scope.bindings[name]
                    if entry[0] < at_lineno
                ]
                if prior:
                    lineno, value = max(prior, key=lambda entry: entry[0])
                    return True, lineno, value
                return True, -1, None
        return False, -1, None

    def _lookup_import(self, name: str) -> str:
        for scope in reversed(self.scopes):
            if name in scope.imports:
                return scope.imports[name]
        return ""

    def _is_streamlit_alias(self, name: str, at_lineno: int) -> bool:
        return _streamlit_alias_available(self.scopes, name, at_lineno)


def _streamlit_alias_available(
    scopes: list[_StaticScope],
    name: str,
    at_lineno: int,
) -> bool:
    for scope in reversed(scopes):
        if name not in scope.bindings and name not in scope.streamlit_aliases:
            continue
        prior_bindings = [
            lineno
            for lineno, _value in scope.bindings.get(name, [])
            if lineno < at_lineno
        ]
        prior_aliases = [
            lineno
            for lineno in scope.streamlit_aliases.get(name, [])
            if lineno < at_lineno
        ]
        if not prior_bindings:
            return bool(prior_aliases)
        return bool(prior_aliases) and max(prior_bindings) == max(prior_aliases)
    return False


def _parameter_names(arguments: ast.arguments) -> list[str]:
    return [
        argument.arg
        for argument in [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ]
    ]


def _product_ui_text(paths: list[Path] | tuple[Path, ...] = VISIBLE_UI_FILES) -> str:
    return "\n".join(
        _rendered_ui_text(path) for path in paths if path.name != "case_study.py"
    )


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
            "仅纳入正式评分",
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
            "## 运行与恢复",
            "外部模型服务可能受网络、限流、模型响应时间和输出长度影响",
            "点击一次“开始评测”",
            "模型回答和评分都会增量保存",
            "点击“继续评测”恢复剩余任务",
            "数据库不可用时",
            "不会调用模型服务",
            "开始评测按钮保持禁用",
            "真实模型密钥",
        ]:
            self.assertIn(phrase, text)
        for phrase in [
            "建议分批运行",
            "超过 50 条回答需要确认后再运行",
            "## 运行稳定性与失败恢复",
            "## 演示与恢复",
        ]:
            self.assertNotIn(phrase, text)


class NavigationAndPageConfigGuardrailTests(unittest.TestCase):
    def test_navigation_only_exposes_current_four_pages(self):
        self.assertEqual(MAIN_PAGE_KEYS, list(PAGES.keys()))
        self.assertEqual(list(zip(MAIN_NAV_LABELS, MAIN_NAV_PAGE_KEYS)), PRIMARY_NAV_ITEMS)
        self.assertEqual(("发起评测", "test_run"), OPERATION_NAV_ITEM)

    def test_page_config_only_contains_current_four_pages(self):
        self.assertEqual(PAGE_CONFIG_KEYS, [config.page_key for config in PAGE_CONFIGS])
        self.assertEqual(set(MAIN_PAGE_KEYS), set(PAGE_CONFIG_BY_KEY.keys()))

    def test_visible_project_name_is_current_chinese_name(self):
        self.assertEqual(PROJECT_NAME, COMPONENT_PROJECT_NAME)
        self.assertEqual(PROJECT_NAME, NAV_PROJECT_NAME)


class VisibleTextGuardrailTests(unittest.TestCase):
    def test_product_ui_has_no_demo_mode_or_manual_score_action(self):
        text = _product_ui_text()
        for phrase in ["演示模式", "演示恢复", "生成 AI 评分", "从演示结果文件恢复"]:
            self.assertNotIn(phrase, text)

    def test_visible_ui_has_no_mobile_selection_card_system(self):
        text = Path("src/ui/components.py").read_text(encoding="utf-8") + Path(
            "src/ui/responsive.py"
        ).read_text(encoding="utf-8")
        for selector in [
            "mobile-select-card",
            ".metric-card",
            ".status-badge",
            ".st-key-conclusion_mobile_judgment",
            ".st-key-conclusion_desktop_judgment",
            ".st-key-test_run_stage_scores",
            ".st-key-test_run_score_action",
        ]:
            self.assertNotIn(selector, text)

    def test_ast_guard_recognizes_container_controls_and_visible_keywords_only(self):
        text = _rendered_ui_text(Path("tests/fixtures/ui_visible_text_calls.py"))

        for phrase in [
            "演示模式",
            "生成 AI 评分",
            "演示恢复",
            "可见章节",
            "可见说明",
            "先前禁语应保留",
            "演示弹层",
            "演示加载",
            "演示选择",
            "演示滑杆",
            "演示提交",
        ]:
            self.assertIn(phrase, text)
        self.assertNotIn("从演示结果文件恢复", text)
        self.assertNotIn("假标题不可见", text)
        self.assertNotIn("后置禁语不应出现", text)

    def test_ast_guard_excludes_case_study_fixture(self):
        text = _product_ui_text(
            [Path("tests/fixtures/excluded/case_study.py")]
        )

        self.assertNotIn("从演示结果文件恢复", text)

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
            *sorted(Path("docs").glob("*.md")),
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
            "暂无模型判断",
            "发起评测",
        ]:
            self.assertIn(phrase, text)


class SampleLibraryGuardrailTests(unittest.TestCase):
    def test_sample_table_contract_and_current_sample_actions(self):
        self.assertEqual(
            ["样本编号", "任务标题", "专业场景", "测试状态", "完整度"],
            samples._SAMPLE_TABLE_COLUMNS,
        )

        table_source = inspect.getsource(samples.build_sample_table_rows)
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
        self.assertIn("def _render_sample_index", source)
        self.assertIn('key=f"samples_index_select_{sample.sample_id}"', source)
        self.assertIn('request_scroll("#fde-current-sample")', source)
        self.assertNotIn('"查看样本"', source)
        self.assertNotIn("查看样本详情", source)
        self.assertNotIn("删除样本", source)
        self.assertNotIn('"更多"', source)
