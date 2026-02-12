# 实现计划

- [ ] 1. 基础设施与数据模型准备
- [ ] 1.1 (P) 扩展全局配置，添加 Feed API 的数量控制配置项
  - 在 Settings 中新增 `feed_max_tweets` 字段，默认值 200，范围 1-1000
  - 在 `.env.example` 中添加对应的环境变量示例
  - _Requirements: 4.2_

- [ ] 1.2 (P) 创建 Alembic 数据库迁移，为推文入库时间字段添加索引
  - 新增迁移文件，创建 `ix_tweets_db_created_at` 索引
  - 包含 downgrade 操作以删除索引
  - 遵循项目现有迁移文件命名和结构模式
  - _Requirements: 1.1_

- [ ] 1.3 (P) 定义 Feed API 的请求参数和响应数据模型
  - 创建 `FeedTweetItem` 模型，包含推文基础字段（tweet_id, text, author_username, author_display_name, created_at, db_created_at, reference_type, referenced_tweet_id, media）和可选摘要字段（summary_text, translation_text）
  - 创建 `FeedResponse` 模型，包含 items 列表、count、total、since、until、has_more 元数据
  - 创建 `FeedResult` 内部数据类供 Service 层使用
  - _Requirements: 2.1, 3.1, 3.2, 3.3, 3.4_

- [ ] 2. Feed 查询服务实现
- [ ] 2.1 实现 FeedService 的推文+摘要联合查询逻辑
  - 实现 `get_feed` 方法：接收 since、until、limit、include_summary 参数
  - 先执行 COUNT 查询获取满足时间区间条件的总数
  - 当 include_summary 为 true 时，执行 LEFT JOIN 推文表和摘要表的联合查询，返回摘要和翻译内容
  - 当 include_summary 为 false 时，仅查询推文表，跳过 JOIN
  - 结果按推文原始发布时间倒序排列，受 limit 限制
  - 无摘要记录的推文，summary_text 和 translation_text 返回 null
  - 计算 has_more 标志（返回条数 < 总数时为 true）
  - 参考现有推文查询中的 outerjoin 模式
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.2, 2.3, 2.4, 4.1, 4.3_
  - _Contracts: FeedService Service Interface_

- [ ] 3. Feed API 路由与认证集成
- [ ] 3.1 实现 Feed API 路由端点，包含参数验证、认证和错误处理
  - 创建 `GET /api/feed` 端点，since 为必填查询参数，until/limit/include_summary 为可选
  - 集成现有用户认证中间件（get_current_user），要求 X-API-Key 请求头
  - until 未提供时使用当前服务器时间作为默认值
  - limit 未提供时使用系统配置上限；客户端提供的 limit 超过配置上限时，使用配置值替代
  - 验证 since 必须早于 until，否则返回 422 错误
  - since 缺失时由 FastAPI 自动返回 422 错误
  - 数据库查询异常时返回 500 错误并记录错误日志
  - 统一错误响应格式 `{"detail": "错误描述"}`
  - _Requirements: 1.3, 1.4, 4.2, 4.4, 5.1, 5.2, 5.3, 7.1, 7.2, 7.3, 7.4_
  - _Contracts: FeedRouter API Contract_

- [ ] 4. 系统集成与路由注册
- [ ] 4.1 将 Feed API 路由注册到应用入口并创建模块初始化文件
  - 在应用入口中注册 Feed 路由，添加路由前缀和标签，遵循现有路由注册模式
  - 创建 Feed 模块的 `__init__.py` 文件（src/feed/, src/feed/api/, src/feed/services/）
  - 验证 Feed API 端点可正常访问
  - _Requirements: 1.1, 5.1_

- [ ] 5. Agent 工具元数据定义
- [ ] 5.1 (P) 定义 Feed API 的 Agent 工具元数据并更新系统提示
  - 创建工具元数据文件，定义 `fetch_feed` 工具（描述 GET /api/feed 端点、参数、用途）
  - 定义 `fetch_tweet_detail` 工具（描述 GET /api/tweets/{tweet_id} 端点）
  - 更新 Agent 系统提示，说明可通过 Feed API 获取增量推文
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] 6. 测试覆盖
- [ ] 6.1 编写 FeedService 单元测试
  - 测试时间区间过滤正确性（since/until 边界）
  - 测试 include_summary 开关：true 时返回摘要字段，false 时不返回
  - 测试无摘要记录时字段为 null
  - 测试 limit 截断行为和 has_more 标志计算
  - 测试空结果场景
  - 复用项目现有的 async_session fixture
  - _Requirements: 1.1, 1.2, 1.5, 2.2, 2.3, 2.4, 4.1, 4.3_

- [ ] 6.2 编写 Feed API 集成测试
  - 测试完整调用链：HTTP 请求 → 认证 → 查询 → 响应格式验证
  - 测试认证失败场景：无 API Key 返回 401、无效 API Key 返回 401
  - 测试参数验证：缺少 since 返回 422、since > until 返回 422、格式错误返回 422
  - 测试 limit 钳位行为：客户端 limit 超过系统配置时使用配置值
  - 测试响应元数据：count、total、has_more、since、until 字段正确性
  - 复用项目现有的 async_client fixture
  - _Requirements: 1.4, 3.1, 3.2, 3.3, 3.4, 4.2, 4.4, 5.1, 5.2, 7.1, 7.2, 7.4_

## 需求覆盖追溯

| 需求 ID | 验收标准 | 覆盖任务 |
|---------|---------|---------|
| 1.1 | since 过滤 | 1.2, 2.1, 4.1, 6.1 |
| 1.2 | since + until 过滤 | 2.1, 6.1 |
| 1.3 | until 默认值 | 2.1, 3.1 |
| 1.4 | since 必填验证 | 3.1, 6.2 |
| 1.5 | created_at 倒序排列 | 2.1, 6.1 |
| 2.1 | 推文基础字段 | 1.3 |
| 2.2 | include_summary=true LEFT JOIN | 2.1, 6.1 |
| 2.3 | include_summary=false 不加载 | 2.1, 6.1 |
| 2.4 | 无摘要时返回 null | 2.1, 6.1 |
| 3.1 | 响应 JSON 结构 | 1.3, 6.2 |
| 3.2 | has_more=true | 1.3, 6.2 |
| 3.3 | has_more=false | 1.3, 6.2 |
| 3.4 | until 精确值返回 | 1.3, 6.2 |
| 4.1 | limit 参数 | 2.1, 6.1 |
| 4.2 | FEED_MAX_TWEETS 默认值 | 1.1, 3.1, 6.2 |
| 4.3 | limit 截断 + has_more | 2.1, 6.1 |
| 4.4 | limit 上限钳位 | 3.1, 6.2 |
| 5.1 | X-API-Key 认证 | 3.1, 4.1, 6.2 |
| 5.2 | 401 Unauthorized | 3.1, 6.2 |
| 5.3 | 复用 user/api/auth.py | 3.1 |
| 6.1 | 工具元数据定义 | 5.1 |
| 6.2 | 更新系统提示 | 5.1 |
| 6.3 | 覆盖两个端点 | 5.1 |
| 7.1 | ISO 8601 格式错误 422 | 3.1, 6.2 |
| 7.2 | since >= until 422 | 3.1, 6.2 |
| 7.3 | 数据库异常 500 | 3.1 |
| 7.4 | 统一错误格式 | 3.1, 6.2 |
