# 数据集建设流程

本文件说明 FinDueEval 如何从一道任务构想，落地为可评测、可归因、可补强的样本。
流程贴合本项目的数据结构（`data/` 下的 CSV/JSON、`dataset_manifest.yml`、
`label_taxonomy.yml`），用于支撑从 5 道样板题扩展到更大评测集。

新增样本请先复制 `templates/new_case_template.yml` 填写，再按下列步骤拆分入库。
每一步都对应一个质量门槛，详见 `docs/dataset_quality_standard.md`。

## 1. 任务来源筛选

- 选题标准：具备专业判断价值、存在明确判定标准、能区分回答优劣、含可识别的红线。
- 记录来源类型 `source_type`：脱敏真实场景 / 公开规则改写 / 专家拟题。
- 脱敏要求：不写入真实公司、真实财务数据或个人信息；涉及法规时改写为通用表述。
- 产出：`tasks.csv` 一行（`case_id`、`domain`、`task_type`、`difficulty`、`question`、`context`）。

## 2. Gold Answer 编写

- 四要素必须齐备：核心结论、关键依据（必备要点）、答案边界、不可接受错误（红线）。
- 编写口径遵循尽调报告风格，资料不足时明确写出“需补充依据”，不臆造结论。
- 关键依据需可逐条对照，作为 Rubric 评分和错误标注的判分锚点。
- 产出：`gold_answers.json` 一条记录（`conclusion`、`must_have_points`、`risk_boundary`、`red_line_errors`）。

## 3. Rubric 设计

- 沿用 `dataset_manifest.yml` 声明的五个维度与权重：专业准确性 30、推理与场景适配 20、
  风险覆盖 20、依据可靠性 15、专业表达 15，合计 100。
- 为每个维度写明扣分标准（什么情况扣多少），确保不同评审对同一回答判分一致。
- 扣分标准需能映射到错误标签，使扣分可追溯到具体问题，而非主观印象。

## 4. 模型回答采集

- 待评模型须先登记在 `dataset_manifest.yml` 的模型范围内，再采集回答。
- 当前为脱敏模拟回答，用于演示评测结构；后续可替换为真实模型批量输出（见扩展路线 v0.4）。
- 产出：`model_outputs.csv`（`output_id`、`case_id`、`model_name`、`answer_text`）。

## 5. 人工评分

- 按 Rubric 五维度逐项打分，维度分之和等于 `total_score`。
- 每条评分附扣分说明 `review_note`，使扣分可逐条复核。
- 评分对照 Gold Answer 的关键依据与红线，保证评分一致性。
- 产出：`scores.csv`（五个维度字段、`total_score`、`review_note`）。

## 6. 错误标签标注

- 错误类型只能取自 `label_taxonomy.yml` 已登记标签；需新增类型时先在 taxonomy 登记。
- 标注记录错误表现、严重程度与纠正方向，使错误可归因。
- 产出：`error_labels.csv`（`error_type`、`severity`、`error_description`、`correction`、`optimization_action`）。

## 7. 数据补强建议

- 将高频或高严重度的错误标签，收敛为“补什么数据”的可执行动作。
- 每条动作给出样本格式与验证指标，便于补强后复测是否生效。
- 产出：`optimization_plan.csv`（`frequent_error`/`error_type`、`likely_cause`/`root_cause`、
  `optimization_action`/`data_action`、`data_sample_format`/`sample_format`、`validation_metric`）。

## 8. 优化后验证

- 在 Prompt、RAG 或数据补强前后，记录关键指标变化（平均分、依据可靠性、推理得分、
  幻觉率、红线错误率），判断改进是否有效、哪些维度仍未解决。
- 运行 `python scripts/validate_dataset.py` 复核数据一致性，确认无错误项后方可纳入版本。
- 产出：`optimization_comparison.csv`（版本、变更类型、变更说明与上述指标）。

## 与现有样本的对应关系

以现有 `CM-001`（重大资产重组判定）为例：任务来源为公开规则改写，Gold Answer 给出
是否构成重大资产重组的核心结论、比例测算等关键依据、接近阈值时的审慎边界，以及
“未测算比例即下结论”等红线；基线模型因未测算比例被标注为「风险遗漏」，对应补强动作
为补充财务比例计算示例数据，验证指标为该错误类型出现次数下降。这条链路即为本流程的
一个完整实例，新增样本可据此对照填写。
