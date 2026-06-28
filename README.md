# FinDueEval_MVP

FinDueEval_MVP 是一个面向金融、法律和医药专业尽调场景的最小可运行评测原型。该项目展示了如何将有限的专业任务转化为结构化数据，并通过 Streamlit 应用呈现“任务 → Gold Answer → 多模型回答 → Rubric 评分 → 错误归因 → 数据优化建议”的闭环。原型使用 5 道样板题和 3 个模拟模型来演示评测流程，不包含完整法规或真实公司数据【60309736512362†L0-L60】。

A domain-specific LLM evaluation MVP for financial due diligence, legal review, and capital markets tasks, with gold answers, rubrics, error labels, and model comparison dashboards.

## 目录结构

```
FinDueEval_MVP/
├── README.md               # 项目说明
├── requirements.txt        # Python 依赖
├── app.py                  # Streamlit 应用主入口
├── data/                   # 数据文件目录
│   ├── tasks.csv           # 专业任务列表
│   ├── gold_answers.json   # Gold Answer（标准答案）
│   ├── model_outputs.csv   # 模拟模型回答
│   ├── scores.csv          # 评分结果
│   ├── error_labels.csv    # 错误标签
│   ├── optimization_plan.csv # 数据优化建议
│   ├── evaluation_runs.csv # 评测批次记录
│   └── preference_pairs.csv # 偏好对比样本
└── docs/
    └── project_note.md     # 项目笔记
```

## 运行方式

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 运行 Streamlit 应用：

```bash
streamlit run app.py
```

打开浏览器后即可看到 Demo 界面，包括项目总览、任务列表、单题详情和错误归因与优化建议四个部分。

## 数据字段说明

- **tasks.csv**：包含 `case_id`、`domain`、`scenario`、`task_type`、`difficulty`、`question`、`context`、`expected_capability`、`risk_level` 字段，描述每一道专业任务及其背景。
- **gold_answers.json**：每个条目对应一题的标准答案，字段包括 `case_id`、`conclusion`、`basis`、`analysis`、`materials_to_check`、`risk_boundary`、`must_have_points`、`red_line_errors`。
- **model_outputs.csv**：模拟三种模型对每题的回答，字段包括 `output_id`、`case_id`、`model_name`、`answer_text`。
- **scores.csv**：对模型回答的评分，包含 `accuracy_score`、`reasoning_score`、`coverage_score`、`evidence_score`、`expression_score` 和 `total_score` 等维度。
- **error_labels.csv**：对不理想回答的错误分类，字段包括 `error_type`、`severity`、`error_description`、`correction`、`optimization_action`。
- **optimization_plan.csv**：根据错误标签汇总出的优化建议，字段包括 `frequent_error`、`typical_problem`、`affected_cases`、`likely_cause`、`optimization_action`、`data_sample_format`、`priority`。
- **evaluation_runs.csv**：记录一次评测批次的模型、提示词、评测范围和运行日期，字段包括 `run_id`、`run_name`、`model_name`、`model_version`、`prompt_version`、`eval_scope`、`run_date`、`note`。
- **preference_pairs.csv**：记录同一案例下两个模型回答之间的偏好判断，字段包括 `pair_id`、`case_id`、`preferred_output_id`、`rejected_output_id`、`preference_dimension`、`preference_reason`、`improvement_instruction`、`reviewer`、`review_status`。

## 后续扩展方向

- **任务库扩充**：引入更多领域的真实案例，完善任务分类和权威依据。
- **连接真实模型**：将 API 或本地模型接入评分流程，替换模拟输出。
- **评测指标丰富**：加入更加细化的评价维度，使用多评审人机制。
- **数据闭环优化**：通过持续收集错误标签，迭代数据样本和提示词，提升模型性能。
