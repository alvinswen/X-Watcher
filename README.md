# SeriousNewsAgent

智能新闻助理系统 - 面向科技公司高管的个性化新闻流

## 项目简介

SeriousNewsAgent 是一个基于 AI 的智能新闻助理，专为科技公司高管设计。系统能够：

- 从 X（Twitter）等平台抓取关注人物的动态
- 根据公司战略需求动态过滤新闻
- 自动去重和合并相似内容
- 生成简洁的中文摘要
- 支持动态调整关注列表和偏好

## 技术栈

| 层级 | 技术 |
|------|------|
| **Web 框架** | FastAPI |
| **Agent 框架** | HKUDS/nanobot |
| **LLM** | MiniMax M2.1 |
| **数据库** | SQLite → PostgreSQL |
| **ORM** | SQLAlchemy 2.0 |
| **测试** | pytest + pytest-asyncio |
| **代码质量** | Ruff + Black |

## 安装

### 前置要求

- Python 3.11+
- Git

### 步骤

1. 克隆仓库
```bash
git clone <repository-url>
cd SeriousNewsAgent
```

2. 安装依赖
```bash
pip install -e .
```

3. 安装开发依赖（可选）
```bash
pip install -e ".[dev]"
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

# 抓取器配置
SCRAPER_ENABLED=true
SCRAPER_INTERVAL=3600
SCRAPER_USERNAMES=elonmusk,OpenAI,nvidia
SCRAPER_LIMIT=10

# 数据库配置
DATABASE_URL=sqlite:///./news_agent.db

# 日志级别
LOG_LEVEL=INFO
```

### TwitterAPI.io 配置说明

本项目使用 [TwitterAPI.io](https://twitterapi.io/) 作为 X 平台数据源：

1. 访问 https://twitterapi.io/ 注册账号
2. 从 Dashboard 获取 API Key
3. 在 `.env` 文件中设置 `TWITTER_API_KEY`
4. **注意**: TwitterAPI.io 使用 `X-API-Key` header 认证，不是标准的 Bearer Token

## 运行

### 启动开发服务器

```bash
uvicorn src.main:app --reload
```

或使用：

```bash
python -m src.main
```

应用将在 `http://localhost:8000` 启动。

### 访问 API 文档

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

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

当前测试覆盖率：
- **scraper 模块**: 80% (127 个测试全部通过)
- **整体覆盖率**: 约 80%

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
SeriousNewsAgent/
├── src/
│   ├── api/routes/      # API 路由
│   ├── agent/           # Nanobot Agent 配置
│   ├── tools/           # 工具函数
│   ├── models/          # 数据模型 (Pydantic)
│   ├── database/        # 数据库操作
│   ├── services/        # 业务服务
│   ├── config.py        # 配置管理
│   └── main.py          # FastAPI 应用入口
├── tests/
│   ├── unit/            # 单元测试
│   ├── integration/     # 集成测试
│   └── conftest.py      # pytest 配置
├── docs/                # 项目文档
├── scripts/             # 脚本文件
├── pyproject.toml       # 项目配置
├── .env.example         # 环境变量模板
└── README.md            # 本文件
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
