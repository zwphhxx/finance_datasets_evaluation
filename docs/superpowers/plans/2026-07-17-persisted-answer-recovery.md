# Persisted Answer Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Streamlit 在会话丢失或重启后从 PostgreSQL/Supabase 恢复两个正式批次的 65 条模型回答，并在“发起评测”和“评测结论”页提供精确的回答查看入口。

**Architecture:** 在 `eval_runner` 中增加独立于 Streamlit 会话的持久化批次摘要查询；已完成回答的只读恢复直接按 `run_id` 读取，checkpoint 校验只约束未完成队列续跑。结论服务按 `(run_id, case_id, eval_model)` 将当前兼容评分连接到回答，两个页面复用现有 Markdown 详情展示能力，不修改数据库结构、评分模型、Prompt 或已有数据。

**Tech Stack:** Python 3.11、Streamlit、SQLAlchemy、PostgreSQL/Supabase、pandas、pytest、Ruff

---

## File map

- `app/services/eval_runner.py`：构建持久化回答批次摘要、读取可查看批次、按运行恢复回答。
- `src/ui/test_run.py`：选择持久化批次、区分只读查看和未完成队列续跑。
- `app/services/conclusions.py`：把当前兼容评分与持久化回答按三字段精确连接。
- `src/ui/conclusions.py`：在当前模型详情中选择样本并查看回答全文。
- `tests/test_live_results.py`：持久化批次摘要与读取服务单元测试。
- `tests/test_test_run_flow.py`：批次选择、恢复策略和页面接线测试。
- `tests/test_conclusions.py`：回答连接与结论页接线测试。

## Task 1: 增加持久化回答批次摘要服务

**Files:**
- Modify: `tests/test_live_results.py`
- Modify: `app/services/eval_runner.py`

- [ ] **Step 1: 写入批次摘要失败测试**

在 `tests/test_live_results.py` 增加：

```python
class PersistedAnswerRunTests(unittest.TestCase):
    def test_summaries_include_only_runs_with_responses_and_sort_latest_first(self):
        runs = [
            {
                "run_id": "RUN-OLD",
                "provider": "siliconflow",
                "status": "completed",
                "created_at": "2026-07-16T10:00:00",
                "updated_at": "2026-07-16T11:00:00",
            },
            {
                "run_id": "RUN-NEW",
                "provider": "siliconflow",
                "status": "completed",
                "created_at": "2026-07-17T10:00:00",
                "updated_at": "2026-07-17T11:00:00",
            },
            {
                "run_id": "RUN-EMPTY",
                "provider": "siliconflow",
                "status": "completed",
                "created_at": "2026-07-18T10:00:00",
                "updated_at": "2026-07-18T11:00:00",
            },
        ]
        queue = [
            {"id": 1, "run_id": "RUN-OLD", "case_id": "C1", "model_id": "m1", "status": "success"},
            {"id": 2, "run_id": "RUN-OLD", "case_id": "C2", "model_id": "m1", "status": "success"},
            {"id": 3, "run_id": "RUN-NEW", "case_id": "C1", "model_id": "m2", "status": "success"},
            {"id": 4, "run_id": "RUN-EMPTY", "case_id": "C1", "model_id": "m3", "status": "queued"},
        ]
        responses = [
            {
                "id": 10,
                "run_id": "RUN-OLD",
                "case_id": "C1",
                "model_name": "m1",
                "run_status": "success",
                "answer_text": "旧回答 1",
            },
            {
                "id": 11,
                "run_id": "RUN-OLD",
                "case_id": "C2",
                "model_name": "m1",
                "run_status": "success",
                "answer_text": "旧回答 2",
            },
            {
                "id": 12,
                "run_id": "RUN-NEW",
                "case_id": "C1",
                "model_name": "m2",
                "run_status": "success",
                "answer_text": "新回答",
            },
        ]

        summaries = er.build_persisted_answer_run_summaries(runs, queue, responses)

        self.assertEqual(["RUN-NEW", "RUN-OLD"], [row["run_id"] for row in summaries])
        self.assertEqual(2, summaries[1]["response_count"])
        self.assertEqual(2, summaries[1]["case_count"])
        self.assertEqual(1, summaries[1]["model_count"])
        self.assertEqual(2, summaries[1]["success_count"])
        self.assertEqual(0, summaries[1]["unfinished_count"])

    def test_loader_reads_runs_queue_and_responses(self):
        tables = {
            "live_evaluation_runs": [
                {
                    "run_id": "RUN-A",
                    "provider": "siliconflow",
                    "status": "completed",
                    "created_at": "2026-07-17T10:00:00",
                    "updated_at": "2026-07-17T11:00:00",
                }
            ],
            "live_run_queue": [
                {"id": 1, "run_id": "RUN-A", "case_id": "C1", "model_id": "m1", "status": "success"}
            ],
            "live_run_responses": [
                {
                    "id": 2,
                    "run_id": "RUN-A",
                    "case_id": "C1",
                    "model_name": "m1",
                    "run_status": "success",
                    "answer_text": "已保存回答",
                }
            ],
        }

        class Store:
            def list_rows(self, table):
                return tables[table]

        with mock.patch("app.persistence.get_result_store", return_value=Store()):
            summaries = er.list_persisted_answer_runs()

        self.assertEqual(["RUN-A"], [row["run_id"] for row in summaries])
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
.venv/bin/pytest -q tests/test_live_results.py::PersistedAnswerRunTests
```

Expected: FAIL，提示 `build_persisted_answer_run_summaries` 或
`list_persisted_answer_runs` 尚不存在。

- [ ] **Step 3: 实现纯摘要函数和只读加载器**

在 `app/services/eval_runner.py` 增加：

```python
def build_persisted_answer_run_summaries(
    runs: Sequence[Mapping[str, Any]],
    queue_rows: Sequence[Mapping[str, Any]],
    responses: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    run_metadata = {
        _clean(row.get("run_id")): dict(row)
        for row in runs or []
        if _clean(row.get("run_id"))
    }
    queue_by_run: dict[str, list[Mapping[str, Any]]] = {}
    for row in queue_rows or []:
        run_id = _clean(row.get("run_id"))
        if run_id:
            queue_by_run.setdefault(run_id, []).append(row)

    responses_by_run: dict[str, list[Mapping[str, Any]]] = {}
    for row in responses or []:
        run_id = _clean(row.get("run_id"))
        if run_id and _clean(row.get("case_id")) and _clean(row.get("model_name")):
            responses_by_run.setdefault(run_id, []).append(row)

    summaries: list[dict[str, Any]] = []
    for run_id, answer_rows in responses_by_run.items():
        metadata = run_metadata.get(run_id, {})
        queued = queue_by_run.get(run_id, [])
        models = {
            _clean(row.get("model_name"))
            for row in answer_rows
            if _clean(row.get("model_name"))
        }
        cases = {
            _clean(row.get("case_id"))
            for row in answer_rows
            if _clean(row.get("case_id"))
        }
        success_count = sum(
            _clean(row.get("run_status")).lower() in {"success", STATUS_MOCK}
            and bool(_clean(row.get("answer_text")))
            for row in answer_rows
        )
        unfinished_count = sum(
            _clean(row.get("status")).lower() in {"queued", "running"}
            for row in queued
        )
        order_values = [
            metadata.get("updated_at"),
            metadata.get("created_at"),
            *(row.get("updated_at") or row.get("created_at") for row in answer_rows),
        ]
        order_text = max((_timestamp_text(value) for value in order_values), default="")
        order_id = max((_as_int(row.get("id")) or 0 for row in answer_rows), default=0)
        summaries.append(
            {
                "run_id": run_id,
                "provider": _clean(metadata.get("provider"))
                or _clean(answer_rows[0].get("provider")),
                "status": _clean(metadata.get("status")) or "completed",
                "created_at": _timestamp_text(metadata.get("created_at")),
                "updated_at": _timestamp_text(metadata.get("updated_at")),
                "response_count": len(answer_rows),
                "success_count": success_count,
                "case_count": len(cases),
                "model_count": len(models),
                "queue_count": len(queued),
                "unfinished_count": unfinished_count,
                "_order_text": order_text,
                "_order_id": order_id,
            }
        )

    summaries.sort(
        key=lambda row: (row["_order_text"], row["_order_id"], row["run_id"]),
        reverse=True,
    )
    for row in summaries:
        row.pop("_order_text", None)
        row.pop("_order_id", None)
    return summaries


def list_persisted_answer_runs(
    *,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    try:
        store = _runtime_result_store(db_path)
        if store is None:
            return []
        return build_persisted_answer_run_summaries(
            store.list_rows("live_evaluation_runs"),
            store.list_rows("live_run_queue"),
            store.list_rows("live_run_responses"),
        )
    except Exception:
        return []


def _timestamp_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value).strip()
```

复用本文件已有 `_clean()` 与 `_as_int()`，不增加数据库写入。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_live_results.py::PersistedAnswerRunTests
```

Expected: PASS。

- [ ] **Step 5: 提交服务改动**

```bash
git add app/services/eval_runner.py tests/test_live_results.py
git commit -m "feat: list persisted answer runs"
```

## Task 2: 恢复已完成回答并增加批次选择

**Files:**
- Modify: `tests/test_test_run_flow.py`
- Modify: `src/ui/test_run.py`

- [ ] **Step 1: 写入恢复策略与页面接线失败测试**

在 `tests/test_test_run_flow.py` 的 import 列表加入
`resolve_persisted_answer_run_id`，并增加：

```python
class PersistedAnswerRecoveryTests(unittest.TestCase):
    def test_run_selection_prefers_explicit_selection_then_current_then_latest(self):
        runs = [{"run_id": "RUN-NEW"}, {"run_id": "RUN-OLD"}]

        self.assertEqual(
            "RUN-OLD",
            resolve_persisted_answer_run_id(
                runs,
                selected_run_id="RUN-OLD",
                current_run_id="RUN-NEW",
            ),
        )
        self.assertEqual(
            "RUN-NEW",
            resolve_persisted_answer_run_id(
                runs,
                selected_run_id="missing",
                current_run_id="RUN-NEW",
            ),
        )
        self.assertEqual(
            "RUN-NEW",
            resolve_persisted_answer_run_id(runs),
        )

    def test_page_restores_persisted_answers_before_checkpoint_resume_gate(self):
        source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
        selector_source = source[
            source.index("def _render_persisted_answer_run_selector"):
            source.index("def _recover_persisted_run")
        ]
        recovery_source = source[
            source.index("def _recover_persisted_run"):
            source.index("def _recover_latest_score")
        ]

        self.assertIn("er.list_persisted_answer_runs()", selector_source)
        self.assertIn('"查看持久化批次"', selector_source)
        self.assertIn("er.restore_compare_result_from_db(run_id)", recovery_source)
        self.assertIn("resume_allowed", recovery_source)
        self.assertLess(
            recovery_source.index("er.restore_compare_result_from_db(run_id)"),
            recovery_source.index("_checkpoint_matches_current"),
        )
        self.assertNotIn(
            "if not _checkpoint_matches_current",
            recovery_source,
        )
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
.venv/bin/pytest -q tests/test_test_run_flow.py::PersistedAnswerRecoveryTests
```

Expected: FAIL，提示选择函数或页面恢复函数不存在。

- [ ] **Step 3: 实现批次选择纯函数**

在 `src/ui/test_run.py` 的常量区增加：

```python
_ANSWER_RUN_ID_KEY = "test_run_answer_run_id"
```

并增加：

```python
def resolve_persisted_answer_run_id(
    run_summaries: list[dict],
    *,
    selected_run_id: str = "",
    current_run_id: str = "",
) -> str:
    available = [
        str(row.get("run_id") or "").strip()
        for row in run_summaries or []
        if str(row.get("run_id") or "").strip()
    ]
    selected = str(selected_run_id or "").strip()
    current = str(current_run_id or "").strip()
    if selected in available:
        return selected
    if current in available:
        return current
    return available[0] if available else ""


def _persisted_run_option_label(summary: dict) -> str:
    created_at = str(summary.get("created_at") or "")[:19].replace("T", " ")
    return (
        f"{created_at or '时间未记录'}｜"
        f"{int(summary.get('model_count') or 0)} 个模型｜"
        f"{int(summary.get('case_count') or 0)} 个样本｜"
        f"{int(summary.get('response_count') or 0)} 条回答"
    )
```

- [ ] **Step 4: 实现只读恢复与续跑权限分离**

把 `_set_run_state()` 增加可选参数并保存：

```python
def _set_run_state(
    *,
    status: str,
    run_id: str,
    provider: str,
    model_ids: list[str],
    mode: str,
    created_at: str,
    queue_items: list[dict],
    outcomes: list[er.RunOutcome],
    message: str = "",
    resume_allowed: bool = True,
) -> None:
    st.session_state[_RUN_STATE_KEY] = {
        "status": status,
        "run_id": run_id,
        "provider": provider,
        "model_ids": list(model_ids),
        "mode": mode,
        "created_at": created_at,
        "queue_items": list(queue_items),
        "message": message,
        "resume_allowed": bool(resume_allowed),
    }
    st.session_state[_PARTIAL_OUTCOMES_KEY] = list(outcomes)
    st.session_state[_LAST_RUN_STATUS_KEY] = status
```

增加选择器与恢复函数：

```python
def _render_persisted_answer_run_selector(result) -> str:
    summaries = er.list_persisted_answer_runs()
    if not summaries:
        return ""
    current_run_id = str(getattr(result, "run_id", "") or "")
    selected_run_id = resolve_persisted_answer_run_id(
        summaries,
        selected_run_id=str(st.session_state.get(_ANSWER_RUN_ID_KEY) or ""),
        current_run_id=current_run_id,
    )
    if st.session_state.get(_ANSWER_RUN_ID_KEY) not in {
        str(row.get("run_id") or "") for row in summaries
    }:
        st.session_state[_ANSWER_RUN_ID_KEY] = selected_run_id
    by_id = {str(row["run_id"]): row for row in summaries}
    return st.selectbox(
        "查看持久化批次",
        options=list(by_id),
        format_func=lambda run_id: _persisted_run_option_label(by_id[run_id]),
        key=_ANSWER_RUN_ID_KEY,
    )


def _recover_persisted_run(run_id: str, task_records: list[dict]) -> object | None:
    rows = er.load_run_queue(run_id)
    result = er.restore_compare_result_from_db(run_id)
    if result is None:
        return None

    queue_items = _run_queue_items_from_rows(rows, task_records)
    model_ids = _dedupe(
        [str(row.get("model_id") or "") for row in rows]
        or list(getattr(result, "model_ids", ()) or ())
    )
    provider = str(
        (rows[0].get("provider") if rows else "")
        or getattr(result, "provider", "")
    )
    current_metadata = _run_checkpoint_metadata(
        run_id,
        provider,
        model_ids,
        queue_items,
        _EVAL_TEMPERATURE_DEFAULT,
        resolve_eval_max_tokens(),
    )
    resume_allowed = bool(rows) and _checkpoint_matches_current(
        er.load_run_metadata(run_id),
        current_metadata,
    )
    summary = er.summarize_run_queue(run_id)
    status = "interrupted" if summary.get("unfinished") else "completed"
    eval_state.set_last_run(result)
    _set_run_state(
        status=status,
        run_id=run_id,
        provider=provider,
        model_ids=model_ids,
        mode=str(getattr(result, "mode", "") or "live"),
        created_at=str(
            (rows[0].get("created_at") if rows else "")
            or getattr(result, "created_at", "")
            or datetime.now().isoformat(timespec="seconds")
        ),
        queue_items=queue_items,
        outcomes=list(getattr(result, "outcomes", ()) or ()),
        message="检测到持久化运行记录。已完成结果会保留，未完成项可稍后继续。",
        resume_allowed=resume_allowed,
    )
    st.session_state["test_run_persisted"] = True
    return result
```

将 `_recover_latest_run()` 改为从 `list_persisted_answer_runs()` 取最新
`run_id` 并调用 `_recover_persisted_run()`，删除 checkpoint 不一致时直接
`return None` 的分支。

- [ ] **Step 5: 接入“模型回答”区域并保护不兼容续跑**

在 `_render_results()` 开头：

```python
result = eval_state.get_last_run()
selected_run_id = _render_persisted_answer_run_selector(result)
if selected_run_id and selected_run_id != str(getattr(result, "run_id", "") or ""):
    result = _recover_persisted_run(selected_run_id, task_records)
state = _run_state()
if result is None and not state:
    result = _recover_latest_run(task_records)
    state = _run_state()
```

在 `_render_unfinished_run_without_result()` 与 `_render_partial_run_notice()`
中读取：

```python
resume_allowed = bool(state.get("resume_allowed", True))
if not resume_allowed:
    st.caption("当前运行可查看已保存回答，但运行元数据与当前任务不一致，不能继续未完成项。")
```

把“继续未完成项”和“重试失败项”的 `disabled` 条件分别改为：

```python
disabled=not queue_items or not resume_allowed
```

和：

```python
disabled=not remaining or not resume_allowed
disabled=not failed_items or not resume_allowed
```

在新运行完成并准备 `st.rerun()` 前写入：

```python
st.session_state[_ANSWER_RUN_ID_KEY] = run_id
```

确保新生成运行在下一次渲染时成为默认选择。

- [ ] **Step 6: 运行测试并确认 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_test_run_flow.py::PersistedAnswerRecoveryTests \
  tests/test_test_run_flow.py::TestRunFlowStructureTests
```

Expected: PASS。

- [ ] **Step 7: 提交页面恢复改动**

```bash
git add src/ui/test_run.py tests/test_test_run_flow.py
git commit -m "fix: restore persisted answers after restart"
```

## Task 3: 按运行、样本和模型连接回答

**Files:**
- Modify: `tests/test_conclusions.py`
- Modify: `app/services/conclusions.py`

- [ ] **Step 1: 写入精确连接失败测试**

在 `tests/test_conclusions.py` 增加：

```python
class AnswerDetailJoinTests(unittest.TestCase):
    def test_answers_join_by_run_case_and_model_without_cross_run_leakage(self):
        scores = pd.DataFrame([
            _cohort_score(
                1,
                "RUN-A",
                "C1",
                "same-model",
                updated_at="2026-07-16T11:00:00",
                total_score=81,
            ),
            _cohort_score(
                2,
                "RUN-B",
                "C1",
                "same-model",
                updated_at="2026-07-17T11:00:00",
                total_score=92,
            ),
        ])
        responses = pd.DataFrame([
            {
                "run_id": "RUN-A",
                "case_id": "C1",
                "model_name": "same-model",
                "answer_text": "回答 A",
            },
            {
                "run_id": "RUN-B",
                "case_id": "C1",
                "model_name": "same-model",
                "answer_text": "回答 B",
            },
        ])

        rows = cc.build_answer_detail_rows(scores, responses)

        by_run = {row["run_id"]: row for row in rows}
        self.assertEqual("回答 A", by_run["RUN-A"]["answer_text"])
        self.assertEqual("回答 B", by_run["RUN-B"]["answer_text"])
        self.assertEqual(81.0, by_run["RUN-A"]["total_score"])
        self.assertEqual(92.0, by_run["RUN-B"]["total_score"])

    def test_missing_answer_stays_visible_as_empty_detail(self):
        scores = pd.DataFrame([
            _cohort_score(
                1,
                "RUN-A",
                "C1",
                "model-a",
                updated_at="2026-07-16T11:00:00",
            )
        ])

        rows = cc.build_answer_detail_rows(scores, pd.DataFrame())

        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["answer_text"])
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
.venv/bin/pytest -q tests/test_conclusions.py::AnswerDetailJoinTests
```

Expected: FAIL，提示 `build_answer_detail_rows` 不存在。

- [ ] **Step 3: 实现回答明细构建器**

在 `app/services/conclusions.py` 增加：

```python
def build_answer_detail_rows(
    scores_df: pd.DataFrame,
    responses_df: pd.DataFrame | None,
    *,
    mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(scores_df, pd.DataFrame) or scores_df.empty:
        return []
    answers = _index_answers(responses_df)
    rows: list[dict[str, Any]] = []
    for _, score in scores_df.iterrows():
        run_id = _text(score.get("run_id"))
        case_id = _text(score.get("case_id"))
        model_name = _text(score.get("eval_model"))
        key = (run_id, case_id, model_name)
        rows.append(
            {
                "run_id": run_id,
                "case_id": case_id,
                "model_name": model_name,
                "display_name": display_model_name(
                    model_name,
                    mapping,
                    source="live",
                ),
                "total_score": _num(score.get("total_score")),
                "answer_text": _text(answers.get(key)),
            }
        )
    rows.sort(
        key=lambda row: (
            row["display_name"],
            row["case_id"],
            row["run_id"],
        )
    )
    return rows
```

复用现有 `_index_answers()`，确保连接键保持
`(run_id, case_id, model_name)`。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_conclusions.py::AnswerDetailJoinTests
```

Expected: PASS。

- [ ] **Step 5: 提交回答连接服务**

```bash
git add app/services/conclusions.py tests/test_conclusions.py
git commit -m "feat: join persisted answers to current scores"
```

## Task 4: 在评测结论页展示对应回答

**Files:**
- Modify: `tests/test_conclusions.py`
- Modify: `src/ui/conclusions.py`

- [ ] **Step 1: 写入结论页接线失败测试**

在 `AnswerDetailJoinTests` 增加：

```python
    def test_conclusion_page_loads_and_renders_persisted_answers(self):
        source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
        render_source = source[
            source.index("def render_conclusions_page"):
            source.index("# --------------------------------------------------------------------------- #")
        ]
        detail_source = source[
            source.index("def _render_model_issue_details"):
        ]

        self.assertIn("cc.load_live_responses()", render_source)
        self.assertIn("cc.build_answer_detail_rows", render_source)
        self.assertIn("answer_rows", render_source)
        self.assertIn('"选择样本查看回答"', detail_source)
        self.assertIn("render_markdown_detail_panel", detail_source)
        self.assertIn('row.get("answer_text")', detail_source)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_conclusions.py::AnswerDetailJoinTests::test_conclusion_page_loads_and_renders_persisted_answers
```

Expected: FAIL，因为结论页尚未读取回答。

- [ ] **Step 3: 接入回答数据**

在 `render_conclusions_page()` 中增加：

```python
live_responses = cc.load_live_responses()
answer_rows = cc.build_answer_detail_rows(ai_scores, live_responses)
```

并把：

```python
_render_model_issue_details(model_summaries)
```

改为：

```python
_render_model_issue_details(model_summaries, answer_rows)
```

- [ ] **Step 4: 增加当前模型回答查看器**

把详情函数签名改为：

```python
def _render_model_issue_details(
    model_summaries: list[dict],
    answer_rows: list[dict],
) -> None:
```

在 `_render_issue_markdown(selected)` 后调用：

```python
_render_model_answer_details(selected, answer_rows)
```

并增加：

```python
def _render_model_answer_details(
    selected_model: dict,
    answer_rows: list[dict],
) -> None:
    model_name = str(selected_model.get("model_name") or "")
    rows = [
        row
        for row in answer_rows
        if str(row.get("model_name") or "") == model_name
    ]
    if not rows:
        st.caption("当前模型暂无可查看的持久化回答。")
        return

    selected_index = st.selectbox(
        "选择样本查看回答",
        options=list(range(len(rows))),
        format_func=lambda index: (
            f"{rows[index]['case_id']}｜{_answer_score_label(rows[index])}"
        ),
        key=f"conclusion_answer_select_{_safe_key(model_name)}",
    )
    row = rows[int(selected_index)]
    answer_text = str(row.get("answer_text") or "").strip()
    render_markdown_detail_panel(
        title=f"{row['case_id']}｜{row['display_name']}",
        meta=f"运行批次：{row['run_id']}",
        markdown_text=(
            f"**模型回答**\n\n{answer_text}"
            if answer_text
            else "**模型回答**\n\n暂无模型回答。"
        ),
    )


def _answer_score_label(row: dict) -> str:
    value = row.get("total_score")
    return "未评分" if value is None else f"{float(value):.0f}分"


def _safe_key(value: object) -> str:
    text = str(value or "")
    return "".join(char if char.isalnum() else "_" for char in text)
```

- [ ] **Step 5: 运行结论测试并确认 GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_conclusions.py tests/test_ui_refactor.py
```

Expected: PASS。

- [ ] **Step 6: 提交结论页回答入口**

```bash
git add src/ui/conclusions.py tests/test_conclusions.py
git commit -m "feat: show persisted answers in conclusions"
```

## Task 5: 完整回归和 PostgreSQL 只读验收

**Files:**
- Verify: `app/services/eval_runner.py`
- Verify: `src/ui/test_run.py`
- Verify: `app/services/conclusions.py`
- Verify: `src/ui/conclusions.py`
- Verify: PostgreSQL/Supabase runtime tables

- [ ] **Step 1: 运行目标测试**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_live_results.py \
  tests/test_test_run_flow.py \
  tests/test_conclusions.py \
  tests/test_ui_refactor.py
```

Expected: PASS。

- [ ] **Step 2: 运行全量测试、Ruff 与数据集校验**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . --exclude .claude
.venv/bin/python scripts/validate_dataset.py
```

Expected:

- pytest 全部通过；仅允许现有 PostgreSQL 条件跳过；
- Ruff 无错误；
- 数据集 20 项检查全部通过，无错误。

- [ ] **Step 3: 对 PostgreSQL 做只读行数与内容摘要验证**

Run:

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
import os
import tomllib
from collections import Counter
from pathlib import Path

from app.persistence import get_result_store
from app.services import eval_runner as er

secrets = tomllib.loads(
    Path(".streamlit/secrets.toml").read_text(encoding="utf-8")
)
database_url = str(
    secrets.get("DATABASE_URL")
    or (secrets.get("database") or {}).get("url")
    or ""
)
assert database_url
os.environ["DATABASE_URL"] = database_url
store = get_result_store(secrets=secrets)
assert store.is_postgresql
assert store.ping()

responses = store.list_rows("live_run_responses")
scores = store.list_rows("live_run_scores")
payload = sorted(
    (
        str(row.get("run_id") or ""),
        str(row.get("case_id") or ""),
        str(row.get("model_name") or ""),
        str(row.get("answer_text") or ""),
    )
    for row in responses
)
digest = hashlib.sha256(
    json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

counts = Counter(str(row.get("run_id") or "") for row in responses)
assert counts == {
    "FRESH-20260717-CURRENT13-V1": 39,
    "EXTEND-20260717-DIVERSE2-V1": 26,
}
assert len(responses) == 65
assert all(str(row.get("answer_text") or "").strip() for row in responses)
assert len(scores) >= 65
assert digest == "1337f91818d2f67b07ed7b57d37de9d085c46edac8ca02507d5f7954ad4e642f"
for run_id, expected in counts.items():
    restored = er.restore_compare_result_from_db(run_id)
    assert restored is not None
    assert len(restored.outcomes) == expected
print({
    "responses": len(responses),
    "nonempty": 65,
    "runs": dict(counts),
    "digest_prefix": digest[:12],
})
PY
```

Expected: 输出 65 条回答、两个批次数量为 39/26、回答全部非空。不得打印
数据库 URL、API Key 或回答正文；完整内容摘要必须仍为
`1337f91818d2f67b07ed7b57d37de9d085c46edac8ca02507d5f7954ad4e642f`。

- [ ] **Step 4: 验证当前兼容结论仍为 65 条**

Run:

```bash
.venv/bin/python - <<'PY'
import tomllib
from pathlib import Path

from app.persistence import get_result_store
from app.services.conclusions import select_current_cohort_scores
import pandas as pd

secrets = tomllib.loads(
    Path(".streamlit/secrets.toml").read_text(encoding="utf-8")
)
store = get_result_store(secrets=secrets)
runs = pd.DataFrame(store.list_rows("live_evaluation_runs"))
scores = pd.DataFrame(store.list_rows("live_run_scores"))
current = select_current_cohort_scores(runs, scores)
assert len(current) == 65
assert current["case_id"].nunique() == 13
assert current["eval_model"].nunique() == 5
print({"rows": 65, "cases": 13, "models": 5})
PY
```

Expected: `{"rows": 65, "cases": 13, "models": 5}`。

- [ ] **Step 5: 最终敏感信息和工作区检查**

Run:

```bash
git status --short
git diff --check
git ls-files .streamlit/secrets.toml .env .claude
git log --oneline --decorate -8
```

Expected:

- `.claude/` 仍为用户未跟踪目录且未被提交；
- `.streamlit/secrets.toml`、`.env` 和 `.claude/` 均不在 git 跟踪列表；
- 无数据库密码、API Key 或回答正文进入提交。

- [ ] **Step 6: 提交必要的验证修复**

如果前述验证不需要改代码，不创建空提交。若必须修复，只提交本功能相关文件：

```bash
git add \
  app/services/eval_runner.py \
  app/services/conclusions.py \
  src/ui/test_run.py \
  src/ui/conclusions.py \
  tests/test_live_results.py \
  tests/test_test_run_flow.py \
  tests/test_conclusions.py \
  tests/test_ui_refactor.py
git commit -m "test: verify persisted answer recovery"
```

提交前再次运行 Task 5 Step 1–5。
