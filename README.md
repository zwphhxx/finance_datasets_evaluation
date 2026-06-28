# Finance Model Evaluation MVP

Finance Model Evaluation  是一个面向金融专业尽调、资本市场规则边界和相关专业问答场景的模型评测与数据优化 MVP。项目使用结构化样例数据展示从任务集、Gold Answer、模型回答、Rubric 评分、错误标签、Preference Pair、模型能力诊断到数据补强动作的评测闭环。

当前仓库不接真实模型 API，不包含真实公司数据。数据默认以 `data/` 下的 CSV/JSON 种子文件提供，并可选初始化一个本地 SQLite 数据层（见「SQLite 数据层」），用于后续 CRUD 与运行记录留存；不引入 PostgreSQL、MySQL 等外部数据库。页面中的优化前后对比为 MVP 样例数据和当前评测集观察，不代表真实大规模实验结论。

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

## SQLite 数据层

项目默认直接读取 `data/` 种子文件即可运行。如需使用本地 SQLite 数据层（便于后续 CRUD、运行记录与真实评测接入），可从种子数据初始化数据库：

```bash
# 在 app/db/findueval.db 创建数据库并从 data/ 导入种子数据
python -m app.db.init_db

# 重新初始化（覆盖已存在的数据库）
python -m app.db.init_db --force

# 自定义路径与种子目录
python -m app.db.init_db --db /tmp/findueval.db --data-dir /path/to/data
```

初始化后，页面通过 `app/services/dataset_service.py` 读取数据：数据库存在时读库，否则自动回退到 `data/` 种子文件，两种方式的展示结果一致。初始化只读取种子文件、不修改它们，导入行数与种子文件一一对应。

如需让应用读取非默认位置的数据库，可设置：

```bash
export FINDUEVAL_DB_PATH=/path/to/findueval.db
streamlit run app.py
```

数据层仅使用标准库 `sqlite3`，不新增第三方依赖：

- `app/db/schema.sql`：核心数据表结构（任务题、Gold Answer、Rubric、模型回答、评分、错误标签、数据补强动作、评测批次），含 `status`、`created_at`、`updated_at` 等基础字段。
- `app/db/init_db.py`：初始化数据库并从 `data/` 导入种子数据。
- `app/db/repository.py`：封装基础读写（list/get/insert/update/delete）。
- `app/services/dataset_service.py`：服务层，向页面提供数据并承载最小 CRUD，屏蔽底层来源。

## 数据集管理（最小 CRUD）

「数据集管理」页面提供任务题、Gold Answer、Rubric、错误标签与数据补强动作的最小可用维护：

- 任务题：新增、编辑、停用（停用为 `status=inactive` 软删除，不做物理删除）与查看详情。
- Gold Answer：编辑核心结论、必须覆盖点、关键依据、边界条件、不可接受错误与人工复核说明，`raw_json` 无损保留其余内容。
- Rubric：查看评分维度、编辑权重与满分标准、扣分规则，并按 `impacted_dimension` 展示关联错误标签；权重合计异常时提示但不阻断保存。
- 错误标签：维护定义、典型表现、严重度、关联维度、建议补强方向与验证指标。标签默认低饱和呈现，仅红线/高严重度使用浅玫瑰底；`label_taxonomy.yml` 仍是版本化的 seed 标签源。
- 数据补强动作：新增、编辑、停用补强动作，每条动作必须关联到一个已登记的错误标签（复用 `frequent_error` 列），写入后即被「错误归因与数据优化」页读取，体现错误沉淀为数据集优化动作。
- 配置校验：识别无效错误标签、缺少关联补强动作的高频错误，以及关联到不存在标签的补强动作；同一套规则（`src/error_config.py`）也接入 `scripts/validate_dataset.py`，在 seed 上保持通过。

CRUD 仅写入 SQLite 运行时数据层，**不回写** `data/` 下的 CSV/JSON/YAML——后者仍是初始化 seed 与可审阅的版本化数据资产。维护需先初始化数据库（见上）；数据库不存在时该页回退为 seed 只读展示，并提供一键初始化入口。所有写入统一经由 `app/services/dataset_service.py`，页面层不出现 SQL。

## 如何扩展数据集

当前为 5 道样板题的 MVP，但扩展路径是确定的：复用同一套数据结构与质量门槛，按模板增量加样本。

1. 复制 `templates/new_case_template.yml`，填写任务、Gold Answer、Rubric、错误标签与补强建议。
2. 参照 `docs/dataset_schema.md` 的数据对象、字段与关联关系，按 `docs/dataset_building_guide.md` 的八步流程，将内容拆分写入 `data/` 下对应文件。
3. 对照 `docs/dataset_quality_standard.md` 逐项核对质量门槛（答案边界、评分一致性、错误可追溯、补强可验证）。
4. 运行 `python scripts/validate_dataset.py`，确认无错误项后再纳入版本。
5. 在「数据集质量与扩展框架」页面复核覆盖矩阵与质检结果。

从 MVP 到正式评测集的阶段规划见 `docs/extension_roadmap.md`。

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
