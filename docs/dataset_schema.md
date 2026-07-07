# 数据结构说明

本文说明 财务/法律/投行场景大模型对比评测 当前使用的数据对象、文件回退口径与 SQLite 正式数据层。页面不应直接依赖某个固定样本、模型或分数，而应通过服务层读取这些对象。

## 读取口径

- 当前种子样本固定为 13 条：`FD-001` 至 `FD-005`、`LD-001` 至 `LD-004`、`CM-001` 至 `CM-004`。
- SQLite 已初始化且可用时，`app/services/dataset_service.py` 优先读取 SQLite。
- SQLite 未初始化时，项目回退读取 `data/` 下的种子文件。
- 样本新增、编辑、移出测试和 CSV 导入 在 SQLite 可用时会同步正式评测资产；文件模式仍可浏览种子数据和轻量管理视图。
- 本项目不引入外部数据库、登录或权限系统。

## 主要数据对象

| 对象 | SQLite 表 | 文件回退 | 说明 |
| --- | --- | --- | --- |
| task_cases | `task_cases` | `data/tasks.csv` | 任务题、业务背景、场景、难度、风险等级和状态。 |
| gold_answers | `gold_answers` | `data/gold_answers.json` | 专业标准答案。 |
| rubrics | `rubrics` | `data/dataset_manifest.yml` | 评分维度、满分、满分标准和扣分规则。 |
| model responses | `model_responses` / `live_run_responses` | `data/model_outputs.csv` | 当前 seed 仅保留表头；真实运行回答写入 live 表。 |
| score records | `score_records` / `live_run_scores` | `data/scores.csv` | 当前 seed 仅保留表头；评分草稿和已处理评分写入 live 表。 |
| error labels | `error_annotations` | `data/error_labels.csv` | 错误类型、严重程度、错误表现、纠正方向。 |
| improvement actions | `improvement_actions` | `data/optimization_plan.csv` | 数据补强动作和验证方向。 |
| samples | `data/samples.json` | `data/samples.json` | 样本库轻量管理视图、导入导出和兼容备份。 |

辅助对象包括 `evaluation_runs` / `data/evaluation_runs.csv`、错误标签体系 `error_taxonomy` / `data/label_taxonomy.yml`，以及用于扩展分析的 `preference_pairs.csv`、`optimization_comparison.csv`。

## 样本整体替换

`data/final_replacement_samples_13.csv` 是当前 13 条样本的唯一替换来源。重复执行以下命令可覆盖重写 seed 文件、样本库管理视图，并重建运行期 SQLite：

```bash
PYTHONPATH=. python scripts/replace_samples.py \
  --csv data/final_replacement_samples_13.csv \
  --data-dir data \
  --db app/db/findueval.db
```

该脚本会清空旧模型回答、旧评分、旧错误标签、旧优化建议和旧评测批次 seed 行；运行期 SQLite 会被重建以避免旧 `case_id` 继续出现在页面中。SQLite 数据库文件仍属于运行期状态，不提交到 Git。

## 字段说明

### task_cases

| 字段 | 含义 |
| --- | --- |
| `case_id` | 任务编号，样本不可修改的主键。 |
| `domain` | 底层专业场景字段，前台统一展示为财务场景、法律场景、投行场景。 |
| `scenario` | 业务场景。 |
| `task_type` | 任务类型。 |
| `difficulty` | 难度。 |
| `question` | 任务题。 |
| `context` | 业务背景。 |
| `expected_capability` | 考察能力。 |
| `risk_level` | 任务风险等级。 |
| `status` | 底层状态：`draft` / `active` / `inactive`。 |

样本库页面展示中文业务状态：待复核、已入库、需优化、已移出测试。它们分别映射到底层状态 `draft`、`active`、`draft`、`inactive`。

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
| `raw_json` | 专业标准答案原始结构，用于兼容读取和同步。 |

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

维度字段和满分优先复用 `src/metrics.py` 与正式评分标准数据层，不在页面硬编码第二套评分维度。

### model responses

| 字段 | 含义 |
| --- | --- |
| `output_id` / `id` | 回答记录编号。 |
| `run_id` | 真实运行批次编号，仅 live 表存在。 |
| `case_id` | 任务编号。 |
| `model_name` | 被测模型标识。 |
| `answer_text` | 模型回答。 |
| `run_status` | 真实运行状态：success / failed / mock。 |

被测模型输入由 `app/services/eval_runner.py` 构造，只包含任务题、业务背景和输出要求，不包含专业标准答案或评分标准。

### score records

| 字段 | 含义 |
| --- | --- |
| `case_id` | 任务编号。 |
| `model_name` / `eval_model` | 被测模型。 |
| 评分维度字段 | 各维度得分。 |
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

正式结论只统计已确认评分。待确认草稿不进入正式结论。模型使用边界由 `app/services/conclusions.py` 统一计算，结合平均分、红线错误、关键维度短板、高风险任务表现、样本数量和复核说明。
