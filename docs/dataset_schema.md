# 数据结构说明

本文说明 FinDueEval 当前使用的数据对象、文件回退口径与 SQLite 正式数据层。页面不应直接依赖某个固定样本、模型或分数，而应通过服务层读取这些对象。

## 读取口径

- SQLite 已初始化且可用时，`app/services/dataset_service.py` 优先读取 SQLite。
- SQLite 未初始化时，项目回退读取 `data/` 下的种子文件。
- 样本 CRUD 在 SQLite 可用时会同步正式评测资产；文件模式仍可浏览种子数据和轻量管理视图。
- 本项目不引入外部数据库、登录或权限系统。

## 主要数据对象

| 对象 | SQLite 表 | 文件回退 | 说明 |
| --- | --- | --- | --- |
| task_cases | `task_cases` | `data/tasks.csv` | 任务题、业务背景、场景、难度、风险等级和状态。 |
| gold_answers | `gold_answers` | `data/gold_answers.json` | 理想回复标准 / Gold Answer。 |
| rubrics | `rubrics` | `data/dataset_manifest.yml` | Rubric 评分维度、满分、满分标准和扣分规则。 |
| model responses | `model_responses` / `live_run_responses` | `data/model_outputs.csv` | 种子模型回答与真实运行回答分离保存。 |
| score records | `score_records` / `live_run_scores` | `data/scores.csv` | 已沉淀评分、评分草稿和已复核归档评分。 |
| error labels | `error_annotations` | `data/error_labels.csv` | 错误类型、严重程度、错误表现、纠正方向。 |
| improvement actions | `improvement_actions` | `data/optimization_plan.csv` | 数据补强动作和验证方向。 |
| samples | `data/samples.json` | `data/samples.json` | 样本库轻量管理视图、导入导出和兼容备份。 |

辅助对象包括 `evaluation_runs` / `data/evaluation_runs.csv`、错误标签体系 `error_taxonomy` / `data/label_taxonomy.yml`，以及用于扩展分析的 `preference_pairs.csv`、`optimization_comparison.csv`。

## 字段说明

### task_cases

| 字段 | 含义 |
| --- | --- |
| `case_id` | 任务编号，样本不可修改的主键。 |
| `domain` | 专业领域。 |
| `scenario` | 业务场景。 |
| `task_type` | 任务类型。 |
| `difficulty` | 难度。 |
| `question` | 任务题。 |
| `context` | 业务背景。 |
| `expected_capability` | 考察能力。 |
| `risk_level` | 任务风险等级。 |
| `status` | 底层状态：`draft` / `active` / `inactive`。 |

样本库页面展示中文业务状态：待复核、已入库、需优化、已归档。它们分别映射到底层状态 `draft`、`active`、`draft`、`inactive`。

### gold_answers

| 字段 | 含义 |
| --- | --- |
| `case_id` | 关联任务编号。 |
| `core_conclusion` | 核心结论。 |
| `key_evidence` | 关键依据。 |
| `analysis` | 分析过程。 |
| `materials_to_check` | 需核查材料。 |
| `boundary_conditions` | 适用边界与待核查事项。 |
| `must_have_points` | 必须覆盖点，JSON 数组。 |
| `unacceptable_errors` | 不可接受错误 / 红线错误，JSON 数组。 |
| `manual_review_notes` | 人工复核提示。 |
| `raw_json` | Gold Answer 原始结构，用于无损展示和编辑。 |

测试准入至少要求存在核心结论、必须覆盖点和不可接受错误。

### rubrics

| 字段 | 含义 |
| --- | --- |
| `dimension_field` | 评分字段。 |
| `name` | 评分维度名称。 |
| `weight` / `full_mark` | 维度权重 / 满分。 |
| `full_mark_standard` | 满分标准。 |
| `deduction_rules` | 扣分规则。 |
| `status` | 维度状态。 |

维度字段和满分优先复用 `src/metrics.py` 与正式 Rubric 数据层，不在页面硬编码第二套评分维度。

### model responses

| 字段 | 含义 |
| --- | --- |
| `output_id` / `id` | 回答记录编号。 |
| `run_id` | 真实运行批次编号，仅 live 表存在。 |
| `case_id` | 任务编号。 |
| `model_name` | 被测模型标识。 |
| `answer_text` | 模型回答。 |
| `run_status` | 真实运行状态：success / failed / mock。 |

被测模型输入由 `app/services/eval_runner.py` 构造，只包含任务题、业务背景和输出要求，不包含 Gold Answer 或 Rubric。

### score records

| 字段 | 含义 |
| --- | --- |
| `case_id` | 任务编号。 |
| `model_name` / `eval_model` | 被测模型。 |
| Rubric 维度字段 | 各维度得分。 |
| `total_score` | 总分。 |
| `review_note` | 裁判或人工复核说明。 |
| `review_status` | live 评分复核状态：pending / confirmed。 |
| `judge_status` | 裁判调用状态。 |

`score_records` 是已沉淀评分；`live_run_scores` 中只有 `review_status=confirmed` 的记录进入正式结论。

### error labels 与 improvement actions

错误标签记录模型回答的错误类型、严重程度和修正方向。数据优化建议记录针对错误标签的补强动作。复核页和结论页只基于已有数据归因，不编造模型缺陷。

## 关联关系

```text
task_cases
  ├─ gold_answers
  ├─ model_responses / live_run_responses
  │    ├─ score_records / live_run_scores
  │    └─ error_annotations
  └─ samples.json 管理视图

error_annotations ── improvement_actions
rubrics ── score dimension fields
```

## 正式结论口径

正式结论只统计已沉淀评分和已复核归档评分。待复核草稿不进入正式结论。模型使用边界由 `app/services/conclusions.py` 统一计算，结合平均分、红线错误、关键维度短板、高风险任务表现、样本数量和复核说明。
