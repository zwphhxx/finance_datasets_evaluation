# 审计后续修复 Implementation Plan

> **Status:** Completed
>
> **Started on:** 2026-08-20
>
> **Completed on:** 2026-08-20
>
> **Implementation branch:** `codex/audit-followup-fixes`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复证据索引层级和测试隔离，校正项目状态文档，并在不丢失未合并实验的前提下清理 Git 遗留。

**Architecture:** 视觉变更仅落在证据投影和报告样式；AppTest 通过测试层临时 SQLite fixture 隔离基础设施；文档只校正项目阶段；Git 清理在全部代码验证之后执行。评分、Prompt、schema 与生产数据保持不变。

**Tech Stack:** Python 3.11、Streamlit 1.51、SQLAlchemy 2、pytest、Ego Browser、Git。

---

### Task 1: 证据索引中文语义与视觉层级

**Files:**
- Modify: `src/ui/report_components.py`
- Modify: `src/ui/report_styles.py`
- Modify: `tests/test_report_experience.py`
- Modify: `tests/test_mobile_responsive_ui.py`

- [x] **Step 1: 写入失败测试**

增加行为断言：`evidence_index_html()` 把五个字段显示为现有中文标签与满分，写出“模型整体最弱维度”，不包含 `_score`；CSS 使用高特异性标题选择器、题目 1.45rem、元信息至少 0.94rem、事实值至少 1rem，手机端维度单列。

- [x] **Step 2: 验证 RED**

Run: `PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_mobile_responsive_ui.py`

Expected: FAIL，旧 HTML 仍包含 `accuracy_score`，旧字号仍为 0.78/0.70/0.86rem。

- [x] **Step 3: 最小实现**

在 `report_components.py` 复用 `SCORE_DIMENSIONS` 与 `SCORE_DIMENSION_FULL_MARKS`，新增纯展示 helper，把弱维度和分数映射为中文；为总分、弱维度、维度行增加稳定 class。在 `report_styles.py` 用 `[data-testid="stMarkdownContainer"] .evidence-index-title` 固定题目字号，并提升元信息/事实字号。

- [x] **Step 4: 验证 GREEN**

Run: `PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_mobile_responsive_ui.py tests/test_conclusions.py tests/test_evidence_index.py`

Expected: PASS。

### Task 2: 完整应用渲染测试隔离

**Files:**
- Create: `tests/conftest.py`
- Modify: `tests/test_conclusions.py`
- Modify: `tests/test_recoverable_evaluation_queue.py`

- [x] **Step 1: 写入失败测试**

新增 `isolated_app_database` fixture 契约测试：在 AppTest 运行期间 `DATABASE_URL` 必须是 `sqlite:///` 临时路径，`get_result_store()` engine 不能是 PostgreSQL，测试结束后 `_store_for_url` 与 Streamlit 缓存清空。

- [x] **Step 2: 验证 RED**

Run: `PYTHONPATH=. pytest -q tests/test_conclusions.py::RenderTests::test_page_renders_without_exception tests/test_recoverable_evaluation_queue.py::AppRenderTests::test_pages_render_without_run`

Expected: FAIL，现有用例没有隔离 fixture。

- [x] **Step 3: 最小实现**

在 `tests/conftest.py` 创建显式 fixture，使用 `monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'apptest.db'}")`，并在 yield 前后调用 `_store_for_url.cache_clear()`、`st.cache_data.clear()` 和结论缓存清理。两个 AppTest 类通过 `pytest.mark.usefixtures` 使用该 fixture。

- [x] **Step 4: 重复验证**

Run: 连续 10 次执行两个 AppTest，再执行 `PYTHONPATH=. pytest -q`。

Expected: 所有轮次 PASS，单轮不依赖网络或正式 secrets。

### Task 3: 路线图与计划状态

**Files:**
- Modify: `docs/extension_roadmap.md`
- Modify: `docs/superpowers/plans/2026-08-13-evidence-first-evaluation-report-implementation.md`
- Modify: `docs/superpowers/plans/2026-08-13-premium-consulting-report-implementation.md`
- Modify: `docs/superpowers/plans/2026-08-20-audit-followup-fixes.md`

- [x] **Step 1: 更新当前阶段**

把“项目原型/不提供外部数据库/演示模式/批量真实评测尚未开始”改为“真实链路已验证/外部 PostgreSQL 增量持久化/正式记录与 mock 隔离/下一阶段扩充覆盖和评分一致性”。

- [x] **Step 2: 标记历史计划完成**

在两份历史计划标题下增加状态、完成提交 `0c69946` 和说明，不重写内部历史执行清单。

- [x] **Step 3: 文案守卫**

Run: `PYTHONPATH=. pytest -q tests/test_ui_text_guardrails.py tests/test_project_methodology.py tests/test_repository_readiness.py`

Expected: PASS。

### Task 4: 浏览器与仓库清理

**Files:**
- Verify: `src/ui/report_components.py`
- Verify: `src/ui/report_styles.py`
- Git metadata only for cleanup

- [x] **Step 1: 启动只读本地应用**

使用当前 Supabase 只读展示启动 Streamlit；不得点击评测、导入、删除或保存。

- [x] **Step 2: Ego Browser 回归**

在 1710×1009、390×844、320×844 检查计算字号、中文维度、无页面横向溢出和三个操作按钮可达。

- [x] **Step 3: 全量验证与提交**

Run: `PYTHONPATH=. pytest -q`, `ruff check .`, `python -m py_compile ...`, `git diff --check`。

Expected: 全部 exit 0。

- [x] **Step 4: 安全清理 Git 遗留**

为 `290b3c6` 创建 `archive/portfolio-style-experiment-2026-07-03` tag；随后删除其干净 worktree/分支。移除其余干净且已合并 worktree，删除已合并本地分支，检查并删除过时 stash，执行 `git worktree prune`。不删除当前实现分支和 `.claude/` 用户内容。

- [x] **Step 5: 复核**

Run: `git worktree list --porcelain`, `git branch --merged main`, `git stash list`, `git status --short`。

Expected: 仅主工作区和当前实施分支相关状态保留；未合并实验可从 archive tag 恢复。
