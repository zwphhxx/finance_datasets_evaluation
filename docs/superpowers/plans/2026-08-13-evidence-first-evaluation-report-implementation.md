# 证据优先的专业模型评测报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有四页 Streamlit 项目改造成结论默认、证据可追溯的专业评测报告，并把回答与评分合并为一次可持久化、可安全续跑的真实评测。

**Architecture:** 保留现有 PostgreSQL／Supabase 五张运行表、模型供应商、评分模型和专业数据，新增统一正式记录策略、同步 `EvaluationWorkflow` 编排器和只读证据索引。Streamlit 只负责配置、显示进度和发出“开始／继续评测”意图；报告页面共用无卡片化排版组件，批次和结果始终以数据库为真源。

**Tech Stack:** Python 3.13、Streamlit 1.51、SQLAlchemy 2、psycopg 3、pandas、pytest/unittest、Streamlit AppTest、Ego Browser。

---

## 实施边界

- 设计规格：`docs/superpowers/specs/2026-08-13-evidence-first-evaluation-report-design.md`。
- 不修改评分维度、分值、阈值、裁判模型、被测模型提示词或专业内容。
- 不删除 Supabase 中任何既有正式或历史演示记录。
- 删除产品中的演示模式、演示恢复和独立评分入口；内部假模型只用于自动测试。
- 不新增数据库表或列；复用 `live_evaluation_runs`、`live_run_queue`、`live_run_responses`、`live_score_queue`、`live_run_scores`。
- 测试不得访问真实模型服务或正式 Supabase。
- 实施时在 `codex/evidence-first-evaluation-report` 隔离分支或 worktree 中进行；现有未跟踪 `.claude/` 不纳入任何提交。

## 接口约定

- `EvaluationWorkflow.start_evaluation(config) -> EvaluationRunRef`：只用于新批次；在两类队列原子写入后同步执行，结束时返回同一 `run_id/score_run_id` 引用。
- `EvaluationWorkflow.continue_evaluation(run_id, config) -> EvaluationRunStatus`：只在用户点击继续后调用；未取得原子运行权时只返回最新状态。
- `EvaluationWorkflow.load_evaluation_status(run_id) -> EvaluationRunStatus`：纯读取，不改数据库、不调用模型。
- `FormalRecordPolicy` 以 `filter_formal_responses()`、`filter_formal_scores()` 两个纯函数体现，不增加有状态配置对象。
- `ConclusionReadModel` 只接受 DataFrame／映射并返回 `ConclusionReport`；数据库异常由 `ConclusionSource` 明确区分，不把不可用伪装成空结果。

## 文件结构与职责

### 新增文件

- `app/services/formal_records.py`：唯一正式记录策略；过滤 mock、demo、失败、停用、越界和无真实回答的记录，同时供结论、范围计数、详情、导出和恢复候选读取调用。
- `app/services/evaluation_workflow.py`：一次完成回答、自动评分、持久化、状态归并和安全续跑。
- `app/services/conclusion_read_model.py`：将正式评分、回答、样本和 Gold 投影为报告数据。
- `app/services/evidence_index.py`：按确定规则选择最多 3 个代表样本并建立证据链接。
- `src/ui/report_styles.py`：中文研究简报的桌面与移动端 CSS；不包含业务数据逻辑。
- `src/ui/report_components.py`：报告眉头、范围台账、审阅表、证据索引和状态台账 HTML 原语。
- `src/ui/evaluation_config.py`：样本／模型选择、运行规模和提示词预览。
- `src/ui/evaluation_results.py`：组合批次状态、运行记录、回答与评分详情、技术明细。
- `tests/test_formal_records.py`：正式记录与历史演示排除。
- `tests/test_evaluation_workflow.py`：单入口评测、增量持久化、失败和恢复。
- `tests/test_evidence_index.py`：代表样本确定性和证据连接。
- `tests/test_report_experience.py`：默认入口、导航分层、无卡片报告结构和产品入口守卫。

### 重点修改文件

- `app/persistence/result_store.py`：原子初始化两类队列、批次领取、心跳、停止和组合快照。
- `app/services/eval_runner.py`：公开回答结果序列化函数，保留现有调用逻辑。
- `app/services/scorer.py`：公开评分结果序列化函数；删除演示导入产品函数。
- `app/services/conclusions.py`：使用统一正式记录策略，不再自行维护第二套过滤条件。
- `src/ui/test_run.py`：缩为评测操作页协调器，只呈现配置和一个开始／继续动作；现有导入／导出和技术维护能力全部收进“评测维护”次级 Popover。
- `src/ui/conclusions.py`：结论默认首页、执行摘要、审阅表和证据索引。
- `src/ui/samples.py`：专业样本索引与样本档案；桌面／手机共用一套行数据。
- `src/ui/case_study.py`：项目说明作为方法附录，原文不变。
- `src/ui/navigation.py`、`src/ui/page_config.py`：结论默认入口，三项审阅导航加一次级评测操作。
- `src/ui/components.py`、`src/ui/responsive.py`：接入报告样式，删除卡片式选择器和旧阶段样式。
- `README.md`：记录真实自动评测和恢复方式，不再宣传演示模式。

---

## Milestone A：正式数据与可靠评测编排

> 开始本里程碑前先执行 Task 13 Step 2 的只读 SQL，并保存三项计数作为数据不变量基线；该动作不调用模型、不写数据库。

### Task 1: 建立唯一正式记录策略并永久排除历史演示记录

**Files:**
- Create: `app/services/formal_records.py`
- Modify: `app/services/conclusions.py`
- Modify: `app/services/scorer.py`
- Test: `tests/test_formal_records.py`
- Test: `tests/test_conclusions.py`
- Test: `tests/test_scoring_workflow.py`
- Test: `tests/test_repository_readiness.py`

- [ ] **Step 1: 写入正式记录策略的失败测试**

创建 `tests/test_formal_records.py`：

```python
import pandas as pd

from app.services.formal_records import (
    filter_formal_responses,
    filter_formal_score_rows,
    filter_formal_scores,
)


def _response(run_id="RUN-1", *, mode="live", status="success", provider="siliconflow"):
    return {
        "run_id": run_id,
        "case_id": "C1",
        "model_name": "vendor/model-a",
        "run_mode": mode,
        "run_status": status,
        "provider": provider,
        "status": "active",
        "answer_text": "回答",
    }


def _score(run_id="RUN-1", *, mode="live", status="success", review="ai_final"):
    return {
        "run_id": run_id,
        "score_run_id": f"SCORE-{run_id}",
        "case_id": "C1",
        "eval_model": "vendor/model-a",
        "judge_mode": mode,
        "judge_status": status,
        "review_status": review,
        "status": "active",
        "total_score": 80,
    }


def test_formal_scores_require_matching_live_success_response():
    scores = pd.DataFrame([_score()])
    responses = pd.DataFrame([_response()])

    result = filter_formal_scores(scores, responses, allowed_case_ids={"C1"})

    assert result["run_id"].tolist() == ["RUN-1"]


def test_score_and_response_model_ids_must_match_exactly():
    scores = pd.DataFrame([{**_score(), "eval_model": "Qwen3-32B"}])
    responses = pd.DataFrame([{**_response(), "model_name": "Qwen/Qwen3-32B"}])

    result = filter_formal_scores(scores, responses, allowed_case_ids={"C1"})

    assert result.empty


def test_demo_mock_failed_inactive_skipped_and_out_of_scope_rows_are_excluded():
    scores = pd.DataFrame([
        _score("LIVE"),
        _score("DEMO", mode="demo"),
        _score("MOCK", mode="mock"),
        _score("FAILED", status="failed"),
        {**_score("SKIPPED"), "review_status": "skipped"},
        {**_score("INACTIVE"), "status": "inactive"},
        {**_score("OUTSIDE"), "case_id": "C9"},
    ])
    responses = pd.DataFrame([
        _response("LIVE"),
        _response("DEMO", mode="demo", provider="demo"),
        _response("MOCK", mode="mock", provider="mock"),
        _response("FAILED"),
        _response("SKIPPED"),
        _response("INACTIVE"),
        {**_response("OUTSIDE"), "case_id": "C9"},
    ])

    result = filter_formal_scores(scores, responses, allowed_case_ids={"C1"})

    assert result["run_id"].tolist() == ["LIVE"]


def test_formal_responses_hide_historical_demo_rows():
    rows = pd.DataFrame([
        _response("LIVE"),
        _response("DEMO", mode="demo", provider="demo"),
        _response("MOCK", mode="mock", provider="mock"),
    ])

    result = filter_formal_responses(rows, allowed_case_ids={"C1"})

    assert result["run_id"].tolist() == ["LIVE"]


def test_export_policy_requires_matching_live_response():
    scores = pd.DataFrame([_score("LIVE"), _score("ORPHAN")])
    responses = pd.DataFrame([_response("LIVE")])

    result = filter_formal_score_rows(scores, responses, allowed_case_ids={"C1"})

    assert [row["run_id"] for row in result] == ["LIVE"]


def test_recovery_candidates_exclude_demo_and_mock_runs():
    rows = pd.DataFrame([
        _response("LIVE"),
        _response("DEMO", mode="demo", provider="demo"),
        _response("MOCK", mode="mock", provider="mock"),
    ])

    assert filter_formal_responses(rows)["run_id"].tolist() == ["LIVE"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_formal_records.py
```

Expected: FAIL，`app.services.formal_records` 不存在。

- [ ] **Step 3: 实现纯函数正式记录策略**

创建 `app/services/formal_records.py`：

```python
from __future__ import annotations

from collections.abc import Collection

import pandas as pd

from app.services import model_display as md

EXCLUDED_MODES = frozenset({"mock", "demo"})
EXCLUDED_PROVIDERS = frozenset({"mock", "demo"})
EXCLUDED_REVIEW_STATUSES = frozenset({"skipped"})


def _text_series(frame: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="object")
    return frame[column].fillna(default).astype(str).str.strip()


def _provider_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(True, index=frame.index, dtype=bool)
    return ~_text_series(frame, column).str.lower().isin(EXCLUDED_PROVIDERS)


def _scope_mask(frame: pd.DataFrame, allowed_case_ids: Collection[str] | None) -> pd.Series:
    if allowed_case_ids is None:
        return pd.Series(True, index=frame.index, dtype=bool)
    allowed = {str(value).strip() for value in allowed_case_ids if str(value).strip()}
    return _text_series(frame, "case_id").isin(allowed)


def formal_response_mask(
    responses: pd.DataFrame,
    *,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.Series:
    if not isinstance(responses, pd.DataFrame) or responses.empty:
        return pd.Series(False, index=getattr(responses, "index", None), dtype=bool)
    return (
        (_text_series(responses, "status", "active").str.lower() != "inactive")
        & (_text_series(responses, "run_status").str.lower() == "success")
        & (~_text_series(responses, "run_mode", "live").str.lower().isin(EXCLUDED_MODES))
        & _provider_mask(responses, "provider")
        & (~_text_series(responses, "model_name").map(md.is_seed_model))
        & (_text_series(responses, "run_id") != "")
        & (_text_series(responses, "answer_text") != "")
        & _scope_mask(responses, allowed_case_ids)
    )


def filter_formal_responses(
    responses: pd.DataFrame,
    *,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.DataFrame:
    if not isinstance(responses, pd.DataFrame):
        return pd.DataFrame()
    return responses[formal_response_mask(responses, allowed_case_ids=allowed_case_ids)].copy()


def formal_score_mask(
    scores: pd.DataFrame,
    responses: pd.DataFrame | None = None,
    *,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.Series:
    if not isinstance(scores, pd.DataFrame) or scores.empty:
        return pd.Series(False, index=getattr(scores, "index", None), dtype=bool)
    mask = (
        (_text_series(scores, "status", "active").str.lower() != "inactive")
        & (_text_series(scores, "judge_status").str.lower() == "success")
        & (~_text_series(scores, "judge_mode", "live").str.lower().isin(EXCLUDED_MODES))
        & _provider_mask(scores, "judge_provider")
        & (~_text_series(scores, "review_status", "ai_final").str.lower().isin(EXCLUDED_REVIEW_STATUSES))
        & (~_text_series(scores, "eval_model").map(md.is_seed_model))
        & (_text_series(scores, "run_id") != "")
        & _scope_mask(scores, allowed_case_ids)
    )
    if isinstance(responses, pd.DataFrame):
        live = filter_formal_responses(responses, allowed_case_ids=allowed_case_ids)
        keys = set(zip(
            _text_series(live, "run_id"),
            _text_series(live, "case_id"),
            _text_series(live, "model_name"),
        ))
        score_keys = list(zip(
            _text_series(scores, "run_id"),
            _text_series(scores, "case_id"),
            _text_series(scores, "eval_model"),
        ))
        mask &= pd.Series([key in keys for key in score_keys], index=scores.index)
    return mask


def filter_formal_scores(
    scores: pd.DataFrame,
    responses: pd.DataFrame | None = None,
    *,
    allowed_case_ids: Collection[str] | None = None,
) -> pd.DataFrame:
    if not isinstance(scores, pd.DataFrame):
        return pd.DataFrame()
    return scores[
        formal_score_mask(scores, responses, allowed_case_ids=allowed_case_ids)
    ].copy()


def filter_formal_score_rows(
    scores: pd.DataFrame,
    responses: pd.DataFrame,
    *,
    allowed_case_ids: Collection[str] | None = None,
) -> list[dict]:
    return filter_formal_scores(
        scores,
        responses,
        allowed_case_ids=allowed_case_ids,
    ).to_dict("records")
```

修改 `app/services/conclusions.py`：`_successful_conclusion_score_mask()` 和 `split_live_scores()` 调用 `formal_score_mask()`；`load_live_responses()` 返回 `filter_formal_responses()`。在 `app/services/scorer.py` 的 `load_exportable_score_rows()` 中同时加载 `live_run_responses`，调用 `filter_formal_score_rows(pd.DataFrame(score_rows), pd.DataFrame(response_rows))` 后再做 `_score_export_row()` 投影，保证导出也要求同一真实成功回答。`eval_runner.build_persisted_answer_run_summaries()` 和评测页恢复候选根据 run metadata 的 `provider`，以及已持久化回答的 `run_mode/provider`，排除 demo/mock run；成功回答仍使用 `filter_formal_responses()`。即使历史批次仍为 queued、尚无 response，也不能因缺少回答而被误当成正式恢复候选。

- [ ] **Step 4: 从产品路径移除演示恢复入口**

从 `app/services/scorer.py` 删除：

```python
DEMO_AI_SCORE_EXPORT_PATH
load_demo_score_export_payload
import_demo_ai_scores
```

保留 `data/demo_exports/demo_ai_scores.json` 作为不再引用的历史仓库资产，避免把“产品不再提供演示恢复”误做成历史数据清理。将 `tests/test_repository_readiness.py` 中的演示文件内容测试改为产品引用守卫：

```python
def test_product_code_does_not_reference_demo_score_restore_asset() -> None:
    product_source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (ROOT / "app" / "services", ROOT / "src")
        for path in root.rglob("*.py")
    )
    assert "demo_ai_scores.json" not in product_source
    assert "import_demo_ai_scores" not in product_source
```

删除 `tests/test_scoring_workflow.py` 中只覆盖上述两个演示导入函数的测试；保留 MockProvider 单元测试，因为它们是隔离测试替身，不是产品模式。

- [ ] **Step 5: 运行相关测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_formal_records.py tests/test_conclusions.py tests/test_scoring_workflow.py tests/test_repository_readiness.py
```

Expected: PASS；正式结果中不出现 `judge_mode=demo/mock`，产品代码不再引用演示恢复资产；历史 JSON 和数据库记录均未被删除。

- [ ] **Step 6: 提交**

```bash
git add app/services/formal_records.py app/services/conclusions.py app/services/scorer.py tests/test_formal_records.py tests/test_conclusions.py tests/test_scoring_workflow.py tests/test_repository_readiness.py
git commit -m "refactor: centralize formal evaluation records"
```

### Task 2: 为单入口评测补齐原子队列和批次领取能力

**Files:**
- Modify: `app/persistence/result_store.py`
- Modify: `app/services/eval_runner.py`
- Modify: `app/services/scorer.py`
- Test: `tests/test_result_store.py`
- Test: `tests/test_result_store_postgres.py`

- [ ] **Step 1: 写入原子初始化、停止和领取的失败测试**

在 `tests/test_result_store.py` 增加：

```python
from datetime import datetime, timedelta


def score_queue_row(run_id="RUN-1", score_run_id="SCORE-1") -> dict:
    return {
        "score_run_id": score_run_id,
        "run_id": run_id,
        "case_id": "FD-001",
        "task_type": "Financial Judgment",
        "eval_model": "m1",
        "judge_model": "judge",
        "judge_provider": "siliconflow",
        "status": "queued",
        "attempt_count": 0,
    }


def live_run_metadata(run_id: str = "RUN-1") -> dict:
    return {**run_metadata(run_id), "provider": "siliconflow"}


def successful_response_row() -> dict:
    return {
        "run_id": "RUN-1",
        "case_id": "FD-001",
        "task_type": "Financial Judgment",
        "provider": "siliconflow",
        "model_name": "m1",
        "run_mode": "live",
        "run_status": "success",
        "answer_text": "saved",
    }


def successful_score_row() -> dict:
    return {
        "score_run_id": "SCORE-1",
        "run_id": "RUN-1",
        "case_id": "FD-001",
        "task_type": "Financial Judgment",
        "eval_model": "m1",
        "judge_provider": "siliconflow",
        "judge_model": "judge",
        "judge_mode": "live",
        "judge_status": "success",
        "total_score": 80,
        "review_status": "ai_final",
    }


def test_initialize_evaluation_creates_run_and_both_queues_atomically(tmp_path):
    store = sqlite_store(tmp_path)

    assert store.initialize_evaluation(
        live_run_metadata(), [run_queue_row()], [score_queue_row()]
    ) is True

    assert len(store.list_rows("live_evaluation_runs", run_id="RUN-1")) == 1
    assert len(store.list_rows("live_run_queue", run_id="RUN-1")) == 1
    assert len(store.list_rows("live_score_queue", run_id="RUN-1")) == 1


def test_initialize_evaluation_rejects_misaligned_pairs(tmp_path):
    store = sqlite_store(tmp_path)
    wrong = {**score_queue_row(), "eval_model": "m2"}

    with pytest.raises(ResultStoreError, match="aligned"):
        store.initialize_evaluation(live_run_metadata(), [run_queue_row()], [wrong])

    assert store.list_rows("live_evaluation_runs", run_id="RUN-1") == []


def test_failed_answer_can_skip_matching_score_item(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(live_run_metadata(), [run_queue_row()], [score_queue_row()])

    assert store.mark_score_item_skipped("SCORE-1", "FD-001", "m1", "answer_failed")

    row = store.list_rows("live_score_queue", score_run_id="SCORE-1")[0]
    assert row["status"] == "skipped"
    assert row["error_code"] == "answer_failed"


def test_stale_run_can_be_claimed_only_once(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(live_run_metadata(), [run_queue_row()], [score_queue_row()])
    stale_before = datetime.utcnow() + timedelta(seconds=1)

    assert store.claim_run("RUN-1", stale_before=stale_before) is True
    assert store.claim_run("RUN-1", stale_before=datetime.utcnow() - timedelta(hours=1)) is False


def test_successful_queue_rows_are_not_reset_by_reinitialization(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(live_run_metadata(), [run_queue_row()], [score_queue_row()])
    store.save_run_outcome(
        successful_response_row(), queue_status="success", combined=True
    )
    store.save_score_outcome(successful_score_row(), queue_status="success")

    store.initialize_evaluation(live_run_metadata(), [run_queue_row()], [score_queue_row()])

    assert store.list_rows("live_run_queue", run_id="RUN-1")[0]["status"] == "success"
    assert store.list_rows("live_score_queue", score_run_id="SCORE-1")[0]["status"] == "success"


def test_combined_answer_success_remains_running_until_score_finishes(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(live_run_metadata(), [run_queue_row()], [score_queue_row()])

    store.save_run_outcome(
        successful_response_row(), queue_status="success", combined=True
    )

    run = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]
    assert run["status"] == "running"
    assert run["pending_count"] == 1


def test_mark_run_stopped_records_persistence_error(tmp_path):
    store = sqlite_store(tmp_path)
    store.initialize_evaluation(live_run_metadata(), [run_queue_row()], [score_queue_row()])

    assert store.mark_run_stopped("RUN-1", "database write failed") is True

    row = store.list_rows("live_evaluation_runs", run_id="RUN-1")[0]
    assert row["status"] == "stopped"
    assert row["last_persistence_error"] == "database write failed"
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_result_store.py
```

Expected: FAIL，`ResultStore` 缺少组合初始化、跳过、停止和领取方法。

- [ ] **Step 3: 实现 `ResultStore` 原子能力**

在 `app/persistence/result_store.py` 将 SQLAlchemy 导入改为 `from sqlalchemy import and_, create_engine, func, inspect, or_, select, update`，并实现：

```python
def initialize_evaluation(self, run, answer_rows, score_rows) -> bool:
    run_row = self._validated(
        run,
        "live_evaluation_runs",
        ("run_id", "provider", "dataset_hash", "prompt_hash"),
    )
    answers = [
        self._validated(row, "live_run_queue", ("run_id", "case_id", "model_id"))
        for row in answer_rows
    ]
    scores = [
        self._validated(row, "live_score_queue", ("score_run_id", "case_id", "eval_model"))
        for row in score_rows
    ]
    answer_pairs = {(str(row["case_id"]), str(row["model_id"])) for row in answers}
    score_pairs = {(str(row["case_id"]), str(row["eval_model"])) for row in scores}
    run_ids = {str(row["run_id"]) for row in answers} | {
        str(row.get("run_id") or "") for row in scores
    }
    if (
        not answers
        or len(answers) != len(answer_pairs)
        or len(scores) != len(score_pairs)
        or answer_pairs != score_pairs
        or run_ids != {str(run_row["run_id"])}
    ):
        raise ResultStoreError("evaluation queues must be non-empty and aligned")
    try:
        with self.engine.begin() as connection:
            self._upsert(connection, live_evaluation_runs, run_row, update_existing=False)
            for row in answers:
                self._upsert(connection, live_run_queue, row, update_existing=False)
            for row in scores:
                self._upsert(connection, live_score_queue, row, update_existing=False)
            self._refresh_evaluation_counts(connection, str(run_row["run_id"]))
        return True
    except SQLAlchemyError as exc:
        raise ResultStoreError("could not initialize evaluation") from exc


def mark_score_item_skipped(
    self,
    score_run_id: str,
    case_id: str,
    eval_model: str,
    error_code: str,
) -> bool:
    try:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(live_score_queue)
                .where(
                    live_score_queue.c.score_run_id == score_run_id,
                    live_score_queue.c.case_id == case_id,
                    live_score_queue.c.eval_model == eval_model,
                )
                .values(
                    status="skipped",
                    error_code=error_code,
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise ResultStoreError("score queue item does not exist")
            run_id = connection.execute(
                select(live_score_queue.c.run_id).where(
                    live_score_queue.c.score_run_id == score_run_id,
                    live_score_queue.c.case_id == case_id,
                    live_score_queue.c.eval_model == eval_model,
                )
            ).scalar_one()
            self._refresh_evaluation_counts(connection, str(run_id))
        return True
    except SQLAlchemyError as exc:
        raise ResultStoreError("could not skip score item") from exc


def claim_run(self, run_id: str, *, stale_before) -> bool:
    try:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(live_evaluation_runs)
                .where(
                    live_evaluation_runs.c.run_id == run_id,
                    or_(
                        live_evaluation_runs.c.status.in_(("interrupted", "stopped")),
                        and_(
                            live_evaluation_runs.c.status == "running",
                            live_evaluation_runs.c.updated_at <= stale_before,
                        ),
                    ),
                )
                .values(status="running", last_persistence_error=None, updated_at=func.now())
            )
            return result.rowcount == 1
    except SQLAlchemyError as exc:
        raise ResultStoreError("could not claim evaluation run") from exc


def mark_run_interrupted_if_stale(self, run_id: str, *, stale_before) -> bool:
    try:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(live_evaluation_runs)
                .where(
                    live_evaluation_runs.c.run_id == run_id,
                    live_evaluation_runs.c.status == "running",
                    live_evaluation_runs.c.updated_at <= stale_before,
                )
                .values(status="interrupted", updated_at=func.now())
            )
            return result.rowcount == 1
    except SQLAlchemyError as exc:
        raise ResultStoreError("could not mark stale evaluation run") from exc


def mark_run_stopped(self, run_id: str, message: str) -> bool:
    try:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(live_evaluation_runs)
                .where(live_evaluation_runs.c.run_id == run_id)
                .values(
                    status="stopped",
                    last_persistence_error=str(message),
                    updated_at=func.now(),
                )
            )
            return result.rowcount == 1
    except SQLAlchemyError as exc:
        raise ResultStoreError("could not stop evaluation run") from exc
```

把现有 `_refresh_run_counts()` 重命名为兼容旧流程的 `_refresh_answer_counts()`，再新增回答／评分联合归并 `_refresh_evaluation_counts()`；`live_evaluation_runs` 的三个计数均以“样本 × 模型”计划项为单位：

```python
def _refresh_answer_counts(self, connection: Connection, run_id: str) -> None:
    statuses = connection.execute(
        select(live_run_queue.c.status, func.count().label("count"))
        .where(live_run_queue.c.run_id == run_id)
        .group_by(live_run_queue.c.status)
    ).all()
    counts = {str(status): int(count) for status, count in statuses}
    completed = counts.get("success", 0)
    failed = counts.get("failed", 0)
    pending = sum(counts.get(name, 0) for name in ("queued", "running"))
    connection.execute(
        update(live_evaluation_runs)
        .where(live_evaluation_runs.c.run_id == run_id)
        .values(
            completed_count=completed,
            failed_count=failed,
            pending_count=pending,
            status="completed" if pending == 0 else "running",
            updated_at=func.now(),
        )
    )


def _refresh_evaluation_counts(self, connection: Connection, run_id: str) -> None:
    answer_rows = connection.execute(
        select(
            live_run_queue.c.case_id,
            live_run_queue.c.model_id,
            live_run_queue.c.status,
        ).where(live_run_queue.c.run_id == run_id)
    ).mappings().all()
    score_rows = connection.execute(
        select(
            live_score_queue.c.case_id,
            live_score_queue.c.eval_model,
            live_score_queue.c.status,
        ).where(live_score_queue.c.run_id == run_id)
    ).mappings().all()
    score_by_pair = {
        (str(row["case_id"]), str(row["eval_model"])): str(row["status"])
        for row in score_rows
    }
    completed = 0
    failed = 0
    pending = 0
    for row in answer_rows:
        pair = (str(row["case_id"]), str(row["model_id"]))
        answer_status = str(row["status"])
        score_status = score_by_pair.get(pair, "queued")
        if answer_status == "success" and score_status == "success":
            completed += 1
        elif answer_status == "failed" or score_status in {"failed", "skipped"}:
            failed += 1
        else:
            pending += 1

    if pending:
        run_status = "running"
    elif completed and failed:
        run_status = "partial"
    elif completed:
        run_status = "completed"
    else:
        run_status = "failed"
    connection.execute(
        update(live_evaluation_runs)
        .where(live_evaluation_runs.c.run_id == run_id)
        .values(
            completed_count=completed,
            failed_count=failed,
            pending_count=pending,
            status=run_status,
            updated_at=func.now(),
        )
    )
```

为了保持旧的回答-only 服务与测试兼容，`initialize_run()`／`save_run_outcome()` 默认继续调用 `_refresh_answer_counts()`；新 `initialize_evaluation()`、`save_score_outcome()`、`mark_score_item_skipped()` 和组合模式 mark-running 调用 `_refresh_evaluation_counts()`。给 `save_run_outcome()` 同样增加 `combined: bool = False` 关键字参数，`EvaluationWorkflow` 显式传 `combined=True`，从而回答刚完成而评分仍排队时仍为 `running`；旧调用不传参数，行为不变。

- [ ] **Step 4: 暴露稳定序列化边界并刷新评分后的批次心跳**

在 `app/services/eval_runner.py` 增加：

```python
def serialize_run_outcome(run_id: str, mode: str, outcome: RunOutcome) -> dict[str, Any]:
    return _run_outcome_row(run_id, mode, outcome)
```

在 `app/services/scorer.py` 增加：

```python
def serialize_score_outcome(
    score_run_id: str,
    run_id: str,
    judge_provider: str,
    judge_model: str,
    mode: str,
    outcome: ScoreOutcome,
) -> dict[str, Any]:
    return _score_outcome_row(
        score_run_id,
        run_id,
        judge_provider,
        judge_model,
        mode,
        outcome,
    )
```

`save_score_outcome()` 成功更新评分队列后，以该行 `run_id` 调用 `_refresh_evaluation_counts()`。给 `mark_run_item_running()` 与 `save_run_outcome()` 增加仅供新流程使用的关键字参数 `combined: bool = False`：默认仍走旧回答计数，`EvaluationWorkflow` 显式传 `combined=True` 后走组合计数。`mark_score_item_running()` 始终刷新组合计数；两类 mark-running 都同步更新 `live_evaluation_runs.updated_at` 作为心跳。

注意：只读页面不得调用 `mark_run_interrupted_if_stale()`；失活状态先由 `load_evaluation_status()` 纯派生，只有用户点击“继续评测”时才通过 `claim_run()` 原子取得运行权。

- [ ] **Step 5: 增加 PostgreSQL SQL 编译与事务回归并运行测试**

在 `tests/test_result_store_postgres.py` 增加断言，确认 `claim_run()` 使用单条条件 `UPDATE`，组合初始化不依赖 SQLite 专有语法。然后运行：

```bash
PYTHONPATH=. pytest -q tests/test_result_store.py tests/test_result_store_postgres.py
```

Expected: PASS；重复初始化不重置成功队列，批次领取只有一个调用方成功。

- [ ] **Step 6: 提交**

```bash
git add app/persistence/result_store.py app/services/eval_runner.py app/services/scorer.py tests/test_result_store.py tests/test_result_store_postgres.py
git commit -m "feat: add durable combined evaluation queues"
```

### Task 3: 实现单入口 `EvaluationWorkflow` 和逐条自动评分

**Files:**
- Create: `app/services/evaluation_workflow.py`
- Test: `tests/test_evaluation_workflow.py`

- [ ] **Step 1: 写入成功、回答失败和评分失败的失败测试**

创建 `tests/test_evaluation_workflow.py` 的基础 fixture；测试 provider 使用 `name="test-live"`，不使用产品 MockProvider：

```python
from pathlib import Path

from app.persistence.result_store import ResultStore
from app.services import eval_runner as er
from app.services import scorer as sc
from app.services.evaluation_workflow import EvaluationConfig, EvaluationWorkflow
from app.models.base import GenerationResult


class AnswerProvider:
    name = "test-live"

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def generate_response(self, model_id, messages, **kwargs):
        self.calls += 1
        return self.results.pop(0)


def config(case_ids=("C1",)) -> EvaluationConfig:
    tasks = tuple(
        {"case_id": case_id, "task_type": "analysis", "question": f"问题-{case_id}"}
        for case_id in case_ids
    )
    queue_items = tuple(
        {"case_id": task["case_id"], "model_id": "model-a", "task": task}
        for task in tasks
    )
    return EvaluationConfig(
        provider_name="siliconflow",
        model_ids=("model-a",),
        queue_items=queue_items,
        generation_parameters={"temperature": 0.1, "max_tokens": 512},
        judge_parameters={"temperature": 0.0, "max_tokens": 256, "judge_model": "judge"},
        dataset_version="v1",
        prompt_payload=tuple(
            {"case_id": task["case_id"], "messages": er.build_messages(task)}
            for task in tasks
        ),
        gold_map={task["case_id"]: {"core_conclusion": "标准答案"} for task in tasks},
        dimensions=({"field": "accuracy_score", "name": "准确性", "full_mark": 100},),
    )


def store(tmp_path: Path) -> ResultStore:
    result = ResultStore(f"sqlite:///{tmp_path / 'workflow.db'}")
    result.ensure_schema()
    return result


def success_score(case_id="C1", model="model-a"):
    return sc.ScoreOutcome(
        case_id=case_id,
        task_type="analysis",
        eval_model=model,
        judge_provider="test-live",
        judge_model="judge",
        judge_status="success",
        scores={"accuracy_score": 82},
        total_score=82,
        review_status="ai_final",
    )


def failed_score(case_id="C1", model="model-a"):
    return sc.ScoreOutcome(
        case_id=case_id,
        task_type="analysis",
        eval_model=model,
        judge_provider="test-live",
        judge_model="judge",
        judge_status="failed",
        scores={"accuracy_score": None},
        error_code="timeout",
        error_message="judge timeout",
    )


def answer_result(text="回答", *, status="success", error_code=None):
    return GenerationResult(
        provider="test-live",
        model_id="model-a",
        status=status,
        response_text=text,
        error_code=error_code,
    )


def test_start_persists_answer_then_scores_without_second_action(tmp_path, monkeypatch):
    answer = AnswerProvider([answer_result()])
    score_calls = []

    def score_one(*args, **kwargs):
        score_calls.append((args, kwargs))
        return success_score()

    monkeypatch.setattr(sc, "score_single", score_one)
    workflow = EvaluationWorkflow(store(tmp_path), answer, answer)

    run = workflow.start_evaluation(config())
    status = workflow.load_evaluation_status(run.run_id)

    assert answer.calls == 1
    assert len(score_calls) == 1
    assert status.state == "completed"
    assert status.succeeded == 1
    assert len(workflow.store.list_rows("live_run_responses", run_id=run.run_id)) == 1
    assert len(workflow.store.list_rows("live_run_scores", run_id=run.run_id)) == 1


def test_failed_answer_is_saved_and_skips_scoring(tmp_path, monkeypatch):
    answer = AnswerProvider([answer_result("", status="failed", error_code="timeout")])
    monkeypatch.setattr(sc, "score_single", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    workflow = EvaluationWorkflow(store(tmp_path), answer, answer)

    run = workflow.start_evaluation(config())
    status = workflow.load_evaluation_status(run.run_id)

    assert status.state == "failed"
    score_queue = workflow.store.list_rows("live_score_queue", run_id=run.run_id)
    assert score_queue[0]["status"] == "skipped"


def test_failed_score_preserves_answer_and_finishes_partial_when_other_item_succeeds(tmp_path, monkeypatch):
    answer = AnswerProvider([answer_result("回答-C1"), answer_result("回答-C2")])
    score_outcomes = iter([success_score("C1"), failed_score("C2")])
    monkeypatch.setattr(sc, "score_single", lambda *args, **kwargs: next(score_outcomes))
    workflow = EvaluationWorkflow(store(tmp_path), answer, answer)

    run = workflow.start_evaluation(config(("C1", "C2")))
    status = workflow.load_evaluation_status(run.run_id)

    assert status.state == "partial"
    assert status.succeeded == 1
    assert status.failed == 1
    assert len(workflow.store.list_rows("live_run_responses", run_id=run.run_id)) == 2
```

这些测试全部使用临时 SQLite、确定性 `GenerationResult` 和 monkeypatch 后的 `score_single()`，不得访问网络。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_evaluation_workflow.py
```

Expected: FAIL，`evaluation_workflow.py` 不存在。

- [ ] **Step 3: 定义编排器类型和失活阈值**

创建 `app/services/evaluation_workflow.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from app.persistence.result_store import ResultStore, ResultStoreError
from app.services import eval_runner as er
from app.services import scorer as sc
from app.services.run_checkpoint import build_run_metadata

BATCH_RUNNING = "running"
BATCH_COMPLETED = "completed"
BATCH_PARTIAL = "partial"
BATCH_INTERRUPTED = "interrupted"
BATCH_STOPPED = "stopped"
BATCH_FAILED = "failed"


class WorkflowStopped(RuntimeError):
    pass


@dataclass(frozen=True)
class EvaluationConfig:
    provider_name: str
    model_ids: tuple[str, ...]
    queue_items: tuple[Mapping[str, Any], ...]
    generation_parameters: Mapping[str, Any]
    judge_parameters: Mapping[str, Any]
    dataset_version: str
    prompt_payload: tuple[Mapping[str, Any], ...]
    gold_map: Mapping[str, Mapping[str, Any]]
    dimensions: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class EvaluationRunRef:
    run_id: str
    score_run_id: str


@dataclass(frozen=True)
class EvaluationRunStatus:
    run_id: str
    score_run_id: str
    state: str
    total: int
    succeeded: int
    failed: int
    pending: int
    resumable: bool
    message: str = ""
    persistence_failed_in_session: bool = False


def inactivity_threshold(config: EvaluationConfig) -> timedelta:
    answer_timeout = float(config.generation_parameters.get("timeout_seconds") or 0)
    score_timeout = float(config.judge_parameters.get("timeout_seconds") or 0)
    return timedelta(seconds=max(900.0, max(answer_timeout, score_timeout) + 120.0))
```

在同一文件定义完整的队列行构造和单条回答调用边界，避免 UI 或编排器复制 `eval_runner` 内部实现：

```python
def _answer_queue_row(run_id: str, item: Mapping[str, Any], provider: str) -> dict[str, Any]:
    task = item.get("task") or {}
    return {
        "run_id": run_id,
        "case_id": str(item["case_id"]),
        "task_type": str(task.get("task_type") or ""),
        "model_id": str(item["model_id"]),
        "provider": provider,
        "status": "queued",
        "attempt_count": 0,
    }


def _score_queue_row(
    score_run_id: str,
    run_id: str,
    item: Mapping[str, Any],
    config: EvaluationConfig,
    judge_provider: str,
) -> dict[str, Any]:
    task = item.get("task") or {}
    return {
        "score_run_id": score_run_id,
        "run_id": run_id,
        "case_id": str(item["case_id"]),
        "task_type": str(task.get("task_type") or ""),
        "eval_model": str(item["model_id"]),
        "judge_model": str(config.judge_parameters["judge_model"]),
        "judge_provider": judge_provider,
        "status": "queued",
        "attempt_count": 0,
    }
```

- [ ] **Step 4: 实现初始化和逐条回答→评分顺序**

`EvaluationWorkflow.start_evaluation()` 必须先原子创建回答和评分队列，成功后才允许第一次模型调用：

```python
class EvaluationWorkflow:
    def __init__(self, store: ResultStore, answer_provider, judge_provider, *, now: Callable[[], datetime] = datetime.utcnow):
        self.store = store
        self.answer_provider = answer_provider
        self.judge_provider = judge_provider
        self.now = now
        self._session_stopped_run_ids: set[str] = set()

    def start_evaluation(self, config: EvaluationConfig) -> EvaluationRunRef:
        if str(getattr(self.answer_provider, "name", "")).lower() in {"mock", "demo"}:
            raise ValueError("product evaluation requires a live provider")
        if str(getattr(self.judge_provider, "name", "")).lower() in {"mock", "demo"}:
            raise ValueError("product evaluation requires a live judge")
        run_id = er.generate_run_id()
        score_run_id = sc.generate_score_run_id()
        metadata = build_run_metadata(
            run_id=run_id,
            provider=config.provider_name,
            model_ids=config.model_ids,
            queue_items=config.queue_items,
            generation_parameters=config.generation_parameters,
            judge_parameters=config.judge_parameters,
            dataset_version=config.dataset_version,
            prompt_payload=config.prompt_payload,
        )
        answer_rows = [
            _answer_queue_row(run_id, item, config.provider_name)
            for item in config.queue_items
        ]
        score_rows = [
            _score_queue_row(
                score_run_id,
                run_id,
                item,
                config,
                str(getattr(self.judge_provider, "name", "")),
            )
            for item in config.queue_items
        ]
        self.store.initialize_evaluation(metadata, answer_rows, score_rows)
        self._execute(run_id, score_run_id, config)
        return EvaluationRunRef(run_id, score_run_id)
```

`_execute()` 对每个 pair 先查持久化状态：成功回答直接跳过回答调用，成功评分直接跳过评分调用。回答失败时把评分项置为 skipped；回答成功后立即评分，不等待整批回答结束。核心循环按下列代码实现，`_successful_answer()` 和 `_successful_score()` 分别查询两个结果表的唯一键并检查 success：

```python
def _execute(
    self,
    run_id: str,
    score_run_id: str,
    config: EvaluationConfig,
) -> None:
    answer_by_pair = {
        (str(row["case_id"]), str(row["model_id"])): row
        for row in self.store.list_rows("live_run_queue", run_id=run_id)
    }
    score_by_pair = {
        (str(row["case_id"]), str(row["eval_model"])): row
        for row in self.store.list_rows("live_score_queue", run_id=run_id)
    }
    for item in config.queue_items:
        case_id = str(item["case_id"])
        model_id = str(item["model_id"])
        task = item.get("task") or {}
        if (case_id, model_id) not in answer_by_pair or (case_id, model_id) not in score_by_pair:
            raise ValueError("evaluation checkpoint is incomplete")
        response_row = self._successful_answer(run_id, case_id, model_id)
        score_row = self._successful_score(score_run_id, case_id, model_id)
        if score_row is not None:
            continue
        answer_queue_status = str(answer_by_pair[(case_id, model_id)].get("status") or "queued")
        score_queue_status = str(score_by_pair[(case_id, model_id)].get("status") or "queued")
        if answer_queue_status == "failed" or score_queue_status in {"failed", "skipped"}:
            continue
        if response_row is None:
            try:
                self.store.mark_run_item_running(
                    run_id, case_id, model_id, combined=True
                )
                outcome = er.run_single(
                    self.answer_provider,
                    model_id,
                    task,
                    temperature=float(config.generation_parameters.get("temperature") or 0.2),
                    max_tokens=int(config.generation_parameters.get("max_tokens") or 1024),
                )
                self.store.save_run_outcome(
                    er.serialize_run_outcome(run_id, "live", outcome),
                    queue_status="success" if outcome.success else "failed",
                    combined=True,
                )
            except ResultStoreError as exc:
                self._stop(run_id, exc)
            if not outcome.success:
                try:
                    self.store.mark_score_item_skipped(
                        score_run_id, case_id, model_id, "answer_failed"
                    )
                except ResultStoreError as exc:
                    self._stop(run_id, exc)
                continue
            answer_text = outcome.answer_text
        else:
            answer_text = str(response_row.get("answer_text") or "")

        try:
            self.store.mark_score_item_running(score_run_id, case_id, model_id)
            score = self._score_one(config, task, case_id, model_id, answer_text)
            self.store.save_score_outcome(
                sc.serialize_score_outcome(
                    score_run_id,
                    run_id,
                    str(getattr(self.judge_provider, "name", "")),
                    str(config.judge_parameters["judge_model"]),
                    "live",
                    score,
                ),
                queue_status="success" if score.ok else "failed",
            )
        except ResultStoreError as exc:
            self._stop(run_id, exc)


def _successful_answer(self, run_id: str, case_id: str, model_id: str) -> dict | None:
    rows = self.store.list_rows(
        "live_run_responses",
        run_id=run_id,
        case_id=case_id,
        model_name=model_id,
    )
    return next((row for row in rows if row.get("run_status") == "success"), None)


def _successful_score(self, score_run_id: str, case_id: str, model_id: str) -> dict | None:
    rows = self.store.list_rows(
        "live_run_scores",
        score_run_id=score_run_id,
        case_id=case_id,
        eval_model=model_id,
    )
    return next((row for row in rows if row.get("judge_status") == "success"), None)
```

评分调用使用现有固定裁判配置：

```python
def _score_one(self, config, task, case_id, model_id, answer_text):
    return sc.score_single(
        self.judge_provider,
        str(config.judge_parameters["judge_model"]),
        task,
        answer_text,
        config.gold_map.get(case_id) or {},
        config.dimensions,
        eval_model=model_id,
        temperature=float(config.judge_parameters.get("temperature") or 0.0),
        max_tokens=int(config.judge_parameters.get("max_tokens") or 1024),
    )
```

持久化使用 Task 2 的公开序列化函数；不复制评分提示词、阈值或 provider 重试逻辑。

- [ ] **Step 5: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_evaluation_workflow.py tests/test_result_store.py tests/test_core_evaluation_flow.py
```

Expected: PASS；成功回答后无需第二个 UI 动作即可出现正式评分。

- [ ] **Step 6: 提交**

```bash
git add app/services/evaluation_workflow.py tests/test_evaluation_workflow.py
git commit -m "feat: automate answer scoring workflow"
```

### Task 4: 实现组合状态、安全续跑和持久化失败停机

**Files:**
- Modify: `app/services/evaluation_workflow.py`
- Modify: `app/persistence/result_store.py`
- Test: `tests/test_evaluation_workflow.py`
- Test: `tests/test_durable_execution.py`

- [ ] **Step 1: 增加中断、重复调用和持久化失败测试**

在 `tests/test_evaluation_workflow.py` 增加：

```python
def test_loading_stale_running_batch_returns_interrupted(tmp_path):
    clock = FrozenClock("2026-08-13T12:30:00")
    workflow, run_id = persisted_stale_batch(store(tmp_path), clock)

    status = workflow.load_evaluation_status(run_id)

    assert status.state == "interrupted"
    assert status.resumable is True


def test_persistence_error_cannot_be_written_but_current_session_still_stops(tmp_path):
    broken = FailOnAnswerAndStopWriteStore(f"sqlite:///{tmp_path / 'broken.db'}")
    broken.ensure_schema()
    workflow = EvaluationWorkflow(broken, AnswerProvider([answer_result()]), AnswerProvider([]))

    with pytest.raises(WorkflowStopped):
        workflow.start_evaluation(config())

    status = workflow.load_evaluation_status(broken.run_id)
    assert status.state == "stopped"
    assert status.persistence_failed_in_session is True


def test_continue_skips_existing_answer_and_scores_only_missing_score(tmp_path):
    workflow, run_id, provider = persisted_answer_without_score(store(tmp_path))

    workflow.continue_evaluation(run_id, config())

    assert provider.answer_calls == 0
    assert provider.score_calls == 1


def test_continue_does_not_repeat_successful_answer_or_score(tmp_path):
    workflow, run_id, provider = persisted_complete_pair(store(tmp_path))

    workflow.continue_evaluation(run_id, config())

    assert provider.answer_calls == 0
    assert provider.score_calls == 0


def test_persistence_failure_stops_all_later_token_calls(tmp_path):
    store_with_failure = FailOnFirstAnswerSaveStore(f"sqlite:///{tmp_path / 'stop.db'}")
    store_with_failure.ensure_schema()
    provider = AnswerProvider([answer_result("A1"), answer_result("A2"), answer_result("A3")])
    workflow = EvaluationWorkflow(store_with_failure, provider, provider)

    with pytest.raises(WorkflowStopped):
        workflow.start_evaluation(config(("C1", "C2", "C3")))

    assert provider.calls == 1


def test_mismatched_checkpoint_cannot_resume(tmp_path):
    workflow, run_id = persisted_interrupted_batch(store(tmp_path), config())
    changed = replace(config(), dataset_version="v2")

    with pytest.raises(ValueError, match="checkpoint"):
        workflow.continue_evaluation(run_id, changed)


def test_non_stale_running_batch_cannot_be_claimed_or_call_provider(tmp_path):
    workflow, run_id, counter = persisted_running_batch(store(tmp_path), config())

    status = workflow.continue_evaluation(run_id, config())

    assert status.state == "running"
    assert counter.answer_calls == 0
    assert counter.score_calls == 0
```

同一测试文件定义以下最小辅助类型；所有 fixture 只包装临时 SQLite `ResultStore`：

```python
class FrozenClock:
    def __init__(self, value: str):
        self.value = datetime.fromisoformat(value)

    def __call__(self):
        return self.value


class FailOnFirstAnswerSaveStore(ResultStore):
    def save_run_outcome(self, row, *, queue_status):
        raise ResultStoreError("database write failed")


class FailOnAnswerAndStopWriteStore(FailOnFirstAnswerSaveStore):
    run_id = ""

    def initialize_evaluation(self, run, answer_rows, score_rows):
        self.run_id = str(run["run_id"])
        return super().initialize_evaluation(run, answer_rows, score_rows)

    def mark_run_stopped(self, run_id, message):
        raise ResultStoreError("database remains unavailable")


@dataclass
class CallCounter:
    answer_calls: int = 0
    score_calls: int = 0
```

`persisted_answer_without_score()`、`persisted_complete_pair()` 和 `persisted_interrupted_batch()` 都先调用 `initialize_evaluation()` 写入 Task 2 定义的 metadata／两类队列，再通过 `save_run_outcome()`／`save_score_outcome()` 写入所需终态。每个 fixture 返回 `CallCounter`；测试用 `monkeypatch` 包装 `er.run_single` 和 `sc.score_single`，每次调用分别增加 `answer_calls`／`score_calls` 后返回确定性 outcome。不得直接修改 SQL，不得访问网络。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_evaluation_workflow.py tests/test_durable_execution.py
```

Expected: FAIL，尚无续跑与组合状态实现。

- [ ] **Step 3: 实现确定性组合状态**

在 `evaluation_workflow.py` 增加纯函数：

```python
def derive_status(run: Mapping[str, Any], answers: list[dict], scores: list[dict], *, stale: bool) -> EvaluationRunStatus:
    score_by_pair = {(row["case_id"], row["eval_model"]): row for row in scores}
    succeeded = 0
    failed = 0
    pending = 0
    for answer in answers:
        pair = (answer["case_id"], answer["model_id"])
        answer_state = str(answer.get("status") or "queued")
        score_state = str((score_by_pair.get(pair) or {}).get("status") or "queued")
        if answer_state == "success" and score_state == "success":
            succeeded += 1
        elif answer_state == "failed" or score_state in {"failed", "skipped"}:
            failed += 1
        else:
            pending += 1
    persisted = str(run.get("status") or "")
    stopped_here = str(run.get("_session_state") or "") == "stopped"
    if stopped_here:
        state = BATCH_STOPPED
    elif pending and stale:
        state = BATCH_INTERRUPTED
    elif pending:
        state = BATCH_RUNNING
    elif succeeded and failed:
        state = BATCH_PARTIAL
    elif succeeded:
        state = BATCH_COMPLETED
    else:
        state = BATCH_FAILED
    score_run_id = str(scores[0].get("score_run_id") or "") if scores else ""
    return EvaluationRunStatus(
        run_id=str(run.get("run_id") or ""),
        score_run_id=score_run_id,
        state=state,
        total=len(answers),
        succeeded=succeeded,
        failed=failed,
        pending=pending,
        resumable=state == BATCH_INTERRUPTED,
        message=str(run.get("last_persistence_error") or ""),
        persistence_failed_in_session=stopped_here,
    )
```

`load_evaluation_status()` 的完整读取顺序为：读取单条 run、按 `run_id` 读取回答队列、按 `run_id` 读取评分队列，使用 `updated_at` 与当前时钟计算 `stale`，再调用 `derive_status()`；若 run 或任一队列不存在，抛出 `ValueError("evaluation checkpoint is incomplete")`，不得回退 Session State。

`EvaluationWorkflow.__init__()` 初始化 `self._session_stopped_run_ids: set[str] = set()`；`_stop()` 先把 `run_id` 加入该集合。`load_evaluation_status()` 只在 `run_id in self._session_stopped_run_ids` 时向 `derive_status()` 传入 `{**run, "_session_state": "stopped"}`。数据库里的旧 `status="stopped"` 不永久映射为当前会话“已停止”：若批次仍有 pending 且无当前进程运行权，一律派生为 `interrupted` 并允许主动继续。这样覆盖“错误无法回写”与“数据库恢复后可继续”两种边界，同时不新增字段。

- [ ] **Step 4: 实现领取、哈希校验和主动继续**

`continue_evaluation()`：

1. 读取 run、两类 queue 和持久化结果；
2. 用 `build_run_metadata()` 重新计算当前配置；
3. 比较 `dataset_version`、`dataset_hash`、`prompt_hash`、`generation_parameters_json` 和 `judge_parameters_json`；
4. 以 `now - inactivity_threshold(config)` 调用 `store.claim_run()`；`claim_run()` 允许 `interrupted/stopped` 领取，也允许数据库仍标记 `running` 但已超过失活阈值的批次领取；
5. 领取失败则返回最新只读状态，不调用 provider；
6. 领取成功后只执行 queued/running 且没有成功结果的 pair。

旧 `running` 队列项在原进程中断后可重试；`_execute()` 对 queue status 为 `queued/running` 的 pair 执行，对 `success` 结果跳过，对 `failed/skipped` 终态不自动重试。评分失败和回答失败属于已结算失败项，批次最终归并为部分完成或失败；“继续评测”只恢复未完成项，不擅自重新消耗失败项 Token。

哈希比较使用规范化 JSON，避免只因键顺序产生误判：

```python
def _canonical_json_text(value: object) -> str:
    payload = json.loads(value) if isinstance(value, str) else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checkpoint_matches(saved: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    plain_fields = ("dataset_version", "dataset_hash", "prompt_hash")
    json_fields = ("model_ids_json", "generation_parameters_json", "judge_parameters_json")
    return (
        all(str(saved.get(field) or "") == str(current.get(field) or "") for field in plain_fields)
        and all(
            _canonical_json_text(saved.get(field) or ("[]" if field == "model_ids_json" else "{}"))
            == _canonical_json_text(current.get(field) or ("[]" if field == "model_ids_json" else "{}"))
            for field in json_fields
        )
    )
```

`_stop()` 必须先停止本地循环，再尽力记录错误：

```python
def _stop(self, run_id: str, exc: Exception) -> None:
    self._session_stopped_run_ids.add(run_id)
    try:
        self.store.mark_run_stopped(run_id, str(exc))
    except ResultStoreError:
        pass
    raise WorkflowStopped("evaluation stopped because persistence failed") from exc
```

- [ ] **Step 5: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_evaluation_workflow.py tests/test_durable_execution.py tests/test_result_store.py
```

Expected: PASS；失活批次只在主动继续后调用模型，数据库写失败后的 provider 调用数不再增加。

- [ ] **Step 6: 提交**

```bash
git add app/services/evaluation_workflow.py app/persistence/result_store.py tests/test_evaluation_workflow.py tests/test_durable_execution.py
git commit -m "feat: safely resume persisted evaluations"
```

---

## Milestone B：结论读取模型与证据索引

### Task 5: 建立确定性的代表样本证据索引

**Files:**
- Create: `app/services/evidence_index.py`
- Create: `tests/test_evidence_index.py`

- [ ] **Step 1: 写入最低分、最高分和最弱维度样本测试**

创建 `tests/test_evidence_index.py`：

```python
import pandas as pd

from app.services.evidence_index import build_evidence_index


DIMENSIONS = [
    {"field": "accuracy_score", "name": "准确性", "full_mark": 30},
    {"field": "evidence_score", "name": "依据可靠性", "full_mark": 15},
]


def test_representatives_are_lowest_highest_and_weakest_dimension():
    scores = pd.DataFrame([
        {"run_id": "R", "case_id": "C1", "eval_model": "m", "total_score": 50, "accuracy_score": 20, "evidence_score": 10, "rationale": "r1"},
        {"run_id": "R", "case_id": "C2", "eval_model": "m", "total_score": 95, "accuracy_score": 29, "evidence_score": 14, "rationale": "r2"},
        {"run_id": "R", "case_id": "C3", "eval_model": "m", "total_score": 75, "accuracy_score": 25, "evidence_score": 2, "rationale": "r3"},
        {"run_id": "R", "case_id": "C4", "eval_model": "m", "total_score": 76, "accuracy_score": 24, "evidence_score": 8, "rationale": "r4"},
    ])
    responses = pd.DataFrame([
        {"run_id": "R", "case_id": case_id, "model_name": "m", "answer_text": f"answer-{case_id}"}
        for case_id in ("C1", "C2", "C3", "C4")
    ])
    tasks = pd.DataFrame([
        {"case_id": case_id, "question": f"question-{case_id}"}
        for case_id in ("C1", "C2", "C3", "C4")
    ])
    gold = {case_id: {"core_conclusion": f"gold-{case_id}"} for case_id in ("C1", "C2", "C3", "C4")}

    result = build_evidence_index(scores, responses, tasks, gold, DIMENSIONS, "m")

    assert [(item.case_id, item.selection_reason) for item in result] == [
        ("C1", "最低总分"),
        ("C2", "最高总分"),
        ("C3", "最弱维度：依据可靠性"),
    ]
    assert result[2].answer_text == "answer-C3"
    assert result[2].gold_answer["core_conclusion"] == "gold-C3"


def test_duplicate_candidates_are_deduped_and_ties_use_case_id():
    scores = pd.DataFrame([
        {"run_id": "R", "case_id": "C2", "eval_model": "m", "total_score": 80, "accuracy_score": 20, "evidence_score": 10},
        {"run_id": "R", "case_id": "C1", "eval_model": "m", "total_score": 80, "accuracy_score": 20, "evidence_score": 10},
    ])

    result = build_evidence_index(scores, pd.DataFrame(), pd.DataFrame(), {}, DIMENSIONS, "m")

    assert [item.case_id for item in result] == ["C1", "C2"]
    assert len({item.case_id for item in result}) == len(result)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_evidence_index.py
```

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现只读证据投影**

创建 `app/services/evidence_index.py`，定义：

```python
@dataclass(frozen=True)
class EvidenceItem:
    run_id: str
    case_id: str
    model_name: str
    title: str
    total_score: float | None
    selection_reason: str
    weakest_dimension: str
    dimension_scores: Mapping[str, float | None]
    rationale: object
    review_note: str
    answer_text: str
    gold_answer: Mapping[str, object]
```

`build_evidence_index()` 的候选选择使用以下完整纯函数；先确定当前模型平均得分率最低的维度，再按规格顺序选证据：

```python
def _number(value) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _ranked_candidates(frame: pd.DataFrame, field: str, ascending: bool) -> list[dict]:
    work = frame.copy()
    work["_rank_value"] = pd.to_numeric(work[field], errors="coerce")
    work["_case_order"] = work["case_id"].fillna("").astype(str)
    work = work.dropna(subset=["_rank_value"]).sort_values(
        ["_rank_value", "_case_order"],
        ascending=[ascending, True],
        kind="mergesort",
    )
    return work.to_dict("records")


def _weakest_dimension(frame: pd.DataFrame, dimensions) -> Mapping[str, object] | None:
    attainment = []
    for dimension in dimensions:
        field = str(dimension["field"])
        full_mark = float(dimension["full_mark"])
        values = pd.to_numeric(frame.get(field), errors="coerce").dropna()
        if full_mark > 0 and not values.empty:
            attainment.append((float(values.mean()) / full_mark, field, dimension))
    return min(attainment, key=lambda item: (item[0], item[1]))[2] if attainment else None


def _choose(rows: list[dict], reason: str, chosen: dict[str, tuple[dict, str]]) -> None:
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if case_id and case_id not in chosen:
            chosen[case_id] = (row, reason)
            return


def representative_rows(frame: pd.DataFrame, dimensions) -> list[tuple[dict, str]]:
    if frame.empty:
        return []
    chosen: dict[str, tuple[dict, str]] = {}
    _choose(_ranked_candidates(frame, "total_score", True), "最低总分", chosen)
    _choose(_ranked_candidates(frame, "total_score", False), "最高总分", chosen)
    weakest = _weakest_dimension(frame, dimensions)
    if weakest is not None:
        field = str(weakest["field"])
        label = str(weakest.get("name") or field)
        ranked = frame.copy()
        ranked["_attainment"] = pd.to_numeric(ranked[field], errors="coerce") / float(weakest["full_mark"])
        _choose(_ranked_candidates(ranked, "_attainment", True), f"最弱维度：{label}", chosen)
    return list(chosen.values())[:3]
```

`build_evidence_index()` 只处理指定模型；调用 `representative_rows()` 后，回答按 `(run_id, case_id, model_name)` 精确连接，Gold 按 `case_id` 连接，任务标题按 `case_id` 连接，并把 score 行上的维度分、`rationale`、`review_note` 原样带入 `EvidenceItem`。`rationale` 若来自数据库 JSON 字符串，只允许 `json.loads()` 还原为映射，解析失败时保留原字符串，不生成摘要。函数不得修改输入 DataFrame。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_evidence_index.py
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/services/evidence_index.py tests/test_evidence_index.py
git commit -m "feat: build deterministic conclusion evidence index"
```

### Task 6: 集中结论报告读取模型

**Files:**
- Create: `app/services/conclusion_read_model.py`
- Modify: `src/ui/conclusions_data.py`
- Modify: `app/services/conclusions.py`
- Test: `tests/test_conclusions.py`
- Test: `tests/test_formal_records.py`

- [ ] **Step 1: 写入统一口径和数据不可用测试**

在 `tests/test_conclusions.py` 增加：

```python
from app.persistence.result_store import ResultStoreError
from app.services.conclusion_read_model import build_conclusion_report
from src.ui.conclusions_data import load_conclusion_source


def test_conclusion_report_uses_one_formal_cohort_for_counts_models_and_evidence():
    report = build_conclusion_report(
        scores_df=formal_and_demo_scores(),
        responses_df=formal_and_demo_responses(),
        tasks_df=current_tasks(),
        gold_map=current_gold(),
        dimensions=current_dimensions(),
    )

    assert report.scope.formal_score_count == 1
    assert report.scope.model_count == 1
    assert set(report.evidence_by_model) == {"live-model"}
    assert all(item.model_name == "live-model" for item in report.evidence_by_model["live-model"])


def test_conclusion_loader_reports_unavailable_instead_of_empty_data(monkeypatch):
    monkeypatch.setattr(
        "app.services.conclusions.load_evaluation_runs",
        lambda **kwargs: (_ for _ in ()).throw(ResultStoreError("down")),
    )

    result = load_conclusion_source(
        ("C1",),
        tuple(current_tasks().to_dict("records")),
        tuple(sorted(current_gold().items())),
        tuple(current_dimensions()),
    )

    assert result.available is False
    assert result.report is None


def test_conclusion_loader_distinguishes_available_empty_formal_data(monkeypatch):
    monkeypatch.setattr("app.services.conclusions.load_evaluation_runs", lambda **kwargs: pd.DataFrame())
    monkeypatch.setattr("app.services.conclusions.load_live_scores", lambda **kwargs: pd.DataFrame())
    monkeypatch.setattr("app.services.conclusions.load_live_responses", lambda **kwargs: pd.DataFrame())

    result = load_conclusion_source(
        ("C1",),
        tuple(current_tasks().to_dict("records")),
        tuple(sorted(current_gold().items())),
        tuple(current_dimensions()),
    )

    assert result.available is True
    assert result.report is not None
    assert result.report.scope.formal_score_count == 0
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_conclusions.py tests/test_formal_records.py
```

Expected: FAIL，读取模型和带可用性状态的缓存函数不存在。

- [ ] **Step 3: 实现 `ConclusionReport`**

创建 `app/services/conclusion_read_model.py`：

```python
@dataclass(frozen=True)
class ReportScope:
    sample_count: int
    model_count: int
    formal_score_count: int
    data_basis: str = "仅纳入正式评分"


@dataclass(frozen=True)
class ConclusionReport:
    scope: ReportScope
    formal_scores: pd.DataFrame
    formal_responses: pd.DataFrame
    model_summaries: tuple[dict, ...]
    evidence_by_model: Mapping[str, tuple[EvidenceItem, ...]]
```

`build_conclusion_report()` 使用下列实现；它复用既有结论函数，不改写判断、阈值或排序：

```python
def build_conclusion_report(
    *,
    scores_df: pd.DataFrame,
    responses_df: pd.DataFrame,
    tasks_df: pd.DataFrame,
    gold_map: Mapping[str, Mapping[str, object]],
    dimensions: tuple[Mapping[str, object], ...],
) -> ConclusionReport:
    allowed = (
        set(tasks_df["case_id"].dropna().astype(str))
        if isinstance(tasks_df, pd.DataFrame) and "case_id" in tasks_df.columns
        else set()
    )
    responses = filter_formal_responses(
        responses_df,
        allowed_case_ids=allowed,
    )
    scores = filter_formal_scores(
        scores_df,
        responses,
        allowed_case_ids=allowed,
    )
    summaries = tuple(cc.build_model_issue_summaries(scores, pd.DataFrame(), tasks_df))
    model_names = tuple(
        str(item.get("model_name") or "")
        for item in summaries
        if item.get("model_name")
    )
    evidence = {
        model_name: tuple(
            build_evidence_index(
                scores, responses, tasks_df, gold_map, dimensions, model_name
            )
        )
        for model_name in model_names
    }
    return ConclusionReport(
        scope=ReportScope(
            sample_count=int(scores["case_id"].nunique()) if not scores.empty else 0,
            model_count=int(scores["eval_model"].nunique()) if not scores.empty else 0,
            formal_score_count=len(scores),
        ),
        formal_scores=scores,
        formal_responses=responses,
        model_summaries=summaries,
        evidence_by_model=evidence,
    )
```

`src/ui/conclusions_data.py` 新增：

```python
@dataclass(frozen=True)
class ConclusionSource:
    available: bool
    report: ConclusionReport | None
    message: str = ""


@st.cache_data(show_spinner=False)
def load_conclusion_source(
    allowed_case_ids: tuple[str, ...],
    _tasks_records: tuple[dict, ...],
    _gold_records: tuple[tuple[str, Mapping[str, object]], ...],
    _dimensions: tuple[dict, ...],
) -> ConclusionSource:
    try:
        runs = cc.load_evaluation_runs(suppress_errors=False)
        scores = cc.load_live_scores(suppress_errors=False)
        responses = cc.load_live_responses(suppress_errors=False)
        selected = cc.select_current_cohort_scores(
            runs,
            scores,
            allowed_case_ids=allowed_case_ids,
        )
        report = build_conclusion_report(
            scores_df=selected,
            responses_df=responses,
            tasks_df=pd.DataFrame(list(_tasks_records)),
            gold_map=dict(_gold_records),
            dimensions=_dimensions,
        )
        return ConclusionSource(True, report)
    except (ResultStoreError, SQLAlchemyError):
        return ConclusionSource(False, None, "评测结果数据库暂不可用。")
```

为避免 Streamlit 缓存让测试 monkeypatch 或页面显式刷新读到旧值，`tests/test_conclusions.py` 在每个 loader 测试前后调用 `load_conclusion_source.clear()`；生产写入点统一调用 `clear_conclusions_caches()`。

在 `app/services/conclusions.py` 暴露原始批次读取，并让正式选择支持“已完成”和“部分完成”：

```python
def load_evaluation_runs(db_path=None, *, suppress_errors: bool = True) -> pd.DataFrame:
    return _load_live_table("live_evaluation_runs", db_path, suppress_errors=suppress_errors)


def load_live_scores(db_path=None, *, suppress_errors: bool = True) -> pd.DataFrame:
    return _load_live_table("live_run_scores", db_path, suppress_errors=suppress_errors)


def load_live_responses(
    db_path=None,
    *,
    allowed_case_ids=None,
    suppress_errors: bool = True,
) -> pd.DataFrame:
    rows = _load_live_table("live_run_responses", db_path, suppress_errors=suppress_errors)
    return filter_formal_responses(rows, allowed_case_ids=allowed_case_ids)
```

`_load_live_table()` 增加 `suppress_errors: bool = True` 兼容参数；`False` 时把底层异常转换为 `ResultStoreError("could not read conclusion data")`，旧调用保持空表降级，`ConclusionSource` 的三个读取函数均传 `False` 以区分数据库不可用与正式结果为零。`select_current_cohort_scores()` 的运行状态条件改为：

```python
run_status.isin({"completed", "partial"})
```

`select_current_cohort_scores()` 在选择最新兼容 cohort 后应用 `formal_score_mask(scores, responses=None)` 做评分侧过滤；`build_conclusion_report()` 随后用正式回答做第二次精确连接。这样最新 `partial` 批次中的成功评分可以进入结论，失败／skipped 行仍被排除，旧 cohort 的兼容签名规则保持不变。

`src/ui/conclusions.py` 调用缓存前把可变结构规范化：`tasks_df.to_dict("records")` 转 tuple、`gold_map.items()` 按 case_id 排序后转 tuple、维度记录转 tuple。缓存不得吞掉“不可用”和“零正式结果”的差异；`clear_conclusions_caches()` 同时清理 `load_conclusion_source`。

上述 tuple 内含 dict，Streamlit 仍可能无法稳定哈希；因此在实际签名中给三项只读数据参数加前导下划线（`_tasks_records`、`_gold_records`、`_dimensions`），让缓存键只依赖 `allowed_case_ids`。样本维护成功后继续调用现有 `clear_conclusions_caches()`，以显式失效保证数据更新可见。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_conclusions.py tests/test_formal_records.py tests/test_model_use_boundaries.py
```

Expected: PASS；原有模型判断测试结果不变。

- [ ] **Step 5: 提交**

```bash
git add app/services/conclusion_read_model.py app/services/conclusions.py src/ui/conclusions_data.py tests/test_conclusions.py tests/test_formal_records.py
git commit -m "refactor: centralize conclusion report reads"
```

---

## Milestone C：报告体验与单入口页面

### Task 7: 将导航改为结论默认和审阅／操作分层

**Files:**
- Modify: `src/ui/page_config.py`
- Modify: `src/ui/navigation.py`
- Modify: `app.py`
- Test: `tests/test_navigation_routes.py`
- Test: `tests/test_review_first_ui.py`
- Test: `tests/test_ui_text_guardrails.py`
- Test: `tests/test_report_experience.py`

- [ ] **Step 1: 写入默认页和导航分层失败测试**

创建 `tests/test_report_experience.py`：

```python
from pathlib import Path

from src.ui.navigation import OPERATION_NAV_ITEM, PRIMARY_NAV_ITEMS
from src.ui.page_config import DEFAULT_PAGE_KEY


def test_conclusions_are_default_and_operation_is_secondary():
    assert DEFAULT_PAGE_KEY == "conclusions"
    assert PRIMARY_NAV_ITEMS == [
        ("评测结论", "conclusions"),
        ("项目说明", "case_study"),
        ("样本库", "samples"),
    ]
    assert OPERATION_NAV_ITEM == ("评测操作", "test_run")


def test_navigation_requests_top_scroll_without_extra_marker():
    source = Path("src/ui/navigation.py").read_text(encoding="utf-8")
    assert 'request_scroll("top")' in source
    assert "top-nav-current-marker" not in source


def test_all_four_routes_remain_available():
    from src.ui.navigation import PAGES

    assert set(PAGES) == {"conclusions", "case_study", "samples", "test_run"}
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_navigation_routes.py tests/test_review_first_ui.py
```

Expected: FAIL，默认页仍为 `case_study`，导航仍是四项同权。

- [ ] **Step 3: 修改配置和导航**

`src/ui/page_config.py` 的顺序改为 `conclusions, case_study, samples, test_run`，并设置：

```python
DEFAULT_PAGE_KEY = "conclusions"
```

`src/ui/navigation.py` 定义：

```python
PRIMARY_NAV_ITEMS = [
    ("评测结论", "conclusions"),
    ("项目说明", "case_study"),
    ("样本库", "samples"),
]
OPERATION_NAV_ITEM = ("评测操作", "test_run")
```

`render_top_navigation()` 为前三项使用同一审阅按钮样式；评测操作使用独立稳定 key `top_nav_operation` 和 CSS 类标记容器。继续在点击后调用 `request_scroll("top")`。`get_primary_nav_items()` 只返回三项，新增 `get_operation_nav_item()`。

桌面端使用 `[brand, review-nav, operation]` 三段网格；手机端品牌独占第一行，三项审阅导航等宽排列，评测操作作为下一行右对齐文字入口。激活态只在按钮本身绘制下划线，不渲染额外 marker；测试在四个视口断言三项主导航顶部坐标差不超过 1px。

保留现有 `request_scroll()`／`render_pending_scroll()` 的 `{target, request_id}` 协调机制；导航切页目标固定为 `top`，稳定后 `stMain.scrollTop <= 8px`。模型和样本选择分别请求证据／档案锚点，锚点继续扣除粘性导航高度；本计划不回退到 `scrollIntoView()`。

- [ ] **Step 4: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_navigation_routes.py tests/test_review_first_ui.py tests/test_ui_text_guardrails.py
```

Expected: PASS，四条路由仍可访问，只有三项属于主导航。

- [ ] **Step 5: 提交**

```bash
git add src/ui/page_config.py src/ui/navigation.py app.py tests/test_report_experience.py tests/test_navigation_routes.py tests/test_review_first_ui.py tests/test_ui_text_guardrails.py
git commit -m "feat: make conclusions the default review entry"
```

### Task 8: 建立无卡片中文研究简报组件

**Files:**
- Create: `src/ui/report_styles.py`
- Create: `src/ui/report_components.py`
- Modify: `src/ui/components.py`
- Modify: `src/ui/responsive.py`
- Test: `tests/test_ui_components.py`
- Test: `tests/test_mobile_responsive_ui.py`
- Test: `tests/test_report_experience.py`

- [ ] **Step 1: 写入报告组件和禁止样式测试**

在 `tests/test_report_experience.py` 增加：

```python
from src.ui import report_components as rc
from src.ui.report_styles import REPORT_STYLE_CSS


def test_report_styles_are_flat_and_editorial():
    for required in [".report-masthead", ".report-ledger", ".report-index-row", ".evidence-index"]:
        assert required in REPORT_STYLE_CSS
    for banned in ["linear-gradient", "box-shadow:", "border-radius: 12px", ".kpi-card"]:
        assert banned not in REPORT_STYLE_CSS


def test_scope_ledger_escapes_dynamic_values():
    html = rc.scope_ledger_html([("样本范围", "<13>")])
    assert "&lt;13&gt;" in html
    assert "<13>" not in html
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_ui_components.py tests/test_mobile_responsive_ui.py
```

Expected: FAIL，新组件不存在。

- [ ] **Step 3: 实现报告 HTML 原语**

`src/ui/report_components.py` 提供无业务判断的函数：

```python
def report_masthead_html(title: str, description: str, eyebrow: str = "") -> str
def scope_ledger_html(items: list[tuple[str, str]]) -> str
def report_section_html(index: str, label: str, title: str, body_html: str) -> str
def report_index_row_html(cells: list[str], *, active: bool = False) -> str
def evidence_index_html(items: list[EvidenceItem]) -> str
```

并提供与页面调用一致的 Streamlit 包装器：

```python
def render_report_masthead(title: str, description: str, eyebrow: str = "") -> None:
    render_html(report_masthead_html(title, description, eyebrow))


def render_scope_ledger(items: list[tuple[str, str]]) -> None:
    render_html(scope_ledger_html(items))
```

所有动态文本用 `html.escape()`；只有已经由共享 Markdown 转换器生成的正文 HTML 可以作为 `body_html` 传入。

`src/ui/report_styles.py` 使用现有色值，定义直角报告区、细分隔线、编号、台账和审阅行。内容区不得使用投影、渐变、圆角卡片、图标徽标或 KPI 侧栏。

`src/ui/components.py` 只增加：

```python
from src.ui.report_styles import REPORT_STYLE_CSS

STYLE_CSS = f"{STYLE_CSS}{REPORT_STYLE_CSS}{MOBILE_RESPONSIVE_CSS}\n</style>\n"
```

避免把新的报告 CSS 继续堆进现有 1600 行字符串。

- [ ] **Step 4: 实现响应式重排**

`report_styles.py` 在 `@media (max-width: 760px)` 中：

- 台账改为两列；
- 报告章节的编号列移到标题上方；
- 审阅表头隐藏，数据行改为两列信息结构；
- 证据入口允许换行；
- 不设置内容区 `min-width`；
- 按钮继续至少 44px。
- 主内容底部增加 `max(5.5rem, env(safe-area-inset-bottom))` 安全间距；dialog 最大高度使用 `calc(100dvh - 5.5rem - env(safe-area-inset-bottom))` 并允许内部纵向滚动，避免 Streamlit 固定控件遮挡。

- [ ] **Step 5: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_ui_components.py tests/test_mobile_responsive_ui.py
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/ui/report_styles.py src/ui/report_components.py src/ui/components.py src/ui/responsive.py tests/test_report_experience.py tests/test_ui_components.py tests/test_mobile_responsive_ui.py
git commit -m "feat: add editorial report presentation primitives"
```

### Task 9: 将评测操作页改为一次开始、自动评分和一次继续

**Files:**
- Create: `src/ui/evaluation_config.py`
- Create: `src/ui/evaluation_results.py`
- Modify: `src/ui/test_run.py`
- Modify: `src/ui/page_config.py`
- Test: `tests/test_test_run_flow.py`
- Test: `tests/test_score_result_status.py`
- Test: `tests/test_report_experience.py`
- Test: `tests/test_recoverable_evaluation_queue.py`

- [ ] **Step 1: 写入产品入口守卫和 AppTest 失败测试**

在 `tests/test_report_experience.py` 增加：

```python
from pathlib import Path


def test_evaluation_page_has_one_product_pipeline_and_no_demo_or_score_action():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
    assert 'key="test_run_start_evaluation"' in source
    assert 'key="test_run_continue_evaluation"' in source
    assert 'key="test_run_score_run"' not in source
    assert "生成 AI 评分" not in source
    assert "演示模式" not in source
    assert "从演示结果文件恢复" not in source


def test_evaluation_page_does_not_use_session_state_as_result_source():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
    assert "_PARTIAL_OUTCOMES_KEY" not in source
    assert "_PARTIAL_SCORE_OUTCOMES_KEY" not in source
    assert "EvaluationWorkflow" in source


def test_resume_config_comes_from_checkpoint_not_current_form_selection():
    source = Path("src/ui/test_run.py").read_text(encoding="utf-8")
    assert "build_evaluation_config_from_checkpoint" in source
    assert "workflow.continue_evaluation(status.run_id, checkpoint_config)" in source
```

增加 AppTest：无 API Key 时按钮禁用且数据库／模型均未调用；已中断 fixture 只显示“继续评测”，AppTest 不点击该按钮。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_test_run_flow.py tests/test_score_result_status.py tests/test_recoverable_evaluation_queue.py
```

Expected: FAIL，仍有独立评分阶段、演示状态和 Session State 结果状态机。

- [ ] **Step 3: 拆出配置和结果渲染模块**

从 `src/ui/test_run.py` 移动以下职责到 `src/ui/evaluation_config.py`，函数体保持行为不变：

- `build_sample_options()`、筛选和 checkbox 选择纯函数；
- 样本／模型选择 dialog；
- 提示词预览 dialog；
- `build_run_plan_summary()`、`build_run_queue_items()`；
- 运行参数解析。

从 `src/ui/test_run.py` 移动以下只读渲染到 `src/ui/evaluation_results.py`：

- 回答详情和技术明细；
- 评分维度详情；
- 组合运行记录表；
- `render_evaluation_status(status)`。

保留兼容导入，避免一次性重写所有现有纯函数测试：

```python
from src.ui.evaluation_config import (
    build_run_plan_summary,
    build_run_queue_items,
    build_sample_options,
)
from src.ui.evaluation_results import render_evaluation_status, render_run_record
```

删除独立评分按钮、评分恢复按钮、三段 stage jump 和 mock/demo 展示分支；结果区不再出现“AI 评分”作为可操作阶段名，只把维度分、评分理由和裁判模型信息作为评测记录的一部分展示。

- [ ] **Step 4: 用 `EvaluationWorkflow` 重写页面协调器**

`render_test_run_page()` 固定顺序：

1. 渲染“评测范围”；
2. 从 `ResultStore.latest_queue("live_run_queue")` 取得最近 `run_id`，再调用 `load_evaluation_status(run_id)`；若最近批次已终态，只展示记录并允许创建新批次；只有 `interrupted/stopped/running` 才占用恢复区域；
3. 没有可恢复批次时显示 `开始评测`；
4. 数据库中旧 `stopped` 状态先按 Task 4 派生为 `interrupted`；`interrupted` 时显示 `继续评测`，当前会话刚发生持久化错误的 `stopped` 只显示停止说明，待数据库恢复并重新加载后再提供继续；
5. 其他状态只显示进度、回答、维度评分与技术明细；
6. 所有模型调用前调用现有 `_require_persistence_preflight()`。

现有结果导入／导出、批次技术字段和样本维护跳转移入 `st.popover("评测维护", type="tertiary")`；不得删除维护能力，也不得把它放回主导航或主按钮区。

开始按钮：

```python
if st.button(
    "开始评测",
    key="test_run_start_evaluation",
    type="primary",
    disabled=not run_plan["can_run"] or not service_ready,
    use_container_width=True,
):
    workflow = build_live_workflow()
    workflow.start_evaluation(build_evaluation_config(base, selected_tasks, model_ids))
    cd.clear_conclusions_caches()
    st.rerun()
```

继续按钮：

```python
if status.resumable and st.button(
    "继续评测",
    key="test_run_continue_evaluation",
    type="primary",
    use_container_width=True,
):
    workflow.continue_evaluation(status.run_id, checkpoint_config)
    cd.clear_conclusions_caches()
    st.rerun()
```

页面打开本身只执行 `load_evaluation_status()`，不得调用 `start_evaluation()` 或 `continue_evaluation()`。

续跑配置不能取当前表单的任意新选择。新增 `build_evaluation_config_from_checkpoint(run_id, base)`：读取已持久化回答队列的 case/model 列表与 run metadata 中的生成／评分 JSON，从当前 base 按 `case_id` 重建 task、Gold 和 prompt；若任何样本已缺失或 `build_run_metadata()` 复算哈希不一致，按钮禁用并显示“当前样本或参数已变化，不能继续旧批次”。因此继续按钮前使用的 `checkpoint_config` 必须来自该函数，而不是当前新批次表单。

- [ ] **Step 5: 清理旧评分 UI 状态和测试**

删除 `ScoreResultStatus` 的 `demo` 分支、`_render_scoring()`、`_execute_score_queue()`、`_render_score_recovery_actions()` 和对应 Session State key。`tests/test_score_result_status.py` 改为针对 `EvaluationRunStatus` 覆盖 `running`、`completed`、`partial`、`failed`、`interrupted`、`stopped` 六个互斥状态，每种状态只断言一个标题和一条汇总文案，不再维护评分子状态。

- [ ] **Step 6: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_report_experience.py tests/test_test_run_flow.py tests/test_score_result_status.py tests/test_recoverable_evaluation_queue.py tests/test_evaluation_workflow.py
```

Expected: PASS；产品源码只有开始和继续两个互斥动作，没有独立评分或演示入口。

- [ ] **Step 7: 提交**

```bash
git add src/ui/evaluation_config.py src/ui/evaluation_results.py src/ui/test_run.py src/ui/page_config.py tests/test_test_run_flow.py tests/test_score_result_status.py tests/test_report_experience.py tests/test_recoverable_evaluation_queue.py
git commit -m "feat: expose one automatic evaluation action"
```

### Task 10: 将评测结论页改为执行摘要和证据索引

**Files:**
- Modify: `src/ui/conclusions.py`
- Modify: `src/ui/conclusions_data.py`
- Modify: `src/ui/report_components.py`
- Modify: `src/ui/report_styles.py`
- Test: `tests/test_conclusions.py`
- Test: `tests/test_report_experience.py`
- Test: `tests/test_mobile_responsive_ui.py`

- [ ] **Step 1: 写入首屏顺序、证据入口和隐藏排除项测试**

在 `tests/test_report_experience.py` 增加：

```python
def test_conclusion_page_is_report_first_and_never_surfaces_excluded_count():
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
    page = source[source.index("def render_conclusions_page"):source.index("def _render_data_source_notice")]
    assert page.index("render_report_masthead") < page.index("_render_executive_conclusion")
    assert page.index("_render_executive_conclusion") < page.index("_render_model_recommendations")
    assert page.index("_render_model_recommendations") < page.index("_render_evidence_index")
    assert page.index("_render_evidence_index") < page.index("_render_all_records")
    assert "排除项" not in source
    assert "_render_mobile_model_cards" not in source


def test_each_evidence_item_exposes_gold_answer_response_and_rationale():
    source = Path("src/ui/conclusions.py").read_text(encoding="utf-8")
    for label in ["查看专业标准答案", "查看模型回答全文", "查看评分理由"]:
        assert label in source
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_conclusions.py tests/test_report_experience.py tests/test_mobile_responsive_ui.py
```

Expected: FAIL，页面仍使用 dataframe＋手机卡片和独立回答明细。

- [ ] **Step 3: 实现首屏报告和动态台账**

`render_conclusions_page()` 从现有 `src.ui.components.PROJECT_DISPLAY_NAME` 和 `get_page_config("conclusions").question` 取项目标题与说明，不创建新文案常量，按下列顺序渲染：

```python
config = get_page_config("conclusions")
render_report_masthead(PROJECT_DISPLAY_NAME, config.question)
render_scope_ledger([
    ("样本范围", f"{report.scope.sample_count} 个专业任务样本"),
    ("比较范围", f"{report.scope.model_count} 个模型"),
    ("证据记录", f"{report.scope.formal_score_count} 条正式评分"),
    ("数据口径", report.scope.data_basis),
])
_render_executive_conclusion(report.model_summaries)
_render_model_recommendations(report.model_summaries)
_render_evidence_index(report, selected_model)
```

`_render_executive_conclusion()` 继续调用现有 `_current_judgment()`，不得重写结论。数据来源行不再显示历史演示或其他排除项数量。现有 `_render_model_issue_details()` 改名为 `_render_all_records()` 并放在证据索引之后的折叠区域，使用 `report.formal_scores`／`report.formal_responses`，保证“查看全部评测记录”仍可访问而不会抢占首屏。

- [ ] **Step 4: 用同一模型审阅行替代桌面表＋手机卡片**

使用 `report_index_row_html()` 渲染模型名、样本数／均分、当前判断和主要依据；每行只有一个三级“查看证据”按钮。手机端由 CSS 重排同一 DOM，不调用第二个 `_render_mobile_model_cards()`。

选中模型后调用 `request_scroll("#fde-evidence-index")`，证据索引按 Task 5 数据逐条提供三个详情 dialog。评分理由展示现有 `rationale` 和 `review_note`，不得生成摘要文本；Gold、模型回答和评分理由均显示全文，不做 900 字 UI 截断，局部代码块或原始数据表可在自身容器横向滚动。

- [ ] **Step 5: 数据库不可用和零数据分支**

- `ConclusionSource.available=False`：显示持久化不可用状态，不显示“暂无模型判断”。
- available 且无正式评分：显示现有“暂无模型判断。请先在评测操作页运行评测。”空状态。
- available 且有数据：不出现加载动画残留。

- [ ] **Step 6: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_conclusions.py tests/test_report_experience.py tests/test_mobile_responsive_ui.py tests/test_model_use_boundaries.py
```

Expected: PASS；模型判断、阈值和排序测试保持不变。

- [ ] **Step 7: 提交**

```bash
git add src/ui/conclusions.py src/ui/conclusions_data.py src/ui/report_components.py src/ui/report_styles.py tests/test_conclusions.py tests/test_report_experience.py tests/test_mobile_responsive_ui.py
git commit -m "feat: present conclusions as traceable report"
```

### Task 11: 将项目说明和样本库统一为报告附录与样本档案

**Files:**
- Modify: `src/ui/case_study.py`
- Modify: `src/ui/samples.py`
- Modify: `src/ui/report_components.py`
- Modify: `src/ui/report_styles.py`
- Modify: `src/ui/responsive.py`
- Test: `tests/test_project_brief_presentation.py`
- Test: `tests/test_sample_browser.py`
- Test: `tests/test_sample_asset_detail.py`
- Test: `tests/test_mobile_responsive_ui.py`
- Test: `tests/test_report_experience.py`
- Create: `tests/fixtures/project_method_copy.txt`

- [ ] **Step 1: 写入原文守卫和单一样本索引测试**

在 `tests/test_report_experience.py` 增加：

```python
def test_project_method_copy_is_preserved_verbatim():
    from src.ui.case_study import professional_copy_snapshot

    baseline = Path("tests/fixtures/project_method_copy.txt").read_text(encoding="utf-8")
    assert professional_copy_snapshot() == baseline


def test_samples_use_one_index_renderer_and_archive_tabs():
    source = Path("src/ui/samples.py").read_text(encoding="utf-8")
    assert "def _render_sample_index" in source
    assert "_render_mobile_sample_cards" not in source
    for label in ["任务与模拟数据", "专业标准答案", "质量要求", "评审重点"]:
        assert label in source
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_project_brief_presentation.py tests/test_sample_browser.py tests/test_sample_asset_detail.py tests/test_mobile_responsive_ui.py tests/test_report_experience.py
```

Expected: FAIL，样本页仍有独立手机卡片。

- [ ] **Step 3: 重排项目说明但逐字保留专业正文**

先从当前 `render_case_study_page()` 中提取 `render_brief_intro()` 的 `note`，以及三个 `render_home_section()` 的 `title`、`lead`、`body` 字面量，按源码顺序逐字保存为 `tests/fixtures/project_method_copy.txt`。重构时把这些字面量原样搬入 `BRIEF_NOTE` 和 `CASE_STUDY_SECTIONS` 常量，并新增 `professional_copy_snapshot()` 只拼接这两项；测试直接断言该函数等于 fixture。随后只把封面和章节渲染器换成 `report_masthead`、`scope_ledger` 和 `report_section`。流程标签属于界面流程提示，可改为：

```python
PROCESS_STEPS = ["人工录入样本库", "开始评测", "模型回答与 AI 评分", "进入评测结论"]
```

正文中“模型生成回答后，AI 评分链路……”等方法描述原样保留。

- [ ] **Step 4: 实现单一专业样本索引**

将 `_render_samples_table()` 和 `_render_mobile_sample_cards()` 合并为 `_render_sample_index()`。函数只调用一次 `build_sample_table_rows()`，每一行渲染编号、完整标题、场景、状态和一个“查看详情”动作；移动端通过 CSS 隐藏表头并纵向重排同一行。

维护入口仍是三级文字 Popover。筛选保留关键词、专业场景和折叠“更多筛选”。

- [ ] **Step 5: 将详情改为四个档案页签**

`render_sample_detail_panel()` 使用 `st.tabs()`；四个 tab 都在同一次 Streamlit 渲染中调用既有详情函数，不能只按当前 tab 条件加载，否则内容会在切换时丢失：

```python
task_tab, gold_tab, quality_tab, review_tab = st.tabs([
    "任务与模拟数据",
    "专业标准答案",
    "质量要求",
    "评审重点",
])
```

- task：现有任务题、业务背景和输出要求；
- gold：现有专业标准答案；
- quality：现有评分标准和必须覆盖点／不可接受错误；
- review：现有评审重点、边界与历史运行信息。

所有内容调用既有 HTML／Markdown 转义函数，不截断、不改写原文。

- [ ] **Step 6: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_project_brief_presentation.py tests/test_sample_browser.py tests/test_sample_asset_detail.py tests/test_mobile_responsive_ui.py tests/test_report_experience.py
```

Expected: PASS；手机和桌面使用同一索引行数据。

- [ ] **Step 7: 提交**

```bash
git add src/ui/case_study.py src/ui/samples.py src/ui/report_components.py src/ui/report_styles.py src/ui/responsive.py tests/test_project_brief_presentation.py tests/test_sample_browser.py tests/test_sample_asset_detail.py tests/test_mobile_responsive_ui.py tests/test_report_experience.py
git add tests/fixtures/project_method_copy.txt
git commit -m "feat: align project and samples with report reading"
```

### Task 12: 清理演示文案、旧卡片 CSS 和项目文档

**Files:**
- Modify: `README.md`
- Modify: `src/ui/components.py`
- Modify: `src/ui/responsive.py`
- Modify: `src/ui/conclusions.py`
- Modify: `src/ui/test_run.py`
- Test: `tests/test_ui_text_guardrails.py`
- Test: `tests/test_repository_readiness.py`
- Test: `tests/test_uiux_audit_fixes.py`
- Test: `tests/test_mobile_responsive_ui.py`

- [ ] **Step 1: 写入产品源码无演示入口和无旧卡片选择器测试**

在 `tests/test_ui_text_guardrails.py` 增加：

```python
def test_product_ui_has_no_demo_mode_or_manual_score_action():
    text = "\n".join(
        _rendered_ui_text(path)
        for path in VISIBLE_UI_FILES
        if path.name != "case_study.py"
    )
    for phrase in ["演示模式", "演示恢复", "生成 AI 评分", "从演示结果文件恢复"]:
        assert phrase not in text


def test_visible_ui_has_no_mobile_selection_card_system():
    text = Path("src/ui/components.py").read_text(encoding="utf-8") + Path("src/ui/responsive.py").read_text(encoding="utf-8")
    assert "mobile-select-card" not in text
    assert ".metric-card" not in text
    assert ".status-badge" not in text
```

`_rendered_ui_text()` 使用 AST 收集 `st.button`、`st.caption`、`st.radio`、`st.selectbox`、`render_empty_state` 和 `render_persistence_status` 的字符串参数，只检查实际产品控件／状态文案；`case_study.py` 的专业正文由 Task 11 的逐字 fixture 单独保护，不能因其中说明历史“演示数据”边界而被误改。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_ui_text_guardrails.py tests/test_repository_readiness.py tests/test_uiux_audit_fixes.py tests/test_mobile_responsive_ui.py
```

Expected: FAIL，旧演示文案、卡片 CSS 或 README 标题仍存在。

- [ ] **Step 3: 删除不再被调用的视觉和产品分支**

删除：

- `.mobile-select-card*`、独立桌面／手机视图隐藏规则；
- `.executive-takeaway` 的卡片式背景或圆角，只保留报告引文线；
- `.st-key-test_run_stage_scores` 和 `.st-key-test_run_score_action`；
- 结论页“演示数据不会进入结论”提示；正式数据口径改为“仅纳入正式评分”；
- 产品 UI 中 mock/demo 状态文本。

保留底层 MockProvider 和对应模型／评分单元测试，不把测试替身重新暴露到页面。

- [ ] **Step 4: 更新 README 的真实流程和恢复说明**

将 `## 演示与恢复` 改为 `## 运行与恢复`，明确：

- 点击一次开始评测后自动生成回答并评分；
- 已完成回答和评分增量保存；
- 中断后由用户点击继续评测；
- 数据库不可用时不调用模型；
- 无 API Key 时只能浏览，开始评测按钮保持禁用并说明需要配置真实模型密钥。

不得增加面试脚本、营销文案或泛化排名表述。

- [ ] **Step 5: 运行测试并确认通过**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_ui_text_guardrails.py tests/test_repository_readiness.py tests/test_uiux_audit_fixes.py tests/test_mobile_responsive_ui.py
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add README.md src/ui/components.py src/ui/responsive.py src/ui/conclusions.py src/ui/test_run.py tests/test_ui_text_guardrails.py tests/test_repository_readiness.py tests/test_uiux_audit_fixes.py tests/test_mobile_responsive_ui.py
git commit -m "refactor: remove demo and dashboard presentation paths"
```

---

## Milestone D：系统验证与部署交付

### Task 13: 全量测试、数据不变量和浏览器回归

**Files:**
- Modify when a regression requires a scoped fix: files already listed in Tasks 1–12
- Test: entire `tests/` suite
- Verify: local Streamlit app
- Verify: deployed Streamlit app after merge and push

- [ ] **Step 1: 运行静态检查与全量自动测试**

Run:

```bash
git diff --check
PYTHONPATH=. pytest -q
```

Expected: `git diff --check` 无输出；全量测试 PASS。测试输出中不得出现真实 SiliconFlow 请求或正式 Supabase 写入。

- [ ] **Step 2: 记录实施前后的正式数据不变量**

在开始 Task 1 前先执行一次并保存终端输出；完成 Task 12 后再执行同一命令。通过当前 `DATABASE_URL` 只读查询：

```bash
psql "$DATABASE_URL" --set=ON_ERROR_STOP=1 --tuples-only --no-align \
  --command="select 'formal_responses', count(*) from live_run_responses where run_status = 'success' and coalesce(run_mode, 'live') not in ('mock', 'demo') and status <> 'inactive' union all select 'formal_scores', count(*) from live_run_scores where judge_status = 'success' and coalesce(judge_mode, 'live') not in ('mock', 'demo') and status <> 'inactive' and review_status <> 'skipped' union all select 'historical_demo_scores', count(*) from live_run_scores where coalesce(judge_mode, '') in ('mock', 'demo') or coalesce(judge_provider, '') in ('mock', 'demo');"
```

Expected: 两次输出的三项数量完全一致；历史演示记录允许大于 0，但 `filter_formal_scores()` 对相同行返回 0。命令只执行 `SELECT`，不得执行 `UPDATE`、`DELETE` 或评测调用。若本机没有 `psql`，使用已安装的 PostgreSQL 客户端执行同一条只读查询，仍须在开始 Task 1 前记录基线。

- [ ] **Step 3: 启动本地 Streamlit 并执行 Ego Browser 回归**

Run:

```bash
streamlit run app.py --server.headless true --server.port 8536
```

在 1710×1009、768px、390×844、320px 检查四页：

- 默认打开评测结论；
- 导航三项审阅入口加一次级评测操作；
- 从任意长页面滚动后切页，稳定后 `stMain.scrollTop <= 8px`，三项主导航顶部坐标差不超过 1px；
- 四页 `documentElement.scrollWidth <= innerWidth`；
- 首页无内容卡片墙、KPI 侧栏、渐变或投影；
- 结论证据入口能打开 Gold、回答和评分理由；
- 样本索引与档案页签在手机端完整可达；
- 评测页只出现一个适用主动作：新批次为开始评测，中断批次为继续评测；
- 页面打开和导航切换不产生任何模型调用。

- [ ] **Step 4: 做一次隔离假 provider 的端到端流程验证**

使用临时 SQLite、`name="test-live"` 的确定性 provider 和固定 `ScoreOutcome` 运行 `EvaluationWorkflow`：

```bash
PYTHONPATH=. pytest -q tests/test_evaluation_workflow.py -k "start or continue or persistence"
```

Expected: 回答、评分和队列均持久化；中断续跑不重复调用；没有外部网络访问。

- [ ] **Step 5: 提交最终回归修复**

仅当 Step 1–4 产生了必要修复时执行：

```bash
git add app src tests README.md
git commit -m "test: complete evidence report regression coverage"
```

若工作树没有新的修复，不创建空提交。

- [ ] **Step 6: 合并并推送部署分支**

确认当前分支测试通过后，使用 `superpowers:finishing-a-development-branch` 完成集成。按用户既有部署方式本地合并到 `main`，再推送：

```bash
git switch main
git merge --no-ff codex/evidence-first-evaluation-report
git push origin main
```

不得提交 `.streamlit/secrets.toml`、`.env` 或 `.claude/`。

- [ ] **Step 7: 线上只读回归**

等待 Streamlit 自动部署后，使用 Ego Browser 打开 `https://finance-model-eval.streamlit.app/`，重复 Step 3 的四种视口检查。若仍为旧版本，只重启应用，不重置 Supabase，不点击开始／继续评测，不导入或删除数据。

---

## 完成判定

全部条件同时满足才可宣告完成：

- `PYTHONPATH=. pytest -q` 全部通过；
- 生产 UI 不存在演示模式、演示恢复和独立评分入口；
- 一次开始评测自动完成回答、评分和增量保存；
- 持久化失败后 provider 调用计数不再增加；
- 重启后只展示可恢复进度，必须点击继续评测才产生 Token；
- 历史演示记录未被删除，但所有产品读取为 0；
- 默认首页、导航、结论证据链和样本档案符合中文研究简报基线；
- 四种视口无页面级横向溢出；
- 既有专业文案、评分模型、阈值、提示词和正式数据保持不变；
- `main` 与 `origin/main` 同步，线上页面通过只读回归。

## 规格覆盖自审

- 规格 5–9（默认首页、导航分层、结论证据链、项目说明、样本档案）：Tasks 5–8、10–11。
- 规格 10–11（单入口自动评测、逐条评分、批次关系、恢复与并发领取）：Tasks 2–4、9。
- 规格 12–15（正式数据唯一口径、内部边界、模块拆分、错误处理）：Tasks 1、3–6、9、12。
- 规格 16–17（TDD、四视口、数据不变量、部署顺序）：Tasks 1–13，尤其 Task 13。
- 约束复核：计划不新增数据库表／列，不物理删除历史数据，不修改评分配置／提示词／专业正文，不让浏览器回归触发真实调用。
