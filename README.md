# X-Watcher

面向 AI Agent 的 X（Twitter）信息监控服务。X-Watcher 从 TwitterAPI.io 抓取关注账号的内容，以本地文件持久化，并通过 MCP Server、REST API 和 Web 界面提供检索、浏览、摘要与议题分析能力。

当前版本见 [Releases](https://github.com/alvinswen/X-Watcher/releases)，完整变更历史见 [CHANGELOG.md](CHANGELOG.md)。运行中的实例可用 `curl localhost:8000/health` 查看自报版本与 commit。

## 主要能力

- 管理关注账号，手动触发抓取、增量搜索抓取或历史回填
- 按时间、作者和关键词浏览及搜索推文
- 维护推文中文翻译与摘要，支持 Agent 拉取待处理内容并回写结果
- 创建议题（Subject），维护匹配结果、滚动新闻、累积综述、反馈与评估
- 从存量数据挖掘候选信源，经预审与终审后纳入抓取名单
- 通过 MCP、REST API 或 Web 接入同一份数据
- 导入、导出配置和内容，便于实例间迁移
- 提供健康检查、运行状态和 Prometheus 指标

## 设计要点

**本服务不含任何 LLM。** 摘要、翻译、议题分类、综述撰写全部由调用方 Agent 完成，X-Watcher 只负责抓取、存储、校验、溯源与状态管理。工作流是 Agent-in-the-loop：MCP 客户端先用 `get_unsummarized_tweets` 取待处理推文，Agent 生成结果后调 `save_summaries` 写回。

**无数据库。** 项目使用文件数据层，数据目录为 `data_migrated/`（可用 `XWATCHER_DATA_ROOT` 修改）。推文、摘要、关注列表、用户及议题均由 JSONL / JSON 文件存储，不需要 PostgreSQL 或 SQLite。

## 环境要求

- Python ≥ 3.12（CI 使用 3.12.13）
- Node.js ≥ 22.12.0（仅开发或构建 Web 前端时需要；CI 使用 22.23.1）
- [TwitterAPI.io](https://twitterapi.io/) API Key

## 快速开始

```bash
git clone https://github.com/alvinswen/X-Watcher.git
cd X-Watcher

python -m venv .venv
source .venv/bin/activate
pip install -e .

x-watcher init --twitter-api-key YOUR_TWITTER_API_KEY
x-watcher serve
```

初始化命令会生成 `.env`、创建管理员账号与 API Key。自动生成的密码和 `sna_` 前缀 API Key 只会显示一次，请妥善保存。

启动后可访问：

- Web/API 服务：<http://localhost:8000>
- Swagger API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>
- Prometheus 指标：<http://localhost:8000/metrics>

非交互式初始化：

```bash
x-watcher init \
  --no-input \
  --twitter-api-key YOUR_TWITTER_API_KEY \
  --admin-email admin@example.com \
  --admin-password 'YOUR_STRONG_PASSWORD'
```

## 配置

推荐先复制示例文件，或直接运行 `x-watcher init`：

```bash
cp .env.example .env
```

最小配置：

```dotenv
TWITTER_API_KEY=your_twitterapi_io_key
JWT_SECRET_KEY=至少_32_字符的随机密钥
ADMIN_API_KEY=可选的管理员_API_Key

XWATCHER_DATA_ROOT=./data_migrated
```

可用下面的命令生成 JWT 密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

主要环境变量：

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `TWITTER_API_KEY` | 无 | TwitterAPI.io API Key，**必填** |
| `TWITTER_BASE_URL` | `https://api.twitterapi.io/twitter` | 数据源 API 地址 |
| `XWATCHER_DATA_ROOT` | `data_migrated` | 文件数据根目录 |
| `SCRAPER_LIMIT` | `30` | 单次抓取数量 |
| `SCRAPER_MIN_LIMIT` | `5` | 动态抓取下限 |
| `SCRAPER_MAX_LIMIT` | `300` | 动态抓取上限 |
| `SCRAPER_EARLY_STOP_THRESHOLD` | `5` | 连续遇到已有推文后提前停止的阈值，`0` 禁用 |
| `SCRAPER_MAX_PAGES_PER_SCRAPE` | `10` | 每账号每次抓取的页数上限 |
| `SCRAPER_INCREMENTAL_ENABLED` | `false` | 是否启用按组增量搜索抓取 |
| `SCRAPER_INCREMENTAL_OVERLAP_MINUTES` | `30` | 增量水位安全重叠窗口 |
| `SCRAPER_INCREMENTAL_MAX_PAGES_PER_ROUND` | `25` | **每组每轮**页数上限（与上面的每账号上限语义不同，勿混用） |
| `SCRAPER_INCREMENTAL_SENTINELS` | `GaryMarcus,levelsio,elonmusk` | 哨兵账号，用于检测查询失效 |
| `TASK_MAX_RUNNING_SECONDS` | `1800` | 抓取任务超时时间 |
| `JWT_SECRET_KEY` | 不安全占位值 | 启动时要求非默认值且至少 32 字符，否则拒绝启动 |
| `JWT_EXPIRE_HOURS` | `24` | JWT 有效期（小时） |
| `ADMIN_API_KEY` | 空 | 管理员 API Key |
| `FEED_MAX_TWEETS` | `200` | Feed 单次最大返回数量 |
| `TWITTER_BALANCE_WARNING_THRESHOLD` | `50000` | 余额警告阈值 |
| `TWITTER_BALANCE_DANGER_THRESHOLD` | `10000` | 余额危险阈值 |
| `PROMETHEUS_ENABLED` | `true` | 是否启用 Prometheus 指标 |
| `LOG_LEVEL` | `INFO` | 日志等级 |
| `LOG_FORMAT` | `text` | `text` 或 `json` |
| `LOG_FILE` | `logs/x-watcher.log` | 日志文件路径，留空可禁用 |

配置项的完整定义见 [`src/config.py`](src/config.py)；MCP 动作白名单见 [`.env.example`](.env.example)。

## CLI

```bash
x-watcher init [OPTIONS]          # 生成配置并创建管理员
x-watcher validate                # 检查数据目录与 Twitter API 连通性
x-watcher serve [OPTIONS]         # 启动 REST API 和已构建的 Web 前端
x-watcher mcp [OPTIONS]           # 启动 MCP Server
x-watcher export [OPTIONS]        # 导出配置、内容和议题数据
x-watcher import-data FILE        # 导入数据，支持预览与冲突策略
```

常用示例：

```bash
x-watcher serve --host 127.0.0.1 --port 8000 --reload
x-watcher export --categories config,content --pretty
x-watcher import-data backup.json --dry-run
```

### 监听地址

REST API 与 MCP SSE 的默认监听地址为 `127.0.0.1`，只接受本机连接，以避免服务在未明确授权时暴露到局域网。需要从局域网其他机器访问时，请显式放开：

```bash
x-watcher serve --host 0.0.0.0 --port 8000
x-watcher mcp --transport sse --host 0.0.0.0 --port 8001
```

若升级后其他机器连不上，请先确认启动命令是否仍使用默认地址，并在确认网络边界、防火墙和认证配置符合预期后再放开。

## MCP Server

本地 Agent 推荐使用 stdio：

```bash
x-watcher mcp
```

MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "x-watcher": {
      "command": "/absolute/path/to/.venv/bin/x-watcher",
      "args": ["mcp"],
      "cwd": "/absolute/path/to/X-Watcher"
    }
  }
}
```

远程访问可使用 SSE，该模式启用逐请求 Bearer Token 认证：

```bash
x-watcher mcp --transport sse --host 0.0.0.0 --port 8001
```

MCP 提供 **37 个工具**，覆盖 Feed 与搜索、按日期浏览、状态查询、关注管理、抓取任务、摘要读写、完整的议题工作流，以及信源候选的挖掘与评审。内置资源包括 `xwatcher://status`、`xwatcher://follows`、`xwatcher://config` 和两份工作流配方。

工具契约由 `tests/mcp/golden/mcp_tool_schemas.json` 逐字节冻结，任何签名或文档变更都会被测试拦截。

## REST API

API 支持 API Key 与 JWT 两种认证，**API Key 优先**。登录获取 JWT：

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@x-watcher.local","password":"YOUR_PASSWORD"}'
```

使用初始化时生成的 API Key：

```bash
curl http://localhost:8000/api/feed \
  -H 'X-API-Key: sna_YOUR_API_KEY'
```

主要 API 分组：

| 路径 | 用途 |
|---|---|
| `/api/feed` | 增量信息流 |
| `/api/tweets` | 推文列表与详情 |
| `/api/search` | 关键词搜索 |
| `/api/browse` | 日期、作者与推文浏览 |
| `/api/summaries` | 推文摘要查询 |
| `/api/status` | 系统状态与 Twitter 余额 |
| `/api/scraping` | 关注账号只读查询 |
| `/api/admin/scrape` | 抓取任务管理 |
| `/api/admin/scraping` | 关注账号与抓取配置管理 |
| `/api/admin/subjects` | 议题、Digest、Review、反馈与评估 |
| `/api/admin/source-candidates` | 信源候选查询与终审 |
| `/api/admin/sync` | 数据导入导出 |
| `/api/admin/users` | 用户管理 |
| `/api/auth`、`/api/users` | 登录、个人信息与 API Key 管理 |
| `/metrics` | Prometheus 指标 |

具体请求参数和响应模型以运行中的 Swagger 文档为准。

> 注意：审计日志没有 REST 端点。MCP 的 `get_audit_log` 当前恒返回空，真实审计记录写在日志文件中，需要在 `LOG_FILE` 里检索。

## 安全说明

- **JWT 密钥**：启动时强制校验，不得为默认值、不得空白、长度至少 32 字符，不合规直接退出。
- **API Key**：格式为 `sna_` + 32 位十六进制，服务端只存 SHA-256 哈希，不存明文；无过期时间，靠显式撤销。
- **登录限流**：连续失败 5 次锁定 900 秒。注意这是**全实例单闸**，锁定期内所有登录请求（含密码正确的）一律拒绝；进程重启即清零。
- **MCP 动作白名单**：`manage_follows`、`trigger_scrape`、`trigger_backfill`、`fetch_candidate_sample` 四个高危工具支持通过环境变量做事前拦截，另有 `MCP_SCRAPE_ENABLED` 总开关。详见 `.env.example`。

## Web 前端

开发模式需要分别启动后端和 Vite：

```bash
# 终端 1：项目根目录
x-watcher serve --reload

# 终端 2
cd src/web
npm ci
npm run dev
```

如后端不使用默认的 `8000` 端口：

```bash
VITE_BACKEND_PORT=8001 npm run dev
```

生产构建：

```bash
cd src/web
npm ci
npm run build
```

构建产物位于 `src/web/dist/`；存在该目录时，FastAPI 会自动托管 SPA。

## 开发与测试

依赖安装推荐用 uv 并锁定版本（与 CI 一致）：

```bash
uv sync --locked --extra dev --python 3.12.13
```

也可用 pip：

```bash
pip install -e '.[dev]'
```

本地复现 CI 的六道门禁：

```bash
bash scripts/check-lint.sh          # 全仓 ruff，0 lint 债
bash scripts/check-types.sh         # 全仓 mypy strict，0 类型债
pytest -q --cov                     # 1045 用例 + 覆盖率 ≥85%

cd src/web
npm ci
npm run build                       # 含 vue-tsc 类型检查
npx vitest run
npm run lint
```

> 请使用 `scripts/check-lint.sh` 而非直接跑 `ruff`——脚本内置版本断言，会拒绝在与 `pyproject.toml` 钉定版本不符的环境下运行，避免门禁语义悄悄漂移。

依赖变更必须在同一个 PR 内完成：改 `pyproject.toml` → `uv lock` → `uv sync --locked` → 跑全部门禁。详见 [OPERATIONS.md](OPERATIONS.md)。

## 项目结构

```text
X-Watcher/
├── src/
│   ├── api/                # 管理、状态、推文与同步 API
│   ├── browse/             # 按日期和作者浏览
│   ├── cli/                # CLI 命令
│   ├── data_layer/         # Provider 工厂与仓储契约
│   ├── feed/               # 增量 Feed
│   ├── mcp/                # MCP Server、工具与资源
│   ├── monitoring/         # Prometheus 指标与中间件
│   ├── preference/         # 关注账号与抓取配置
│   ├── scraper/            # TwitterAPI.io 抓取、增量分组与任务管理
│   ├── search/             # 推文搜索
│   ├── shared/             # 审计日志、读缓存、错误文案等横切能力
│   ├── source_candidates/  # 信源候选挖掘与评审
│   ├── storage/            # JSONL、索引、原子写与路径规则
│   ├── subjects/           # 议题匹配、Digest、Review、反馈与评估
│   ├── summarization/      # 摘要读写及译文校验
│   ├── sync/               # 数据导入导出
│   ├── user/               # 用户、JWT 与 API Key
│   ├── web/                # Vue 3 前端
│   ├── config.py           # 配置定义
│   └── main.py             # FastAPI 应用入口
├── tests/                  # 114 个测试文件
├── scripts/                # 门禁脚本与运维脚本
├── .github/workflows/      # CI 与依赖审计
├── .env.example
├── uv.lock
├── CHANGELOG.md
├── OPERATIONS.md
└── pyproject.toml
```

## 技术栈

- FastAPI、Uvicorn、Pydantic v2、returns
- MCP Python SDK（FastMCP）
- 本地 JSON/JSONL 文件存储
- Vue 3、TypeScript、Element Plus、Pinia、Vite
- pytest、Vitest、Ruff、mypy、ESLint

## 文档

| 文档 | 内容 |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | 全部 60 个版本的变更记录 |
| [OPERATIONS.md](OPERATIONS.md) | 运维约定、迁移 runbook、CI 与依赖纪律 |

## 许可证

MIT License
