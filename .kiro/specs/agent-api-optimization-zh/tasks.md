# 面向 Agent 的 API 优化 — 实现计划

## 概述

X-watcher 当前 API（60+ 端点）在管理和配置维度非常完善，但从 Agent 作为主要消费者的角度存在多个缺口。本计划将缺口按优先级分为 4 个阶段，共 11 个功能改进项，每项可独立交付。

> **评分现状**：综合 4.4/5 — 功能完整性 5/5、Agent 友好度 4/5、查询灵活性 4/5、批量操作支持 3/5

---

## Phase 1 — 高优先级：Agent 核心体验提升

### 1. 推文搜索 API

Agent 经常需要"查找提到某个话题的推文"，但目前只能按日期/作者筛选，无关键词搜索能力。

- [x] 1.1 创建 search 模块基础结构
  - 创建 `src/search/` 模块目录，包含 `api/`、`services/` 子目录和 `__init__.py`
  - 在 `src/search/api/schemas.py` 中定义请求参数和响应模型：
    - `SearchTweetItem`（复用 `FeedTweetItem` 字段结构，含 summary_text、translation_text）
    - `SearchResponse`（items、count、total、page、page_size、total_pages、query 元数据）
  - 在 `src/search/api/routes.py` 中创建 `GET /api/search/tweets` 端点
    - 查询参数：`q`（必填关键词）、`author`（可选单作者）、`authors`（可选逗号分隔多作者）、`since`（可选起始时间）、`until`（可选截止时间）、`page`（默认 1）、`page_size`（默认 20，最大 100）、`include_summary`（默认 true）
  - 使用 `get_current_user` 认证（用户级）

- [x] 1.2 实现 SearchService 搜索查询逻辑
  - 在 `src/search/services/search_service.py` 中实现 `SearchService`
  - 构建 SQLAlchemy 查询：对 `TweetOrm.text` 使用 `LIKE '%keyword%'` 进行关键词匹配（SQLite 兼容）
  - 同时搜索 `TweetOrm.referenced_tweet_text`（被引用推文内容）
  - 支持 `SummaryOrm.summary_text` 和 `SummaryOrm.translation_text` 的关键词搜索（LEFT JOIN）
  - 支持多关键词空格分隔（AND 逻辑）
  - 支持 `author` / `authors` 筛选（`func.lower()` 大小写不敏感）
  - 支持 `since` / `until` 时间范围筛选
  - 分页（page + page_size），按 `created_at` 倒序排列
  - 参考 `BrowseService.get_tweets()` 的 LEFT JOIN 和 COUNT 查询模式

- [x] 1.3 注册搜索路由
  - 在 `src/main.py` 中注册 search 模块路由

- [x] 1.4 编写搜索 API 测试
  - 在 `tests/search/` 目录下创建测试文件
  - SearchService 单元测试：关键词匹配、多关键词 AND、作者筛选、时间范围、分页、空结果
  - API 集成测试：完整调用链、认证验证、参数验证（缺少 q 返回 422）、响应格式

---

### 2. 批量关注操作 API

当前逐条添加/删除关注，Agent 批量初始化或调整监控列表效率低。

- [x] 2.1 定义批量操作请求/响应模型
  - 在 `src/preference/api/schemas.py` 中添加：
    - `BatchFollowRequest`：`usernames: list[str]`（1-100 个用户名），复用现有用户名验证器
    - `BatchFollowResponse`：`succeeded: list[str]`、`failed: list[BatchFollowError]`、`total`、`succeeded_count`、`failed_count`
    - `BatchFollowError`：`username: str`、`reason: str`

- [x] 2.2 在 PreferenceService 中实现批量添加/删除逻辑
  - 在 `src/preference/services/preference_service.py` 中添加 `batch_add_follows` 和 `batch_remove_follows` 方法
  - 逐条处理，每条独立 try/catch，确保部分失败不影响其余操作
  - 批量添加时复用 `add_follow` 的验证逻辑（检查 scraper_follows 存在性）
  - 返回成功/失败列表，包含每个失败项的原因（不在抓取列表、已存在、不存在等）

- [x] 2.3 实现批量关注 API 端点
  - 在 `src/preference/api/preference_router.py` 中添加：
    - `POST /api/preferences/follows/batch` — 批量添加关注
    - `DELETE /api/preferences/follows/batch` — 批量删除关注（请求体携带 usernames 列表）
  - 使用 `get_current_user` 认证
  - 返回 200（部分成功也算成功）+ 详细的成功/失败清单

- [x] 2.4 编写批量关注 API 测试
  - 测试批量添加正常流程（多个用户名全部成功）
  - 测试批量添加部分失败（部分不在抓取列表、部分已存在）
  - 测试批量删除正常流程和部分失败
  - 测试边界：空列表 422、超过 100 个 422
  - 测试认证验证

---

### 3. Feed API 增强过滤

当前 Feed 只有时间范围过滤（since/until/limit/include_summary），Agent 可能只关心特定作者或话题的动态。

- [x] 3.1 扩展 Feed API 查询参数
  - 在 `src/feed/api/routes.py` 的 `get_feed` 端点中添加可选查询参数：
    - `author: str | None`（单作者筛选）
    - `authors: str | None`（逗号分隔的多作者筛选）
    - `keyword: str | None`（关键词过滤，搜索 text + summary_text + translation_text）
  - 在 `src/feed/api/schemas.py` 中更新 `FeedResponse`，添加筛选条件元数据

- [x] 3.2 扩展 FeedService 支持多维过滤
  - 在 `src/feed/services/feed_service.py` 的 `get_feed` 方法中添加 `author`、`authors`、`keyword` 参数
  - author/authors 筛选使用 `func.lower()` 大小写不敏感匹配
  - keyword 筛选使用 LIKE 匹配 `TweetOrm.text`；当 `include_summary=True` 时同时搜索摘要和翻译
  - author 和 authors 互斥，同时提供时返回 422
  - COUNT 和数据查询均需应用新的过滤条件

- [x] 3.3 编写 Feed 增强过滤测试
  - 扩展 `tests/feed/` 下的测试文件
  - 测试按 author 筛选、按 authors 多选筛选、按 keyword 筛选、组合筛选
  - 测试 author 和 authors 互斥验证
  - 测试关键词匹配推文正文 + 摘要 + 翻译
  - 测试大小写不敏感的作者匹配

---

### 4. ~~Webhook 事件推送系统~~ [归档：MCP stdio + recipes 已覆盖 Agent 主动获取场景，Webhook 推送需求未被验证]

Agent 只能轮询 Feed/任务状态，无法被动接收通知。当有重要内容时无法主动推送。

- [ ] ~~4.1 设计 Webhook 数据模型和存储~~
  - 创建 `src/webhook/` 模块目录结构（`api/`、`services/`、`domain/`、`infrastructure/`）
  - 定义 ORM 模型：
    - `WebhookSubscriptionOrm`：id、user_id、url、secret（HMAC 签名密钥）、event_types（JSON 数组）、is_active、created_at、updated_at
    - `WebhookDeliveryLogOrm`：id、subscription_id、event_type、payload（JSON）、status_code、response_body（截断）、delivered_at、next_retry_at、retry_count
  - 创建 Alembic 数据库迁移
  - 定义事件类型枚举：`new_tweets`、`summary_completed`、`scrape_completed`、`topic_summary_completed`

- [ ] ~~4.2 实现 WebhookService 订阅管理和事件分发~~
  - 在 `src/webhook/services/webhook_service.py` 中实现：
    - 订阅管理：注册、列表、更新、删除、启用/禁用
    - 事件分发：接收事件 → 查找匹配订阅 → 异步 POST 投递（httpx）
    - HMAC-SHA256 签名：使用订阅的 secret 对 payload 签名，放入 `X-Webhook-Signature` 请求头
    - 指数退避重试：失败后 30s、2min、10min 重试，最多 3 次
    - 投递日志记录
  - 使用 `asyncio.create_task` 非阻塞投递，不影响主流程

- [ ] ~~4.3 实现 Webhook API 端点~~
  - 在 `src/webhook/api/routes.py` 中创建端点：
    - `POST /api/webhooks` — 注册 Webhook
    - `GET /api/webhooks` — 列出当前用户的所有 Webhook
    - `PUT /api/webhooks/{webhook_id}` — 更新 Webhook 配置
    - `DELETE /api/webhooks/{webhook_id}` — 删除 Webhook
    - `GET /api/webhooks/{webhook_id}/deliveries` — 查看投递日志（分页）
    - `POST /api/webhooks/{webhook_id}/test` — 发送测试事件
  - 使用 `get_current_user` 认证
  - 在 `src/main.py` 中注册路由

- [ ] ~~4.4 在现有服务中集成事件触发点~~
  - 实现内存事件总线（发布/订阅模式），避免服务间直接耦合
  - 在 `ScrapingService` 中抓取完成后触发 `scrape_completed` 和 `new_tweets` 事件
  - 在 `SummarizationQueue` 中摘要完成后触发 `summary_completed` 事件
  - 在 `TopicSummaryService` 中主题摘要完成后触发 `topic_summary_completed` 事件

- [ ] ~~4.5 编写 Webhook 测试~~
  - 单元测试：订阅 CRUD、事件匹配、HMAC 签名计算
  - 集成测试：API 端点完整流程、测试事件投递（mock httpx）、重试逻辑
  - 测试认证：用户只能管理自己的 Webhook

---

## Phase 2 — 中优先级：数据消费效率提升

### 5. ~~数据导出 API~~ [归档：src/sync/ ���块的 export 功能已覆盖此需求]

Agent 可能需要将数据导入其他系统或生成报告，目前无批量导出能力。

- [ ] ~~5.1 实现 Feed 导出端点~~
  - 在 `src/feed/api/routes.py` 中添加 `GET /api/feed/export` 端点
  - 支持查询参数：`format`（markdown / json / csv，默认 markdown）、`since`（必填）、`until`（可选）、`author`（可选）、`authors`（可选）、`keyword`（可选）、`include_summary`（默认 true）
  - Markdown 格式：按作者分组，每条推文含时间、正文、摘要、翻译
  - JSON 格式：与 Feed API 相同的结构化输出（无 limit 限制）
  - CSV 格式：扁平化表格（tweet_id、author、created_at、text、summary、translation）
  - 使用 `StreamingResponse` 流式输出，避免大数据量 OOM
  - 设置 `Content-Disposition` 头触发下载，硬上限 10000 条
  - 复用 `FeedService` 的查询逻辑
  - 使用 `get_current_user` 认证

- [ ] ~~5.2 编写导出 API 测试~~
  - 测试 Markdown / JSON / CSV 三种格式输出
  - 测试筛选条件传递（author、keyword）
  - 测试认证和参数验证

---

### 6. 主题摘要快捷接口

当前主题摘要偏管理操作（创建任务→等待→查详情），Agent 需要一步到位获取结果。

- [x] 6.1 实现最新摘要快捷查询
  - 在 `src/topic/api/routes.py` 中添加 `GET /api/topics/{topic_id}/latest-summary` 端点
  - 在 `TopicSummaryService` 中添加 `get_latest_summary` 方法：查询指定主题最近一次 `completed` 状态的摘要任务及其结果
  - 响应直接返回：摘要内容 + 元数据（生成时间、覆盖时段、推文数、账号数）
  - 主题不存在返回 404，无已完成摘要返回 404 并说明原因
  - 使用 `get_current_user` 认证（降低访问门槛）

- [x] 6.2 编写最新摘要快捷接口测试
  - 测试正常返回最新摘要
  - 测试主题不存在 404、无已完成摘要 404
  - 测试多个已完成摘要时返回最新的

---

### 7. 系统状态概览 API

Agent 需要快速了解系统健康状况和数据时效性，当前只有低级的 /health 端点。

- [x] 7.1 实现系统状态概览端点
  - 在 `src/api/routes/` 下创建 `status.py`，实现 `GET /api/status/overview` 端点
  - 聚合返回：
    - `tweets`：总数、最新推文时间、今日新增数
    - `follows`：抓取账号总数（活跃/非活跃）
    - `summaries`：总数、待摘要推文数
    - `topics`：主题总数、最近一次主题摘要的时间和状态
    - `scheduler`：调度器状态（running/stopped）、下次抓取时间、抓取间隔
    - `system`：服务启动时间、数据库大小（SQLite 文件大小）
  - 使用 `get_current_user` 认证
  - 在 `src/main.py` 中注册路由

- [x] 7.2 编写系统状态概览测试
  - 测试响应结构完整性
  - 测试各统计数字正确性
  - 测试认证验证

---

### 8. ~~实时事件流��SSE）~~ [归档：MCP stdio 模式已提供 Agent 实时交互能力，SSE 需求不强]

长时间任务（抓取、摘要）缺���实时进度反馈，Agent 只能轮询 task 端点。

- [ ] ~~8.1 实现 SSE 事件流端点~~
  - 在 `src/api/routes/` 下创建 `events.py`，实现 `GET /api/events/stream` 端点
  - 使用 `StreamingResponse` + `text/event-stream` Content-Type
  - 支持事件类型筛选查询参数：`event_types`（逗号分隔）
  - 实现内存事件总线（`asyncio.Queue` 每连接一个）+ 发布/订阅
  - 事件类型：`scrape_progress`、`summary_progress`、`task_status_change`
  - 心跳：每 30 秒发送 `:keepalive` 注释行
  - 连接断开时自动清理队列
  - 使用 `get_current_user` 认证（通过查询参数传递 api_key）
  - 与 Webhook（任务 4）共享事件总线

- [ ] ~~8.2 在现有服务中集成事件发布~~
  - 在 `ScrapingService` 中发布抓取进度事件（开始、每批完成、结束）
  - 在 `SummarizationQueue` 中发布摘要队列进度事件
  - 在 `TaskRegistry` 中任务状态变更时发布事件

- [ ] ~~8.3 编写 SSE 测试~~
  - 测试 SSE 连接建立和心跳
  - 测试事件类型筛选
  - 测试事件数据格式（符合 SSE 规范）
  - 测试连接断开清理

---

## Phase 3 — 低优先级：数据质量闭环

### 9. ~~去重结果浏览 API~~ [删除：去重功能已被 commit e77222e 完全移除]

当前缺少"哪些推文被去重了"的概览能力，不利于质量监控。

- ~~[x] 9.1 实现去重结果按日期浏览端点~~
  - 在 `src/deduplication/api/routes.py` 中添加：
    - `GET /api/deduplicate/groups` — 列出去重组，支持 `date`（YYYY-MM-DD）、`page`、`page_size` 参数
    - `GET /api/deduplicate/stats/daily` — 按月查询每日去重统计（参考 `BrowseService.get_daily_stats` 模式）
  - 返回每个去重组的组内推文数量、去重类型、代表推文摘要等信息
  - 使用 `get_current_admin_user` 认证

- ~~[x] 9.2 编写去重浏览测试~~
  - 测试按日期筛选去重组列表
  - 测试分页
  - 测试每日统计

---

### 10. ~~推文反馈/标注 API~~ [暂挂：有潜在价值但当前无明确需求信号，待需求验证后按 SDD 流程启动新 spec]

Agent 无法标记推文的重要性或反馈摘要质量，不利于未来持续改进。

- [ ] ~~10.1 设计反馈数据模型~~
  - 创建 `src/feedback/` 模块目录结构
  - 定义 ORM 模型 `TweetFeedbackOrm`：id、user_id、tweet_id、feedback_type（important / irrelevant / bad_summary）、comment（可选文本）、created_at
  - 创建 Alembic 数据库迁移
  - 设置 (user_id, tweet_id, feedback_type) 复合唯一约束

- [ ] ~~10.2 实现反馈 API 端点~~
  - 在 `src/feedback/api/routes.py` 中创建：
    - `POST /api/feedback/tweets/{tweet_id}` — 提交反馈（feedback_type + 可选 comment）
    - `GET /api/feedback/tweets/{tweet_id}` — 查询某推文的反馈
    - `DELETE /api/feedback/tweets/{tweet_id}/{feedback_type}` — 撤销反馈
    - `GET /api/feedback/summary` — 反馈统计概览（按类型汇总）
  - 使用 `get_current_user` 认证
  - 在 `src/main.py` 中注册路由

- [ ] ~~10.3 编写反馈 API 测试~~
  - 测试提交、查询、撤销反馈完整流程
  - 测试重复提交同类型反馈返回 409
  - 测试统计接口正确性

---

## Phase 4 — 收尾：文档与集成验证

### 11. ~~文档更新与集成验证~~ [删除：steering 文档已于 2026-03-30 同步更新]

- [x] ~~11.1 更新项目文档~~
  - 更新 `.kiro/steering/product.md`，添加新增核心能力描述（搜索、批量操作、Webhook、导出、SSE、反馈）
  - 更新 `.kiro/steering/structure.md`，添加新模块（search、webhook、feedback）目录结构
  - 更新 `.kiro/steering/tech.md`，记录新增技术决策（事件总线、SSE、Webhook 签名等）

- [ ] ~~11.2 运行全量测试确保无回归~~
  - 运行 pytest 全量测试套件
  - 验证现有 Feed、Preference、Topic、Browse 模块未受影响

---

## 设计决策速查

| 决策 | 选择 | 理由 |
|------|------|------|
| 搜索模块位置 | 独立 `src/search/` | 查询模式（多字段 LIKE + OR）与 Feed 增量拉取差异大 |
| 批量关注位置 | 扩展现有 preference 模块 | 复用已有验证逻辑和 service |
| Feed 增强方式 | 扩展现有端点参数 | Agent 无需学习新端点，向后兼容 |
| 事件系统架构 | 内存事件总线 + Webhook/SSE 双消费 | 避免在各 service 中硬编码投递逻辑 |
| 新端点认证策略 | 优先 `get_current_user` | 降低 Agent 访问门槛，管理类操作保持 admin |
| 搜索引擎 | SQLite LIKE | 当前数据规模够用，未来可升级 PostgreSQL 全文搜索 |

## 关键文件索引

| 改进项 | 主要修改文件 |
|--------|-------------|
| 搜索 API | `src/search/`（新建）、`src/main.py` |
| 批量关注 | `src/preference/api/preference_router.py`、`src/preference/services/preference_service.py` |
| Feed 增强 | `src/feed/api/routes.py`、`src/feed/services/feed_service.py` |
| Webhook | `src/webhook/`（新建）、`src/main.py`、各 service 事件触发点 |
| 数据导出 | `src/feed/api/routes.py` |
| 主题快捷 | `src/topic/api/routes.py`、`src/topic/services/topic_summary_service.py` |
| 状态概览 | `src/api/routes/status.py`（新建）、`src/main.py` |
| SSE 事件 | `src/api/routes/events.py`（新建）、`src/main.py` |
| 去重浏览 | `src/deduplication/api/routes.py` |
| 反馈标注 | `src/feedback/`（新建）、`src/main.py` |
