# X-watcher

面向 Agent 的 X 平台智能信息监控服务

## Quick Start (Agent)

```bash
pip install -e .
x-watcher init --no-input \
  --twitter-api-key=YOUR_TWITTER_API_KEY \
  --llm-provider=deepseek \
  --llm-api-key=YOUR_LLM_API_KEY
x-watcher serve
```

服务启动后访问 `http://localhost:8000/docs` 查看 API 文档。

## Quick Start (人类开发者)

```bash
git clone <repository-url> && cd x-watcher
pip install -e ".[dev]"
x-watcher init                  # 交互式引导配置
x-watcher serve                 # 启动服务
```

## 支持的 LLM 提供商

| Provider | Slug | Default Model | 备注 |
|----------|------|---------------|------|
| OpenRouter | `openrouter` | `anthropic/claude-sonnet-4.6` | 高质量，支持多模型 |
| MiniMax | `minimax` | `MiniMax-M2.5` | 国内低成本 |
| DeepSeek | `deepseek` | `deepseek-chat` | 国内高性价比 |
| 智谱 AI | `zhipu` | `glm-5` | 国内免费额度 |
| Moonshot (Kimi) | `moonshot` | `kimi-k2.5` | 国内 |
| Custom | `custom` | (用户提供) | 任何 OpenAI 兼容 API |

## 环境配置

### 新格式（推荐）

```bash
# .env
LLM_PROVIDERS=openrouter,deepseek        # 提供商优先级
LLM_OPENROUTER_API_KEY=sk-or-xxx         # 各提供商 API Key
LLM_DEEPSEEK_API_KEY=sk-xxx
TWITTER_API_KEY=your_key                  # TwitterAPI.io Key
TWITTER_BEARER_TOKEN=placeholder
```

可选覆盖默认值：
```bash
LLM_OPENROUTER_MODEL=anthropic/claude-sonnet-4.6
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

### 旧格式（向后兼容）

```bash
MINIMAX_API_KEY=your_key
OPENROUTER_API_KEY=your_key
```

### 完整环境变量参考

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_PROVIDERS` | 否* | `""` | 提供商优先级列表（逗号分隔） |
| `LLM_<SLUG>_API_KEY` | 是* | - | 各提供商 API Key |
| `LLM_<SLUG>_MODEL` | 否 | 预设默认值 | 覆盖默认模型 |
| `LLM_<SLUG>_BASE_URL` | 否 | 预设默认值 | 覆盖默认 API 地址 |
| `TWITTER_API_KEY` | 是 | - | TwitterAPI.io API Key |
| `TWITTER_BEARER_TOKEN` | 是 | - | Twitter Bearer Token |
| `DATABASE_URL` | 否 | `sqlite:///./news_agent.db` | 数据库连接 |
| `JWT_SECRET_KEY` | 否 | auto-generated | JWT 签名密钥 |
| `SCRAPER_ENABLED` | 否 | `true` | 启用定时抓取 |
| `SCRAPER_INTERVAL` | 否 | `43200` | 抓取间隔（秒） |
| `AUTO_SUMMARIZATION_ENABLED` | 否 | `true` | 抓取后自动摘要 |
| `LOG_LEVEL` | 否 | `INFO` | 日志级别 |

*新格式和旧格式二选一，至少配置一个 LLM 提供商

## CLI 命令

```bash
x-watcher init [OPTIONS]     # 初始化项目（生成 .env、创建数据库、创建管理员）
x-watcher validate           # 验证配置和服务连通性
x-watcher serve [OPTIONS]    # 启动 API 服务
```

### init 选项

| 选项 | 说明 |
|------|------|
| `--twitter-api-key` | TwitterAPI.io API Key |
| `--llm-provider` | LLM 提供商 (openrouter/deepseek/minimax/zhipu/moonshot) |
| `--llm-api-key` | LLM API Key |
| `--admin-email` | 管理员邮箱（默认 admin@x-watcher.local） |
| `--admin-password` | 管理员密码（默认自动生成） |
| `--no-input` | 非交互模式 |
| `--skip-db` | 跳过数据库初始化 |
| `--skip-validate` | 跳过验证 |

## Agent 工作流示例

```bash
# 1. 登录获取 JWT Token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@x-watcher.local","password":"YOUR_PASSWORD"}' | jq -r .access_token)

# 2. 添加关注账号
curl -X POST http://localhost:8000/api/follows/batch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"usernames":["elonmusk","OpenAI","nvidia"]}'

# 3. 手动触发抓取
TASK_ID=$(curl -s -X POST http://localhost:8000/api/admin/scrape \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"usernames":"elonmusk,OpenAI","limit":20}' | jq -r .task_id)

# 4. 查询抓取状态
curl http://localhost:8000/api/admin/scrape/$TASK_ID \
  -H "Authorization: Bearer $TOKEN"

# 5. 获取 Feed（增量拉取）
curl "http://localhost:8000/api/feed?since=2025-01-01T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"

# 6. 搜索推文
curl "http://localhost:8000/api/search/tweets?q=AI&limit=10" \
  -H "Authorization: Bearer $TOKEN"

# 7. 系统状态概览
curl http://localhost:8000/api/status/overview \
  -H "Authorization: Bearer $TOKEN"

# 8. 验证配置健康度
curl http://localhost:8000/api/admin/config/validate \
  -H "Authorization: Bearer $TOKEN"
```

## 技术栈

| 层级 | 技术 |
|------|------|
| **Web 框架** | FastAPI + Uvicorn |
| **前端** | Vue 3 + Element Plus + TypeScript |
| **LLM** | 通用 OpenAI 兼容协议（支持 6+ 提供商） |
| **数据库** | SQLite（开发）→ PostgreSQL（生产） |
| **ORM** | SQLAlchemy 2.0 + Alembic |
| **任务调度** | APScheduler |
| **CLI** | Click |
| **测试** | pytest + pytest-asyncio（550+ 测试） |
| **代码质量** | Ruff + Black + mypy |
| **监控** | Prometheus |
| **数据源** | TwitterAPI.io |
| **认证** | JWT + bcrypt |

## 功能模块

| 模块 | 说明 |
|------|------|
| **推文抓取** | 从 X 平台抓取关注人物推文，支持定时和手动触发 |
| **AI 摘要** | 使用多提供商生成中文摘要和翻译，智能降级 |
| **关注列表** | 动态管理 Twitter 关注列表 |
| **Feed** | 增量信息流 API |
| **用户管理** | 用户注册、JWT 认证、管理员权限 |
| **主题聚合** | 多账号推文聚合分析，生成主题报告 |
| **推文搜索** | 多字段关键词搜索（正文、摘要、翻译） |
| **推文浏览** | 按日期和作者维度浏览推文 |
| **系统监控** | Prometheus 指标 + 系统状态概览 API |

## API 端点

访问 `http://localhost:8000/docs` 查看完整 Swagger 文档。

详细 API 使用指南：[docs/api-guide.md](docs/api-guide.md)

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 用户登录 |
| GET | `/api/feed` | 增量 Feed |
| POST | `/api/admin/scrape` | 触发抓取 |
| POST | `/api/summaries/batch` | 批量摘要 |
| GET | `/api/search/tweets` | 推文搜索 |
| GET | `/api/status/overview` | 系统状态 |
| GET | `/api/admin/config/validate` | 配置验证 |
| GET | `/health` | 健康检查 |

## 测试

```bash
pytest                                      # 运行所有测试
pytest tests/summarization/ -q              # 运行摘要模块测试
pytest --cov=src --cov-report=html          # 覆盖率报告
```

## 代码质量

```bash
black src/ tests/        # 格式化
ruff check src/ tests/   # Lint
ruff check --fix src/    # 自动修复
```

## 项目结构

```
x-watcher/
├── src/
│   ├── api/routes/          # API 路由
│   ├── cli/                 # CLI 命令（init/validate/serve）
│   ├── scraper/             # 推文抓取模块
│   ├── summarization/       # AI 摘要模块
│   │   └── llm/             # LLM 集成（通用 OpenAI 兼容 + 预设）
│   ├── preference/          # 关注列表管理
│   ├── feed/                # Feed API
│   ├── topic/               # 主题聚合
│   ├── search/              # 推文搜索
│   ├── browse/              # 推文浏览
│   ├── user/                # 用户管理
│   ├── monitoring/          # Prometheus 监控
│   ├── database/            # 数据库层
│   ├── web/                 # 前端 SPA
│   ├── config.py            # 配置管理
│   └── main.py              # FastAPI 入口
├── tests/                   # 550+ 测试
├── scripts/                 # 工具脚本
├── docs/                    # 文档
└── pyproject.toml           # 项目配置
```

## 许可证

MIT License
