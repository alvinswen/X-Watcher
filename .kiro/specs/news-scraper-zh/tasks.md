# Implementation Plan

## Task Overview

本实现计划将 news-scraper 功能分解为可执行的代码任务。任务按分层架构组织，从数据模型开始，逐步构建工具层、服务层、API 层和基础设施。

**并行执行说明**: 标记 `(P)` 的任务可以并行开发，前提是其依赖任务已完成。

---

## Data Layer

### 1. 数据模型和数据库层

- [ ] 1.1 (P) 创建推文数据模型和数据库表结构
  - 使用 Pydantic 定义 Tweet、Media、ReferenceType 模型
  - 使用 SQLAlchemy 创建 Tweet ORM 模型
  - 添加必需字段：tweet_id, text, created_at, author_username, author_display_name, referenced_tweet_id, reference_type, media, referenced_tweet_text, referenced_tweet_media
  - 添加数据库跟踪字段：db_created_at, db_updated_at
  - 配置数据库表约束：主键、唯一索引、外键
  - 创建复合索引 (author_username, created_at DESC) 优化查询
  - 在数据库初始化脚本中添加表创建逻辑
  - _Requirements: 2, 3, 9_

- [ ] 1.2 实现推文数据仓库
  - 创建 TweetRepository 类处理数据库 CRUD 操作
  - 实现 save_tweets 方法，支持批量插入推文
  - 基于 tweet_id 唯一约束实现去重逻辑
  - 实现 tweet_exists 方法检查推文是否已存在
  - 实现 get_tweets_by_author 方法按作者查询推文
  - 使用事务确保数据一致性
  - 返回 SaveResult 包含成功和跳过数量
  - _Requirements: 3_

---

## Tool Layer

### 2. Twitter API 客户端和解析工具

- [ ] 2.1 实现 Twitter API 客户端
  - 创建 TwitterClient 类封装 TwitterAPI.io HTTP 调用
  - 使用 httpx 异步客户端实现 fetch_user_tweets 方法
  - 从环境变量加载 TWITTER_BEARER_TOKEN 进行认证
  - 实现指数退避重试策略（初始延迟 1 秒，最大 60 秒）
  - 处理不同错误类型：401 立即停止告警，429 等待重试，5xx 按策略重试
  - 支持 limit 和 since_id 参数过滤推文
  - 返回 Result 类型包含成功数据或错误信息
  - [x] 实现 `_extract_media_from_tweet_obj()` 辅助函数提取嵌套推文媒体
  - [x] 在响应标准化时提取 `referenced_tweet_text` 和 `referenced_tweet_media`
  - _Requirements: 1, 2, 5, 6_

- [ ] 2.2 (P) 实现推文数据解析器
  - 创建 TweetParser 类解析 Twitter API v2 响应格式
  - 实现 parse_tweet_response 方法转换 JSON 为 Tweet 模型列表
  - 处理 includes 中的用户关联数据（author_id 映射到用户信息）
  - 提取媒体附件信息（media_keys 映射到 URL 和类型）
  - 解析 referenced_tweets 字段提取引用/转发关系
  - [x] 从标准化字典中提取 `referenced_tweet_text` 和 `referenced_tweet_media` 字段
  - 跳过无效数据并记录警告日志
  - 确保每个 Tweet 包含所有必需字段
  - _Requirements: 2_

- [ ] 2.3 (P) 实现推文数据验证器
  - 创建 TweetValidator 类验证推文数据完整性
  - 实现 validate_and_clean 方法检查必需字段
  - 必需字段验证：tweet_id, text, created_at, author_username
  - 清理推文文本：移除换行符、回车符、多余空格
  - 标准化日期格式为 ISO 8601
  - 截断过长文本（MAX_TEXT_LENGTH = 25,000，支持 X Premium 长文）
  - [x] 清理 `referenced_tweet_text`（应用与主文本相同的正则清理规则）
  - 提取并可选展开短链接
  - 返回 Result 类型包含验证后的数据或验证错误
  - _Requirements: 9_

---

## Service Layer

### 3. 抓取服务和任务管理

- [ ] 3.1 实现任务注册表
  - 创建 TaskRegistry 单例类管理异步任务状态
  - 实现 create_task 方法生成唯一 task_id（使用 UUID）
  - 实现 update_task_status 方法更新任务状态（pending, running, completed, failed）
  - 实现 get_task_status 方法查询任务状态和结果
  - 实现 is_task_running 方法检查任务是否正在执行
  - 使用内存存储（dict）和线程锁保护并发访问
  - 添加过期任务清理逻辑（TTL 24 小时）
  - _Requirements: 4, 8_

- [ ] 3.2 实现抓取服务编排
  - 创建 ScrapingService 类编排完整抓取流程
  - 实现 scrape_users 方法处理多个用户的抓取任务
  - 实现 scrape_single_user 方法处理单个用户抓取
  - 协调 TwitterClient, TweetParser, TweetValidator, TweetRepository
  - 使用 TaskRegistry 检查任务运行状态，防止并发执行
  - 使用 asyncio.Semaphore 控制并发请求数
  - 实时记录进度日志：当前用户、已获取数量、新增数量、跳过数量、错误数量
  - 生成汇总报告：用户总数、推文总数、新增总数、任务耗时
  - 处理单用户失败不影响其他用户
  - _Requirements: 1, 4, 6, 7_

---

## API Layer

### 4. 管理端点

- [x] 4.1 实现手动抓取 API 端点
  - 创建 ScrapeRequest Pydantic 模型（usernames 字符串, limit 整数）
  - 实现 POST /api/admin/scrape 端点
  - 解析 usernames 字符串为用户列表，验证用户名格式
  - 调用 TaskRegistry.create_task 生成 task_id
  - 异步执行 ScrapingService.scrape_users
  - 返回 {task_id, status} 响应
  - 添加错误处理：400 无效输入，409 任务冲突，500 服务器错误
  - _Requirements: 8_

- [x] 4.2 实现任务状态查询端点
  - 创建 TaskStatusResponse Pydantic 模型
  - 实现 GET /api/admin/scrape/{task_id} 端点
  - 调用 TaskRegistry.get_task_status 查询任务状态
  - 任务完成时返回汇总报告（result 字段）
  - 添加错误处理：404 任务不存在
  - _Requirements: 8_

---

## Infrastructure

### 5. 定时任务调度

- [x] 5.1 实现 APScheduler 集成
  - 在 FastAPI lifespan 上下文管理器中初始化 BackgroundScheduler
  - 配置定时任务：间隔时间从环境变量 SCRAPER_INTERVAL 读取（默认 1 小时）
  - 添加 max_instances=1 防止任务重复执行
  - 定时任务调用 ScrapingService.scrape_users
  - 从配置文件读取关注用户列表（SCRAPER_USERNAMES）
  - 记录任务开始和结束时间
  - 检查 SCRAPER_ENABLED 环境变量控制是否启用调度器
  - 应用关闭时正确停止调度器
  - 添加跳过逻辑：上一次任务未完成时跳过本次执行
  - _Requirements: 4, 7_

---

## Integration & Configuration

### 6. 系统集成和配置

- [x] 6.1 更新环境配置和依赖
  - 在 .env.example 中添加 Twitter API 相关环境变量
  - 添加依赖：httpx, apscheduler
  - 更新 src/config.py 加载 Twitter API 配置
  - 配置 Loguru 日志级别（LOG_LEVEL 环境变量）
  - 验证必需的环境变量在应用启动时存在
  - _Requirements: 5, 7, 10_

- [x] 6.2 注册 Admin API 路由
  - 在 src/api/routes/admin.py 中注册抓取端点
  - 在 FastAPI app 中包含 admin 路由器
  - 更新 API 文档（自动生成）
  - _Requirements: 8_

---

## Testing

### 7. 单元测试

- [ ] 7.1 (P) 测试数据层和解析工具
  - 测试 TweetRepository CRUD 操作和去重逻辑
  - 测试 TweetParser 解析正常、边界、异常数据
  - 测试 TweetValidator 字段验证和清理逻辑
  - 使用测试数据库（SQLite 内存模式）
  - Mock API 响应数据
  - 验证覆盖率不低于 80%
  - _Requirements: 10_

- [ ] 7.2 (P) 测试抓取服务和任务管理
  - 测试 ScrapingService 完整抓取流程（Mock API）
  - 测试错误处理和重试逻辑
  - 测试 TaskRegistry 状态管理和并发安全性
  - 测试进度日志和汇总报告生成
  - 验证覆盖率不低于 80%
  - _Requirements: 10_

- [ ] 7.3 (P) 测试 API 端点
  - 测试 POST /api/admin/scrape 端点响应和状态码
  - 测试 GET /api/admin/scrape/{task_id} 状态查询
  - 测试异步任务执行和状态更新
  - 测试错误场景（无效输入、任务冲突）
  - 使用 TestClient 模拟 HTTP 请求
  - 验证覆盖率不低于 80%
  - _Requirements: 10_

### 8. 集成测试

- [x] 8.1 测试完整抓取流程
  - 测试手动抓取完整流程：POST 触发 → GET 查询 → 数据库验证
  - 测试定时抓取流程：调度器触发 → 数据存储 → 日志验证
  - 使用 Mock Twitter API 响应
  - 验证数据去重逻辑
  - 验证并发任务冲突处理
  - _Requirements: 1, 3, 4, 8_

- [x] 8.2* 测试错误场景和恢复
  - 测试 API 认证失败（401）场景
  - 测试配额耗尽（429）重试逻辑
  - 测试网络超时恢复
  - 测试数据库错误回滚
  - 验证日志记录完整
  - _Requirements: 6, 7, 10_

---

## 动态抓取优化

### 9. 动态 Limit 计算

- [x] 9.1 (P) 创建 FetchStats 领域模型和 FetchStatsOrm
  - 定义 FetchStats Pydantic 模型（username, last_fetch_at, last_fetched_count, last_new_count, total_fetches, avg_new_rate, consecutive_empty_fetches）
  - 创建 FetchStatsOrm 及 to_domain/from_domain 转换方法
  - _Requirements: 1 (扩展)_

- [x] 9.2 实现 FetchStatsRepository
  - 实现 get_stats(username) 方法查询单用户统计
  - 实现 batch_get_stats(usernames) 方法批量查询
  - 实现 upsert_stats(stats) 方法更新或创建统计记录
  - _Requirements: 1 (扩展)_

- [x] 9.3 实现 LimitCalculator
  - 实现 calculate_next_limit(stats) 方法：无历史→默认、全量→翻倍、连续空→回退、正常→EMA 预测
  - 实现 update_stats_after_fetch() 方法更新 EMA 和计数器
  - 配置参数：default_limit=100, min_limit=10, max_limit=300, ema_alpha=0.3, safety_margin=1.2
  - _Requirements: 1 (扩展)_

- [x] 9.4 集成到 ScrapingService
  - 每次抓取前调用 LimitCalculator 计算动态 limit
  - 抓取后更新 FetchStats 统计
  - _Requirements: 1 (扩展)_

- [x] 9.5 创建数据库迁移 (b3a1d5e7f9c2)
  - 创建 scraper_fetch_stats 表
  - _Requirements: 1 (扩展)_

---

### 10. 自动摘要触发

- [x] 10.1 ScrapingService 抓取完成后异步触发摘要生成
  - 使用 asyncio.create_task() 在后台运行
  - _Requirements: 7 (扩展), 与 news-summarizer-zh 联动_

- [x] 10.2 支持 auto_summarization_enabled 配置开关
  - 配置项：AUTO_SUMMARIZATION_ENABLED, AUTO_SUMMARIZATION_BATCH_SIZE
  - _Requirements: 7 (扩展)_

- [x] 10.3 支持 wait 模式
  - 等待摘要完成再结束抓取任务
  - _Requirements: 7 (扩展)_

---

## Requirements Coverage Summary

| Requirement | Covered Tasks |
|-------------|---------------|
| 1 | 2.1, 3.2, 8.1, 9.1-9.5 |
| 2 | 1.1, 2.1, 2.2 |
| 3 | 1.1, 1.2, 8.1 |
| 4 | 3.1, 3.2, 5.1, 8.1 |
| 5 | 2.1, 6.1 |
| 6 | 2.1, 3.2, 7.2, 8.2 |
| 7 | 3.2, 5.1, 10.1-10.3 |
| 8 | 3.1, 4.1, 4.2, 6.2, 8.1 |
| 9 | 1.1, 2.3 |
| 10 | 7.1, 7.2, 7.3, 8.1, 8.2 |

**所有 10 个需求均已覆盖，其中需求 1 和 7 包含扩展任务。**

---

## Parallel Execution Opportunities

以下任务组可以并行开发（前提是其依赖任务已完成）：

1. **并行组 A**（数据层和工具层基础）:
   - 1.1 数据模型 (P)
   - 1.2 数据仓库（依赖 1.1）
   - 2.2 解析器 (P)
   - 2.3 验证器 (P)

2. **并行组 B**（服务层）:
   - 2.1 客户端（依赖 1.1）
   - 3.1 任务注册表
   - 3.2 抓取服务（依赖 1.1, 1.2, 2.1, 2.2, 2.3, 3.1）

3. **并行组 C**（API 和基础设施）:
   - 4.1 API 端点（依赖 3.1, 3.2）
   - 4.2 状态查询（依赖 3.1, 3.2）
   - 5.1 调度器（依赖 3.2）
   - 6.1 配置（依赖 1.1, 2.1）
   - 6.2 路由注册（依赖 4.1, 4.2）

4. **并行组 D**（测试）:
   - 7.1 数据层测试 (P)（依赖 1.1, 1.2, 2.2, 2.3）
   - 7.2 服务层测试 (P)（依赖 2.1, 3.1, 3.2）
   - 7.3 API 测试 (P)（依赖 4.1, 4.2）

---

## Task Dependency Graph

```
1.1 (P) ──→ 1.2 ──┐
                   │
2.2 (P) ──┐       │
2.3 (P) ──┼───────┼──→ 3.2 ──┬──→ 4.1 ──┬──→ 6.2
         │       │           │        │
3.1 ─────┴───────┘           │        │
                             │        │
2.1 ─────────────────────────┘        │
                                      │
5.1 ──────────────────────────────────┘
                                      │
6.1 ──────────────────────────────────┘
```
