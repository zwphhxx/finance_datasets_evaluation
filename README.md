# FinDueEval MVP

FinDueEval 是一个面向金融、投行、财务和法律尽调场景的模型评测 MVP。项目主线是：

**待复核样本 → 已入库样本 → 发起测试 → 评分草稿 → 人工复核 → 正式结论**

项目不包含真实公司数据。任务、理想回复标准 / Gold Answer、Rubric 评分标准和历史样例默认来自 `data/` 下的版本化文件；也可以初始化本地 SQLite 运行时数据层，用于样本 CRUD、测试准入、真实模型运行记录、裁判评分和人工复核留存。不引入外部数据库、登录或复杂权限系统。

## 项目目标

- 用脱敏样本描述可复现的专业尽调任务。
- 调用真实模型或模拟回退链路，生成模型回答。
- 由裁判模型生成评分草稿，再经人工复核确认。
- 把已沉淀和已复核的评分汇总为当前样本内正式结论。
- 保持面试 MVP 定位：专业、克制、可解释，不扩展成平台型系统。

## 页面导航

当前应用保留 5 个主导航项：

1. **项目说明**：说明项目定位、评测闭环、动态指标和主入口。
2. **样本库**：筛选样本、查看评测资产结构；新增、编辑、状态变更、归档、导入导出收在「样本管理」折叠区。
3. **发起测试**：按选择样本、选择对比模型、运行模型回答、生成评分草稿的流程执行评测。
4. **评测复核**：逐条核对模型回答、建议分和扣分理由，人工确认后归档。
5. **评测结论**：只汇总已沉淀和已复核归档的评分；评分草稿不进入正式结论。

## 数据表说明

数据位于 `data/` 目录：

- `tasks.csv`：评测任务。包含 `case_id`、`domain`、`scenario`、`task_type`、`difficulty`、`question`、`context` 等字段。
- `gold_answers.json`：理想回复标准 / Gold Answer。包含 `case_id`、核心结论、必须覆盖点、不可接受错误与必要边界。
- `samples.json`：样本库轻量管理视图，记录中文业务状态、备注和页面管理信息；SQLite 可用时，CRUD 会同步维护正式评测资产。
- `model_outputs.csv`：模型回答的初始化资产，保留历史样例与列结构。
- `scores.csv`：Rubric 评分的初始化资产，作为已沉淀结论的一部分。
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

## 样本库与正式评测口径

样本库 CRUD 是正式评测样本的维护入口。SQLite 可用时：

- 新增或编辑样本会写入 `task_cases`，维护任务题、场景、难度、业务背景和底层状态。
- 理想回复标准 / Gold Answer 会写入 `gold_answers`，并保持 `raw_json` 与结构化字段一致。
- 结构化 Rubric 输入会写入或更新 `rubrics` 中对应维度的满分标准、扣分规则等字段。
- `data/samples.json` 继续保留为轻量管理视图、导入导出和兼容备份；正式评测以 SQLite 的 `task_cases`、`gold_answers`、`rubrics` 为准。

样本库不是普通题目列表。列表只保留样本编号、标题、场景、状态、完整度、难度和更新时间等摘要；选中样本详情按完整评测资产展示：

- 样本基础信息：编号、标题、场景、难度、状态和更新时间。
- 任务内容：被测模型可见的任务题、业务背景和输出要求。
- 理想回复标准 / Gold Answer：核心结论、关键依据、必须覆盖点、不可接受错误、边界条件和人工复核提示。
- Rubric 评分标准：评分维度、满分、满分标准、扣分规则和关联错误说明。
- 错误标签与数据优化建议：用于解释常见模型问题，并支撑后续数据集迭代。
- 状态、完整度与复核记录：说明样本能否进入发起测试。

这些信息直接衔接后续流程：任务题和业务背景进入被测模型，Gold Answer 和 Rubric 进入裁判评分链路，错误标签和优化建议用于人工复核与数据集优化。

页面只展示中文业务状态：

- `待复核`：保存为底层 `draft`，不可进入测试。
- `已入库`：保存为底层 `active`，但仍需通过完整度校验后才可测试。
- `需优化`：保存为底层 `draft`，不可进入测试。
- `已归档`：保存为底层 `inactive`，不可进入测试。

样本不是手动标记为「已入库」即可测试。可测试样本必须同时通过完整度校验：

- 正式题库中存在任务编号、任务题、业务背景和场景。
- Gold Answer 存在，并包含核心结论、必须覆盖点和不可接受错误。
- Rubric 评分标准存在且可用于裁判评分。
- 样本状态为「已入库」，且未归档或停用。

「发起测试」页只读取通过上述校验的样本。不完整样本即使状态为「已入库」也不会进入测试；样本库会在列表和详情中展示完整度、缺失项与是否可测试。数据库未初始化时，应用仍可用文件模式展示 seed 数据；样本管理区会提示本地视图不能进入正式测试。

## 发起测试页

「发起测试」是评测执行页，不是模型 API 调试页。默认主流程为：

1. 选择可测样本；
2. 选择一个或多个对比模型；
3. 运行模型回答；
4. 生成评分草稿。

样本选择只展示通过正式完整度校验的样本；模型列表来自当前 provider 的模型列表接口或既有 provider 逻辑，不在页面硬编码模型名称。模型服务 provider、连通性检查、刷新模型列表、手动追加模型 ID、`temperature`、`max_tokens`、`trace_id`、HTTP 状态码和错误详情均收在高级设置或运行明细折叠区，用于调试和运行控制。

被测模型与裁判模型输入隔离：被测模型只看到任务题、业务背景和输出要求，不看到 Gold Answer、必须覆盖点、不可接受错误或 Rubric；裁判评分链路才读取 Gold Answer 和 Rubric。评分草稿是建议分，必须在「评测复核」页确认或修订后才会进入正式结论。

## 模型调用与评分

项目提供统一的模型适配层（`app/models/`），可通过硅基流动调用文本对话模型；未配置密钥时自动进入模拟回退，应用仍可演示完整链路。

适配层结构：

- `app/models/base.py`：统一接口 `ModelProvider`（`list_models` / `generate_response`）与返回结构（`ModelInfo` / `ModelListResult` / `GenerationResult`）。
- `app/models/siliconflow.py`：硅基流动接入，仅用标准库 `urllib` 发起 HTTP，不引入第三方 SDK。
- `app/models/mock.py`：无密钥时的占位供应商，返回结构一致，回答明确标注为模拟、不冒充真实模型。
- `app/models/registry.py`：供应商注册表，页面层只按名称获取 provider，不直接依赖具体实现。

### 配置

按 `st.secrets` → 环境变量 → `.env` 的顺序解析以下配置（参考 `.env.example`）：

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `SILICONFLOW_API_KEY` | 硅基流动 API Key（缺失则进入模拟回退） | 无 |
| `SILICONFLOW_BASE_URL` | API Base URL | `https://api.siliconflow.cn/v1` |
| `SILICONFLOW_TIMEOUT_SECONDS` | 请求超时（秒） | `30` |

```bash
cp .env.example .env   # 填入真实 Key；.env 已被 .gitignore 忽略，请勿提交
```

接口与官方文档对应：`list_models` 调用 `GET /v1/models`（默认按 `type=text`、`sub_type=chat` 过滤，避免混入图片 / 语音 / 视频模型），`generate_response` 调用 `POST /v1/chat/completions`（认证 `Authorization: Bearer <API_KEY>`，PR-33 默认 `stream=False`）。模型列表不硬编码，全部来自接口实时返回。

### 无密钥时的模拟回退

未配置 `SILICONFLOW_API_KEY` 时，`registry.get_text_provider()` 自动回退 `MockProvider`，应用不会报错崩溃。模拟回答仅用于打通链路，不代表任何真实模型结果；模拟裁判不产生真实分数。

### 安全边界

API Key、`Authorization` 请求头与完整请求头不会出现在页面、日志或 `raw_response` 中；4xx/5xx 与超时统一转为结构化错误（如 401/403 提示检查 Key 或权限、429 提示限流、503/504 提示服务繁忙或超时），不向用户抛供应商异常堆栈。

## 运行与复核边界

- **运行编排**：`app/services/eval_runner.py` 负责多模型运行，结果可写入 `live_run_responses`。
- **裁判评分**：`app/services/scorer.py` 负责对照理想回复标准 / Gold Answer 和 Rubric 评分标准生成建议分，评分可写入 `live_run_scores`。
- **Prompt 边界**：被评测模型只看到任务场景、题干、业务背景与输出要求，不发送 Gold Answer、必须覆盖点、不可接受错误或 Rubric；裁判模型可见这些评判标准，这是独立链路。
- **人工复核**：评分写入后为待复核草稿，人工可修订各维度分与复核说明，确认后才进入正式结论。
- **正式结论**：`app/services/conclusions.py` 只统计已沉淀评分和已复核归档评分，不统计待复核草稿。
- **安全边界**：密钥、认证请求头和完整请求头不会展示在页面或日志；超时、限流和权限错误会转成结构化错误，页面不崩溃。

## 如何扩展数据集

当前为 5 道样板题的 MVP，但扩展路径是确定的：复用同一套数据结构与质量门槛，按模板增量加样本。

1. 复制 `templates/new_case_template.yml`，填写任务、Gold Answer、Rubric、错误标签与补强建议。
2. 参照 `docs/dataset_schema.md` 的数据对象、字段与关联关系，按 `docs/dataset_building_guide.md` 的八步流程，将内容拆分写入 `data/` 下对应文件。
3. 对照 `docs/dataset_quality_standard.md` 逐项核对质量门槛（答案边界、评分一致性、错误可追溯、补强可验证）。
4. 运行 `python scripts/validate_dataset.py`，确认无错误项后再纳入版本。
5. 在「样本库」页面确认状态，再在「发起测试」页运行小范围回归。

从 MVP 到正式评测集的阶段规划见 `docs/extension_roadmap.md`。

## Streamlit Community Cloud 部署

1. 将仓库推送到 GitHub。
2. 登录 Streamlit Community Cloud。
3. 选择该 GitHub 仓库。
4. 设置主文件路径为 `app.py`。
5. 确认 Python 依赖来自 `requirements.txt`。
6. 部署后检查侧边栏页面是否可访问，重点查看数据校验提示。

不配置数据库或模型密钥也能运行；未配置模型密钥时会进入模拟回退。若需要真实调用，请通过环境变量或 Streamlit Secrets 配置密钥。

## 为什么当前使用 CSV/JSON

- MVP 阶段数据量小，CSV/JSON 便于审阅、版本管理和面试讲解。
- 评测表结构仍在迭代，文件格式比数据库迁移更轻量。
- Git diff 可以直接展示样本、评分、错误标签和优化计划的变化。
- 部署到 Streamlit Community Cloud 时不需要额外基础设施。

## 何时迁移外部数据库或协作后端

当出现以下情况时，再考虑迁移：

- 样本量扩大到需要检索、分页、权限控制或多人协作标注。
- 评测批次需要保留完整运行历史和可追溯审计。
- Preference Pair、错误标签和优化动作需要在线编辑。
- 需要将真实模型调用结果、人工复核流程和实验指标接入统一存储。

SQLite 更适合单机原型和轻量查询；Supabase 等协作后端更适合多人标注、远程部署和权限管理。当前 MVP 不引入外部数据库。
