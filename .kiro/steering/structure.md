# 项目结构

## 组织理念

采用**六边形架构 + 模块化设计**：
- 清晰的层次划分（API / Service / Domain / Infrastructure）
- 按业务功能组织独立模块（scraper, summarization, preference, topic）
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
│       ├── admin.py         # 管理功能 API（抓取任务、任务历史查询、Article 回溯）
│       ├── config_routes.py # 配置验证 API（GET /api/admin/config/validate）
│       ├── scheduler.py     # 调度器执行历史 API（GET /api/admin/scheduler/history）
│       ├── status.py        # 系统状态概览 API（GET /api/status/overview）
│       ├── sync_routes.py   # 数据同步 API（导出下载/导入预览/导入执行）
│       └── tweets.py        # 推文列表/详情 API
├── scraper/                 # 推文抓取模块
│   ├── client.py            # TwitterAPI.io 客户端（含引用推文预处理）
│   ├── parser.py            # 推文解析器
│   ├── validator.py         # 数据验证器（MAX_TEXT_LENGTH=25000）
│   ├── circuit_breaker.py   # 轻量级熔断器（CLOSED→OPEN→HALF_OPEN，5 次失败触发，60s 恢复）
│   ├── scraping_service.py  # 抓取编排服务（含自动摘要触发）
│   ├── scheduled_job.py     # 定时抓取任务函数（供 main.py 和 schedule_service 共用）
│   ├── scheduler_listener.py # APScheduler 事件监听器（EXECUTED/ERROR/MISSED → DB + Prometheus）
│   ├── task_registry.py     # 异步任务注册表（含任务历史持久化到 TaskExecutionLog）
│   ├── domain/
│   │   ├── models.py        # 领域模型（Tweet, Media, ArticlePreview, Article, SaveResult）
│   │   ├── fetch_stats.py   # 抓取统计领域模型（FetchStats）
│   │   └── scheduler_log.py # 调度器执行日志领域模型（SchedulerEventType, SchedulerExecutionLog）
│   ├── infrastructure/
│   │   ├── models.py        # ORM 模型（TweetOrm）
│   │   ├── repository.py    # 推文数据仓库
│   │   ├── fetch_stats_models.py     # FetchStatsOrm
│   │   ├── fetch_stats_repository.py # 抓取统计仓库
│   │   ├── scheduler_log_models.py     # SchedulerExecutionLogOrm
│   │   └── scheduler_log_repository.py # 调度器日志仓库（同步写入 + 异步查询）
│   └── services/
│       └── limit_calculator.py  # 动态抓取数量计算（EMA 算法）
├── cli/                     # CLI 命令模块
│   ├── __init__.py
│   ├── main.py              # click Group 入口（init/validate/serve/mcp/export/import-data）
│   ├── init_command.py      # x-watcher init 实现
│   ├── validate_command.py  # x-watcher validate 实现
│   └── sync_command.py      # x-watcher export / import-data 实现
├── mcp/                     # MCP (Model Context Protocol) 服务模块
│   ├── __init__.py
│   ├── server.py            # FastMCP 实例创建、工具/资源注册、run_mcp_server() 入口
│   ├── lifespan.py          # 轻量级 DB 初始化 + MCP 日志配置（不启动调度器和摘要队列）
│   ├── auth.py              # MCP 认证上下文（stdio=admin，SSE=API Key 验证）
│   ├── token_verifier.py    # MCP Token 验证器（ADMIN_API_KEY + 数据库 API Key 双层验证）
│   ├── security.py          # 审计日志 + Action Guard 操作白名单（环境变量控制可执行操作）
│   ├── helpers.py           # 结构化 JSON 响应工具（success_response / error_response）
│   ├── tools/               # MCP 工具（22 个）
│   │   ├── feed_tools.py    # get_feed, search_tweets
│   │   ├── browse_tools.py  # get_daily_stats, get_authors_for_date, browse_tweets
│   │   ├── status_tools.py  # get_system_status, get_audit_log
│   │   ├── topic_tools.py   # list_topics, get_topic, manage_topic, manage_topic_accounts, get_topic_summary
│   │   ├── analytics_tools.py  # get_posting_frequency
│   │   ├── admin_tools.py   # manage_follows, trigger_scrape, trigger_backfill, get_task_status, manage_scheduler, batch_summarize, get_follow_accounts_info
│   │   └── summarization_tools.py  # get_unsummarized_tweets, save_summaries（Claude Code 翻译接管）
│   └── resources/           # MCP 动态资源（6 个）
│       ├── providers.py     # xwatcher://status, xwatcher://follows, xwatcher://topics, xwatcher://config
│       └── recipes.py       # xwatcher://recipes/daily-summary, xwatcher://recipes/claude-code-summarize
├── summarization/           # AI 摘要模块
│   ├── domain/models.py     # 领域模型
│   ├── infrastructure/
│   │   ├── models.py        # ORM 模型
│   │   └── repository.py    # 仓库
│   ├── services/
│   │   ├── summarization_service.py
│   │   └── summarization_queue.py  # 集中式摘要任务队列（PriorityQueue + 单 worker）
│   ├── llm/                 # LLM 集成（统一 OpenAI 兼容架构）
│   │   ├── base.py          # 抽象基类
│   │   ├── config.py        # LLM 配置（新旧格式兼容）
│   │   ├── presets.py       # Provider 预设配置（6+ 提供商）
│   │   └── openai_compatible.py  # 通用 OpenAI 兼容 Provider
│   └── api/
│       ├── routes.py        # API 端点
│       └── schemas.py       # 请求/响应模型
├── preference/              # 抓取配置与调度管理模块
│   ├── domain/
│   │   ├── models.py        # 领域模型
│   │   └── validators.py    # 验证逻辑
│   ├── infrastructure/
│   │   ├── scraper_config_repository.py
│   │   ├── schedule_repository.py   # 调度配置仓库（singleton 单行模式）
│   │   └── x_user_profile_repository.py  # X 用户档案仓库（upsert/查询，按 platform_user_id 主键）
│   ├── services/
│   │   ├── scraper_config_service.py
│   │   └── schedule_service.py      # 调度配置业务服务（含启用/暂停、惰性 job 创建、独立 session 重试）
│   └── api/
│       ├── routes.py        # 路由导出
│       ├── auth.py          # API Key 认证
│       ├── schemas.py       # 请求/响应模型
│       └── scraper_config_router.py  # 管理员抓取配置 + 调度管理（含 enable/disable）+ 账号运行时统计（follows/stats）+ 用户档案管理（profiles CRUD + 手动同步）+ 公共只读 API
├── user/                    # 用户管理与认证模块
│   ├── api/
│   │   ├── auth.py          # JWT + API Key 统一认证依赖
│   │   ├── auth_router.py   # POST /api/auth/login
│   │   ├── user_router.py   # 用户资料、API Key 管理
│   │   └── admin_user_router.py  # 管理员创建/管理/编辑用户
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
├── topic/                   # 主题管理模块（多账号聚合分析，支持多用户所有权）
│   ├── domain/
│   │   └── models.py        # 领域模型（TopicDomain, TopicSummaryTaskDomain, TopicSummaryTaskStatus）
│   ├── infrastructure/
│   │   ├── models.py        # ORM 模型（TopicOrm, TopicAccountOrm, TopicSummaryTaskOrm, TopicSummaryOrm）
│   │   └── repository.py    # TopicRepository + TopicSummaryTaskRepository（支持 user_id 过滤）
│   ├── services/
│   │   ├── topic_service.py           # 主题 CRUD + 账号管理（per-user 所有权）
│   │   └── topic_summary_service.py   # 摘要任务异步执行（LLM 聚合摘要）
│   └── api/
│       ├── routes.py        # 主题 CRUD + 账号管理 + 摘要任务 API 端点（含所有权检查）
│       └── schemas.py       # 请求/响应模型
├── browse/                  # 推文浏览模块（按日期/作者维度浏览）
│   ├── api/
│   │   ├── routes.py        # GET /api/browse/stats/daily, /authors, /tweets
│   │   └── schemas.py       # DailyStatsResponse, AuthorListResponse, BrowseTweetListResponse
│   └── services/
│       └── browse_service.py  # 每日统计、作者列表、推文列表查询
├── search/                  # 推文搜索模块（多字段关键词搜索）
│   ├── api/
│   │   ├── routes.py        # GET /api/search/tweets
│   │   └── schemas.py       # SearchTweetItem, SearchResponse
│   └── services/
│       └── search_service.py  # 多字段搜索（正文、摘要、翻译、引用推文）
├── analytics/               # 分析模块（聚类分析 + 发文频次统计）
│   ├── domain/
│   │   └── models.py        # 领域模型（ClusteringRunDomain, ClusterAssignmentDomain, AccountDistribution）
│   ├── infrastructure/
│   │   ├── models.py        # ORM 模型（ClusteringRunOrm, ClusterAssignmentOrm）
│   │   └── repository.py    # ClusteringRepository
│   ├── services/
│   │   ├── feature_engineering.py  # 24 维小时分布向量构建
│   │   ├── clustering_service.py   # 层次聚类（JSD + average linkage）
│   │   └── analytics_service.py    # 主题发文频次分布查询（30分钟时段聚合）
│   └── api/
│       ├── routes.py        # /api/admin/analytics/* 端点（分布预览、聚类运行、重切割、手动调整、发文频次）
│       └── schemas.py       # 请求/响应模型
├── sync/                    # 数据同步模块（跨服务器 JSON 导出/导入）
│   ├── domain/
│   │   └── models.py        # 领域模型（SyncCategory, ConflictStrategy, ExportPackage, ImportResult）
│   ├── services/
│   │   ├── export_service.py  # 导出编排（repository → serializer → ExportPackage）
│   │   └── import_service.py  # 导入编排（验证 → 冲突策略 → per-category 事务写入）
│   ├── infrastructure/
│   │   ├── serializers.py     # ORM ↔ dict 转换（每张表一对 to_dict / from_dict）
│   │   ├── export_repository.py  # 同步读取各表数据（支持 since/until/authors 过滤）
│   │   └── import_repository.py  # 批量写入 + 冲突检测 + Topics 嵌套 ID 重映射
│   └── format/
│       └── json_format.py   # JSON 文件读写 + schema 版本校验
├── monitoring/              # Prometheus 监控
│   ├── metrics.py           # 指标定义
│   ├── middleware.py         # 中间件
│   └── routes.py            # /metrics 端点
├── shared/                  # 公共基础设施
│   └── schemas.py           # UTCDatetimeModel 公共基类（SQLite naive datetime → UTC 序列化）
├── database/                # 数据库层
│   ├── models.py            # SQLAlchemy 基础模型（User, ScraperScheduleConfig, TaskExecutionLog, AuditLog 等）
│   ├── x_user_profile_model.py  # X 用户档案 ORM 模型（x_user_profiles 表，缓存 TwitterAPI.io 用户信息）
│   └── async_session.py     # 异步会话管理（WAL 模式 + busy_timeout）
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
├── summarization/      # 摘要模块测试
├── preference/         # 抓取配置与调度模块测试（含公共只读端点测试）
├── user/               # 用户认证测试
├── feed/               # Feed API 测试
├── search/             # 搜索 API 测试
├── analytics/          # 分析模块测试（聚类 + 统计）
├── mcp/                # MCP 工具单元测试
├── sync/               # 数据同步模块测试（导出/导入 + CLI 端到端）
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

### 当前阶段：API + Service + MCP 三层驱动
- FastAPI 路由直接调用 Service 层（RESTful API）
- MCP Server 直接调用 Service 层（Model Context Protocol，20 工具 + 5 资源）
- Service 层编排业务逻辑（抓取、摘要、主题管理）
- 统一 LLM Provider 架构：通用 OpenAI 兼容协议，支持 6+ 提供商
- CLI 工具（click）：init / validate / serve / mcp / export / import-data 命令

### 未来扩展方向
- Webhook 推送：主动通知下游消费者
- 多数据源：扩展到 Newsletter、RSS 等

---
_记录模式，而非文件树。遵循模式的新文件不需要更新此文档_
