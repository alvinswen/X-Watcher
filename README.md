# X-watcher

面向 Agent 的 X 平台智能信息监控服务

## 项目简介

X-watcher 是一个面向 Agent 的 X 平台（Twitter）智能信息监控服务，为 AI Agent 提供结构化的信息采集、处理和分发能力。系统能够：

- 从 X（Twitter）平台抓取关注人物的动态
- 自动去重和合并相似内容
- 生成简洁的中文摘要和翻译
- 支持动态调整关注列表
- 提供 Web 管理界面（Vue 3 + Element Plus）
- 用户认证和权限管理
- Prometheus 监控指标

## 技术栈

| 层级 | 技术 |
|------|------|
| **Web 框架** | FastAPI + Uvicorn |
| **前端** | Vue 3 + Element Plus + TypeScript |
| **LLM** | MiniMax M2.1 / OpenRouter (Claude Sonnet 4.5) |
| **数据库** | SQLite（开发）→ PostgreSQL（生产） |
| **ORM** | SQLAlchemy 2.0 + Alembic |
| **任务调度** | APScheduler |
| **测试** | pytest + pytest-asyncio（510+ 测试） |
| **代码质量** | Ruff + Black + mypy |
| **监控** | Prometheus |
| **数据源** | TwitterAPI.io |
| **认证** | JWT + bcrypt |
| **Agent 框架** | HKUDS/nanobot（计划中） |

## 安装

### 前置要求

- Python 3.11+
- Node.js >= 18（前端开发）
- Git

### 步骤

1. 克隆仓库
```bash
git clone <repository-url>
cd X-watcher
```

2. 安装依赖
```bash
pip install -e .
```

3. 安装开发依赖（可选）
```bash
pip install -e ".[dev]"
```

4. 安装前端依赖（可选）
```bash
cd src/web
npm install
```

## 配置

1. 复制环境变量模板
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入必要的配置：

```bash
# MiniMax API 配置
MINIMAX_API_KEY=your_minimax_api_key_here
MINIMAX_BASE_URL=https://api.minimaxi.com

# X 平台 API 配置（使用 TwitterAPI.io）
TWITTER_API_KEY=your_twitterapi_io_api_key_here
TWITTER_BEARER_TOKEN=dummy_placeholder
TWITTER_BASE_URL=https://api.twitterapi.io/twitter

# 管理员 API Key
ADMIN_API_KEY=your_admin_api_key

# 抓取器配置
SCRAPER_ENABLED=true
SCRAPER_INTERVAL=3600
SCRAPER_USERNAMES=elonmusk,OpenAI,nvidia
SCRAPER_LIMIT=100

# 数据库配置
DATABASE_URL=sqlite:///./news_agent.db

# 日志级别
LOG_LEVEL=INFO

# 自动摘要
AUTO_SUMMARIZATION_ENABLED=true
AUTO_SUMMARIZATION_BATCH_SIZE=50
```

### TwitterAPI.io 配置说明

本项目使用 [TwitterAPI.io](https://twitterapi.io/) 作为 X 平台数据源：

1. 访问 https://twitterapi.io/ 注册账号
2. 从 Dashboard 获取 API Key
3. 在 `.env` 文件中设置 `TWITTER_API_KEY`
4. **注意**: TwitterAPI.io 使用 `X-API-Key` header 认证，不是标准的 Bearer Token

## 运行

### 启动后端服务

```bash
# 初始化数据库和管理员账户
python -m scripts.seed_admin

# 启动开发服务器
python -m src.main

# 或使用 uvicorn
uvicorn src.main:app --reload

# 或使用安装后的命令
x-watcher
```

应用将在 `http://localhost:8000` 启动。

### 启动前端开发服务器

```bash
cd src/web
npm run dev
```

前端运行在 `http://localhost:5173`，已配置 API 代理。

### 访问 API 文档

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### API 使用指南
详细的 API 使用文档请参阅：[docs/api-guide.md](docs/api-guide.md)

**快速链接**：
- [推文 API](docs/api-guide.md#推文-api) - 推文列表和详情查询
- [抓取 API](docs/api-guide.md#抓取-api) - 从 X 平台抓取推文
- [抓取配置 API](docs/api-guide.md#抓取配置-api) - 平台抓取账号管理
- [去重 API](docs/api-guide.md#去重-api) - 推文去重和合并
- [摘要 API](docs/api-guide.md#摘要-api) - 生成中文摘要
- [关注列表 API](docs/api-guide.md#关注列表-api) - 关注列表管理
- [监控 API](docs/api-guide.md#监控-api) - Prometheus 指标

### Python 示例代码
```bash
# 运行 API 使用示例
python examples/api_examples.py
```

## 测试

```bash
# 运行所有测试
pytest

# 运行测试并显示覆盖率
pytest --cov=src --cov-report=html

# 运行特定测试文件
pytest tests/scraper/test_twitter_client.py
```

### 测试覆盖率

当前测试规模：510+ 个测试函数，39 个测试文件，覆盖抓取、去重、摘要、偏好、用户管理、Feed API 等全部模块。

## 功能模块

| 模块 | 说明 |
|------|------|
| **推文抓取** | 从 X 平台抓取关注人物推文，支持定时和手动触发 |
| **内容去重** | 基于文本相似度识别和合并重复/相似推文 |
| **AI 摘要** | 使用 MiniMax/OpenRouter 生成中文摘要和翻译 |
| **关注列表** | 动态管理 Twitter 关注列表 |
| **Feed** | 增量信息流 API |
| **用户管理** | 用户注册、JWT 认证、管理员权限 |
| **Web 管理** | Vue 3 前端 SPA（推文浏览、关注管理、任务监控） |
| **系统监控** | Prometheus 指标（HTTP 请求、任务状态、数据库连接） |

## API 端点

### 抓取相关端点

#### 手动抓取推文
```bash
POST /api/admin/scrape
Content-Type: application/json

{
  "usernames": "elonmusk,OpenAI",
  "limit": 10
}
```

#### 查询任务状态
```bash
GET /api/admin/scrape/{task_id}
```

#### 列出所有任务
```bash
GET /api/admin/scrape
```

### 示例：使用 curl 测试抓取功能

```bash
# 1. 启动服务
python -m src.main

# 2. 触发抓取任务
curl -X POST "http://localhost:8000/api/admin/scrape" \
  -H "Content-Type: application/json" \
  -d '{"usernames": "elonmusk", "limit": 10}'

# 3. 查询任务状态（替换 {task_id}）
curl "http://localhost:8000/api/admin/scrape/{task_id}"
```

## 代码质量

```bash
# 代码格式化
black src/ tests/

# Lint 检查
ruff check src/ tests/

# 自动修复 Lint 问题
ruff check --fix src/ tests/
```

## 项目结构

```
X-watcher/
├── src/
│   ├── api/routes/          # API 路由（admin, tweets）
│   ├── agent/               # Agent 配置（nanobot 集成）
│   ├── scraper/             # 推文抓取模块
│   │   ├── domain/          # 领域模型（Tweet, Media 等）
│   │   └── infrastructure/  # ORM 模型和仓库
│   ├── deduplication/       # 内容去重模块
│   │   ├── domain/          # 领域模型和检测器
│   │   ├── infrastructure/  # 仓库
│   │   ├── services/        # 去重服务
│   │   └── api/             # 去重 API 端点
│   ├── summarization/       # AI 摘要模块
│   │   ├── domain/          # 领域模型
│   │   ├── infrastructure/  # ORM 模型和仓库
│   │   ├── services/        # 摘要服务
│   │   ├── llm/             # LLM 集成（MiniMax, OpenRouter）
│   │   └── api/             # 摘要 API 端点
│   ├── preference/          # 关注列表管理模块
│   │   ├── domain/          # 领域模型和验证
│   │   ├── infrastructure/  # 仓库
│   │   ├── services/        # 关注列表服务
│   │   └── api/             # 关注列表 API 端点
│   ├── feed/                # 信息流模块
│   │   └── api/             # Feed API 端点
│   ├── user/                # 用户管理模块
│   │   └── api/             # 认证和用户 API
│   ├── monitoring/          # Prometheus 监控
│   ├── database/            # 数据库（ORM 模型, 异步会话）
│   ├── web/                 # 前端 SPA（Vue 3 + Element Plus）
│   ├── config.py            # 配置管理
│   └── main.py              # FastAPI 应用入口
├── tests/
│   ├── unit/                # 单元测试
│   ├── scraper/             # 抓取模块测试
│   ├── deduplication/       # 去重模块测试
│   ├── summarization/       # 摘要模块测试
│   ├── preference/          # 关注列表模块测试
│   ├── api/                 # API 端点测试
│   ├── integration/         # 集成测试
│   └── conftest.py          # pytest 配置
├── alembic/                 # 数据库迁移脚本
├── docs/                    # 项目文档
│   ├── api-guide.md         # API 使用指南
│   ├── architecture.md      # 架构文档
│   ├── news-scraper.md      # 抓取模块文档
│   ├── user-guide.md        # 使用指南
│   └── nanobot-integration-plan.md  # Nanobot 集成计划
├── examples/                # 代码示例
├── scripts/                 # 脚本（seed_admin.py 等）
├── pyproject.toml           # 项目配置
├── alembic.ini              # 数据库迁移配置
├── .env.example             # 环境变量模板
└── README.md                # 本文件
```

## 开发指南

### TDD 开发流程

本项目遵循测试驱动开发（TDD）：

1. **RED** - 先写失败的测试
2. **GREEN** - 写最小代码使测试通过
3. **REFACTOR** - 清理代码

### 添加新功能

1. 在 `tests/` 中创建测试
2. 运行测试确认失败
3. 实现功能代码
4. 运行测试确认通过
5. 运行 `black` 和 `ruff` 检查代码质量

## 许可证

MIT License

## 联系方式

- 项目主页: [GitHub Repository]
