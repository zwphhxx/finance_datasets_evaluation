-- FinDueEval SQLite 数据层 schema（PR-30）
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

-- 任务题：对应 data/tasks.csv。status 复用任务的 active/inactive 标记。
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
-- 由数据集管理页按需维护；种子导入时留空，不预置任何编造内容。
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
CREATE TABLE improvement_actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    frequent_error      TEXT,
    typical_problem     TEXT,
    affected_cases      TEXT,
    likely_cause        TEXT,
    optimization_action TEXT,
    data_sample_format  TEXT,
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
