# 项目结构

## 组织理念

采用**六边形架构 + 模块化设计**：
- 清晰的层次划分（API / Service / Domain / Infrastructure）
- 按业务功能组织独立模块（scraper, deduplication, summarization, preference, topic）
- 每个模块遵循 Domain → Service → Infrastructure 分层
- 保持低耦合、高内聚

## 目录模式

### 根目录
**位置**：`/`
**用途**：项目配置、依赖管理、构建脚本
**示例**：`pyproject.toml`, `.env`, `README.md`

### 源代码
**位置**：`src/`
**用途**：主要业务逻辑代码

```
src/
├── api/                     # FastAPI 路由和端点
│   └── routes/
│       ├── admin.py         # 管理功能 API（抓取任务、任务历史查询）
│       ├── scheduler.py     # 调度器执行历史 API（GET /api/admin/scheduler/history）
│       └── tweets.py        # 推文列表/详情 API
├── agent/                   # Nanobot Agent 配置
│   ├── tools.py             # API 工具元数据定义（Feed、摘要修复）
│   └── config.py            # Agent 系统提示和工具注册
├── scraper/                 # 推文抓取模块
│   ├── client.py            # TwitterAPI.io 客户端（含引用推文预处理）
│   ├── parser.py            # 推文解析器
│   ├── validator.py         # 数据验证器（MAX_TEXT_LENGTH=25000）
│   ├── scraping_service.py  # 抓取编排服务（含自动摘要触发）
│   ├── scheduled_job.py     # 定时抓取任务函数（供 main.py 和 schedule_service 共用）
│   ├── scheduler_listener.py # APScheduler 事件监听器（EXECUTED/ERROR/MISSED → DB + Prometheus）
│   ├── task_registry.py     # 异步任务注册表（含任务历史持久化到 TaskExecutionLog）
│   ├── domain/
│   │   ├── models.py        # 领域模型（Tweet, Media, SaveResult）
│   │   ├── fetch_stats.py   # 抓取统计领域模型（FetchStats）
│   │   └── scheduler_log.py # 调度器执行日志领域模型（SchedulerEventType, SchedulerExecutionLog）
│   ├── infrastructure/
│   │   ├── models.py        # ORM 模型（TweetOrm, DeduplicationGroupOrm）
│   │   ├── repository.py    # 推文数据仓库
│   │   ├── fetch_stats_models.py     # FetchStatsOrm
│   │   ├── fetch_stats_repository.py # 抓取统计仓库
│   │   ├── scheduler_log_models.py     # SchedulerExecutionLogOrm
│   │   └── scheduler_log_repository.py # 调度器日志仓库（同步写入 + 异步查询）
│   └── services/
│       └── limit_calculator.py  # 动态抓取数量计算（EMA 算法）
├── deduplication/           # 内容去重模块
│   ├── domain/
│   │   ├── models.py        # 领域模型
│   │   └── detectors.py     # 相似度检测器
│   ├── infrastructure/
│   │   └── repository.py    # 仓库
│   ├── services/
│   │   └── deduplication_service.py
│   └── api/routes.py        # API 端点
├── summarization/           # AI 摘要模块
│   ├── domain/models.py     # 领域模型
│   ├── infrastructure/
│   │   ├── models.py        # ORM 模型
│   │   └── repository.py    # 仓库
│   ├── services/
│   │   ├── summarization_service.py
│   │   └── summarization_queue.py  # 集中式摘要任务队列（PriorityQueue + 单 worker）
│   ├── llm/                 # LLM 集成
│   │   ├── base.py          # 抽象基类
│   │   ├── config.py        # LLM 配置
│   │   ├── minimax.py       # MiniMax 集成
│   │   └── openrouter.py    # OpenRouter 集成
│   └── api/
│       ├── routes.py        # API 端点
│       └── schemas.py       # 请求/响应模型
├── preference/              # 关注列表管理模块
│   ├── domain/
│   │   ├── models.py        # 领域模型
│   │   └── validators.py    # 验证逻辑
│   ├── infrastructure/
│   │   ├── preference_repository.py
│   │   ├── scraper_config_repository.py
│   │   └── schedule_repository.py   # 调度配置仓库（singleton 单行模式）
│   ├── services/
│   │   ├── preference_service.py
│   │   ├── scraper_config_service.py
│   │   └── schedule_service.py      # 调度配置业务服务（含启用/暂停、惰性 job 创建、独立 session 重试）
│   └── api/
│       ├── routes.py        # 路由导出
│       ├── auth.py          # API Key 认证
│       ├── schemas.py       # 请求/响应模型
│       ├── preference_router.py   # 关注列表 API
│       └── scraper_config_router.py  # 管理员抓取配置 + 调度管理（含 enable/disable）+ 账号运行时统计（follows/stats）+ 公共只读 API
├── user/                    # 用户管理与认证模块
│   ├── api/
│   │   ├── auth.py          # JWT + API Key 统一认证依赖
│   │   ├── auth_router.py   # POST /api/auth/login
│   │   ├── user_router.py   # 用户资料、API Key 管理
│   │   ├── admin_user_router.py  # 管理员创建/管理/编辑用户
│   │   └── admin_user_follows_router.py  # 管理员代理管理用户关注列表
│   ├── domain/
│   │   ├── models.py        # UserDomain, ApiKeyInfo, BOOTSTRAP_ADMIN
│   │   └── schemas.py       # Login/User/ApiKey 请求响应模型
│   ├── infrastructure/
│   │   └── repository.py    # UserRepository
│   └── services/
│       ├── auth_service.py  # bcrypt 密码、JWT 令牌、API Key 生成/验证
│       └── user_service.py  # 用户业务逻辑
├── feed/                    # Agent 导向 Feed API
│   ├── api/
│   │   ├── routes.py        # GET /api/feed（时间范围查询）
│   │   └── schemas.py       # FeedTweetItem, FeedResponse
│   └── services/
│       └── feed_service.py  # Feed 查询（tweets LEFT JOIN summaries）
├── topic/                   # 主题管理模块（多账号聚合分析）
│   ├── domain/
│   │   └── models.py        # 领域模型（TopicDomain, TopicSummaryTaskDomain, TopicSummaryTaskStatus）
│   ├── infrastructure/
│   │   ├── models.py        # ORM 模型（TopicOrm, TopicAccountOrm, TopicSummaryTaskOrm, TopicSummaryOrm）
│   │   └── repository.py    # TopicRepository + TopicSummaryTaskRepository
│   ├── services/
│   │   ├── topic_service.py           # 主题 CRUD + 账号管理
│   │   └── topic_summary_service.py   # 摘要任务异步执行（LLM 聚合摘要）
│   └── api/
│       ├── routes.py        # 主题 CRUD + 账号管理 + 摘要任务 API 端点
│       └── schemas.py       # 请求/响应模型
├── browse/                  # 推文浏览模块（按日期/作者维度浏览）
│   ├── api/
│   │   ├── routes.py        # GET /api/browse/stats/daily, /authors, /tweets
│   │   └── schemas.py       # DailyStatsResponse, AuthorListResponse, BrowseTweetListResponse
│   └── services/
│       └── browse_service.py  # 每日统计、作者列表、推文列表查询
├── monitoring/              # Prometheus 监控
│   ├── metrics.py           # 指标定义
│   ├── middleware.py         # 中间件
│   └── routes.py            # /metrics 端点
├── shared/                  # 公共基础设施
│   └── schemas.py           # UTCDatetimeModel 公共基类（SQLite naive datetime → UTC 序列化）
├── database/                # 数据库层
│   ├── models.py            # SQLAlchemy 基础模型（User, ScraperScheduleConfig, TaskExecutionLog 等）
│   └── async_session.py     # 异步会话管理（WAL 模式 + busy_timeout）
├── models/                  # （legacy 空壳，待清理）
├── services/                # （legacy 空壳，待清理）
├── tools/                   # （legacy 空壳，待清理）
├── web/                     # 前端 SPA（Vue 3 + Element Plus）
├── scheduler_accessor.py    # 调度器全局引用管理（解耦 Service 与 APScheduler）
├── logging_config.py        # 日志配置（JSONFormatter + EnhancedTextFormatter + TraceIdFilter + trace_id_var + setup_logging）
├── config.py                # 全局配置（Pydantic Settings）
└── main.py                  # FastAPI 应用入口（惰性调度启动 + DB 迁移）
```

### 测试代码
**位置**：`tests/`
**用途**：所有测试代码
**示例**：
```
tests/
├── unit/               # 单元测试（config, main, models）
├── scraper/            # 抓取模块测试
├── deduplication/      # 去重模块测试
├── summarization/      # 摘要模块测试
├── preference/         # 关注列表模块测试（含调度配置、公共只读端点测试）
├── user/               # 用户认证测试
├── feed/               # Feed API 测试
├── api/                # API 端点测试
├── integration/        # 集成测试
├── performance/        # 性能测试
└── conftest.py         # pytest 配置和 fixtures
```

### 文档
**位置**：`docs/`
**用途**：项目文档、API 文档
**示例**：`docs/api/`, `docs/architecture/`

### 脚本
**位置**：`scripts/`
**用途**：定时任务、数据迁移、部署脚本
**示例**：`scripts/fetch_news.py`, `scripts/migrate_db.py`

## 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 文件名 | `snake_case.py` | `twitter_client.py` |
| 类名 | `PascalCase` | `TwitterClient` |
| 函数/变量 | `snake_case` | `fetch_tweets()` |
| 常量 | `UPPER_SNAKE_CASE` | `MAX_TWEETS` |
| 私有成员 | `_leading_underscore` | `_internal_func()` |

## 导入组织

```python
# 1. 标准库
import os
from datetime import datetime

# 2. 第三方库
from fastapi import FastAPI
from pydantic import BaseModel
import httpx

# 3. 本地模块
from src.scraper.client import TwitterClient
from src.scraper.domain.models import Tweet
```

## 代码组织原则

### 模块内分层架构
```
API 层 (FastAPI routes, schemas)
    ↓ 调用
Service 层 (业务编排)
    ↓ 使用
Domain 层 (领域模型, 业务规则)
    ↓ 通过
Infrastructure 层 (Repository, ORM 模型)
    ↓ 通信
External (数据库, TwitterAPI.io, MiniMax LLM)
```

### 模块设计原则
- **独立可测试**：每个模块可独立测试
- **清晰接口**：输入输出类型明确（Pydantic 模型）
- **领域驱动**：业务逻辑在 Domain/Service 层，基础设施在 Infrastructure 层
- **错误处理**：使用 returns 库的 Result 类型进行函数式错误处理

### 数据流
```
用户输入
  → API (FastAPI routes)
    → Service (业务编排)
      → Domain (领域逻辑) + Infrastructure (数据持久化)
        → External APIs / Database
  → API (返回结果)
```

## 演进策略

### 当前阶段：API + Service 层直接驱动
- FastAPI 路由直接调用 Service 层
- Service 层编排业务逻辑（抓取、去重、摘要、关注列表）
- 双 LLM 提供商：MiniMax M2.1 / OpenRouter (Claude Sonnet 4.5)

### 未来阶段：Agent 集成（按需）
当出现以下需求时，考虑引入 Agent 层：
- 需要自然语言意图理解和多步推理
- 需要动态工具调度
- 不同功能需要使用不同 LLM（成本优化）

演进方式：
```
当前: API → Service → Infrastructure
未来: API → Agent (意图理解) → Service → Infrastructure
```

---
_记录模式，而非文件树。遵循模式的新文件不需要更新此文档_
