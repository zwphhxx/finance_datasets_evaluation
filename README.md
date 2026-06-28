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
- `model_outputs.csv`：模型回答的初始化资产（列结构样例）。包含 `output_id`、`case_id`、`model_name`、`answer_text`；分析页展示的回答改由首页评测控制台的真实运行产生，本文件不再作为展示结果。
- `scores.csv`：Rubric 评分的初始化资产。包含 `accuracy_score`、`reasoning_score`、`coverage_score`、`evidence_score`、`expression_score`、`total_score`；分析页展示的评分改由真实裁判评分产生。
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

## SiliconFlow 模型 Provider

为支持后续接入真实文本对话模型评测，项目提供统一的模型适配层（`app/models/`），可通过硅基流动（SiliconFlow）调用不同对话模型。**本能力仅为 provider 层**：可读取模型列表、发起 Chat Completion 调用，**尚未**包含真实评测运行页、Gold Answer 对比或评分——这些留待后续 PR。

适配层结构：

- `app/models/base.py`：统一接口 `ModelProvider`（`list_models` / `generate_response`）与返回结构（`ModelInfo` / `ModelListResult` / `GenerationResult`）。
- `app/models/siliconflow.py`：硅基流动接入，仅用标准库 `urllib` 发起 HTTP，不引入第三方 SDK。
- `app/models/mock.py`：无 API Key 时的占位供应商，返回结构一致、`status=mock`，回答明确标注为模拟、不冒充真实模型。
- `app/models/registry.py`：供应商注册表，页面层只按名称获取 provider，不直接依赖具体实现。

### 配置

按 `st.secrets` → 环境变量 → `.env` 的顺序解析以下配置（参考 `.env.example`）：

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `SILICONFLOW_API_KEY` | 硅基流动 API Key（必填，缺失则回退 mock） | 无 |
| `SILICONFLOW_BASE_URL` | API Base URL | `https://api.siliconflow.cn/v1` |
| `SILICONFLOW_TIMEOUT_SECONDS` | 请求超时（秒） | `30` |

```bash
cp .env.example .env   # 填入真实 Key；.env 已被 .gitignore 忽略，请勿提交
```

接口与官方文档对应：`list_models` 调用 `GET /v1/models`（默认按 `type=text`、`sub_type=chat` 过滤，避免混入图片 / 语音 / 视频模型），`generate_response` 调用 `POST /v1/chat/completions`（认证 `Authorization: Bearer <API_KEY>`，PR-33 默认 `stream=False`）。模型列表不硬编码，全部来自接口实时返回。

### 无 API Key 时的 mock 模式

未配置 `SILICONFLOW_API_KEY` 时，`registry.get_text_provider()` 自动回退 `MockProvider`，应用不会报错崩溃；返回结果 `status=mock`，页面据此可明确标识当前为 mock 模式。mock 回答仅用于打通链路，不代表任何真实模型结果。

### 安全边界

API Key、`Authorization` 请求头与完整请求头不会出现在页面、日志或 `raw_response` 中；4xx/5xx 与超时统一转为结构化错误（如 401/403 提示检查 Key 或权限、429 提示限流、503/504 提示服务繁忙或超时），不向用户抛供应商异常堆栈。

## 真实评测驱动的分析页（首页评测控制台）

应用为**真实评测驱动**：题库与 Gold Answer 来自 `data/` 脱敏样本，而**模型回答与评分只来自真实评测运行**——`data/` 中的 `model_outputs.csv` / `score_records.csv` 仅作初始化资产，不再作为分析页的展示结果。

首页「总览」顶部即「评测控制台」，在上述 provider 层之上，支持选择 Provider、**一个或多个**模型（从接口实时加载、不硬编码，也可手动追加模型 ID）、任务范围（**默认勾选全部活跃任务**，可取消到子集以缓解多模型多任务时的超时）、生成参数（temperature、max_tokens），运行后各自生成真实（或 mock）回答并对比；并可选地由「裁判模型」对照 Gold Answer 与 Rubric 给出**机器建议分**，建议分需**人工复核确认后归档**。控制台不自动定稿、不替用户下「哪个模型最好」的结论。

运行/评分完成后，既有分析页（总览摘要、任务样本、样板题深度评测、模型能力诊断、模型边界报告、数据集质量）以**同一套真实结果**渲染——`app.py` 通过 `src/ui/eval_console.resolve_active_data` 把会话中的运行结果与裁判评分组装成与 seed 同形的 `EvaluationData`（适配器在 `app/services/live_results.py`），各分析页逻辑不变。未运行时分析页显示空状态（「请先在总览页运行评测」）。各评分展示处固定标注「裁判建议分，待人工复核」。

- **导航变化**：独立的「真实模型评测」页已撤销（逻辑迁入首页控制台）。依赖人工标注数据的「错误归因与数据补强」「优化验证」两页已从导航移除——单次真实运行只产出「模型回答 + 裁判建议分」，无法产出人工标注的错误标签 / 优化前后对比 / 偏好对；样板题页的偏好对、错误标注子块在无数据时自动隐藏。当前导航为 7 项：总览、任务样本、样板题深度评测、模型能力诊断、模型边界报告、数据集质量与扩展框架、数据集管理。
- 运行编排在 `app/services/eval_runner.py`（多模型 `run_models` 汇总为 `CompareRunResult`），评分编排在
  `app/services/scorer.py`（`score_compare`），控制台不含模型调用细节，也不构造 prompt。
- **Prompt 边界**：被评测模型只看到任务场景、题干与必要背景，**绝不发送 Gold Answer / 必须覆盖点 /
  不可接受错误**；不让模型自评。**裁判模型可见 Gold Answer**（评分必需），这是与被评测模型相互独立的另一条链路。
- **评分方式**：LLM-as-judge，对照 Gold Answer 与 Rubric 五维度（满分复用 `src/metrics.py` 的方法学配置）
  打分，分数由各维度求和、并 clamp 到各维满分；裁判输出按 JSON 解析，解析失败即标记为失败而非臆造分数。
- **人工复核**：建议分写入时 `review_status=pending`，人工可逐条修订各维度分与复核说明并确认归档为 `confirmed`。
- 运行结果写入独立表 `live_run_responses`，评分写入独立表 `live_run_scores`，均与承载 seed 的 `model_responses` /
  `score_records` 表分离，不污染初始化资产、不回写 `data/`；数据库未初始化时结果暂存于页面会话，仍可驱动分析页。
- 未配置 API Key 时自动使用 mock 模式：回答标注「模拟生成」，mock 裁判**不产生任何真实分数**（各维度留空、状态 mock）。超时与失败统一转为结构化错误，页面不崩溃。超时上限可经 `SILICONFLOW_TIMEOUT_SECONDS` 配置；Streamlit Cloud 经 Secrets 注入 Key（见「部署」）。


## 数据集管理（最小 CRUD）

「数据集管理」页面提供任务题、Gold Answer、Rubric、错误标签与数据补强动作的最小可用维护：

- 任务题：新增、编辑、停用（停用为 `status=inactive` 软删除，不做物理删除）与查看详情。
- Gold Answer：编辑核心结论、必须覆盖点、关键依据、边界条件、不可接受错误与人工复核说明，`raw_json` 无损保留其余内容。
- Rubric：查看评分维度、编辑权重与满分标准、扣分规则，并按 `impacted_dimension` 展示关联错误标签；权重合计异常时提示但不阻断保存。
- 错误标签：维护定义、典型表现、严重度、关联维度、建议补强方向与验证指标。标签默认低饱和呈现，仅红线/高严重度使用浅玫瑰底；`label_taxonomy.yml` 仍是版本化的 seed 标签源。
- 数据补强动作：新增、编辑、停用补强动作，每条动作必须关联到一个已登记的错误标签（复用 `frequent_error` 列），沉淀为数据集的优化动作资产，供后续错误归因与数据补强分析复用。
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
