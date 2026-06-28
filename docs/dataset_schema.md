# 数据集 Schema 说明（Dataset Schema）

本文件说明 FinDueEval 评测数据集的数据对象、字段含义与关联关系，配合
`data/dataset_manifest.yml`（版本与样本范围）、`data/label_taxonomy.yml`（错误标签体系）
与 `scripts/validate_dataset.py`（质量校验）使用。

新增任务、模型回答、评分或错误标签时，按本结构补齐字段并保持主键、外键一致，
即可在不改动页面代码的前提下被页面与校验脚本识别。

## 数据对象与物理文件

| 数据对象 | 物理文件 | 主键 | 说明 |
| --- | --- | --- | --- |
| task_cases | `data/tasks.csv` | `case_id` | 专业尽调任务题 |
| gold_answers | `data/gold_answers.json` | `case_id` | 任务参考答案与评测标准 |
| rubrics | `data/dataset_manifest.yml`（`rubric`） | `field` | 评分维度、权重与满分定义 |
| model_responses | `data/model_outputs.csv` | `output_id` | 各模型对任务的回答 |
| score_records | `data/scores.csv` | `output_id` | 模型回答的分维度评分 |
| error_annotations | `data/error_labels.csv` | `output_id`+`error_type` | 模型回答的错误标签 |
| improvement_actions | `data/optimization_plan.csv` | `frequent_error` | 由错误标签收敛的数据补强动作 |

> 错误标签的类型取值由 `data/label_taxonomy.yml` 约束；其余辅助资产
> （`preference_pairs.csv`、`optimization_comparison.csv`、`evaluation_runs.csv`）
> 在 `dataset_manifest.yml` 的 `assets` 中登记。

## 字段说明

### task_cases（tasks.csv）
| 字段 | 含义 |
| --- | --- |
| `case_id` | 任务唯一编号，全数据集主键 |
| `domain` | 所属专业领域 |
| `scenario` | 任务场景 |
| `task_type` | 任务类型 |
| `difficulty` | 难度等级 |
| `question` | 任务要求 |
| `context` | 任务背景材料 |
| `expected_capability` | 考察的核心能力 |
| `risk_level` | 任务风险等级 |

### gold_answers（gold_answers.json）
列表结构，每条对应一个 `case_id`。
| 字段 | 含义 |
| --- | --- |
| `case_id` | 关联的任务编号 |
| `conclusion` | 标准结论（必备） |
| `basis` | 关键判断依据（必备） |
| `analysis` | 分析过程 |
| `materials_to_check` | 需核查的材料清单 |
| `must_have_points` | 必须覆盖的要点 |
| `risk_boundary` | 风险边界条件 |
| `red_line_errors` | 不可接受的红线错误 |

> 质量门槛：`conclusion`、`basis` 为必备字段；`risk_boundary` 与 `red_line_errors`
> 至少具备其一。该门槛由 `dataset_manifest.yml` 的 `gold_answer` 段声明，由校验脚本核对。

### rubrics（dataset_manifest.yml → rubric）
| 字段 | 含义 |
| --- | --- |
| `total` | 满分（各维度权重之和应等于该值） |
| `total_field` | 记录总分的评分字段名 |
| `dimensions[].field` | 维度对应 `scores.csv` 中的列名 |
| `dimensions[].name` | 维度业务名称 |
| `dimensions[].weight` | 维度权重（即满分） |

### model_responses（model_outputs.csv）
| 字段 | 含义 |
| --- | --- |
| `output_id` | 回答唯一编号 |
| `case_id` | 关联任务（外键 → task_cases） |
| `model_name` | 模型标识（须在 manifest `scope.models` 内） |
| `answer_text` | 模型回答正文 |

### score_records（scores.csv）
| 字段 | 含义 |
| --- | --- |
| `output_id` | 关联回答（外键 → model_responses） |
| `case_id` | 关联任务（外键 → task_cases） |
| `model_name` | 模型标识 |
| `accuracy_score` / `reasoning_score` / `coverage_score` / `evidence_score` / `expression_score` | 各 Rubric 维度得分 |
| `total_score` | 维度合计总分 |
| `review_note` | 评审扣分说明 |

### error_annotations（error_labels.csv）
| 字段 | 含义 |
| --- | --- |
| `output_id` | 关联回答（外键 → model_responses） |
| `case_id` | 关联任务（外键 → task_cases） |
| `model_name` | 模型标识 |
| `error_type` | 错误标签（须来自 `label_taxonomy.yml`） |
| `severity` | 严重程度 |
| `error_description` | 错误说明 |
| `correction` | 纠正方向 |
| `optimization_action` | 对应的数据补强动作 |

### improvement_actions（optimization_plan.csv）
| 字段 | 含义 |
| --- | --- |
| `frequent_error` | 关联的错误标签（外键 → error_annotations.error_type） |
| `typical_problem` | 典型表现 |
| `affected_cases` | 涉及任务 |
| `likely_cause` | 可能的数据原因 |
| `optimization_action` | 数据补强动作 |
| `data_sample_format` | 补强样本格式 |
| `priority` | 优先级 |

## 关联关系

```
task_cases (case_id)
   ├─ 1:1 ─ gold_answers (case_id)
   └─ 1:N ─ model_responses (case_id, output_id)
                ├─ 1:1 ─ score_records (output_id)        ── 维度对应 rubrics.field
                └─ 1:N ─ error_annotations (output_id, error_type)
                              └─ N:1 ─ improvement_actions (frequent_error)
                                            ↑ error_type 受 label_taxonomy 约束
```

- 每个 `case_id` 必须有且仅有一条 Gold Answer。
- `model_responses`、`score_records`、`error_annotations` 通过 `case_id` 关联任务，
  通过 `output_id` 关联回答。
- `error_annotations.error_type` 必须是 `label_taxonomy.yml` 中已定义的标签，
  其 `impacted_dimension` 须为某个 Rubric 维度名称。
- `improvement_actions.frequent_error` 必须关联到已出现的错误标签。

## 校验与扩展

运行质量校验：

```bash
python scripts/validate_dataset.py
```

脚本依据 `dataset_manifest.yml` 与 `label_taxonomy.yml` 动态读取数据文件，输出
通过项、警告项与错误项，可识别 `case_id` 重复、Gold Answer 缺失或要素不全、
Rubric 权重不一致、回答/评分关联缺失、错误标签不合法、影响维度越界、补强动作悬空等问题。

扩展数据集时：先按本 Schema 补齐字段与关联，再在 `dataset_manifest.yml` 同步样本范围与版本，
在 `label_taxonomy.yml` 登记新增错误标签，最后运行校验脚本确认无错误项。
当前数据集为 MVP 样例规模，用于展示数据资产结构、质量门槛、版本边界与可扩展接入方式，
样本量有限，不代表真实生产环境或大规模实验结论。
