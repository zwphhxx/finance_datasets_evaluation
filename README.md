# Finance Model Evaluation MVP

Finance Model Evaluation  是一个面向金融专业尽调、资本市场规则边界和相关专业问答场景的模型评测与数据优化 MVP。项目使用结构化样例数据展示从任务集、Gold Answer、模型回答、Rubric 评分、错误标签、Preference Pair、模型能力诊断到数据补强动作的评测闭环。

当前仓库不接真实模型 API，不使用数据库，不包含真实公司数据。页面中的优化前后对比为 MVP 样例数据和当前评测集观察，不代表真实大规模实验结论。

## 项目目标

- 用 CSV/JSON 描述可复现的专业评测样本。
- 展示多模型回答、评分、错误标签和偏好样本如何组织。
- 将错误归因转化为数据补强建议和验证指标。
- 提供一个可本地运行、可部署到 Streamlit Community Cloud 的面试项目原型。

## 数据表说明

数据位于 `data/` 目录：

- `tasks.csv`：评测任务。包含 `case_id`、`domain`、`scenario`、`task_type`、`difficulty`、`question`、`context` 等字段。
- `gold_answers.json`：标准答案。包含 `case_id`、`gold_answer` 或 `conclusion`，并可扩展 `must_have_points`、`red_line_errors`、`evidence`、`optimization_note`。
- `model_outputs.csv`：模拟模型回答。包含 `output_id`、`case_id`、`model_name`、`answer_text`。
- `scores.csv`：Rubric 评分。包含 `accuracy_score`、`reasoning_score`、`coverage_score`、`evidence_score`、`expression_score`、`total_score`。
- `error_labels.csv`：错误标签。记录 `error_type`、`severity`、`error_description`、`correction`、`optimization_action`。
- `optimization_plan.csv`：错误归因与数据补强计划。兼容 `frequent_error`、`likely_cause`、`optimization_action`、`data_sample_format` 等旧字段，也支持后续扩展字段。
- `evaluation_runs.csv`：评测批次。记录模型版本、提示词版本、评测范围和运行日期。
- `preference_pairs.csv`：偏好对比样本。记录同一题下 preferred/rejected 输出及偏好理由。
- `optimization_comparison.csv`：优化前后对比。记录 Prompt、RAG、数据补强等版本的 `avg_score`、`hallucination_rate`、`evidence_score`、`reasoning_score`、`red_line_error_rate`。

## 本地运行

建议使用 Python 3.11 或以上版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

如需使用自定义数据目录，可设置：

```bash
export FINDUEVAL_DATA_DIR=/path/to/data
streamlit run app.py
```

## Streamlit Community Cloud 部署

1. 将仓库推送到 GitHub。
2. 登录 Streamlit Community Cloud。
3. 选择该 GitHub 仓库。
4. 设置主文件路径为 `app.py`。
5. 确认 Python 依赖来自 `requirements.txt`。
6. 部署后检查侧边栏页面是否可访问，重点查看数据校验提示。

当前项目只依赖本仓库内的 CSV/JSON 文件，不需要配置数据库、模型密钥或外部服务。

## 为什么当前使用 CSV/JSON

- MVP 阶段数据量小，CSV/JSON 便于审阅、版本管理和面试讲解。
- 评测表结构仍在迭代，文件格式比数据库迁移更轻量。
- Git diff 可以直接展示样本、评分、错误标签和优化计划的变化。
- 部署到 Streamlit Community Cloud 时不需要额外基础设施。

## 何时迁移 SQLite 或 Supabase

当出现以下情况时，再考虑迁移：

- 样本量扩大到需要检索、分页、权限控制或多人协作标注。
- 评测批次需要保留完整运行历史和可追溯审计。
- Preference Pair、错误标签和优化动作需要在线编辑。
- 需要将真实模型调用结果、人工复核流程和实验指标接入统一存储。

SQLite 更适合单机原型和轻量查询；Supabase 更适合多人协作、远程部署和权限管理。当前 PR 不迁移数据库。
