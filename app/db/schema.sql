-- 项目 SQLite 数据层 schema（PR-30）
--
-- 设计原则：
--   1. 每张表的业务列与现有 data/ 种子文件（CSV/JSON 与 manifest）的字段一一对应，
--      便于从种子数据无损导入，并保证页面读取结果与旧数据完全一致。
--   2. 每张表附带 status、created_at、updated_at 基础字段，便于后续 CRUD 与运行记录留痕。
--   3. 任务题、Gold Answer、Rubric 等核心对象额外保留 version，便于后续版本追踪。
--   4. 仅使用 SQLite 内建能力，不引入任何外部数据库或服务。
--
-- 重复执行安全：先 DROP 再 CREATE，确保 init 脚本可重复初始化得到干净结构。

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS task_cases;
DROP TABLE IF EXISTS gold_answers;
DROP TABLE IF EXISTS rubrics;
DROP TABLE IF EXISTS model_responses;
DROP TABLE IF EXISTS score_records;
DROP TABLE IF EXISTS error_annotations;
DROP TABLE IF EXISTS improvement_actions;
DROP TABLE IF EXISTS evaluation_runs;
DROP TABLE IF EXISTS error_taxonomy;
DROP TABLE IF EXISTS live_run_responses;
DROP TABLE IF EXISTS live_run_scores;
DROP TABLE IF EXISTS live_run_queue;
DROP TABLE IF EXISTS live_score_queue;

-- 任务题：对应 data/tasks.csv。status 复用任务的 draft/active/inactive 标记，
-- 由样本库中文状态映射后控制测试准入。
CREATE TABLE task_cases (
    case_id              TEXT PRIMARY KEY,
    domain               TEXT,
    scenario             TEXT,
    task_type            TEXT,
    difficulty           TEXT,
    question             TEXT,
    context              TEXT,
    expected_capability  TEXT,
    risk_level           TEXT,
    status               TEXT NOT NULL DEFAULT 'active',
    version              TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Gold Answer：对应 data/gold_answers.json。结构化字段单列存储便于查询；
-- raw_json 保留原始条目，作为页面重建的权威来源，确保展示结果与旧数据一致。
CREATE TABLE gold_answers (
    case_id              TEXT PRIMARY KEY,
    core_conclusion      TEXT,
    key_evidence         TEXT,
    analysis             TEXT,
    materials_to_check   TEXT,
    boundary_conditions  TEXT,
    must_have_points     TEXT,   -- JSON 数组
    unacceptable_errors  TEXT,   -- JSON 数组
    manual_review_notes  TEXT,
    raw_json             TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active',
    version              TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (case_id) REFERENCES task_cases (case_id)
);

-- Rubric 维度：对应 dataset_manifest.yml 的 rubric.dimensions。
-- full_mark_standard / deduction_rules 为质量治理补充字段：满分标准与扣分规则，
-- 由 dataset_manifest.yml 初始化，样本库编辑可按需维护。
CREATE TABLE rubrics (
    dimension_field    TEXT PRIMARY KEY,
    name               TEXT,
    weight             INTEGER,
    full_mark          INTEGER,
    total              INTEGER,
    full_mark_standard TEXT,
    deduction_rules    TEXT,
    status             TEXT NOT NULL DEFAULT 'active',
    version            TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 模型回答：对应 data/model_outputs.csv。
CREATE TABLE model_responses (
    output_id    INTEGER PRIMARY KEY,
    case_id      TEXT,
    model_name   TEXT,
    answer_text  TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (case_id) REFERENCES task_cases (case_id)
);

-- Rubric 评分：对应 data/scores.csv，与 model_responses 共享 output_id。
CREATE TABLE score_records (
    output_id         INTEGER PRIMARY KEY,
    case_id           TEXT,
    model_name        TEXT,
    accuracy_score    INTEGER,
    reasoning_score   INTEGER,
    coverage_score    INTEGER,
    evidence_score    INTEGER,
    expression_score  INTEGER,
    total_score       INTEGER,
    review_note       TEXT,
    status            TEXT NOT NULL DEFAULT 'active',
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (output_id) REFERENCES model_responses (output_id)
);

-- 错误标签：对应 data/error_labels.csv，原始无单列主键，使用自增 id。
CREATE TABLE error_annotations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    output_id           INTEGER,
    case_id             TEXT,
    model_name          TEXT,
    error_type          TEXT,
    severity            TEXT,
    error_description   TEXT,
    correction          TEXT,
    optimization_action TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (output_id) REFERENCES model_responses (output_id)
);

-- 数据补强动作：对应 data/optimization_plan.csv，原始无单列主键，使用自增 id。
-- frequent_error 既是原始列，也作为「关联错误标签」(related_error_label) 的取值来源，
-- 关联到 error_taxonomy.error_label；action_id 为可读业务编号；action_type /
-- expected_effect / validation_method 为补强动作的治理补充字段，种子导入时留空，不预置编造内容。
CREATE TABLE improvement_actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id           TEXT,
    frequent_error      TEXT,
    typical_problem     TEXT,
    affected_cases      TEXT,
    likely_cause        TEXT,
    optimization_action TEXT,
    data_sample_format  TEXT,
    action_type         TEXT,
    expected_effect     TEXT,
    validation_method   TEXT,
    priority            TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 评测批次：对应 data/evaluation_runs.csv。
CREATE TABLE evaluation_runs (
    run_id          TEXT PRIMARY KEY,
    run_name        TEXT,
    model_name      TEXT,
    model_version   TEXT,
    prompt_version  TEXT,
    eval_scope      TEXT,
    run_date        TEXT,
    note            TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 错误标签体系：对应 data/label_taxonomy.yml 的 labels，作为可维护的运行时标签层。
-- 业务列与 taxonomy 字段对应：error_label←name、definition、typical_symptom←typical_signs、
-- related_dimension←impacted_dimension、suggested_data_action←data_direction。
-- severity_level 与 validation_metric 在 seed 中不存在，留空待维护，不预置编造内容。
CREATE TABLE error_taxonomy (
    error_label           TEXT PRIMARY KEY,
    definition            TEXT,
    typical_symptom       TEXT,
    severity_level        TEXT,
    related_dimension     TEXT,
    suggested_data_action TEXT,
    validation_metric     TEXT,
    status                TEXT NOT NULL DEFAULT 'active',
    version               TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 真实模型评测运行结果（PR-34）。本表不来自任何 seed 文件，仅承载「真实模型评测」页
-- 运行产生的模型回答，与承载评分的 model_responses（seed）分离，避免污染既有分析页。
-- run_status 为生成业务状态（success/failed/mock）；status 为行生命周期标记（active/inactive）。
-- 不存储 API Key、Authorization 头或任何认证信息。
CREATE TABLE live_run_responses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    case_id       TEXT,
    task_type     TEXT,
    provider      TEXT,
    model_name    TEXT,
    run_mode      TEXT,
    run_status    TEXT,
    answer_text   TEXT,
    answer_length INTEGER,
    latency_ms    INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    total_tokens  INTEGER,
    http_status   INTEGER,
    trace_id      TEXT,
    finish_reason TEXT,
    incomplete_reason TEXT,
    retry_count   INTEGER,
    first_finish_reason TEXT,
    final_finish_reason TEXT,
    timeout_seconds REAL,
    timeout_source TEXT,
    error_code    TEXT,
    error_message TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 可恢复的模型回答队列。本表只记录运行状态，不代表后台任务；页面中断后用于恢复
-- 未完成/失败项，已完成回答仍以 live_run_responses 为准。
CREATE TABLE live_run_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    case_id       TEXT,
    task_type     TEXT,
    model_id      TEXT,
    provider      TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_code    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 真实模型评测的 LLM-as-judge 评分（PR-35）。本表不来自任何 seed 文件，仅承载「真实模型评测」
-- 页由裁判模型对照 Gold Answer + Rubric 产出的「机器建议分」，与 seed 的 score_records 分离。
-- 评分为机器建议，需人工复核：review_status 为 pending（待复核）/ confirmed（已确认）/ skipped（暂不采用）。
-- judge_status 为裁判调用业务状态（success/failed/mock）；mock 模式不产生真实分数（维度列为空）。
-- eval_model 为被评测模型，judge_model 为裁判模型；不存储任何认证信息。
CREATE TABLE live_run_scores (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    score_run_id     TEXT,
    run_id           TEXT,
    case_id          TEXT,
    task_type        TEXT,
    eval_model       TEXT,
    judge_provider   TEXT,
    judge_model      TEXT,
    judge_mode       TEXT,
    judge_status     TEXT,
    accuracy_score   INTEGER,
    reasoning_score  INTEGER,
    coverage_score   INTEGER,
    evidence_score   INTEGER,
    expression_score INTEGER,
    total_score      INTEGER,
    rationale        TEXT,
    review_note      TEXT,
    review_status    TEXT NOT NULL DEFAULT 'pending',
    latency_ms       INTEGER,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    total_tokens     INTEGER,
    trace_id         TEXT,
    error_code       TEXT,
    error_message    TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 可恢复的评分队列。本表只记录裁判评分队列状态；评分结果仍以 live_run_scores 为准。
CREATE TABLE live_score_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    score_run_id  TEXT,
    run_id        TEXT,
    case_id       TEXT,
    task_type     TEXT,
    eval_model    TEXT,
    judge_model   TEXT,
    judge_provider TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_code    TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
