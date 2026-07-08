# 财务/法律/投行场景大模型对比评测

## 项目定位

本项目是面向财务、法律、投行专业任务的大模型评测原型。它不是通用 Chatbot，也不做脱离样本范围的泛化模型排名；核心是用脱敏专业样本、专业标准答案、评分标准、模型回答和 AI 评分，观察模型在当前样本范围内的回答质量、主要问题和使用边界。

项目不包含真实公司、真实交易或真实个人数据。当前结论只服务于样本内观察，不替代专业判断，也不构成模型整体能力或采购建议。

## 核心能力

- 脱敏专业任务样本库：维护任务题、业务背景、专业场景和测试状态。
- 专业标准答案与必须覆盖点：为 AI 评分提供稳定依据。
- 输入隔离：被测模型只看到任务题、业务背景和输出要求，不看到专业标准答案、必须覆盖点、不可接受错误或评分标准。
- 多模型回答对比：按样本和模型生成回答，保留成功、失败、重试和技术明细。
- AI 评分：基于专业标准答案和评分标准生成维度分、评分依据和评分说明。
- AI 评测结论：成功 AI 评分直接形成当前样本范围内结论。

## 主流程

1. **样本库**：维护和查看专业任务样本。完整且已入库的样本才可进入发起评测。
2. **发起评测**：选择样本和模型，运行评测，系统依次生成模型回答和 AI 评分。
3. **评测结论**：汇总成功 AI 评分，形成当前样本范围内的模型表现和使用边界。

## 当前样本集

当前版本保留 13 条脱敏专业任务样本：

- 财务场景：`FD-001` 至 `FD-005`，共 5 条；
- 法律场景：`LD-001` 至 `LD-004`，共 4 条；
- 投行场景：`CM-001` 至 `CM-004`，共 4 条。

样本来源为 `data/final_replacement_samples_13.csv`。详细字段、数据结构和 SQLite / 文件映射见 `docs/dataset_schema.md`。

## 评测边界

- 样本为脱敏抽象任务，不包含真实公司、真实交易、真实个人或敏感数据。
- 被测模型不看到专业标准答案、必须覆盖点、不可接受错误或评分标准。
- AI 评分完成后直接形成评测结论。
- 结论基于当前样本、模型回答和 AI 评分生成；失败评分和示例评价不进入评测结论，模拟回退也不作为结论来源。
- 结论只代表当前样本范围，不代表模型整体能力或采购建议。
- 实时模型调用依赖外部服务，不能保证每次都成功。

## 本地运行

建议使用 Python 3.11 或以上版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

如需使用自定义数据目录：

```bash
export FINDUEVAL_DATA_DIR=/path/to/data
streamlit run app.py
```

## 模型服务配置

可参考 `.env.example` 或 Streamlit Secrets 配置：

| 配置项 | 说明 |
| --- | --- |
| `SILICONFLOW_API_KEY` | 硅基流动模型服务 API Key；不要提交真实 Key。 |
| `SILICONFLOW_TIMEOUT_SECONDS` | 请求超时秒数；示例值为 `180`。 |
| `FINDUEVAL_EVAL_MAX_TOKENS` | 被测模型回答输出 token 上限。 |
| `FINDUEVAL_EVAL_TEMPERATURE` | 被测模型回答随机性；裁判评分固定为 `0.0`。 |

不配置 API Key 时，可以浏览项目说明、样本库和文档，但不能发起真实模型调用。

## 演示与恢复

项目支持实时调用模型，也支持通过 AI 评测结果导出 / 导入恢复稳定结论。外部模型服务可能受网络、限流、模型响应时间和输出长度影响；已完成结果会保留，未完成项可继续运行，失败项可单独重试。

如需重新生成最终 13 条样本对应的数据文件，可执行：

```bash
PYTHONPATH=. python scripts/replace_samples.py \
  --csv data/final_replacement_samples_13.csv \
  --data-dir data \
  --skip-db
```

本地 SQLite 数据库属于运行期产物，不应提交到 Git。

## Streamlit 部署

1. 将仓库推送到 GitHub。
2. 在 Streamlit Community Cloud 选择该仓库。
3. 设置主文件为 `app.py`。
4. 确认依赖来自 `requirements.txt`。
5. 如需真实模型调用，通过 Streamlit Secrets 配置密钥。

## 文档索引

- `docs/dataset_schema.md`：数据对象、字段说明和 SQLite / 文件映射。
- `docs/dataset_building_guide.md`：样本建设、导入和维护流程。
- `docs/dataset_quality_standard.md`：样本完整度和入库质量门槛。
- `docs/extension_roadmap.md`：后续扩展方向。
- `docs/project_note.md`：展示路径、讲解要点和常见追问。
