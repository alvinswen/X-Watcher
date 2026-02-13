# 技术栈

## 架构

采用 **API + Service 层** 的架构模式：
- **FastAPI**：Web 服务，提供 API 端点和定时任务调度
- **Service 层**：独立的业务编排（抓取、去重、摘要、关注列表）
- **Agent（计划中）**：未来引入 HKUDS/nanobot 实现意图理解
- **演进策略**：按需引入 Agent 层实现自然语言交互

```
用户请求 (Web / API)
    ↓
API 层 (FastAPI 路由)
    ↓
Service 层 (业务编排)
    ↓
数据层 (SQLite/PostgreSQL) + LLM API (MiniMax / OpenRouter)
```

## 核心技术

| 层级 | 技术选择 | 理由 |
|------|----------|------|
| **编程语言** | Python 3.11+ | 开发者熟悉，生态成熟 |
| **Web 框架** | FastAPI | 高性能、异步支持、自动文档 |
| **任务调度** | APScheduler | 定时抓取新闻任务 |
| **数据库** | SQLite → PostgreSQL | 本地开发用 SQLite，云端升级 |
| **LLM** | MiniMax M2.1 / OpenRouter (Claude Sonnet 4.5) | 双提供商，高性价比 |
| **Agent 框架** | HKUDS/nanobot（计划中） | 超轻量（4000 行），微内核设计 |

## AI 能力

| 功能 | 提供商 | 模型 | 成本估算 |
|------|--------|------|----------|
| 摘要/翻译 | MiniMax | M2.1 (abab6.5s-chat) | ¥0.015/千 tokens |
| 摘要/翻译 | OpenRouter | Claude Sonnet 4.5 | $0.003-0.015/千 tokens |
| 去重判断 | 嵌入模型（可选） | - | 另计 |

**成本优势**：MiniMax 比 OpenAI 便宜 10 倍以上；OpenRouter 提供更高质量但稍贵的选择

## X 平台数据获取

| 服务商 | 定价 | 推荐理由 |
|--------|------|----------|
| **TwitterAPI.io** | $0.15/1000条 + 100K 免费额度 | 前期测试首选 |
| **RapidAPI** | $179.99/月（100万条） | 量大时考虑 |
| **官方 X API** | $100/月起 | 备选 |

## 关键库

```python
# Web 服务
fastapi             # API 框架
uvicorn             # ASGI 服务器
pydantic            # 数据验证

# 任务调度
apscheduler         # 定时任务

# 数据库
sqlalchemy          # ORM
alembic             # 数据库迁移

# HTTP 客户端
httpx               # 异步 HTTP

# LLM 集成
openai              # MiniMax 和 OpenRouter 均兼容 OpenAI 格式

# 认证
bcrypt              # 密码哈希（SHA-256 预处理 + bcrypt 12 rounds）
python-jose[cryptography]  # JWT 令牌（HS256）

# 工具库
python-dotenv       # 环境变量
loguru              # 日志

# Agent 框架（计划中）
# nanobot-ai        # HKUDS/nanobot — 待引入
```

## 开发标准

### 代码风格
- **PEP 8**：Python 代码规范
- **Black**：代码格式化
- **Ruff**：快速 Lint（替代 Flake8 + isort）
- **mypy**：类型检查（可选）

### 架构原则
- **YAGNI**：不提前实现不需要的功能
- **单职责**：每个 Service 只做一件事
- **易演进**：保持 Service 独立，便于未来引入 Agent 层
- **数据完整性**：抓取逻辑原则上需保留所有抓取到的重要信息，如果这与当前程序逻辑冲突（如 FK 约束、存储格式限制等），需要及时提醒

### 测试
- **TDD**：测试驱动开发
- **pytest**：测试框架
- **pytest-asyncio**：异步测试支持
- **覆盖率目标**：80%+

## 开发环境

### 必需工具
- Python 3.11+
- Git
- 可选：Docker（容器化部署）

### 环境变量
```bash
# MiniMax API
MINIMAX_API_KEY=your_api_key
MINIMAX_BASE_URL=https://api.minimaxi.com

# OpenRouter API（可选）
OPENROUTER_API_KEY=your_api_key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# X 平台 API
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_secret

# 数据库
DATABASE_URL=sqlite:///./news_agent.db

# 认证与用户管理
ADMIN_API_KEY=your_admin_key        # 管理员 API Key（Bootstrap 模式）
JWT_SECRET_KEY=your_jwt_secret      # JWT 签名密钥
JWT_EXPIRE_HOURS=24                 # JWT 过期时间

# 自动摘要
AUTO_SUMMARIZATION_ENABLED=true     # 抓取后自动摘要
AUTO_SUMMARIZATION_BATCH_SIZE=10    # 批量摘要大小

# Feed
FEED_MAX_TWEETS=200                 # Feed 返回最大推文数

# 抓取调度
SCRAPER_INTERVAL=43200              # 默认抓取间隔（秒），可通过管理 API 运行时覆盖

# 抓取优化
SCRAPER_MIN_LIMIT=10                # 动态 limit 最小值
SCRAPER_MAX_LIMIT=300               # 动态 limit 最大值
SCRAPER_EMA_ALPHA=0.3               # EMA 平滑系数

# 摘要长度配置（可选）
SUMMARIZATION_MIN_TWEET_LENGTH=30
SUMMARIZATION_MIN_LENGTH_RATIO=0.5
SUMMARIZATION_MAX_LENGTH_RATIO=1.5
```

### 配置项说明

#### 摘要长度配置

系统支持智能摘要长度策略，根据推文原始长度动态调整摘要长度：

- **`SUMMARIZATION_MIN_TWEET_LENGTH`**（默认：30）
  - 推文最小长度阈值
  - 低于此值的推文直接返回原文，标记 `is_generated_summary=False`
  - 可根据业务需求调整

- **`SUMMARIZATION_MIN_LENGTH_RATIO`**（默认：0.5）
  - 摘要最小长度比例
  - 摘要最小长度 = 原文长度 × 此比例
  - 例如：100 字推文的最小摘要长度为 50 字

- **`SUMMARIZATION_MAX_LENGTH_RATIO`**（默认：1.5）
  - 摘要最大长度比例
  - 摘要最大长度 = 原文长度 × 此比例
  - 例如：100 字推文的最大摘要长度为 150 字

**业务逻辑**：
- 短推文（< 30 字）→ 返回原文，不调用 LLM
- 中长推文（≥ 30 字）→ 生成动态长度摘要（原文的 50%-150%）
- 摘要长度范围：1-500 字

### 常用命令
```bash
# 安装依赖
pip install -e .

# 运行开发服务器
uvicorn src.main:app --reload

# 运行测试
pytest

# 代码格式化
black src/
ruff check src/

# 类型检查
mypy src/
```

## 关键技术决策

### 为什么暂不引入 Agent 框架？
- **YAGNI 原则**：当前 API + Service 层架构已满足所有需求
- **直接驱动**：FastAPI 路由直接调用 Service，减少不必要的中间层
- **演进灵活**：Service 独立，未来可按需引入 Nanobot Agent 层

### 为什么选择 Nanobot 作为未来 Agent 框架？
- **轻量优先**：4000 行代码 vs 数十万行，易于理解和维护
- **微内核设计**：只提供核心调度能力，不引入过多抽象

### 为什么选择 MiniMax + OpenRouter 双 LLM？
- **MiniMax 成本优势**：比 OpenAI 便宜 10 倍以上，中文友好
- **OpenRouter 质量优势**：Claude Sonnet 4.5 提供更高质量的摘要
- **按量付费**：两者均无需固定套餐，灵活切换

---
_记录标准和模式，而非每个依赖_
