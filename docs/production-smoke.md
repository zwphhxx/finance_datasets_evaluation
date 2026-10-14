# 生产只读巡检

`Production read-only smoke` 是独立的 GitHub Actions 工作流，不导入应用、不初始化数据库、不运行评测或评分，也不读取任何模型密钥。它先检查数据库中存在至少一条已保存运行，再通过 Chromium 打开[公开首页](https://finance-model-eval.streamlit.app/)，确认首页的历史回答与数字评分，进入一个已有评分的完整案例，确认回答和数字评分实际渲染。HTTP 200、加载占位页和未评分任务都不能通过。

脚本逐个读取页面及 iframe。唯一允许的点击是 Streamlit 的 `Yes, get this app back up!` 和首页 `查看完整案例 →`；唤醒按钮最多点击一次。检查不会触发付费、继续评分、删除或管理动作。数据库失败时直接失败，不自动恢复暂停项目或重试修复。

## 独立数据库凭证

由数据库管理员为巡检建立独立登录角色。以下是配置示例，仅供管理员审阅后执行；加入本功能不会执行这些管理语句。

```sql
CREATE ROLE findueval_healthcheck
  LOGIN PASSWORD '<independent-random-password>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE postgres TO findueval_healthcheck;
GRANT USAGE ON SCHEMA public TO findueval_healthcheck;
GRANT SELECT (run_id) ON public.live_evaluation_runs TO findueval_healthcheck;
ALTER ROLE findueval_healthcheck SET default_transaction_read_only = on;
```

角色仅需要读取 `public.live_evaluation_runs.run_id`。不要授予写入、DDL、角色成员关系、其他业务表权限或管理权限。若此表启用了 RLS，管理员需要审阅该角色的专用只读策略，确认至少一条现有运行对角色可见；不修改面向其他角色的策略。管理员还应检查继承自 `PUBLIC` 的权限、可执行的写入函数及角色成员关系，确认该账号不能写入任何生产业务表。避免复用应用数据库账号、Supabase 管理令牌或模型密钥。

在 GitHub 仓库的 **Settings → Secrets and variables → Actions → Secrets** 建立 `FINDUEVAL_HEALTHCHECK_DATABASE_URL`，值为此独立账号的 PostgreSQL 连接 URL。使用可从 GitHub runner 访问的数据库地址，URL 必须包含 `sslmode=require`、`verify-ca` 或 `verify-full`，例如：

```text
postgresql://findueval_healthcheck:<url-encoded-password>@<database-host>:5432/postgres?sslmode=require
```

不要在仓库文件、issue、Actions 输出或截图中保存实际凭证。脚本还在连接参数和事务属性中强制只读，并且只执行：

```sql
SELECT run_id FROM public.live_evaluation_runs LIMIT 1
```

返回值不会打印或保存。连接错误及其主机、账号、密码、记录内容均不会输出；日志仅报告配置失败或哪个检查失败。

## 首次验证与启用

1. 先保持仓库变量 `FINDUEVAL_SMOKE_ENABLED` 缺省或为 `false`，定时运行默认跳过。
2. 不配置 secret 时手动运行一次工作流，应在第一步以 `CONFIGURATION FAILURE: missing FINDUEVAL_HEALTHCHECK_DATABASE_URL` 失败；此步骤不安装依赖、不访问生产数据库或页面。
3. 完成独立角色权限核验并设置 secret 后，从 **Actions → Production read-only smoke → Run workflow** 手动运行。手动触发无需启用定时变量。
4. 只有真实数据库读取、首页和已评分案例均通过，才将仓库变量 `FINDUEVAL_SMOKE_ENABLED` 设置为字符串 `true`。

定时表达式是 UTC `17 */6 * * *`，对应北京时间每日 **02:17、08:17、14:17、20:17**。GitHub 调度是尽力执行，可能延迟；定时事件使用默认分支上的工作流。每次运行最多 10 分钟，同一巡检工作流不并行执行，新的运行不会取消正在运行的巡检。若要停止定时巡检，将上述变量改为 `false`。

## 输出与验收边界

成功仅输出数据库、首页、已有评分案例检查通过。浏览器失败时保存公开页面截图，遮盖 Streamlit 服务端异常区域；不保存数据库结果、trace、HAR、浏览器控制台、页面正文或成功截图。失败截图的 GitHub artifact 保留 **7 天**。数据库失败或缺少 secret 时没有浏览器截图。

退出码：`0` 为全部通过，`1` 为数据库或公开页面检查失败，`2` 为缺少 secret 或 URL 配置不安全。脚本的公开 URL 参数只能指向约定的 HTTPS 首页，不接受账号密码、其他域名、登录票据、查询参数或管理路径。浏览器通过页面按钮产生的案例路由只用于读取已有公开案例。

离线验证：

```sh
python -m pytest tests/test_production_smoke.py
ruff check scripts/production_smoke.py tests/test_production_smoke.py
```

假页面测试覆盖 iframe、休眠唤醒、持续加载、未评分记录、异常页、点击白名单、单条只读查询、空表、TLS 配置、凭证缺失及错误脱敏。离线测试通过不能替代首次真实 GitHub 手动运行；未完成首次真实通过前，定时巡检仍保持关闭。

`requirements-smoke.txt` 独立锁定 Playwright 及其 Python 依赖、psycopg binary 和类型依赖。工作流使用完整 commit SHA 固定 checkout、setup-python 和 upload-artifact，便于审阅和后续有意识地升级。
