# X-Watcher

面向 AI Agent 的 X（Twitter）信息监控服务。X-Watcher 从 TwitterAPI.io 抓取关注账号的内容，以本地文件持久化，并通过 Web 界面、REST API 和 MCP Server 提供检索、浏览、摘要与议题分析能力。

## 主要能力

- 管理关注账号，手动触发增量抓取或文章回填
- 按时间、作者和关键词浏览及搜索推文
- 维护推文中文翻译与摘要，支持 Agent 拉取待处理内容并回写结果
- 创建议题（Subject），维护匹配结果、摘要、综述、反馈与评估
- 通过 Web、REST API 或 MCP 接入同一份数据
- 导入、导出配置和内容，便于实例间迁移
- 提供健康检查、运行状态、审计日志和 Prometheus 指标

## 当前架构

项目默认且实际使用 `file` 数据层，数据目录为 `data_migrated/`（可用 `XWATCHER_DATA_ROOT` 修改）。推文、摘要、关注列表、用户及议题等数据均由文件存储，不需要 PostgreSQL 或 SQLite。

摘要与翻译采用 Agent-in-the-loop 工作流：MCP 客户端先通过 `get_unsummarized_tweets` 获取待处理推文，再由 Agent 生成结果并调用 `save_summaries` 写回。本项目不再内置外部 LLM Provider 自动调用链。

## 环境要求

- Python 3.12 或 3.13
- Node.js（仅开发或构建 Web 前端时需要）
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

最小配置如下：

```dotenv
TWITTER_API_KEY=your_twitterapi_io_key
TWITTER_BEARER_TOKEN=placeholder
JWT_SECRET_KEY=至少_32_字符的随机密钥
ADMIN_API_KEY=可选的管理员_API_Key

XWATCHER_DATA_LAYER=file
XWATCHER_DATA_ROOT=./data_migrated
```

可用下面的命令生成 JWT 密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

主要环境变量：

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `TWITTER_API_KEY` | 无 | TwitterAPI.io API Key，必填 |
| `TWITTER_BEARER_TOKEN` | 无 | 兼容配置，`init` 会写入 `placeholder` |
| `TWITTER_BASE_URL` | `https://api.twitterapi.io/twitter` | 数据源 API 地址 |
| `XWATCHER_DATA_ROOT` | `data_migrated` | 文件数据根目录 |
| `SCRAPER_ENABLED` | `true` | 是否启用抓取能力 |
| `SCRAPER_USERNAMES` | 空 | 初始关注账号，逗号分隔 |
| `SCRAPER_LIMIT` | `30` | 单次抓取数量 |
| `SCRAPER_MIN_LIMIT` | `5` | 动态抓取下限 |
| `SCRAPER_MAX_LIMIT` | `300` | 动态抓取上限 |
| `SCRAPER_EARLY_STOP_THRESHOLD` | `5` | 连续遇到已有推文后的提前停止阈值，`0` 表示禁用 |
| `SCRAPER_MAX_EXTRA_PAGES` | `3` | 增量抓取最多追加页数 |
| `TASK_MAX_RUNNING_SECONDS` | `1800` | 抓取任务超时时间 |
| `JWT_SECRET_KEY` | 不安全占位值 | 启动时要求非默认值且至少 32 字符 |
| `JWT_EXPIRE_HOURS` | `24` | JWT 有效期（小时） |
| `ADMIN_API_KEY` | 空 | 管理员 API Key |
| `FEED_MAX_TWEETS` | `200` | Feed 单次最大返回数量 |
| `PROMETHEUS_ENABLED` | `true` | 是否启用 Prometheus 指标 |
| `LOG_LEVEL` | `INFO` | 日志等级 |
| `LOG_FORMAT` | `text` | `text` 或 `json` |
| `LOG_FILE` | `logs/x-watcher.log` | 日志文件路径，留空可禁用 |

完整示例及 MCP 动作白名单配置见 [`.env.example`](.env.example)。

## CLI

```bash
x-watcher init [OPTIONS]          # 生成配置并创建管理员
x-watcher validate                # 检查数据目录与 Twitter API
x-watcher serve [OPTIONS]         # 启动 REST API 和已构建的 Web 前端
x-watcher mcp [OPTIONS]           # 启动 MCP Server
x-watcher export [OPTIONS]        # 导出配置、内容和议题数据
x-watcher import-data FILE        # 导入数据，支持预览与冲突策略
```

常用示例：

```bash
x-watcher serve --host 127.0.0.1 --port 8000 --reload
x-watcher export --categories config,content,topics --pretty
x-watcher import-data backup.json --dry-run
x-watcher import-data backup.json --strategy merge
```

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

远程访问可使用 SSE；该模式启用逐请求 Bearer Token 认证：

```bash
x-watcher mcp --transport sse --host 0.0.0.0 --port 8001
```

MCP 提供 Feed、搜索、按日期浏览、状态查询、关注管理、抓取任务、摘要读写，以及完整的 Subject 工作流。内置资源包括 `xwatcher://status`、`xwatcher://follows`、`xwatcher://config` 和工作流配方。

## REST API

API 支持 JWT 和 API Key 认证。登录获取 JWT：

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
| `/api/summaries` | 查询待摘要内容 |
| `/api/admin/scrape` | 抓取任务管理 |
| `/api/admin/scraping` | 关注账号与抓取配置管理 |
| `/api/admin/subjects` | 议题、Digest、Review、反馈与评估 |
| `/api/admin/sync` | 数据导入导出 |
| `/api/status` | 系统状态与审计日志 |
| `/api/auth`、`/api/users` | 登录、用户与 API Key 管理 |

具体请求参数和响应模型以运行中的 Swagger 文档为准。

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

```bash
pip install -e '.[dev]'
pytest
pytest --cov=src --cov-report=html
ruff check src tests
black --check src tests
mypy src

cd src/web
npm ci
npm test
npm run build
```

## 项目结构

```text
X-Watcher/
├── src/
│   ├── api/              # 管理、状态、推文与同步 API
│   ├── browse/           # 按日期和作者浏览
│   ├── cli/              # CLI 命令
│   ├── data_layer/       # 文件数据层入口
│   ├── feed/             # 增量 Feed
│   ├── mcp/              # MCP Server、工具与资源
│   ├── preference/       # 关注账号与抓取配置
│   ├── scraper/          # TwitterAPI.io 抓取与任务管理
│   ├── search/           # 推文搜索
│   ├── storage/          # JSONL、索引和原子写入基础设施
│   ├── subjects/         # 议题匹配、Digest、Review、反馈与评估
│   ├── summarization/    # 摘要读写及校验
│   ├── sync/             # 数据导入导出
│   ├── user/             # 用户、JWT 与 API Key
│   ├── web/              # Vue 3 前端
│   └── main.py           # FastAPI 应用入口
├── tests/
├── scripts/
├── .env.example
└── pyproject.toml
```

## 技术栈

- FastAPI、Uvicorn、Pydantic
- MCP Python SDK
- 本地 JSON/JSONL 文件存储
- Vue 3、TypeScript、Element Plus、Pinia、ECharts、Vite
- pytest、Vitest、Ruff、Black、mypy

## 许可证

MIT License
