# Research & Design Decisions Template

---

**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

---

## Summary
- **Feature**: `news-scraper`
- **Discovery Scope**: New Feature
- **Key Findings**:
  - TwitterAPI.io 支持 Bearer Token 认证，无需 OAuth 复杂流程
  - X 平台 API v2 响应格式明确，Tweet 对象包含所有必需字段
  - APScheduler 与 FastAPI 集成需要使用 lifespan 管理避免多进程重复触发
  - Twitter 数据模型应支持推文、引用和转发的统一存储

## Research Log
Document notable investigation steps and their outcomes. Group entries by topic for readability.

### Twitter/X API 数据结构
- **Context**: 需要了解 X 平台 API v2 返回的 Tweet 数据结构，以便设计解析逻辑
- **Sources Consulted**:
  - [Data Dictionary - X Developer Platform](https://docs.x.com/x-api/fundamentals/data-dictionary)
  - [Fetch Tweets Using Twitter API Step by Step Guide](https://qodex.ai/blog/fetch-tweets-using-twitter-api)
- **Findings**:
  - Tweet 对象核心字段：`id`, `text`, `created_at`, `author_id`
  - 引用推文：`referenced_tweets` 数组，包含 `type` (retweeted/quoted/replied_to) 和 `id`
  - 媒体附件：`attachments` 对象，包含 `media_keys` 可关联到 `includes.media`
  - API v2 原生支持 280 字符，无 extended tweet 概念
  - 用户信息在 `includes.users` 中，需通过 `author_id` 关联
- **Implications**:
  - 需要设计 Pydantic 模型映射 API 响应结构
  - 解析逻辑需要处理 includes 中的关联数据（用户、媒体）
  - 引用/转发关系需要单独字段存储

### TwitterAPI.io 服务商集成
- **Context**: 验证 TwitterAPI.io 的认证方式、速率限制和 API 格式兼容性
- **Sources Consulted**:
  - [twitterapi.io 官方文档](https://docs.twitterapi.io/)
  - [Twitter API Rate Limits vs Alternative Solutions Compared](https://twitterapi.io/articles/twitter-api-rate-limits-vs-alternative-solutions)
  - [Understanding Twitter API Rate Limits: A Developer's Guide](https://twitterapi.io/blog/understanding-twitter-api-rate-limits)
- **Findings**:
  - 认证：支持 Bearer Token（推荐）和 API Key/Secret
  - 速率限制：1000+ req/sec（远高于官方 API 的 300 req/15min）
  - 成本：$0.15/1K 请求，100K 免费额度
  - 响应格式：与 X 平台官方 API v2 兼容
  - 无需 OAuth 认证流程，配置简单
- **Implications**:
  - 优先使用 Bearer Token 认证
  - 不需要复杂的 OAuth 流程实现
  - 速率限制宽松，不需要严格的配额管理
  - 错误处理仍需考虑 429（配额耗尽）场景

### APScheduler 与 FastAPI 集成
- **Context**: 确保定时任务在 FastAPI 应用中正确启动和停止，避免多进程重复触发
- **Sources Consulted**:
  - [FastAPI + APScheduler：异步定时任务调度器完全指南](https://www.51cto.com/article/814943.html)
  - [避免FastAPI 多进程环境下ApScheduler 定时任务重复触发](https://juejin.cn/post/7350143919788916762)
  - [Python基于Fastapi与APScheduler的应用定时任务](https://developer.aliyun.com/article/1684916)
- **Findings**:
  - 必须使用 FastAPI 的 `lifespan` 上下文管理器启动/停止调度器
  - 多进程部署（如 Gunicorn + Uvicorn workers）会导致任务重复触发
  - 解决方案：使用 `BackgroundScheduler` 或数据库锁确保单实例运行
  - 异步任务检测：使用 `asyncio.iscoroutinefunction()` 判断任务类型
  - 持久化：可配置 SQLAlchemy JobStore 实现任务持久化
- **Implications**:
  - 设计中必须包含 lifespan 管理
  - 使用 `BackgroundScheduler` 而非 `AsyncScheduler`（简化配置）
  - 添加 `max_instances=1` 防止任务重叠执行
  - 提供环境变量控制是否启用调度器（便于开发调试）

### Twitter 数据库模型设计
- **Context**: 设计高效的数据库模型存储推文、用户和关联关系
- **Sources Consulted**:
  - [How to Design a Database for Twitter](https://www.geeksforgeeks.org/dbms/how-to-design-a-database-for-twitter/)
  - [How to implement Twitter tweet, reply and retweet database schema](https://stackoverflow.com/questions/questions/64637105/how-to-implement-twitter-tweet-reply-and-retweet-database-schema-without-empty)
  - [System Design Primer - Twitter](https://github.com/donnemartin/system-design-primer/blob/master/solutions/system_design/twitter/README.md)
- **Findings**:
  - 核心表：`tweets`, `users`, `media`
  - Tweets 表应包含：`tweet_id` (主键), `text`, `created_at`, `author_id`, `referenced_tweet_id`, `reference_type`
  - 引用/转发统一处理：使用 `referenced_tweet_id` 和 `reference_type` 字段
  - 去重：`tweet_id` 添加 `UNIQUE` 约束
  - 索引：`author_id`, `created_at` (DESC) 用于查询优化
- **Implications**:
  - 设计 `Tweet` 模型包含 `referenced_tweet_id` (外键) 和 `reference_type` 枚举
  - 使用 `tweet_id` 作为字符串主键（兼容 X 平台的 snowflake ID）
  - 添加复合索引 `(author_id, created_at DESC)` 提升查询性能
  - 用户信息可简化存储（不需要完整的 Users 表，仅存储作者信息）

## Architecture Pattern Evaluation
| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 分层架构 | API → Service → Repository → Database | 清晰的职责分离，易于测试和扩展 | 层次较多可能增加简单操作的复杂度 | 符合现有 steering 原则 |
| 单层脚本 | 直接在 API 路由中调用抓取逻辑 | 简单直接，代码少 | 难以测试，逻辑耦合，无法复用 | 不符合项目规范 |
| 事件驱动 | 抓取完成后发布事件，其他组件消费 | 松耦合，易于扩展（如添加通知） | 增加复杂度，需要消息队列 | 当前阶段过度设计 |

**选择**: 分层架构（与现有项目结构对齐）

## Design Decisions
Record major decisions that influence `design.md`. Focus on choices with significant trade-offs.

### Decision: TwitterAPI.io 作为唯一数据源
- **Context**: 需求 5.5 要求支持 TwitterAPI.io 服务商格式
- **Alternatives Considered**:
  1. 抽象层设计（支持多个服务商切换） - 增加复杂度，当前不需要
  2. 仅支持 TwitterAPI.io - 简单直接，满足当前需求
- **Selected Approach**: 硬编码 TwitterAPI.io 客户端，不实现抽象层
- **Rationale**: 用户明确表示切换服务商不是核心需求，遵循 YAGNI 原则
- **Trade-offs**: 牺牲灵活性换取简单性
- **Follow-up**: 未来如需支持其他服务商，可重构引入抽象层

### Decision: 推文与引用推文分离存储 vs 统一存储
- **Context**: 需要存储推文及其引用/转发关系
- **Alternatives Considered**:
  1. 分离存储 - tweets 和 referenced_tweets 两张表
  2. 统一存储 - 单张 tweets 表，用 referenced_tweet_id 关联
- **Selected Approach**: 统一存储在 `tweets` 表
- **Rationale**: 简化查询逻辑，引用推文本身也是推文，无需区分
- **Trade-offs**: 查询引用推文需要 JOIN 或二次查询
- **Follow-up**: 监控查询性能，必要时添加缓存

### Decision: 同步 vs 异步 HTTP 客户端
- **Context**: 需要调用 TwitterAPI.io 的 HTTP 接口
- **Alternatives Considered**:
  1. `httpx` 异步客户端 - 与 FastAPI 完美集成，性能高
  2. `requests` 同步客户端 - 简单稳定，但阻塞事件循环
- **Selected Approach**: 使用 `httpx` 异步客户端
- **Rationale**: FastAPI 是异步框架，使用同步客户端会阻塞事件循环
- **Trade-offs**: 异步代码复杂度略高，但性能收益明显
- **Follow-up**: 确保所有抓取函数都是 async 函数

### Decision: 定时任务是否持久化
- **Context**: APScheduler 支持内存和数据库持久化两种模式
- **Alternatives Considered**:
  1. 内存存储 - 简单，但重启丢失任务状态
  2. 数据库持久化 - 状态可恢复，但增加复杂度
- **Selected Approach**: 内存存储（默认配置）
- **Rationale**: 定时任务是固定的（每小时抓取），不需要动态管理
- **Trade-offs**: 应用重启后无法恢复任务执行历史
- **Follow-up**: 如需任务历史记录，可添加执行日志表

## Risks & Mitigations
- **TwitterAPI.io 服务稳定性** - 添加官方 API 作为备用选项（未来考虑）
- **多进程重复抓取** - 使用 `max_instances=1` 和数据库锁（需求 4.5）
- **API 速率限制误触发** - 实现指数退避重试，监控 429 错误
- **数据解析失败** - 使用 Pydantic 验证，跳过无效数据并记录日志
- **定时任务冲突** - 添加任务执行状态标记，防止并发执行

## References
Provide canonical links and citations (official docs, standards, ADRs, internal guidelines).
- [Data Dictionary - X Developer Platform](https://docs.x.com/x-api/fundamentals/data-dictionary) — Twitter API v2 完整数据字典
- [TwitterAPI.io Documentation](https://docs.twitterapi.io/) — TwitterAPI.io 官方文档
- [FastAPI + APScheduler 完全指南](https://www.51cto.com/article/814943.html) — FastAPI 集成最佳实践
- [How to Design a Database for Twitter](https://www.geeksforgeeks.org/dbms/how-to-design-a-database-for-twitter/) — Twitter 数据库设计参考
