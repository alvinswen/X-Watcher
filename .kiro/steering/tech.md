# 技术栈

## 架构

采用 **API + Service 层** 的架构模式：
- **FastAPI**：Web 服务，提供 API 端点和定时任务调度
- **Service 层**：独立的业务编排（抓取、摘要、关注列表）
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
| **任务调度** | APScheduler | 定时抓取新闻任务（惰性启动，需管理员 API 显式启用） |
| **数据库** | SQLite（WAL 模式） → PostgreSQL | 本地开发用 SQLite，云端升级 |
| **LLM** | 通用 OpenAI 兼容协议（OpenRouter / MiniMax / DeepSeek / 智谱 / Moonshot 等） | 统一 Provider 架构，可扩展 |
| **Agent 框架** | HKUDS/nanobot（计划中） | 超轻量（4000 行），微内核设计 |

## AI 能力

| 功能 | 提供商 | 模型 | 成本估算 |
|------|--------|------|----------|
| 摘要/翻译 | OpenRouter | Claude Sonnet 4.5 | $0.003-0.015/千 tokens |
| 摘要/翻译 | MiniMax | M2.1 (abab6.5s-chat) | ¥0.015/千 tokens |
| 摘要/翻译 | DeepSeek | deepseek-chat | ¥0.001-0.002/千 tokens |
| 摘要/翻译 | 智谱 AI | glm-4-flash | ¥0.001/千 tokens |
| 摘要/翻译 | Moonshot | moonshot-v1-8k | ¥0.012/千 tokens |
**LLM 架构**：统一 `OpenAICompatibleProvider` + 预设（presets.py），所有提供商通过 OpenAI 兼容协议调用。新增提供商只需添加预设配置，无需编写新代码。

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
openai              # 所有 LLM 提供商均兼容 OpenAI 格式（统一 Provider 架构）

# 认证
bcrypt              # 密码哈希（SHA-256 预处理 + bcrypt 12 rounds）
python-jose[cryptography]  # JWT 令牌（HS256）

# 监控
prometheus_client   # Prometheus 指标采集

# 工具库
python-dotenv       # 环境变量
# logging — 使用标准库 logging + 自定义 logging_config.py（JSON/文本双格式 + trace_id + 文件轮转）

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
# === 新格式：统一 LLM Provider 配置（推荐） ===
LLM_PROVIDERS=openrouter,deepseek          # 提供商优先级列表
LLM_OPENROUTER_API_KEY=your_api_key        # 各提供商 API Key
LLM_DEEPSEEK_API_KEY=your_api_key
# LLM_<SLUG>_MODEL=custom-model            # 可选：覆盖默认模型
# LLM_<SLUG>_BASE_URL=https://...          # 可选：覆盖默认 base_url

# === 旧格式（向后兼容，优先级低于新格式） ===
# MINIMAX_API_KEY=your_api_key
# OPENROUTER_API_KEY=your_api_key

# X 平台 API
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_secret

# 数据库
DATABASE_URL=sqlite:///./news_agent.db

# 日志
LOG_FORMAT=text                     # 控制台日志格式（text=人类可读, json=结构化）
LOG_FILE=logs/x-watcher.log         # 日志文件路径，留空禁用
LOG_FILE_MAX_BYTES=52428800         # 单个日志文件最大 50MB
LOG_FILE_BACKUP_COUNT=5             # 保留 5 个备份文件

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
SCRAPER_INTERVAL=43200              # 默认抓取间隔（秒），仅作为 GET /schedule 的回退默认值；启动时不自动创建 job，需管理员通过 API 显式启用

# 抓取优化
SCRAPER_LIMIT=30                    # 自动计算默认 limit（无历史数据时使用）
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

## SQLite 并发写入策略

本地开发环境使用 SQLite，需处理多写者并发场景（如：长时间摘要任务运行期间修改调度配置）。

### WAL 模式 + busy_timeout
- **WAL（Write-Ahead Logging）模式**：允许读写并发，比默认 rollback journal 性能更好
- **busy_timeout=30s**：写入锁竞争时等待 30 秒，避免立即失败
- **synchronous=NORMAL**：平衡写入性能和数据安全
- 配置位置：`src/database/async_session.py` 和 `src/database/models.py`

### 短事务 + 独立 Session 策略
- **摘要服务每处理完一个 group/tweet 后立即 commit**，将 RESERVED 锁持有时间从分钟级降至毫秒级
- **调度配置服务的 retry 操作每次使用独立 session**，避免 SQLAlchemy 的 PendingRollbackError（session 中毒）
- **指数退避重试**：0.5s → 1s → 2s，配合 busy_timeout 应对瞬时锁竞争

### 任务历史持久化
- 完成/失败的抓取任务自动写入 `task_execution_logs` 表（`TaskExecutionLog` 模型）
- 使用**同步 engine** 写入，避免与异步事件循环冲突
- 提供 `GET /api/admin/tasks/history` 端点查询历史记录

### 大小写不敏感的用户名查询
- **背景**：Twitter API 对用户名查询大小写不敏感，但返回结果使用官方大小写（如 `IndieHackers`），而 `scraper_follows` 表中的用户名由用户手动输入（如 `indiehackers`），SQLite 的 `=` 和 `IN` 默认大小写敏感
- **统一模式**：所有 `TweetOrm.author_username` 查询必须使用 `func.lower()` 包裹
  - `==` 比较：`func.lower(TweetOrm.author_username) == value.lower()`
  - `IN` 比较：`func.lower(TweetOrm.author_username).in_([u.lower() for u in usernames])`
  - `GROUP BY` 也需同步使用 `func.lower()`，结果映射用 `.lower()` 键匹配

## 关键技术决策

### 为什么暂不引入 Agent 框架？
- **YAGNI 原则**：当前 API + Service 层架构已满足所有需求
- **直接驱动**：FastAPI 路由直接调用 Service，减少不必要的中间层
- **演进灵活**：Service 独立，未来可按需引入 Nanobot Agent 层

### 为什么选择 Nanobot 作为未来 Agent 框架？
- **轻量优先**：4000 行代码 vs 数十万行，易于理解和维护
- **微内核设计**：只提供核心调度能力，不引入过多抽象

### 为什么用集中式队列替代 fire-and-forget 摘要触发？
- **并发安全**：原有 `asyncio.create_task()` 散落在多个 Service 中，多用户并发时产生大量协程堆积
- **背压控制**：有界 `asyncio.PriorityQueue(100)` 提供背压信号，队列满时丢弃并告警而非无限堆积
- **优先级**：手动 batch API (HIGH) > 自动触发 (NORMAL) > 重试 (LOW)
- **安全重试**：内置指数退避（5s × 2^n），最多 3 次，替代原有不安全的类级 `_pending_summary_retry` set
- **跨线程安全**：APScheduler 后台线程通过 `asyncio.run_coroutine_threadsafe()` 安全入队
- **可观测性**：集成 TaskRegistry + Prometheus 指标（queue_size, enqueued, processed, dropped）
- **分块处理**：终于使用 `auto_summarization_batch_size` 配置项分块入队

### 为什么引入 Prometheus 监控？
- **可观测性需求**：抓取任务、摘要队列、调度器执行状态需要量化监控
- **多维度指标**：HTTP 请求（计数 + 延迟直方图）、活跃任务数、调度器执行/错误/漏跑、摘要队列（入队/处理/丢弃）
- **标准集成**：`prometheus_client` 库 + FastAPI 中间件自动采集，`/metrics` 端点暴露
- **低侵入性**：通过 APScheduler 事件监听器（`scheduler_listener.py`）和队列钩子自动上报，业务代码无需关心

### 为什么用自定义 logging_config 替代 basicConfig？
- **extra 字段可见**：`basicConfig` 格式完全丢弃 `extra={}` 结构化字段，SummaryLogger 精心构建的上下文（tweet_id, provider, tokens, cost）不可见
- **双输出策略**：控制台用人类可读文本（开发友好），文件强制 JSON 格式（机器可解析，支持 grep/jq）
- **trace_id 链路追踪**：基于 `contextvars.ContextVar`，在管道入口（抓取任务/摘要队列 worker）设置，通过 `TraceIdFilter` 自动注入所有日志
- **文件轮转**：`RotatingFileHandler`，50MB/文件，5 个备份，避免磁盘爆满
- **增强文本格式**：在消息后追加关键 extra 字段（`| provider=xxx tweet_id=xxx`），开发时也能看到结构化上下文

### 为什么使用统一 OpenAI 兼容 Provider 架构？
- **协议统一**：所有目标提供商（OpenRouter、MiniMax、DeepSeek、智谱、Moonshot 等）均兼容 OpenAI Chat Completions API
- **代码复用**：单一 `OpenAICompatibleProvider` 替代重复的 Provider 实现
- **易于扩展**：新增提供商只需在 `presets.py` 添加预设配置，无需编写新代码
- **向后兼容**：旧的 `OpenRouterProvider` / `MiniMaxProvider` 作为 thin wrapper 保留
- **灵活配置**：新格式 `LLM_PROVIDERS=openrouter,deepseek` + 旧格式 `MINIMAX_API_KEY` 均可使用

---
_记录标准和模式，而非每个依赖_
