# 需求文档

## 项目概述

news-scraper 是 X-watcher 系统的核心数据采集组件，负责从 X（Twitter）平台抓取关注人物的动态内容。本组件将实现定时抓取、数据解析、持久化存储等功能，为后续的新闻分析、去重、摘要和翻译提供原始数据。

## 需求

### Requirement 1: X 平台用户动态抓取
**目标**：作为系统，我需要从 X 平台抓取指定用户的推文，以便获取原始新闻数据。

#### 验收标准

1. **When** 抓取任务启动时，**NewsScraper** **shall** 从用户配置中获取关注列表
2. **When** 抓取单个用户推文时，**the** **scraper** **shall** 调用 X 平台 API 获取该用户的最新推文
3. **The** 抓取操作 **shall** 支持指定获取数量（默认 100 条，可配置）
4. **The** 抓取操作 **shall** 支持按时间范围过滤（例如：仅获取过去 24 小时的推文）
5. **If** API 调用失败，**the** **scraper** **shall** 记录错误日志并继续处理其他用户
6. **If** API 配额耗尽，**the** **scraper** **shall** 发送告警通知

### Requirement 2: 推文数据解析
**目标**：作为系统，我需要解析推文数据，以便提取结构化信息。

#### 验收标准

1. **When** 获取推文数据后，**NewsScraper** **shall** 提取以下字段：
   - 推文 ID（tweet_id）
   - 作者信息（用户名、显示名称）
   - 推文内容（text）
   - 发布时间（created_at）
   - 媒体附件（图片、视频链接）
   - 引用/转发关系（引用推文 ID、转发源推文 ID）
2. **The** 数据解析 **shall** 兼容 X 平台 API v2 响应格式
3. **If** 推文包含媒体附件，**the** **parser** **shall** 提取媒体 URL 和类型
4. **If** 推文为引用或转发推文，**the** **parser** **shall** 保留被引用推文的 ID，并提取被引用推文的完整文本（`referenced_tweet_text`）、媒体附件（`referenced_tweet_media`）和原作者用户名（`referenced_tweet_author_username`）
5. **The** 解析后的数据 **shall** 符合预定义的 Pydantic 模型结构
6. **When** 推文为转发或引用，**the** client **shall** 从 TwitterAPI.io 响应的嵌套 `retweeted_tweet` 或 `quoted_tweet` 对象中提取完整文本、媒体和原作者用户名（`referenced_tweet_author_username`），在传递给 parser 之前完成预处理

### Requirement 3: 数据持久化存储
**目标**：作为系统，我需要将抓取的推文持久化存储，以便后续处理和检索。

#### 验收标准

1. **When** 推文数据解析完成后，**NewsScraper** **shall** 将数据存储到数据库
2. **The** 存储 **shall** 使用 SQLAlchemy ORM 操作数据库
3. **The** 存储 **shall** 实现去重逻辑（基于推文 ID），避免重复存储
4. **If** 推文已存在，**the** **scraper** **shall** 跳过存储并记录跳过日志
5. **When** 存储完成时，**the** **scraper** **shall** 记录成功存储的推文数量
6. **The** 数据库操作 **shall** 支持事务，确保数据一致性

### Requirement 4: 定时任务调度
**目标**：作为系统，我需要定时执行抓取任务，以便保持数据的时效性。

#### 验收标准

1. **When** 应用启动时，**NewsScraper** **shall** 使用 APScheduler 注册定时任务
2. **The** 定时任务 **shall** 支持配置抓取间隔（默认每小时一次）
3. **The** 定时任务 **shall** 支持通过配置文件动态调整
4. **When** 定时任务执行时，**the** **scraper** **shall** 记录任务开始和结束时间
5. **If** 上一次任务仍在执行，**the** **scheduler** **shall** 跳过本次执行并记录警告
6. **The** 定时任务 **shall** 支持手动触发（用于测试和补抓）

### Requirement 5: API 密钥管理
**目标**：作为系统，我需要安全地管理 X 平台 API 密钥，以便进行认证调用。

#### 验收标准

1. **When** 应用初始化时，**NewsScraper** **shall** 从环境变量加载 API 密钥
2. **The** 环境 **shall** 包含以下配置项：
   - `TWITTER_API_KEY` - API 密钥
   - `TWITTER_API_SECRET` - API 密钥密文
   - `TWITTER_ACCESS_TOKEN` - 访问令牌（可选）
   - `TWITTER_ACCESS_TOKEN_SECRET` - 访问令牌密文（可选）
   - `TWITTER_BEARER_TOKEN` - Bearer 令牌（推荐）
3. **If** 必需的 API 密钥缺失，**the** 应用 **shall** 在启动时报错并提示
4. **The** API 客户端 **shall** 使用 Bearer 令牌进行认证（如已配置）
5. **The** API 客户端 **shall** 支持 TwitterAPI.io 服务商格式

### Requirement 6: 错误处理和重试
**目标**：作为系统，我需要优雅地处理错误和重试机制，以便提高抓取成功率。

#### 验收标准

1. **When** API 请求失败时，**NewsScraper** **shall** 根据错误类型决定是否重试
2. **The** 重试 **shall** 支持指数退避策略（初始延迟 1 秒，最大延迟 60 秒）
3. **The** 最大重试次数 **shall** 可配置（默认 3 次）
4. **If** 错误为认证失败（401），**the** **scraper** **shall** 立即停止并告警
5. **If** 错误为配额耗尽（429），**the** **scraper** **shall** 等待后重试或告警
6. **If** 错误为服务器错误（5xx），**the** **scraper** **shall** 按重试策略重试
7. **The** 所有错误 **shall** 记录到日志，包含错误类型和堆栈信息

### Requirement 7: 抓取进度报告
**目标**：作为运维人员，我需要了解抓取任务的执行状态，以便监控系统运行情况。

#### 验收标准

1. **When** 抓取任务执行时，**NewsScraper** **shall** 实时记录进度日志
2. **The** 进度日志 **shall** 包含以下信息：
   - 当前处理的用户
   - 已获取的推文数量
   - 新增的推文数量
   - 跳过的推文数量（已存在）
   - 错误数量
3. **When** 任务完成时，**the** **scraper** **shall** 输出汇总报告
4. **The** 汇总报告 **shall** 包含：
   - 处理的用户总数
   - 获取的推文总数
   - 新增的推文总数
   - 任务耗时
5. **The** 日志级别 **shall** 可通过环境变量配置

### Requirement 8: 手动抓取 API
**目标**：作为管理员，我需要手动触发抓取任务，以便按需更新数据。

#### 验收标准

1. **The** FastAPI 应用 **shall** 提供 `/api/admin/scrape` POST 端点
2. **When** 调用该端点时，**the** 系统 **shall** 立即执行抓取任务
3. **The** 端点 **shall** 支持以下可选参数：
   - `usernames` - 指定抓取的用户列表（逗号分隔）
   - `limit` - 每个用户获取的推文数量
4. **The** 端点 **shall** 返回异步任务 ID，用于查询执行状态
5. **The** 应用 **shall** 提供 `/api/admin/scrape/{task_id}` GET 端点查询任务状态
6. **If** 任务已完成，**the** 状态查询 **shall** 返回汇总报告

### Requirement 9: 数据验证和清理
**目标**：作为系统，我需要验证和清理抓取的数据，以便保证数据质量。

#### 验收标准

1. **When** 推文数据解析后，**NewsScraper** **shall** 验证必需字段是否存在
2. **The** 必需字段 **shall** 包括：tweet_id、text、created_at、author_username
3. **If** 必需字段缺失，**the** **scraper** **shall** 记录警告并跳过该条推文
4. **The** 清理 **shall** 包括：移除多余空格、标准化日期格式、截断过长文本（推文文本上限 25,000 字符，支持 X Premium 长文）
5. **The** 推文内容 **shall** 移除换行符和多余空格，以便后续处理
6. **The** URL **shall** 被提取并可选地展开（短链接处理）
7. **If** 推文包含 `referenced_tweet_text`，**the** validator **shall** 对该文本应用与主文本相同的清理规则（移除换行符、多余空格，截断至 25,000 字符）

### Requirement 10: 测试和可观测性
**目标**：作为开发者，我需要完整的测试覆盖和可观测性，以便保证代码质量和问题排查。

#### 验收标准

1. **The** 抓取模块 **shall** 提供单元测试，覆盖所有核心函数
2. **The** 单元测试 **shall** 使用 Mock 对象模拟 API 响应
3. **The** 抓取模块 **shall** 提供集成测试，使用测试数据库
4. **The** 应用 **shall** 导出抓取相关的 Prometheus 指标（可选）：
   - 抓取任务执行次数
   - 抓取成功/失败次数
   - 抓取耗时
   - 新增推文数量
5. **The** 日志 **shall** 包含结构化字段，便于日志聚合和分析
6. **The** 测试覆盖率 **shall** 不低于 80%

---

_本需求文档遵循 EARS 格式，所有验收标准均可测试和验证_
