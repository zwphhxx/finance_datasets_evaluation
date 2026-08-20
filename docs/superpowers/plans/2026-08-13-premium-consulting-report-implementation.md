# 精品咨询报告视觉升级 Implementation Plan

> **Status:** Completed
>
> **Completed on:** 2026-08-20
>
> **Implementation baseline:** 已合并到 `main`，截至 `0c69946`。
>
> 下列复选框保留为实施过程清单，不再代表当前项目进度。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将四页 Streamlit 评测项目升级为 B2/T2 精品咨询报告视觉，并让 Supabase 暂停或配置失效时在 3–5 秒内明确失败、停止重复连接且禁止真实模型调用。

**Architecture:** 视觉层继续集中在 `src/ui/components.py` 与 `src/ui/responsive.py`，四个页面只通过语义化共享组件表达层级，避免页面各自堆叠 CSS。持久化层在 SQLAlchemy 引擎配置中加入有限连接超时，并通过一次 rerun 范围的失败熔断器阻止同一页面重复连接；真实模型调用继续经过现有持久化预检门。

**Tech Stack:** Python 3.13、Streamlit 1.51、SQLAlchemy 2、psycopg 3、pandas、Altair、pytest/unittest、Ruff、Playwright 浏览器验收。

---

## 文件职责与变更边界

- `app/persistence/config.py`：解析数据库 URL 和连接超时配置，不执行连接。
- `app/persistence/result_store.py`：创建受控超时的 SQLAlchemy Engine，并保留现有事务语义。
- `app/persistence/__init__.py`：缓存可用 store；记录本次 Streamlit rerun 中的首次连接失败，后续读取快速失败。
- `app.py`：建立本次 rerun 的持久化访问范围，并将可展示的数据库状态传给页面。
- `src/ui/components.py`：B2/T2 设计令牌、报告标题、结论先行线、事实数据和共享控件样式。
- `src/ui/responsive.py`：平板、390px 和 430px 下的报告布局、导航、指标与操作布局。
- `src/ui/case_study.py`：首页报告封面和可验证事实数据。
- `src/ui/samples.py`：样本库“标题—筛选—列表—详情”层级与选中标记。
- `src/ui/test_run.py`：评测步骤层级、即时反馈和数据库不可用状态；不修改评分模型或调用参数。
- `src/ui/conclusions.py`：结论先行结构和“结论—证据—边界”顺序；不改变结论算法或文案。
- `tests/test_result_store_config.py`、`tests/test_result_store.py`：超时和失败熔断测试。
- `tests/test_ui_components.py`、`tests/test_project_brief.py`、`tests/test_mobile_responsive_ui.py`、`tests/test_test_run_flow.py`、`tests/test_conclusions.py`：视觉语义、文案守卫和响应式契约。

## Task 1: 数据库连接超时配置

**Files:**
- Modify: `app/persistence/config.py`
- Modify: `app/persistence/result_store.py`
- Test: `tests/test_result_store_config.py`
- Test: `tests/test_result_store.py`

- [ ] **Step 1: 写入失败测试，固定 3–5 秒配置边界**

在 `tests/test_result_store_config.py` 增加：

```python
from app.persistence.config import resolve_database_connect_timeout


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 4), ("", 4), ("3", 3), ("5", 5), ("1", 3), ("12", 5), ("bad", 4)],
)
def test_database_connect_timeout_is_bounded(raw, expected):
    environ = {} if raw is None else {"FINDUEVAL_DATABASE_CONNECT_TIMEOUT_SECONDS": raw}
    assert resolve_database_connect_timeout(environ=environ) == expected
```

在 `tests/test_result_store.py` 增加一个通过 mock `create_engine` 检查 PostgreSQL `connect_timeout` 的测试，并验证 SQLite 不接收该参数。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_result_store_config.py tests/test_result_store.py
```

Expected: FAIL，提示 `resolve_database_connect_timeout` 尚不存在或 Engine 未传入超时。

- [ ] **Step 3: 实现超时解析与 Engine 参数**

在 `app/persistence/config.py` 增加纯函数：

```python
DATABASE_CONNECT_TIMEOUT_ENV = "FINDUEVAL_DATABASE_CONNECT_TIMEOUT_SECONDS"


def resolve_database_connect_timeout(*, environ=None) -> int:
    env = os.environ if environ is None else environ
    raw = str(env.get(DATABASE_CONNECT_TIMEOUT_ENV) or "").strip()
    try:
        value = int(raw) if raw else 4
    except ValueError:
        value = 4
    return max(3, min(value, 5))
```

修改 `ResultStore.__init__`，只对 PostgreSQL Engine 传入：

```python
engine_kwargs = {"pool_pre_ping": True, "future": True}
if normalized.startswith("postgresql+psycopg://"):
    engine_kwargs["connect_args"] = {
        "connect_timeout": resolve_database_connect_timeout()
    }
self.engine = create_engine(normalized, **engine_kwargs)
```

不得更改 `_upsert`、队列状态或事务提交行为。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_result_store_config.py tests/test_result_store.py
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/persistence/config.py app/persistence/result_store.py tests/test_result_store_config.py tests/test_result_store.py
git commit -m "fix: bound database connection wait"
```

## Task 2: 单次 rerun 数据库失败熔断

**Files:**
- Modify: `app/persistence/__init__.py`
- Modify: `app.py`
- Test: `tests/test_result_store_config.py`
- Test: `tests/test_navigation_routes.py`

- [ ] **Step 1: 写入失败测试，证明一次失败后不再重复建连**

在 `tests/test_result_store_config.py` 增加：

```python
def test_store_failure_is_memoized_inside_request_scope(monkeypatch):
    attempts = 0

    def fail(_url):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.persistence._store_for_url", fail)
    with result_store_request_scope():
        with pytest.raises(ResultStoreUnavailableError):
            get_result_store(secrets={"DATABASE_URL": "postgresql://u:p@db/x"})
        with pytest.raises(ResultStoreUnavailableError):
            get_result_store(secrets={"DATABASE_URL": "postgresql://u:p@db/x"})
    assert attempts == 1
```

另写测试确认新 request scope 会重新尝试，以支持 Supabase 恢复后自动连接。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_result_store_config.py
```

Expected: FAIL，缺少 request scope 和统一异常。

- [ ] **Step 3: 实现 request 范围熔断器**

在 `app/persistence/__init__.py` 使用 `ContextVar` 保存当前 rerun 的失败信息：

```python
_request_store_failure = ContextVar("request_store_failure", default=None)


@contextmanager
def result_store_request_scope():
    token = _request_store_failure.set(None)
    try:
        yield
    finally:
        _request_store_failure.reset(token)
```

`get_result_store()` 若当前 scope 已记录失败，立即抛出 `ResultStoreUnavailableError`；首次 `_store_for_url()` 失败时保存不含密码的用户可见原因。不要清除 `_store_for_url` 的成功缓存。

在 `app.py` 中把一次页面脚本主体包在 `result_store_request_scope()` 内，确保每次 Streamlit rerun 都是新的尝试范围。页面仍应在数据库失败时完成静态部分渲染。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_result_store_config.py tests/test_navigation_routes.py
```

Expected: PASS，且同一 scope 失败只调用一次建连函数。

- [ ] **Step 5: 提交**

```bash
git add app/persistence/__init__.py app.py tests/test_result_store_config.py tests/test_navigation_routes.py
git commit -m "fix: stop repeated database reconnects per rerun"
```

## Task 3: 持久化不可用的页面反馈与模型调用安全门

**Files:**
- Modify: `src/ui/test_run.py`
- Modify: `src/ui/conclusions.py`
- Test: `tests/test_test_run_flow.py`
- Test: `tests/test_conclusions.py`
- Test: `tests/test_durable_execution.py`

- [ ] **Step 1: 写入失败测试，固定不可用状态的行为**

测试要求：

```python
def test_live_run_preflight_stops_before_provider_when_store_is_unavailable(...):
    # get_result_store raises ResultStoreUnavailableError
    # provider.generate_response must not be called
    ...


def test_test_run_page_renders_database_unavailable_feedback():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
    assert "render_persistence_status" in source
    assert "ResultStoreUnavailableError" in source
```

结论页测试数据库读取失败时仍渲染页面标题与现有静态空状态，不无限 spinner。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_test_run_flow.py tests/test_conclusions.py tests/test_durable_execution.py
```

Expected: FAIL，缺少明确状态组件或异常分支。

- [ ] **Step 3: 实现共享状态反馈与安全门**

在 `src/ui/components.py`（如 Task 4 尚未开始，可先添加最小版本）提供：

```python
def render_persistence_status(message: str, *, available: bool) -> None:
    tone = "available" if available else "unavailable"
    render_html(
        f'<div class="persistence-status persistence-status-{tone}">'
        f'{escape(str(message))}</div>'
    )
```

`_require_persistence_preflight()` 捕获统一持久化异常，先显示可理解的状态，再停止 `_execute_run_queue()`；必须保证 provider 构造或 `generate_response()` 之前完成预检。结论页将半分钟 spinner 改为普通加载反馈，并在快速失败后展示数据不可用状态。

不得增加真实模型重试，不得把 SQLite 自动用作线上真实调用的无提示后备。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_test_run_flow.py tests/test_conclusions.py tests/test_durable_execution.py
```

Expected: PASS；测试中 provider 调用次数为 0。

- [ ] **Step 5: 提交**

```bash
git add src/ui/components.py src/ui/test_run.py src/ui/conclusions.py tests/test_test_run_flow.py tests/test_conclusions.py tests/test_durable_execution.py
git commit -m "fix: surface persistence outages before model calls"
```

## Task 4: B2/T2 全局视觉令牌与共享组件

**Files:**
- Modify: `src/ui/components.py`
- Modify: `src/ui/navigation.py`
- Test: `tests/test_ui_components.py`
- Test: `tests/test_ui_text_guardrails.py`

- [ ] **Step 1: 写入失败的视觉契约测试**

在 `tests/test_ui_components.py` 增加以下契约：

```python
def test_consulting_report_tokens_and_typography_are_centralized():
    from src.ui.components import STYLE_CSS
    for token in ["#F7F5F0", "#252621", "#6F6B62", "#D9D4C9", "#9A7435"]:
        assert token in STYLE_CSS
    assert 'ui-serif, "Songti SC"' in STYLE_CSS
    assert "executive-takeaway" in STYLE_CSS
    assert "transition" in STYLE_CSS
    assert "prefers-reduced-motion" in STYLE_CSS


def test_brief_intro_supports_derived_facts_without_new_copy():
    assert "facts" in inspect.signature(components.render_brief_intro).parameters
```

增加导航契约：当前页必须有语义类或稳定 key 可绘制短金线，不新增导航文案。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_ui_components.py tests/test_ui_text_guardrails.py
```

Expected: FAIL，旧令牌和组件签名仍在。

- [ ] **Step 3: 实现全局设计系统**

重写 `STYLE_CSS` 的令牌和相关规则：

```css
:root {
  --fde-paper: #F7F5F0;
  --fde-surface: #FFFFFF;
  --fde-ink: #252621;
  --fde-muted: #6F6B62;
  --fde-line: #D9D4C9;
  --fde-gold: #9A7435;
  --fde-serif: ui-serif, "Songti SC", "STSong", "Noto Serif CJK SC", serif;
  --fde-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
}
```

实现或扩展以下共享语义：

- `render_brief_intro(title, note, facts=None)`；
- `render_executive_takeaway(text)`；
- `render_fact_strip(facts)`；
- 顶部导航当前页短金线；
- 深墨主按钮、白底次按钮；
- 暖灰表格/输入框/弹窗；
- `prefers-reduced-motion: reduce` 下关闭非必要过渡。

保留现有文本转义和 Markdown 安全逻辑，不恢复已经删除的 legacy card API。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_ui_components.py tests/test_ui_text_guardrails.py
```

Expected: PASS；没有出现被禁止的营销文案。

- [ ] **Step 5: 提交**

```bash
git add src/ui/components.py src/ui/navigation.py tests/test_ui_components.py tests/test_ui_text_guardrails.py
git commit -m "feat: add consulting report design system"
```

## Task 5: 首页报告封面与事实数据

**Files:**
- Modify: `src/ui/case_study.py`
- Modify: `src/ui/components.py`
- Test: `tests/test_project_brief.py`
- Test: `tests/test_ui_text_guardrails.py`

- [ ] **Step 1: 写入失败测试，保证事实来自现有数据**

在 `tests/test_project_brief.py` 增加：

```python
def test_home_facts_are_derived_from_dataset_and_rubric():
    facts = build_home_facts(base)
    assert facts[0] == ("当前样本", "13")
    assert facts[1][0] == "覆盖领域"
    assert facts[2] == ("评分总分", "100")
```

另用文本守卫保存 `src/ui/case_study.py` 现有中文文案列表，确保重排不改写表述。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_project_brief.py tests/test_ui_text_guardrails.py
```

Expected: FAIL，尚无 `build_home_facts` 或 facts 未接入封面。

- [ ] **Step 3: 实现报告封面**

在 `case_study.py` 增加纯函数，从 `base.tasks` 和 `ds.get_rubric_dimensions()` 推导：

```python
def build_home_facts(base) -> list[tuple[str, str]]:
    tasks = getattr(base, "tasks", None)
    sample_count = 0 if tasks is None else len(tasks)
    domain_count = 0 if tasks is None or "domain" not in tasks else tasks["domain"].dropna().nunique()
    score_total = sum(int(item.get("full_mark") or 0) for item in ds.get_rubric_dimensions())
    return [
        ("当前样本", str(sample_count)),
        ("覆盖领域", str(domain_count)),
        ("评分总分", str(score_total)),
    ]
```

将 facts 交给 `render_brief_intro`；现有 `title`、`note`、三个章节标题、lead 和 body 字符串逐字保留。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_project_brief.py tests/test_ui_text_guardrails.py
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/ui/case_study.py src/ui/components.py tests/test_project_brief.py tests/test_ui_text_guardrails.py
git commit -m "feat: present project brief as consulting report"
```

## Task 6: 样本库与发起评测层级改造

**Files:**
- Modify: `src/ui/samples.py`
- Modify: `src/ui/test_run.py`
- Modify: `src/ui/components.py`
- Test: `tests/test_ui_components.py`
- Test: `tests/test_test_run_flow.py`
- Test: `tests/test_mobile_responsive_ui.py`

- [ ] **Step 1: 写入失败测试，固定语义容器和即时反馈**

测试源码包含稳定容器 key：

```python
assert 'key="samples_filter_region"' in samples_source
assert 'key="samples_list_region"' in samples_source
assert 'key="samples_detail_region"' in samples_source
assert 'key="test_run_stage_configuration"' in test_run_source
assert 'key="test_run_stage_answers"' in test_run_source
assert 'key="test_run_stage_scores"' in test_run_source
```

同时断言运行按钮仍在现有持久化预检之后触发队列，且回答查看器保持摘要/全文逻辑。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_ui_components.py tests/test_test_run_flow.py tests/test_mobile_responsive_ui.py
```

Expected: FAIL，语义容器尚不存在。

- [ ] **Step 3: 实现页面分层**

样本库：用命名 container 包裹筛选、清单和详情；CSS 以 container key 设定留白和分隔线，选中状态沿用现有 session state，只改变视觉标记。

发起评测：用三个命名 container 包裹现有阶段；点击长任务按钮后立即渲染 spinner/progress 占位，继续使用现有逐条持久化队列。不得改变 `TEST_RUN_STEPS`、模型参数、提示词、默认样本或评分入口。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_ui_components.py tests/test_test_run_flow.py tests/test_mobile_responsive_ui.py
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/ui/samples.py src/ui/test_run.py src/ui/components.py tests/test_ui_components.py tests/test_test_run_flow.py tests/test_mobile_responsive_ui.py
git commit -m "feat: clarify sample and evaluation workflows"
```

## Task 7: 评测结论“结论—证据—边界”布局

**Files:**
- Modify: `src/ui/conclusions.py`
- Modify: `src/ui/components.py`
- Test: `tests/test_conclusions.py`
- Test: `tests/test_ui_refactor.py`
- Test: `tests/test_model_display.py`

- [ ] **Step 1: 写入失败测试，保护算法和展示顺序**

在 `tests/test_conclusions.py` 增加源码顺序断言：

```python
page_source = source[source.index("def render_conclusions_page"):source.index("def _render_data_source_notice")]
assert page_source.index("_render_executive_conclusion") < page_source.index("_render_model_recommendations")
assert page_source.index("_render_model_recommendations") < page_source.index("_render_model_issue_details")
```

测试 `_render_executive_conclusion` 只使用 `model_summaries` 已存在的当前判断，不创造新评分或跨样本排名。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_conclusions.py tests/test_ui_refactor.py tests/test_model_display.py
```

Expected: FAIL，尚无 executive conclusion 层。

- [ ] **Step 3: 实现结论先行布局**

增加 `_render_executive_conclusion(model_summaries)`，复用 `_current_judgment()` 和现有模型显示名，使用 `render_executive_takeaway` 呈现当前数据支持的一句话。随后保留现有模型表、图表、回答明细和使用边界逻辑，只调整章节顺序和视觉容器。

当没有成功评分时，不生成推断性结论，继续显示现有空状态文案。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_conclusions.py tests/test_ui_refactor.py tests/test_model_display.py
```

Expected: PASS；模型汇总和详情数据内容不变。

- [ ] **Step 5: 提交**

```bash
git add src/ui/conclusions.py src/ui/components.py tests/test_conclusions.py tests/test_ui_refactor.py tests/test_model_display.py
git commit -m "feat: lead conclusions with supported judgment"
```

## Task 8: 响应式 B2/T2 适配

**Files:**
- Modify: `src/ui/responsive.py`
- Modify: `src/ui/components.py`
- Test: `tests/test_mobile_responsive_ui.py`

- [ ] **Step 1: 写入失败契约测试**

覆盖：

```python
for selector in [
    ".brief-facts",
    ".executive-takeaway",
    ".st-key-samples_filter_region",
    ".st-key-test_run_stage_configuration",
]:
    assert selector in css
assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in mobile_css
assert "overflow-x: auto" in mobile_nav_rules
```

保留现有 44px 触控、弹窗、表格横向局部滚动、固定运行按钮不遮挡回答等契约。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest -q tests/test_mobile_responsive_ui.py
```

Expected: FAIL，新语义区域未适配。

- [ ] **Step 3: 实现平板与手机布局**

- 事实数据在手机端使用两列并允许第三项自然换行；
- 首页标题在 390px 保持报告气质但不超过三行；
- 结论先行线占满可读宽度；
- 三个评测阶段单列；
- 样本筛选双列控件在 390px 下按必要性转为单列；
- 导航保留横向滚动与当前项短金线；
- 长回答、表格和弹窗不产生页面级横向溢出。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
python -m pytest -q tests/test_mobile_responsive_ui.py
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/ui/responsive.py src/ui/components.py tests/test_mobile_responsive_ui.py
git commit -m "feat: adapt consulting layout across viewports"
```

## Task 9: 全量自动化验证

**Files:**
- Modify only if a verified regression requires a scoped fix

- [ ] **Step 1: 运行代码规范检查**

Run:

```bash
ruff check app.py app src scripts tests
```

Expected: `All checks passed!`

- [ ] **Step 2: 运行数据集校验**

Run:

```bash
python scripts/validate_dataset.py
```

Expected: 13 个 active 样本、20 项通过、0 警告、0 错误。

- [ ] **Step 3: 运行完整测试套件**

使用仅供测试的临时 SQLite secret，避免测试连接线上 Supabase：

```bash
python - <<'PY'
import pytest
import streamlit.config as config
config.set_option("secrets.files", ["/tmp/findueval-test-secrets.toml"])
raise SystemExit(pytest.main(["-q"]))
PY
```

Expected: 全部非 PostgreSQL 集成测试通过；仅明确依赖 `TEST_DATABASE_URL` 的测试跳过。

- [ ] **Step 4: 检查 diff 与文案守卫**

Run:

```bash
git diff --check
python -m pytest -q tests/test_ui_text_guardrails.py tests/test_project_brief.py
```

Expected: 无空白错误；现有项目文案守卫全部通过。

## Task 10: 浏览器视觉与故障注入验收

**Files:**
- Create temporary diagnostic files only under `/tmp`; delete after verification
- Do not modify production data

- [ ] **Step 1: 启动使用临时 SQLite 的本地 Streamlit**

设置测试专用 `DATABASE_URL=sqlite:////tmp/findueval-visual-qa.sqlite3` 和 mock provider 环境，仅用于渲染；不得使用真实模型密钥。

- [ ] **Step 2: 验收桌面和平板**

使用 Playwright 检查 1440×1000 和 768×1024：

- 四个导航页均可点击；
- 当前页短金线存在；
- 首页封面、事实数据、结论先行线层级正确；
- 样本、评测和结论页面无重叠或页面级横向滚动。

- [ ] **Step 3: 验收 390px 和 430px 手机端**

逐页截图并读取 computed layout：

- `document.documentElement.scrollWidth == window.innerWidth`；
- 标题无 Streamlit 原生额外 padding；
- 事实数据两列排列；
- 导航横向滚动；
- 按钮触控高度不少于 44px；
- 固定运行按钮不遮挡回答内容。

- [ ] **Step 4: 故障注入 Supabase 暂停状态**

使用指向不可达测试地址、`connect_timeout=3` 的临时连接配置，测量一次点击后的页面反馈：

- 3–5 秒内出现数据库不可用状态；
- 同一次 rerun 只发起一次数据库连接；
- 静态项目说明和样本仍可展示；
- provider mock 断言真实生成函数未调用。

- [ ] **Step 5: 清理临时服务与产物**

关闭 Playwright 和 Streamlit，删除 `/tmp` 测试数据库、临时 secrets 和诊断脚本；工作区只保留实现及测试文件。

## Task 11: 最终审查、提交与部署

**Files:**
- Review all modified files from Tasks 1–10

- [ ] **Step 1: 核对规格逐项覆盖**

对照 `docs/superpowers/specs/2026-08-13-premium-consulting-report-visual-design.md`，确认视觉、四页结构、响应式、异常反馈、模型调用安全和文案保护均有自动化或浏览器证据。

- [ ] **Step 2: 确认 Git 范围**

Run:

```bash
git status --short
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
```

Expected: 不包含 `.claude/`、`.superpowers/`、本地 secrets、截图或数据库文件。

- [ ] **Step 3: 提交剩余验收修复**

如浏览器验收产生了必要的小范围修复：

```bash
git add <only-reviewed-files>
git commit -m "fix: complete consulting report visual QA"
```

- [ ] **Step 4: 推送前重新执行完整验证**

重复 Task 9 的 Ruff、数据校验和完整测试；不得使用旧测试结果替代。

- [ ] **Step 5: 推送部署分支**

在用户已授权发布时：

```bash
git push origin main
```

Expected: `origin/main` 指向本地最终提交，Streamlit Community Cloud 自动重新部署。普通代码提交不要求手动 reboot；只有平台部署未更新时再单独诊断。

## 自检结论

- 规格覆盖：视觉系统、四页结构、移动端、状态组件、Supabase 快速失败、模型调用安全门、文案与评分边界均已映射到任务。
- 范围拆分：持久化可靠性先独立交付，视觉升级后交付，两者通过同一最终验收汇合，不更改数据口径。
- 类型一致性：统一使用 `ResultStoreUnavailableError`、`result_store_request_scope()`、`render_executive_takeaway()`、`render_fact_strip()` 和命名 container key。
- 无占位项：实现步骤包含具体文件、函数、测试命令与预期结果。
