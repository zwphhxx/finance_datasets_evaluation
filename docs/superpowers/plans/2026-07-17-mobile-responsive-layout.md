# Streamlit Mobile Responsive Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改任何项目文案、评分逻辑或持久化流程的前提下，为四个 Streamlit 页面增加已确认的手机和平板响应式布局。

**Architecture:** 新建纯样式模块 `src/ui/responsive.py`，由现有 `src/ui/components.py` 注入全局样式；桌面布局保持不变，`860px`、`760px` 和 `480px` 三档规则分别处理平板、手机和小屏手机。页面状态继续使用现有 Streamlit 组件和 key，只有需要保留横向表格行为的样本选择区增加稳定容器 key；模型回答、评分和 PostgreSQL/Supabase 数据流不改。

**Tech Stack:** Python 3、Streamlit 1.51.0、CSS media queries、unittest/pytest、Ruff、Codex in-app Browser 响应式视口检查。

---

## 文件结构

- Create: `src/ui/responsive.py` — 只维护平板和手机响应式 CSS。
- Create: `tests/test_mobile_responsive_ui.py` — 响应式断点、导航、弹窗、表格、长内容和底部操作区契约测试。
- Modify: `src/ui/components.py` — 注入响应式 CSS，并为 Markdown 表格增加局部横向滚动容器。
- Modify: `src/ui/test_run.py` — 为样本选择表增加稳定容器 key；不修改评测执行逻辑。
- Modify: `tests/test_uiux_audit_fixes.py` — 将“桌面导航不得固定”的旧断言限定到桌面 CSS，允许已确认的手机端吸附导航和底部操作区。
- Modify: `.gitignore` — 忽略临时 `.superpowers/` 线框目录。

`src/ui/samples.py`、`src/ui/conclusions.py` 和 `src/ui/navigation.py` 不需要业务代码改动：它们现有的 `st.columns`、`st.dataframe`、组件 key 和 `.top-nav-brand` 已足以被集中响应式规则安全适配。避免为移动端复制页面或增加第二套会话状态。

### Task 1: 建立响应式契约测试

**Files:**
- Create: `tests/test_mobile_responsive_ui.py`
- Modify: `tests/test_uiux_audit_fixes.py:82-103`
- Modify: `.gitignore`

- [ ] **Step 1: 忽略临时线框目录**

在 `.gitignore` 末尾加入：

```gitignore
.superpowers/
```

运行：

```bash
git status --short
```

预期：`.superpowers/` 不再出现；用户已有的 `.claude/` 仍保持未跟踪且不加入提交。

- [ ] **Step 2: 写入失败的响应式契约测试**

创建 `tests/test_mobile_responsive_ui.py`：

```python
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESPONSIVE_SOURCE = PROJECT_ROOT / "src/ui/responsive.py"
COMPONENTS_SOURCE = PROJECT_ROOT / "src/ui/components.py"
TEST_RUN_SOURCE = PROJECT_ROOT / "src/ui/test_run.py"


class MobileResponsiveUITests(unittest.TestCase):
    def _responsive_css(self) -> str:
        self.assertTrue(RESPONSIVE_SOURCE.exists(), "responsive CSS module must exist")
        return RESPONSIVE_SOURCE.read_text(encoding="utf-8")

    def test_breakpoints_safe_area_and_touch_targets_are_declared(self):
        css = self._responsive_css()
        self.assertIn("@media (min-width: 761px) and (max-width: 860px)", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn("@media (max-width: 480px)", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("min-height: 44px", css)

    def test_mobile_navigation_is_sticky_and_horizontally_scrollable(self):
        css = self._responsive_css()
        self.assertIn('[data-testid="stHorizontalBlock"]:has(.top-nav-brand)', css)
        self.assertIn("position: sticky", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("grid-template-columns: repeat(4, max-content)", css)

    def test_mobile_columns_dialogs_and_tables_have_bounded_overflow(self):
        css = self._responsive_css()
        self.assertIn('.block-container [data-testid="stHorizontalBlock"]', css)
        self.assertIn('[data-testid="stDialog"] [role="dialog"]', css)
        self.assertIn('[data-testid="stDataFrame"]', css)
        self.assertIn(".markdown-detail-table-scroll", css)
        self.assertIn("overflow-wrap: anywhere", css)

    def test_run_button_is_the_only_mobile_fixed_primary_action(self):
        css = self._responsive_css()
        self.assertIn(".st-key-test_run_run", css)
        self.assertEqual(1, css.count("position: fixed"))
        self.assertIn('.stApp:has([data-testid="stDialog"]) .st-key-test_run_run', css)
        self.assertIn(".stApp:has(input:focus) .st-key-test_run_run", css)

    def test_sample_picker_has_a_stable_horizontal_scroll_scope(self):
        source = TEST_RUN_SOURCE.read_text(encoding="utf-8")
        css = self._responsive_css()
        self.assertIn('key="test_run_sample_table"', source)
        self.assertIn(".st-key-test_run_sample_table", css)
        self.assertIn("min-width: 44rem", css)

    def test_components_compose_responsive_css_and_wrap_markdown_tables(self):
        source = COMPONENTS_SOURCE.read_text(encoding="utf-8")
        self.assertIn("from src.ui.responsive import MOBILE_RESPONSIVE_CSS", source)
        self.assertIn("MOBILE_RESPONSIVE_CSS", source)
        self.assertIn('class="markdown-detail-table-scroll"', source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 调整旧导航测试的作用范围**

在 `tests/test_uiux_audit_fixes.py::test_top_navigation_is_lightweight_not_primary_cta` 中，将：

```python
self.assertNotIn("position: sticky", components_source)
self.assertNotIn("position: fixed", components_source)
```

替换为：

```python
import src.ui.components as components

desktop_css = components.STYLE_CSS.split("@media (max-width: 760px)", 1)[0]
self.assertNotIn("position: sticky", desktop_css)
self.assertNotIn("position: fixed", desktop_css)
```

保留该测试中关于导航不得使用 primary 按钮、不得全宽出血和不得使用旧状态色的其他断言。

- [ ] **Step 4: 运行测试确认按预期失败**

运行：

```bash
python -m pytest tests/test_mobile_responsive_ui.py tests/test_uiux_audit_fixes.py -q
```

预期：`tests/test_mobile_responsive_ui.py` 因 `src/ui/responsive.py` 尚不存在、样本选择容器 key 尚未增加而失败；现有 UI 审计测试保持通过。

- [ ] **Step 5: 提交契约测试**

```bash
git add .gitignore tests/test_mobile_responsive_ui.py tests/test_uiux_audit_fixes.py
git commit -m "test: define mobile responsive UI contracts"
```

### Task 2: 实现集中式响应式样式

**Files:**
- Create: `src/ui/responsive.py`
- Modify: `src/ui/components.py:1-12`
- Modify: `src/ui/components.py:875-878`
- Modify: `src/ui/components.py:1438-1460`

- [ ] **Step 1: 创建完整的响应式 CSS 模块**

创建 `src/ui/responsive.py`：

```python
"""Responsive CSS for the shared Streamlit UI.

The selectors are intentionally limited to stable Streamlit test IDs,
existing component classes, and explicit widget keys.
"""

MOBILE_RESPONSIVE_CSS = r"""
@media (min-width: 761px) and (max-width: 860px) {
    .block-container {
        max-width: 100%;
        padding-left: 1.1rem;
        padding-right: 1.1rem;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        overflow-x: auto;
        scrollbar-width: thin;
    }
}

@media (max-width: 760px) {
    .stApp {
        overflow-x: clip;
    }
    .block-container {
        box-sizing: border-box;
        max-width: 100%;
        overflow-x: clip;
        padding-left: 0.875rem;
        padding-right: 0.875rem;
        padding-bottom: calc(6.75rem + env(safe-area-inset-bottom));
    }
    .block-container [data-testid="stHorizontalBlock"] {
        align-items: stretch;
        flex-direction: column;
        gap: 0.55rem;
        width: 100%;
    }
    .block-container [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        min-width: 0 !important;
        width: 100% !important;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        background: color-mix(in srgb, var(--fde-bg) 94%, transparent);
        border-bottom: 1px solid var(--fde-line);
        display: grid;
        gap: 0.35rem 0.45rem;
        grid-template-columns: repeat(4, max-content);
        margin: 0 -0.875rem 1rem;
        overflow-x: auto;
        padding: 0.55rem 0.875rem 0.62rem;
        position: sticky;
        scrollbar-width: thin;
        top: 0;
        z-index: 50;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) > [data-testid="stColumn"] {
        flex: none !important;
        min-width: max-content !important;
        width: auto !important;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) > [data-testid="stColumn"]:first-child {
        grid-column: 1 / -1;
        min-width: 100% !important;
        width: 100% !important;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton {
        justify-content: flex-start;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) .stButton > button {
        min-height: 44px;
        padding-left: 0.62rem;
        padding-right: 0.62rem;
    }
    .page-title-heading {
        font-size: 1.3rem;
    }
    .page-title-copy {
        font-size: 0.9rem;
    }
    .detail-panel-body,
    .sample-detail-panel-body {
        padding: 0.82rem 0.82rem 0.95rem;
    }
    .markdown-detail-body,
    .document-text,
    .sample-detail-text,
    .sample-detail-list {
        min-width: 0;
        overflow-wrap: anywhere;
        word-break: break-word;
    }
    .markdown-detail-code,
    .markdown-detail-table-scroll,
    .sample-detail-table-wrap {
        max-width: 100%;
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }
    .markdown-detail-table {
        min-width: 36rem;
    }
    [data-testid="stDataFrame"] {
        max-width: 100%;
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }
    [data-testid="stDialog"] [role="dialog"] {
        box-sizing: border-box;
        max-height: calc(100dvh - 24px);
        max-width: calc(100vw - 24px);
        overflow-x: hidden;
        overflow-y: auto;
        width: calc(100vw - 24px);
    }
    [data-testid="stDialog"] [data-testid="stHorizontalBlock"] {
        align-items: stretch;
        flex-direction: column;
        gap: 0.55rem;
    }
    [data-testid="stDialog"] [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        min-width: 0 !important;
        width: 100% !important;
    }
    .st-key-test_run_sample_table {
        max-width: 100%;
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }
    .st-key-test_run_sample_table > div {
        min-width: 44rem;
    }
    .st-key-test_run_sample_table [data-testid="stHorizontalBlock"] {
        display: grid;
        grid-template-columns: 3rem 6rem minmax(15rem, 2.6fr) 6rem 4.5rem 5.5rem;
        min-width: 44rem;
    }
    .st-key-test_run_sample_table [data-testid="stColumn"] {
        min-width: 0 !important;
        width: auto !important;
    }
    .st-key-test_run_run {
        background: color-mix(in srgb, var(--fde-surface) 96%, transparent);
        border-top: 1px solid var(--fde-line);
        bottom: 0;
        box-shadow: 0 -8px 24px rgba(31, 39, 51, 0.08);
        box-sizing: border-box;
        left: 0;
        padding: 0.65rem 0.875rem calc(0.65rem + env(safe-area-inset-bottom));
        position: fixed;
        right: 0;
        z-index: 45;
    }
    .st-key-test_run_run button {
        min-height: 44px;
        width: 100%;
    }
    .stApp:has([data-testid="stDialog"]) .st-key-test_run_run {
        visibility: hidden;
    }
    .stApp:has(input:focus) .st-key-test_run_run,
    .stApp:has(textarea:focus) .st-key-test_run_run {
        border-top: 0;
        box-shadow: none;
        padding: 0;
        position: static;
    }
    .stButton > button,
    .stDownloadButton > button,
    [data-testid="stFormSubmitButton"] > button {
        min-height: 44px;
    }
}

@media (max-width: 480px) {
    .block-container {
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }
    [data-testid="stHorizontalBlock"]:has(.top-nav-brand) {
        margin-left: -0.75rem;
        margin-right: -0.75rem;
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }
    .top-nav-brand {
        font-size: 0.86rem;
    }
    .brief-title {
        font-size: 1.6rem;
    }
    .section-heading-page .section-heading-title {
        font-size: 1.08rem;
    }
    .inline-status {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
"""
```

- [ ] **Step 2: 将响应式 CSS 注入现有全局样式**

在 `src/ui/components.py` 的 import 区加入：

```python
from src.ui.responsive import MOBILE_RESPONSIVE_CSS
```

在现有 `STYLE_CSS` 三引号结束后加入：

```python
STYLE_CSS = STYLE_CSS.replace(
    "</style>",
    f"{MOBILE_RESPONSIVE_CSS}\n</style>",
)
```

不要把 `STYLE_CSS` 改成 f-string，避免现有 CSS 花括号被解释。

- [ ] **Step 3: 为 Markdown 表格增加独立滚动容器**

将 `src/ui/components.py::_markdown_table_html` 的返回值改为：

```python
return (
    '<div class="markdown-detail-table-scroll">'
    '<table class="markdown-detail-table">'
    f"<thead><tr>{header_html}</tr></thead>"
    f"<tbody>{body_html}</tbody>"
    "</table>"
    "</div>"
)
```

表头、表体、单元格内容和转义逻辑保持不变。

- [ ] **Step 4: 运行组件与响应式测试**

运行：

```bash
python -m pytest \
  tests/test_mobile_responsive_ui.py \
  tests/test_html_rendering.py \
  tests/test_ui_components.py \
  tests/test_uiux_audit_fixes.py -q
```

预期：除“样本选择表缺少 `test_run_sample_table` key”外全部通过；现有 HTML 不被渲染为代码块。

- [ ] **Step 5: 提交集中样式**

```bash
git add src/ui/responsive.py src/ui/components.py
git commit -m "feat: add shared mobile responsive styles"
```

### Task 3: 为样本选择表增加稳定响应式作用域

**Files:**
- Modify: `src/ui/test_run.py:996-1040`
- Test: `tests/test_mobile_responsive_ui.py`
- Test: `tests/test_test_run_flow.py`

- [ ] **Step 1: 修改样本选择表容器**

在 `src/ui/test_run.py::_render_sample_checkbox_table` 中，将：

```python
with st.container(height=SAMPLE_TABLE_HEIGHT, border=True):
```

替换为：

```python
with st.container(
    height=SAMPLE_TABLE_HEIGHT,
    border=True,
    key="test_run_sample_table",
):
```

其余表头、checkbox key、选中状态合并逻辑和现有文案全部保持不变。该 key 只用于让手机端保持表格横向滑动，避免全局单列规则破坏六列选择表。

- [ ] **Step 2: 运行样本选择和状态测试**

运行：

```bash
python -m pytest \
  tests/test_mobile_responsive_ui.py \
  tests/test_test_run_flow.py::TestRunFlowStructureTests::test_selection_controls_are_dialog_driven \
  tests/test_test_run_flow.py::SampleSelectionTests::test_sample_dialog_confirm_is_only_path_that_writes_confirmed_selection \
  tests/test_uiux_audit_fixes.py -q
```

预期：样本选择只在“确认选择”时写入正式选择状态，响应式契约全部通过。

- [ ] **Step 3: 提交稳定作用域**

```bash
git add src/ui/test_run.py
git commit -m "refactor: scope sample picker responsive overflow"
```

### Task 4: 自动化回归与本地响应式验收

**Files:**
- Verify only; no model or scoring code changes.

- [ ] **Step 1: 运行静态检查和数据集校验**

```bash
ruff check app.py app src scripts tests
python scripts/validate_dataset.py
```

预期：Ruff 无错误；数据集校验成功且不重写样本。

- [ ] **Step 2: 运行全量测试**

```bash
python -m pytest
```

预期：全部测试通过；评分、结论、持久化读取、恢复队列和 UI 文案防护测试无回归。

- [ ] **Step 3: 记录持久化基线**

运行只读命令：

```bash
python -c "from app.services import conclusions as cc; from app.services import eval_runner as er; responses=cc.load_live_responses(); scores=cc.load_current_cohort_scores(); runs=er.list_persisted_answer_runs(); print({'responses': len(responses), 'scores': len(scores), 'runs': len(runs)})"
```

预期：回答和评分数量与实施前基线一致；当前已知正式基线为 65 条回答、65 条评分。不要点击“运行评测”“生成 AI 评分”或任何重试按钮。

- [ ] **Step 4: 启动本地 Streamlit**

```bash
streamlit run app.py --server.headless true --server.port 8501
```

预期：`http://localhost:8501` 返回应用页面，无 traceback。

- [ ] **Step 5: 用真实浏览器检查四档视口**

使用 Codex in-app Browser 的 viewport capability，依次检查：

```text
390×844
430×932
768×1024
1440×900
```

每个视口检查以下页面：

```text
项目说明
样本库
发起评测
评测结论
```

验收信号：

```text
1. 页面整体没有横向滚动。
2. 顶部四项导航均可见或可横向滑动，当前项状态清楚。
3. 760px 以下主要 st.columns 纵向排列。
4. 样本库 dataframe 和样本选择六列表只在自身区域横向滑动。
5. “查看持久化批次”、模型回答和 AI 评分仍可见。
6. “运行评测”固定在手机底部，不遮挡最后一段内容。
7. 打开任一弹窗时，底部“运行评测”按钮隐藏。
8. 弹窗宽度不超过视口，双列字段在手机端变为单列。
9. 长回答、代码块、长链接和 Markdown 表格不撑破卡片。
10. 1440×900 桌面布局与改造前一致。
```

在 `390×844` 和 `1440×900` 至少各保存一组四页面截图作为验收证据。

- [ ] **Step 6: 再次核对持久化数据未变化**

重复 Step 3 的只读命令。

预期：回答、评分和批次数量与 Step 3 完全一致；没有新模型调用、评分调用或数据库写入。

### Task 5: 整合、推送与线上部署验收

**Files:**
- No new source files unless verification exposes a reproducible defect; any defect must first receive a failing regression test in `tests/test_mobile_responsive_ui.py`.

- [ ] **Step 1: 检查提交范围**

```bash
git status --short
git diff main...HEAD --stat
git log --oneline main..HEAD
```

预期：只包含 `.gitignore`、响应式样式、Markdown 表格滚动容器、样本选择表 key 和对应测试；`.claude/` 不在 diff 中。

- [ ] **Step 2: 运行最终验证**

```bash
ruff check app.py app src scripts tests
python -m pytest
python scripts/validate_dataset.py
git diff --check main...HEAD
```

预期：所有命令成功。

- [ ] **Step 3: 合并到部署分支**

实施分支使用：

```bash
codex/mobile-responsive-layout
```

在确认工作区干净后执行：

```bash
git switch main
git merge --ff-only codex/mobile-responsive-layout
```

预期：`main` 快进到已验证提交，不产生额外冲突提交。

- [ ] **Step 4: 推送 GitHub**

```bash
git push origin main
```

预期：远端 `origin/main` 与本地 `main` 指向相同提交。

- [ ] **Step 5: 检查 GitHub CI**

```bash
gh run list --branch main --limit 1
gh run watch --exit-status
```

预期：Ruff 与 pytest 工作流成功。

- [ ] **Step 6: 检查 Streamlit 部署**

```bash
curl -I https://finance-model-eval.streamlit.app/
```

预期：应用返回可用 HTTP 响应。随后使用真实浏览器重新检查 `390×844`、`430×932` 和 `1440×900`：

```text
顶部导航
样本表
持久化批次
模型回答
AI 评分
评测结论
手机底部运行评测按钮
弹窗打开时底部按钮隐藏
```

不得修改 Supabase 网络白名单，不得通过运行新评测来验证布局。

- [ ] **Step 7: 完成线上数据只读核对**

在线上“发起评测”页面选择现有持久化批次，确认可查看模型回答；在“评测结论”页面确认现有 65 条评分仍可汇总。只进行读取和页面切换，不点击任何模型调用、评分或恢复写入操作。
