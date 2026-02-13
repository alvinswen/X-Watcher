# News-Scraper 模块文档

## 概述

news-scraper 是 X-watcher 的核心抓取模块，负责从 X 平台（Twitter）抓取关注人物的推文并存储到数据库。

## 功能特性

- ✅ 支持多用户并发抓取
- ✅ 自动去重（基于 tweet_id）
- ✅ 推文内容验证和清理
- ✅ 异步任务队列管理
- ✅ 定时自动抓取
- ✅ 推文引用关系提取（转推/引用/回复）
- ✅ 完善的错误处理和重试机制
- ✅ 集成 TwitterAPI.io API

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Routes                            │
│                    (/api/admin/scrape)                           │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ScrapingService                             │
│  - 协调抓取流程                                                  │
│  - 管理任务状态                                                  │
│  - 并发控制                                                      │
└──────┬────────────┬────────────┬────────────┬────────────┬──────┘
       │            │            │            │            │
       ▼            ▼            ▼            ▼            ▼
┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│TwitterClient│ │TweetParser│ │Validator │ │ Repository│ │TaskRegistry│
│             │ │          │ │          │ │          │ │           │
│- API 调用   │ │- 解析JSON│ │- 验证数据│ │- 数据持久化│ │- 任务状态 │
│- 重试机制   │ │- 日期转换│ │- 清理文本│ │- 去重逻辑│ │- 进度跟踪│
│- 格式转换   │ │          │ │          │ │          │ │           │
└─────────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      TwitterAPI.io API                          │
│                   (/user/last_tweets)                           │
└─────────────────────────────────────────────────────────────────┘
```

## 数据流程

```
1. API 请求 → FastAPI Route
2. 创建任务 → TaskRegistry (状态: pending)
3. 启动后台任务 → ScrapingService.scrape_users()
4. 遍历用户列表:
   a. TwitterClient.fetch_user_tweets() → 获取原始数据
   b. 响应格式转换 (TwitterAPI.io → 标准 Twitter API v2)
      - 提取引用关系: retweeted_tweet / quoted_tweet / isReply
      - 提取作者信息: author 对象 → includes.users
      - 文本完整性: _extract_full_text() 按优先级提取 note_tweet > full_text > text
   c. TweetParser.parse_tweet_response() → 解析为 Tweet 模型
   d. TweetValidator.validate_and_clean_batch() → 验证和清理
   e. TweetRepository.save_tweets() → 保存到数据库
      - FK 保护: 被引用推文不在数据库中时，保留 reference_type 但清除 FK
5. 更新任务状态 → TaskRegistry (状态: completed/failed)
6. (可选) 自动去重和摘要 → 如果 AUTO_SUMMARIZATION_ENABLED=true
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必需 | 默认值 |
|--------|------|------|--------|
| `TWITTER_API_KEY` | TwitterAPI.io API 密钥 | ✅ | - |
| `TWITTER_BEARER_TOKEN` | X 平台 Bearer 令牌 | ✅ | - |
| `TWITTER_BASE_URL` | TwitterAPI.io API 地址 | ❌ | `https://api.twitterapi.io/twitter` |
| `SCRAPER_ENABLED` | 是否启用定时抓取 | ❌ | `true` |
| `SCRAPER_INTERVAL` | 抓取间隔（秒） | ❌ | `3600` (1小时) |
| `SCRAPER_USERNAMES` | 关注用户列表（逗号分隔） | ❌ | - |
| `SCRAPER_LIMIT` | 单次抓取数量限制（1-1000） | ❌ | `100` |
| `LOG_LEVEL` | 日志级别 | ❌ | `INFO` |

### TwitterAPI.io 集成

本项目使用 [TwitterAPI.io](https://twitterapi.io/) 作为数据源：

**认证方式**: `X-API-Key: {api_key}` header（不是 Bearer Token）

**API 端点**: `/user/last_tweets`

**请求参数**:
```python
{
    "userName": "elonmusk",      # 用户名（必需）
    "includeReplies": False,      # 是否包含回复（可选）
    # 其他分页参数...
}
```

**响应格式**:
```json
{
  "status": "success",
  "data": {
    "tweets": [
      {
        "id": "1234567890",
        "text": "Hello World",
        "createdAt": "Fri Feb 06 09:31:48 +0000 2026",
        "isReply": false,
        "inReplyToId": null,
        "retweeted_tweet": null,
        "quoted_tweet": null,
        "author": {
          "id": "44196397",
          "userName": "elonmusk",
          "name": "Elon Musk"
        }
      }
    ]
  }
}
```

**引用关系字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `retweeted_tweet` | object/null | 转推的原始推文对象，包含 `id` 字段 |
| `quoted_tweet` | object/null | 引用推文对象，包含 `id` 字段 |
| `isReply` | boolean | 是否为回复 |
| `inReplyToId` | string/null | 回复的目标推文 ID |
| `author` | object | 推文作者信息（`id`, `userName`, `name`） |

**引用类型优先级**: `retweeted` > `quoted` > `replied_to`

**推文文本提取策略**:

TwitterAPI.io 对嵌套推文（`retweeted_tweet`、`quoted_tweet`）可能在不同字段中返回文本：

| 字段 | 优先级 | 说明 |
|------|--------|------|
| `note_tweet.text` | 1 (最高) | X Premium 长推文（>280 字符） |
| `full_text` | 2 | 部分 API 响应使用此字段提供完整文本 |
| `text` | 3 (回退) | 标准字段，嵌套推文中可能被截断至 ~140 字符 |

`_extract_full_text()` 函数收集所有可用候选文本，返回最长的版本。当嵌套推文文本疑似被截断（<300 字符且以省略号结尾）时，会输出 warning 日志。

## 使用示例

### 通过 FastAPI 端点抓取

```bash
# 启动服务
python -m src.main

# 触发抓取
curl -X POST "http://localhost:8000/api/admin/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "usernames": "elonmusk,nvidia",
    "limit": 20
  }'

# 响应示例
{
  "task_id": "abc-123-def",
  "status": "pending"
}

# 查询任务状态
curl "http://localhost:8000/api/admin/scrape/abc-123-def"

# 响应示例
{
  "task_id": "abc-123-def",
  "status": "completed",
  "result": {
    "total_users": 2,
    "successful_users": 2,
    "total_tweets": 40,
    "new_tweets": 40,
    "skipped_tweets": 0,
    "total_errors": 0,
    "elapsed_seconds": 8.5
  }
}
```

### 直接使用 ScrapingService

```python
from src.scraper.scraping_service import ScrapingService
from src.database.async_session import get_async_session_maker
import asyncio

async def scrape():
    session_maker = get_async_session_maker()

    async with session_maker() as session:
        from src.scraper.infrastructure.repository import TweetRepository
        repo = TweetRepository(session)
        service = ScrapingService(repository=repo)

        try:
            # 抓取用户推文
            task_id = await service.scrape_users(
                usernames=["elonmusk", "OpenAI"],
                limit=50
            )

            print(f"任务 ID: {task_id}")
        finally:
            await service.close()
            await session.commit()

asyncio.run(scrape())
```

## 数据模型

### Tweet 模型

```python
class Tweet(BaseModel):
    tweet_id: str                    # 推文 ID
    text: str                        # 推文文本
    created_at: datetime             # 创建时间
    author_username: str             # 作者用户名
    author_display_name: str | None  # 作者显示名称
    referenced_tweet_id: str | None  # 引用的推文 ID
    reference_type: ReferenceType | None  # 引用类型
    media: list[Media] | None        # 媒体附件
```

### 任务状态模型

```python
class TaskStatus(Enum):
    PENDING = "pending"       # 待执行
    RUNNING = "running"       # 执行中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
```

## 错误处理

### 重试机制

TwitterClient 实现了指数退避重试策略：

- **最大重试次数**: 5
- **基础延迟**: 1 秒
- **最大延迟**: 60 秒
- **不重试的状态码**: 401, 403, 404, 422

### 错误类型

| 错误类型 | 说明 | 处理方式 |
|----------|------|----------|
| `TwitterClientError` | API 调用失败 | 记录日志，标记任务失败 |
| `ValidationError` | 数据验证失败 | 跳过该推文，继续处理 |
| `DatabaseError` | 数据库错误 | 记录错误，不影响其他推文 |

## 测试

```bash
# 运行所有 scraper 测试
pytest tests/scraper/ -v

# 运行特定测试
pytest tests/scraper/test_twitter_client.py::TestTwitterClient::test_fetch_user_tweets_success -v

# 运行测试并查看覆盖率
pytest tests/scraper/ --cov=src/scraper --cov-report=html
```

### 测试覆盖率

scraper 模块测试覆盖完整，包含 TwitterClient、TweetParser、TweetValidator、TweetRepository、TaskRegistry、ScrapingService 等组件的全面测试。

运行测试查看当前覆盖率：
```bash
pytest tests/scraper/ --cov=src/scraper --cov-report=term-missing
```

## 性能优化

1. **并发控制**: 使用 `asyncio.Semaphore` 限制并发请求数（默认 3）
2. **去重机制**: 基于 `tweet_id` 唯一约束，避免重复保存
3. **批量处理**: 支持批量抓取和保存
4. **异步 I/O**: 所有数据库和 API 调用均为异步

## 故障排查

### 常见问题

#### 1. 401 Unauthorized
**原因**: API 密钥错误或认证方式不正确
**解决**: 检查 `.env` 中的 `TWITTER_API_KEY` 是否正确

#### 2. 405 Method Not Allowed
**原因**: API 端点路径错误
**解决**: 确保使用正确的端点 `/user/last_tweets`

#### 3. 推文未保存到数据库
**原因**: 事务未提交
**解决**: 确保调用 `await session.commit()`

#### 4. 抓取速度慢
**原因**: API 限流或网络延迟
**解决**: 调整 `SCRAPER_INTERVAL` 或减少并发数

### 调试日志

设置日志级别为 DEBUG 以查看详细信息：

```bash
# .env
LOG_LEVEL=DEBUG
```

## 开发指南

### 添加新的数据源

1. 创建新的 Client 类（参考 `TwitterClient`）
2. 实现相同的接口（`fetch_user_tweets`）
3. 在 `ScrapingService` 中添加支持

### 扩展解析器

如果需要处理不同的响应格式：

1. 在 `TwitterClient` 中添加响应格式转换
2. 确保 `TweetParser` 能够解析转换后的数据

## 维护者

- 代码位置: `src/scraper/`
- 测试位置: `tests/scraper/`
- 相关文档: `docs/news-scraper.md`
