# FinDueEval MVP

FinDueEval 是一个面向金融尽调场景的模型评测样本库 MVP，用于通过样本 CRUD、模型对比、理想回复标准 / Gold Answer、Rubric 评分、错误归因和人工复核，形成当前样本内的模型评价结论与使用边界。

项目不包含真实公司数据，不引入登录、权限系统或外部数据库。当前定位是面试 MVP：流程完整、边界清楚、可解释，但不是完整平台系统。

## 核心流程

**样本库 CRUD → 样本完整度校验 → 选择已入库样本 → 选择对比模型 → 生成模型回答 → 评分草稿入库 → 评分确认 → 正式结论**

1. **样本库 CRUD**：维护任务题、业务背景、理想回复标准 / Gold Answer、Rubric 评分标准、错误标签、优化建议和中文业务状态。
2. **样本完整度校验**：样本不是手动设为“已入库”即可测试；必须具备任务题、业务背景、场景、Gold Answer 核心结论、必须覆盖点、不可接受错误和 Rubric。
3. **选择已入库样本**：发起评测页只展示正式数据层中状态为已入库、未移出测试且完整的样本。
4. **选择对比模型**：页面固定展示硅基流动模型服务；未配置模型服务密钥时不能发起真实调用，后端 mock 仅作为开发兜底。
5. **生成模型回答**：被测模型只看到任务题、业务背景和输出要求。
6. **评分草稿入库**：裁判模型读取模型回答、Gold Answer 和 Rubric，按成功回答逐条生成建议分、维度评分依据和复核提示，并写入 SQLite，状态为待确认。
7. **评分确认**：人工确认或修订分数、填写复核说明后确认生效；低风险评分可批量确认，高风险评分需逐条处理，明显不采用的评分可标记为暂不采用。
8. **正式结论**：只统计已沉淀评分和已确认评分，不统计待确认草稿。

## 页面导航

应用保留 5 个主页面：

| 页面 | 作用 |
| --- | --- |
| 项目说明 | 说明项目定位、评测流程、当前状态和进入样本库 / 发起评测的入口。 |
| 样本库 | 维护正式评测样本，通过查询样本、样本列表和当前样本文档管理样本资产。 |
| 发起评测 | 通过评测配置、运行结果和评分草稿三块完成评测；样本和模型在弹窗中选择，评分草稿逐条展示分数、依据和复核提示并写入数据库。 |
| 评分确认 | 通过待确认队列处理评分草稿；低风险评分可批量确认，高风险评分需查看依据后逐条确认或暂不采用。 |
| 评测结论 | 汇总已沉淀和已确认评分，形成当前样本内的使用边界。 |

## 数据对象与数据流

主要对象如下：

| 对象 | SQLite 表 / 文件 | 说明 |
| --- | --- | --- |
| 任务题与业务背景 | `task_cases` / `data/tasks.csv` | 任务编号、场景、题干、背景、难度、风险等级和状态。 |
| 理想回复标准 | `gold_answers` / `data/gold_answers.json` | 核心结论、关键依据、必须覆盖点、不可接受错误和人工复核提示。 |
| Rubric 评分标准 | `rubrics` / `data/dataset_manifest.yml` | 评分维度、满分、满分标准和扣分规则。 |
| 模型回答 | `model_responses`、`live_run_responses` / `data/model_outputs.csv` | 种子回答和真实运行回答分离保存。 |
| 评分记录 | `score_records`、`live_run_scores` / `data/scores.csv` | 已沉淀评分、评分草稿和已确认评分。 |
| 错误归因 | `error_annotations` / `data/error_labels.csv` | 错误类型、严重程度、错误表现和修正方向。 |
| 数据优化建议 | `improvement_actions` / `data/optimization_plan.csv` | 从错误标签收敛出的数据补强动作。 |
| 样本视图 | `data/samples.json` | 中文业务状态、备注、导入导出和兼容管理信息。 |

SQLite 初始化后，正式评测资产优先从 SQLite 读取。未初始化数据库时，项目仍可从 `data/` 种子文件运行。部署环境中的本地 SQLite 适合单机原型和演示，不应被描述为多人协作的长期持久化能力。

## 模型结果来源

`data/` 中的 `Model_A_baseline`、`Model_B_rag`、`Model_C_prompt_v2` 是种子样例结果，用于演示评分、错误归因和数据优化方法。页面展示时分别标注为“示例基线回答”“示例检索增强回答”“示例提示词优化回答”，不作为用户实际选择的模型。

真实评测结果以“发起评测”页实际选择的硅基流动模型为准。页面主展示使用模型短名，详情保留完整模型 ID；不会把 seed 分数、回答或错误标签改名并挂到真实模型下面。示例评价只用于说明历史演示数据，不进入评分确认和正式结论主流程。

## 样本库与正式评测资产

SQLite 可用时，样本库 CRUD 会同步维护正式评测数据层：

- `task_cases`：写入或更新样本编号、场景、难度、任务题、业务背景和底层状态。
- `gold_answers`：写入或更新理想回复标准 / Gold Answer，并保持 `raw_json` 与结构化字段一致。
- `rubrics`：当样本维护中提供结构化 Rubric 维度对象时，更新对应维度的满分标准、扣分规则等字段；普通文本仍保留在样本视图中，不臆造新维度。
- `samples.json`：继续作为轻量管理视图、导入导出和兼容备份；正式测试准入和评测内容以正式数据层为准。

页面只展示中文业务状态，底层状态用于测试准入：

| 页面状态 | 底层状态 | 测试准入 |
| --- | --- | --- |
| 待复核 | `draft` | 不可测试 |
| 已入库 | `active` | 仍需通过完整度校验 |
| 需优化 | `draft` | 不可测试 |
| 已移出测试 | `inactive` | 不可测试 |

可测试样本必须同时满足：正式题库存在任务题、业务背景和场景；Gold Answer 具备核心结论、必须覆盖点和不可接受错误；Rubric 评分标准存在；状态为已入库且未移出测试。

删除在当前 MVP 中采用移出测试方式实现。移出后样本不会进入发起评测，历史评测记录仍保留，避免破坏确认和结论追溯。

## 模型与裁判输入隔离

这是项目可信度边界：

- 被测模型只看到任务题、业务背景和输出要求。
- 被测模型不看到 Gold Answer、必须覆盖点、不可接受错误或 Rubric。
- 裁判模型才读取 Gold Answer、Rubric 和模型回答。
- 裁判评分只是评分草稿，不是最终结论。
- 人工确认或修订后，评分才会纳入正式结论；低风险评分可批量确认，高风险评分需要逐条填写复核说明。

## 正式结论口径

FinDueEval 不是模型排行榜。结论只代表当前样本内观察，不代表模型整体能力或采购建议。

正式结论只包括：

- `data/scores.csv` / `score_records` 中已沉淀的评分；
- `live_run_scores` 中已确认生效的评分。

待确认草稿和暂不采用记录不进入正式结论。模型使用边界不只看平均分，还结合红线错误、关键维度短板、高风险任务表现、样本数量和人工复核说明。边界表达统一为：

- 可作为初稿参考；
- 必须人工复核；
- 不可作为依据。

## 建议演示路径

1. 打开“项目说明”，看项目定位、评测闭环和入口。
2. 进入“样本库”，查询样本索引，在“当前样本”区查看 Gold Answer、Rubric 和完整度。
3. 在“当前样本”区切换样本，编辑当前样本或将样本移出测试。
4. 进入“发起评测”，在评测配置中选择已入库且完整的样本。
5. 通过模型弹窗选择硅基流动可用模型；运行参数采用固定评测配置。
6. 运行模型回答，查看运行结果摘要和明细。
7. 生成评分草稿，查看逐条评分、维度依据和复核提示。
8. 进入“评分确认”，在待确认队列筛选建议处理；低风险评分可批量确认，高风险评分查看依据后逐条处理。
9. 人工确认或修订后确认生效，暂不采用的评分不会进入正式结论。
10. 到“评测结论”查看正式结论和模型使用边界。

演示不依赖固定样本、固定模型或固定分数。

## 本地运行

建议使用 Python 3.11 或以上版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

如需使用自定义种子数据目录：

```bash
export FINDUEVAL_DATA_DIR=/path/to/data
streamlit run app.py
```

## SQLite 初始化

项目不初始化数据库也能运行；此时读取 `data/` 种子文件。启动时会默认检查本地 SQLite：如果数据库不存在或不可用，会从种子数据自动初始化一次；如果数据库已可用，不会重复覆盖，避免清空运行时样本、评分草稿和人工复核记录。

如需手动初始化或重建，可执行：

```bash
python -m app.db.init_db
python -m app.db.init_db --force
python -m app.db.init_db --db /path/to/findueval.db --data-dir /path/to/data
```

自定义数据库路径：

```bash
export FINDUEVAL_DB_PATH=/path/to/findueval.db
streamlit run app.py
```

如需关闭部署启动时的自动初始化：

```bash
export FINDUEVAL_AUTO_INIT_DB=0
streamlit run app.py
```

SQLite 数据层仅使用标准库 `sqlite3`。相关文件：

- `app/db/schema.sql`：任务题、Gold Answer、Rubric、模型回答、评分、错误标签、优化动作、评测运行和 live 结果表。
- `app/db/init_db.py`：从 `data/` 初始化数据库。
- `app/db/repository.py`：基础读写封装。
- `app/services/dataset_service.py`：SQLite 优先、文件回退的数据服务层。
- `app/services/sample_repository.py`：样本视图与正式数据层同步。

当前 SQLite 仅适合单机演示和面试 MVP。Streamlit Cloud 等部署环境的本地文件系统不应被视为长期多人协作数据库；需要多人标注、权限或审计时，应另行设计协作后端。

## 模型服务与安全

按 `st.secrets`、环境变量、`.env` 的顺序读取配置。可参考 `.env.example`：

| 配置项 | 说明 |
| --- | --- |
| `SILICONFLOW_API_KEY` | 硅基流动模型服务 API Key；缺失时发起评测页不能发起真实调用。 |
| `SILICONFLOW_BASE_URL` | API Base URL。 |
| `SILICONFLOW_TIMEOUT_SECONDS` | 请求超时秒数。 |
| `FINDUEVAL_AUTO_INIT_DB` | 是否在启动时自动初始化 SQLite；默认启用，设为 `0` 可关闭。 |

安全边界：

- 不要提交 API Key。
- API Key、Authorization 请求头和完整请求头不应展示在页面、日志或错误信息中。
- 后端保留模拟回退用于开发和自动化验证，但不在发起评测页作为可选模型服务展示。
- 模拟回退只用于打通链路，不冒充真实模型结果。

## Streamlit Cloud 部署

1. 将仓库推送到 GitHub。
2. 在 Streamlit Community Cloud 选择该仓库。
3. 设置主文件为 `app.py`。
4. 确认依赖来自 `requirements.txt`。
5. 如需真实模型调用，通过 Streamlit Secrets 配置密钥。
6. 不配置数据库或模型密钥也能启动；未配置密钥时可以浏览页面和样本，但不能发起真实模型调用。

## 文档索引

- `docs/dataset_schema.md`：数据对象、字段和 SQLite / 文件映射。
- `docs/dataset_building_guide.md`：新增样本的建设流程。
- `docs/dataset_quality_standard.md`：样本完整度和入库质量门槛。
- `docs/extension_roadmap.md`：从 MVP 到更完整评测集的扩展路线。
- `docs/project_note.md`：面试展示路径与讲解要点。
