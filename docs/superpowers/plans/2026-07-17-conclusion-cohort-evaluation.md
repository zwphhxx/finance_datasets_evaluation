# Conclusion Cohort Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复现有结论边界的误判，并让结论只合并元数据完全兼容的独立评测批次；部署后新增两个模型的 26 条回答和 26 条评分，逐条持久化到 PostgreSQL/Supabase。

**Architecture:** 保留每个回答批次和评分批次的不可变身份，通过运行元数据计算兼容签名。在结论读取层选定最新可验证批次为基线，合并所有签名相同的批次，并按 `(case_id, eval_model)` 选择最新成功评分。边界判断只使用结构化分数和结构化错误严重度；自由文本说明保留展示，但不再改变结论等级。

**Tech Stack:** Python 3.11、Streamlit、pandas、pytest、PostgreSQL/Supabase、SiliconFlow API、GitHub Actions

---

## Task 1: 修复评分边界规则

**Files:**
- Modify: `tests/test_model_use_boundaries.py`
- Modify: `app/services/conclusions.py`

- [x] **Step 1: 写入会失败的边界回归测试**

在 `tests/test_model_use_boundaries.py` 增加以下用例：

1. 平均分和分项均达标时，`review_note="风险覆盖全面，无不可接受错误"` 不得将模型降级，结论应为 `可作为初稿参考`。
2. 平均分达标但一个高风险样本低于 60 分时，结论最多降为 `需谨慎参考`，不得直接变成 `不建议作为证据来源`。
3. 高风险样本中存在结构化高严重度错误时，仍应为 `不建议作为证据来源`。

- [x] **Step 2: 运行测试并确认旧逻辑失败**

Run: `pytest -q tests/test_model_use_boundaries.py`

Expected: 新增的前两个测试失败；结构化高严重度错误测试继续通过。

- [x] **Step 3: 实现最小规则修复**

在 `app/services/conclusions.py`：

1. 删除基于 `review_note`、`judge_rationale` 自由文本关键词改变边界等级的路径。
2. 高风险样本分数低于 60 只将等级提升到 `需谨慎参考`。
3. 保留平均分低于 60、严重分项达成率低于 35%、高风险样本存在结构化高严重度错误时的危险等级。
4. 保留说明文本作为明细证据，不修改界面文案。

- [x] **Step 4: 运行边界测试并确认通过**

Run: `pytest -q tests/test_model_use_boundaries.py`

Expected: 全部通过。

- [x] **Step 5: 提交边界修复**

```bash
git add app/services/conclusions.py tests/test_model_use_boundaries.py
git commit -m "fix: derive model boundaries from structured evidence"
```

## Task 2: 增加兼容批次选择和去重

**Files:**
- Modify: `tests/test_conclusions.py`
- Modify: `app/services/conclusions.py`

- [x] **Step 1: 写入会失败的批次兼容测试**

在 `tests/test_conclusions.py` 增加纯函数测试，覆盖：

1. `dataset_version`、`dataset_hash`、`prompt_hash`、`generation_parameters_json`、`judge_parameters_json` 完全相同的多个独立批次可以合并。
2. JSON 键顺序不同但语义相同仍视为兼容。
3. 任一兼容字段不同的批次必须排除。
4. 同一 `(case_id, eval_model)` 有多条成功记录时，按 `updated_at`、`created_at`、`id` 选择最新一条。
5. 较新的失败记录不得覆盖较早的成功记录。
6. 缺少必需元数据时不猜测兼容性，不进入当前结论样本。

- [x] **Step 2: 运行测试并确认缺少选择器**

Run: `pytest -q tests/test_conclusions.py`

Expected: 因 `select_current_cohort_scores` / `load_current_cohort_scores` 尚未实现而失败。

- [x] **Step 3: 实现兼容签名和当前样本选择**

在 `app/services/conclusions.py`：

1. 新增 JSON 规范化和运行兼容签名辅助函数。
2. 新增 `select_current_cohort_scores(runs_df, scores_df)`：选择最新完成且至少有一条有效成功评分的运行作为基线，合并签名相同运行的成功记录，再按样本和模型去重。
3. 只纳入 `status=success`、活动、非种子记录；失败、跳过、模拟和非活动记录不进入结论。
4. 新增 `load_current_cohort_scores(db_path=None)`，从 `live_evaluation_runs` 和 `live_run_scores` 读取后调用纯函数。
5. 保留原 `load_live_scores()`，避免改变导出和审计用途。

- [x] **Step 4: 运行结论服务测试并确认通过**

Run: `pytest -q tests/test_conclusions.py tests/test_model_use_boundaries.py`

Expected: 全部通过。

- [x] **Step 5: 提交批次选择实现**

```bash
git add app/services/conclusions.py tests/test_conclusions.py
git commit -m "feat: select compatible evaluation cohorts"
```

## Task 3: 让结论页使用当前兼容样本

**Files:**
- Modify: `tests/test_ui_refactor.py`
- Modify: `src/ui/conclusions.py`

- [x] **Step 1: 写入会失败的界面接线测试**

增加源码级回归测试，要求结论页调用 `load_current_cohort_scores()`，且不直接用全部 `load_live_scores()` 生成结论。

- [x] **Step 2: 运行测试并确认失败**

Run: `pytest -q tests/test_ui_refactor.py`

Expected: 新测试失败。

- [x] **Step 3: 修改结论页数据入口**

将 `src/ui/conclusions.py` 的结论数据读取改为 `cc.load_current_cohort_scores()`；不修改任何页面文案。

- [x] **Step 4: 运行相关测试并确认通过**

Run: `pytest -q tests/test_ui_refactor.py tests/test_conclusions.py tests/test_model_use_boundaries.py`

Expected: 全部通过。

- [x] **Step 5: 提交界面接线**

```bash
git add src/ui/conclusions.py tests/test_ui_refactor.py
git commit -m "fix: scope conclusions to compatible runs"
```

## Task 4: 回归验证和真实数据只读验证

**Files:**
- Verify: `app/services/conclusions.py`
- Verify: `src/ui/conclusions.py`
- Verify: `data/fin_eval_v2.jsonl`

- [ ] **Step 1: 运行完整测试和静态检查**

Run:

```bash
pytest -q
ruff check .
python scripts/validate_dataset.py
```

Expected: 所有测试通过，ruff 无错误，数据集校验通过。

- [ ] **Step 2: 运行 PostgreSQL 持久化测试**

Run: `pytest -q tests/test_postgres_store.py tests/test_persistence.py tests/test_eval_runner.py tests/test_scorer.py`

Expected: 全部通过。

- [ ] **Step 3: 对 Supabase 当前 39 条评分进行只读重算**

读取 `FRESH-SCORE-20260717-CURRENT13-V1`，断言：

- 13 个活动样本 × 3 个模型 = 39 条成功评分；
- 当前数据集、提示和参数哈希均与运行元数据一致；
- 修复后的边界分别为：DeepSeek `可作为初稿参考`，LongCat `需谨慎参考`，Qwen `需谨慎参考`。

不得写数据库，不得发起模型调用。

## Task 5: 推送、合并并确认部署代码

**Files:**
- Verify: Git history and GitHub Actions

- [ ] **Step 1: 提交实施计划中的剩余跟踪更新（如有）**

只提交本任务相关文件；不得加入用户的 `.claude/` 目录或本地 secret。

- [ ] **Step 2: 推送功能分支**

Run: `git push -u origin codex/fix-conclusion-cohorts`

Expected: 推送成功。

- [ ] **Step 3: 创建 PR 并合并到 `main`**

PR 标题：`Fix conclusion cohorts and scoring boundaries`

PR 内容应说明边界修复、兼容签名、去重规则和测试结果。合并前确认目标分支为 `main`。

- [ ] **Step 4: 确认部署分支 CI 成功**

检查合并后的 `main` GitHub Actions 状态；失败则先诊断并修复，不能进入模型调用。

## Task 6: 新建独立回答批次并逐条持久化

**Files:**
- Use: `app/services/eval_runner.py`
- Use: `app/services/run_checkpoint.py`
- Use: `src/ui/test_run.py`

- [ ] **Step 1: 运行持久化预检**

在任何 Token 调用之前断言：

1. 当前 store 是 PostgreSQL/Supabase，而不是 SQLite。
2. `ping()` 成功。
3. 13 个活动样本的版本、数据哈希、提示哈希与基线运行完全一致。
4. 两个模型在 SiliconFlow 模型目录中可用。
5. 新批次 ID 不与其他元数据冲突；若同 ID 已有队列，仅允许按原元数据断点续跑。

- [ ] **Step 2: 初始化完整回答队列**

使用运行 ID `EXTEND-20260717-DIVERSE2-V1`，模型：

- `zai-org/GLM-5.2`
- `Pro/moonshotai/Kimi-K2.6`

参数：`temperature=0.1`，`max_tokens=4096`。在第一次 API 调用前，将 13 × 2 = 26 条队列及兼容元数据一次性写入 Supabase。

- [ ] **Step 3: 逐条生成和提交**

对每一项执行：标记 running → 调用模型 → 单行事务持久化 success/error。只有本行持久化成功后才允许调用下一项；持久化失败立即停止。已有 success 项跳过以支持断点续跑。

- [ ] **Step 4: 验证回答批次**

断言 Supabase 中该运行有 26 条队列、26 条成功回答、0 个重复 `(case_id, model_id)`，并校验所有响应的模型归属。

## Task 7: 新建独立评分批次并逐条持久化

**Files:**
- Use: `app/services/scorer.py`
- Use: `app/services/run_checkpoint.py`

- [ ] **Step 1: 初始化完整评分队列**

使用评分运行 ID `EXTEND-SCORE-20260717-DIVERSE2-V1`，judge 模型固定为 `deepseek-ai/DeepSeek-V4-Pro`，参数 `temperature=0.0`、`max_tokens=2048`。在第一次 judge 调用前，将 26 条评分队列及兼容元数据写入 Supabase。

- [ ] **Step 2: 逐条评分和提交**

对每一项执行：标记 running → 调用 judge → 单行事务持久化 success/error。只有本行持久化成功后才继续；持久化失败立即停止。已有 success 项跳过。

- [ ] **Step 3: 验证评分批次**

断言 Supabase 中该评分运行有 26 条队列、26 条成功评分、0 个重复 `(case_id, eval_model)`；每条评分均能连接到对应回答、活动样本和 rubric。

- [ ] **Step 4: 验证当前结论样本和输出**

使用 `load_current_cohort_scores()` 断言当前兼容样本为 65 条成功评分、13 个样本、5 个模型；旧 39 条与新 26 条按兼容规则合并，没有把新模型追加到旧批次。重新生成五个模型的边界和核心统计，并记录实际结果。

- [ ] **Step 5: 最终敏感信息与工作区检查**

确认 git 历史、日志和输出中无数据库密码/API key；确认 `.streamlit/secrets.toml`、`.env`、`.claude/` 均未被提交。
