# API 使用指南

本文档详细介绍 X-watcher 的 API 接口使用方法。

## 目录

- [快速开始](#快速开始)
- [浏览 API（普通用户）](#浏览-api普通用户)
- [信息流 API（普通用户）](#信息流-api普通用户)
- [搜索 API（普通用户）](#搜索-api普通用户)
- [主题 API（普通用户）](#主题-api普通用户)
- [发文频次分析 API（普通用户）](#发文频次分析-api普通用户)
- [推文 API（管理员）](#推文-api管理员)
- [抓取 API（管理员）](#抓取-api管理员)
- [抓取配置 API（管理员）](#抓取配置-api管理员)
- [摘要 API（管理员）](#摘要-api管理员)
- [监控 API（公开）](#监控-api公开)
- [错误处理](#错误处理)
- [代码示例](#代码示例)

---

## 快速开始

### 服务地址

- **开发环境**: `http://localhost:8000`
- **API 文档**:
  - Swagger UI: `http://localhost:8000/docs`
  - ReDoc: `http://localhost:8000/redoc`

### 认证

API 端点按权限分为三个等级：

| 权限等级 | 认证方式 | 可访问端点 |
|---------|---------|-----------|
| 公开 | 无需认证 | `/health`、`/metrics`、`/api/auth/*` |
| 普通用户 | `X-API-Key` 或 JWT | `/api/browse/*`、`/api/feed`、`/api/search/*`、`/api/topics/*`、`/api/analytics/topics/*`、`/api/users/*`、`/api/status` |
| 管理员 | `X-API-Key`（admin）或 JWT（admin） | `/api/admin/*`、`/api/tweets/*`、`/api/summaries/*` |

认证方式（二选一）：

```bash
# 方式 1: API Key
-H "X-API-Key: your_api_key"

# 方式 2: JWT Bearer Token（通过 /api/auth/login 获取）
-H "Authorization: Bearer your_jwt_token"
```

### 健康检查

```bash
curl http://localhost:8000/health
```

**响应**:
```json
{
  "status": "healthy"
}
```

---

## 浏览 API（普通用户）

浏览 API 提供按日期维度的推文浏览功能，包含每日统计、作者列表和推文列表。

### 1. 获取每日推文统计

**端点**: `GET /api/browse/stats/daily`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| year | integer | 是 | 年份 |
| month | integer | 是 | 月份（1-12） |
| tz_offset | integer | 否 | 时区偏移（分钟），来自 JS `getTimezoneOffset()`，默认 0 |
| min_text_length | integer | 否 | 最小推文长度（字符数） |

**请求示例**:
```bash
curl "http://localhost:8000/api/browse/stats/daily?year=2026&month=2" \
  -H "X-API-Key: your_api_key"
```

### 2. 获取作者列表

**端点**: `GET /api/browse/authors`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| date | string | 是 | 日期，YYYY-MM-DD 格式 |
| tz_offset | integer | 否 | 时区偏移（分钟），默认 0 |
| min_text_length | integer | 否 | 最小推文长度（字符数） |

**请求示例**:
```bash
curl "http://localhost:8000/api/browse/authors?date=2026-02-24" \
  -H "X-API-Key: your_api_key"
```

**响应**:
```json
{
  "authors": [
    {"username": "elonmusk", "display_name": "Elon Musk", "tweet_count": 5}
  ],
  "total": 1
}
```

### 3. 获取推文浏览列表

**端点**: `GET /api/browse/tweets`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| date | string | 是 | 日期，YYYY-MM-DD 格式 |
| author | string | 否 | 按作者用户名筛选 |
| page | integer | 否 | 页码，默认 1 |
| page_size | integer | 否 | 每页条数，1-100，默认 20 |
| tz_offset | integer | 否 | 时区偏移（分钟），默认 0 |
| min_text_length | integer | 否 | 最小推文长度（字符数） |

**请求示例**:
```bash
curl "http://localhost:8000/api/browse/tweets?date=2026-02-24&page=1&page_size=20" \
  -H "X-API-Key: your_api_key"
```

**响应**:
```json
{
  "items": [
    {
      "tweet_id": "1234567890",
      "text": "Hello World",
      "author_username": "elonmusk",
      "created_at": "2026-02-24T09:31:48",
      "summary_text": "中文摘要...",
      "translation_text": "翻译文本..."
    }
  ],
  "total": 50,
  "page": 1,
  "page_size": 20,
  "total_pages": 3
}
```

---

## 信息流 API（普通用户）

信息流 API 提供按时间区间查询推文的能力，支持增量拉取。

### 获取推文 Feed

**端点**: `GET /api/feed`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| since | datetime | 是 | 推文发布时间起始（含），ISO 8601 格式 |
| until | datetime | 否 | 推文发布时间截止（不含），默认当前服务器时间 |
| limit | integer | 否 | 最大返回条数 |
| include_summary | boolean | 否 | 是否包含摘要和翻译，默认 true |
| author | string | 否 | 按单个作者筛选（大小写不敏感） |
| authors | string | 否 | 按多个作者筛选（逗号分隔，大小写不敏感） |
| keyword | string | 否 | 关键词过滤（搜索推文正文、摘要、翻译） |

> 注意：`author` 和 `authors` 参数不能同时使用。

**请求示例**:
```bash
# 查询最近 24 小时的推文
curl "http://localhost:8000/api/feed?since=2026-02-23T00:00:00Z" \
  -H "X-API-Key: your_api_key"

# 按作者筛选
curl "http://localhost:8000/api/feed?since=2026-02-23T00:00:00Z&author=elonmusk" \
  -H "X-API-Key: your_api_key"

# 按多个作者筛选 + 关键词过滤
curl "http://localhost:8000/api/feed?since=2026-02-23T00:00:00Z&authors=elonmusk,OpenAI&keyword=AI" \
  -H "X-API-Key: your_api_key"
```

**响应**:
```json
{
  "items": [
    {
      "tweet_id": "1234567890",
      "text": "Original tweet text...",
      "author_username": "elonmusk",
      "created_at": "2026-02-24T09:31:48Z",
      "summary_text": "中文摘要...",
      "translation_text": "翻译文本..."
    }
  ],
  "count": 10,
  "total": 50,
  "since": "2026-02-23T00:00:00Z",
  "until": "2026-02-24T12:00:00Z",
  "has_more": true
}
```

---

## 搜索 API（普通用户）

搜索 API 提供推文全文搜索功能。

### 搜索推文

**端点**: `GET /api/search/tweets`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| q | string | 是 | 搜索关键词（空格分隔多词为 AND 逻辑） |
| author | string | 否 | 按作者用户名筛选（大小写不敏感） |
| authors | string | 否 | 按多个作者筛选（逗号分隔，大小写不敏感） |
| since | string | 否 | 起始时间（含），ISO 8601 格式 |
| until | string | 否 | 截止时间（不含），ISO 8601 格式 |
| page | integer | 否 | 页码，默认 1 |
| page_size | integer | 否 | 每页条数，1-100，默认 20 |
| include_summary | boolean | 否 | 是否包含摘要和翻译，默认 true |

> 注意：`author` 和 `authors` 参数不能同时使用。

**请求示例**:
```bash
# 搜索包含 "AI" 的推文
curl "http://localhost:8000/api/search/tweets?q=AI" \
  -H "X-API-Key: your_api_key"

# 搜索特定作者的推文
curl "http://localhost:8000/api/search/tweets?q=GPT&author=OpenAI" \
  -H "X-API-Key: your_api_key"

# 限定时间范围搜索
curl "http://localhost:8000/api/search/tweets?q=AI&since=2026-02-01T00:00:00Z&until=2026-02-24T00:00:00Z" \
  -H "X-API-Key: your_api_key"
```

**响应**:
```json
{
  "items": [
    {
      "tweet_id": "1234567890",
      "text": "AI is transforming...",
      "author_username": "OpenAI",
      "created_at": "2026-02-24T09:31:48Z",
      "summary_text": "中文摘要...",
      "translation_text": "翻译文本..."
    }
  ],
  "count": 5,
  "total": 25,
  "page": 1,
  "page_size": 20,
  "total_pages": 2,
  "q": "AI"
}
```

---

## 主题 API（普通用户）

主题 API 用于管理个人主题，支持 CRUD 操作、关联账号管理和主题摘要生成。每个用户只能访问自己创建的主题（管理员可访问所有主题）。

### 1. 创建主题

**端点**: `POST /api/topics`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 主题名称 |
| description | string | 否 | 主题描述 |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/topics" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"name": "AI 动态", "description": "追踪 AI 领域最新进展"}'
```

### 2. 获取主题列表

**端点**: `GET /api/topics`

**请求示例**:
```bash
curl "http://localhost:8000/api/topics" \
  -H "X-API-Key: your_api_key"
```

### 3. 获取主题详情

**端点**: `GET /api/topics/{topic_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/topics/1" \
  -H "X-API-Key: your_api_key"
```

### 4. 更新主题

**端点**: `PUT /api/topics/{topic_id}`

**请求示例**:
```bash
curl -X PUT "http://localhost:8000/api/topics/1" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"name": "AI 前沿", "description": "更新后的描述"}'
```

### 5. 删除主题

**端点**: `DELETE /api/topics/{topic_id}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/topics/1" \
  -H "X-API-Key: your_api_key"
```

### 6. 设置关联账号

批量设置主题关联的 Twitter 账号（覆盖原有关联）。

**端点**: `PUT /api/topics/{topic_id}/accounts`

**请求示例**:
```bash
curl -X PUT "http://localhost:8000/api/topics/1/accounts" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"usernames": ["elonmusk", "OpenAI"]}'
```

### 7. 添加单个关联账号

**端点**: `POST /api/topics/{topic_id}/accounts/{username}`

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/topics/1/accounts/nvidia" \
  -H "X-API-Key: your_api_key"
```

### 8. 移除关联账号

**端点**: `DELETE /api/topics/{topic_id}/accounts/{username}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/topics/1/accounts/nvidia" \
  -H "X-API-Key: your_api_key"
```

### 9. 创建摘要任务

异步创建主题摘要任务，由 LLM 对主题关联账号的推文进行汇总分析。

**端点**: `POST /api/topics/summary-tasks`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| topic_id | integer | 是 | 主题 ID |
| time_span_hours | integer | 否 | 时间跨度（小时） |
| deadline | string | 否 | 截止时间，ISO 8601 格式 |
| custom_prompt | string | 否 | 自定义摘要提示词 |
| tz_offset | integer | 否 | 时区偏移（分钟） |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/topics/summary-tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"topic_id": 1, "time_span_hours": 24}'
```

**响应** (202 Accepted):
```json
{
  "id": 1,
  "topic_id": 1,
  "status": "pending",
  "time_span_hours": 24
}
```

### 10. 获取摘要任务列表

**端点**: `GET /api/topics/summary-tasks`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| topic_id | integer | 否 | 按主题 ID 过滤 |

**请求示例**:
```bash
curl "http://localhost:8000/api/topics/summary-tasks?topic_id=1" \
  -H "X-API-Key: your_api_key"
```

### 11. 获取摘要任务详情

**端点**: `GET /api/topics/summary-tasks/{task_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/topics/summary-tasks/1" \
  -H "X-API-Key: your_api_key"
```

### 12. 获取主题最新摘要

**端点**: `GET /api/topics/{topic_id}/latest-summary`

**请求示例**:
```bash
curl "http://localhost:8000/api/topics/1/latest-summary" \
  -H "X-API-Key: your_api_key"
```

### 13. 生成配图提示词

基于摘要内容生成配图提示词（用于 AI 绘图）。

**端点**: `POST /api/topics/summary-tasks/{task_id}/generate-image-prompt`

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/topics/summary-tasks/1/generate-image-prompt" \
  -H "X-API-Key: your_api_key"
```

### 14. 获取默认摘要提示词

**端点**: `GET /api/topics/summary-tasks/default-prompt`

**请求示例**:
```bash
curl "http://localhost:8000/api/topics/summary-tasks/default-prompt" \
  -H "X-API-Key: your_api_key"
```

### 15. 删除摘要任务

**端点**: `DELETE /api/topics/summary-tasks/{task_id}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/topics/summary-tasks/1" \
  -H "X-API-Key: your_api_key"
```

---

## 发文频次分析 API（普通用户）

分析主题关联账号的发文时间分布。

### 获取发文频次分布

**端点**: `GET /api/analytics/topics/{topic_id}/posting-frequency`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tz_offset | integer | 否 | 时区偏移（分钟），默认 0 |
| slots | integer | 否 | 时间槽数量，1-336，默认 50 |

**请求示例**:
```bash
curl "http://localhost:8000/api/analytics/topics/1/posting-frequency?tz_offset=-480&slots=48" \
  -H "X-API-Key: your_api_key"
```

**响应**:
```json
{
  "topic_id": 1,
  "topic_name": "AI 动态",
  "slot_minutes": 30,
  "slots": 48,
  "tz_offset": -480,
  "time_range": {
    "start": "2026-02-23T00:00:00",
    "end": "2026-02-24T00:00:00"
  },
  "distribution": [
    {"slot": 0, "count": 5},
    {"slot": 1, "count": 3}
  ],
  "total_tweets": 120
}
```

---

## 推文 API（管理员）

推文 API 用于管理员查询已抓取的推文列表和详情。

### 1. 获取推文列表

**端点**: `GET /api/tweets`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | integer | 否 | 页码，从 1 开始，默认 1 |
| page_size | integer | 否 | 每页数量，1-100，默认 20 |
| author | string | 否 | 按作者用户名筛选 |
| created_after | datetime | 否 | 推文创建时间起始（含），ISO 8601 格式 |
| created_before | datetime | 否 | 推文创建时间截止（不含），ISO 8601 格式 |

**请求示例**:
```bash
# 获取第一页
curl "http://localhost:8000/api/tweets?page=1&page_size=20" \
  -H "X-API-Key: your_admin_api_key"

# 按作者筛选
curl "http://localhost:8000/api/tweets?author=elonmusk" \
  -H "X-API-Key: your_admin_api_key"
```

**响应**:
```json
{
  "items": [
    {
      "tweet_id": "1234567890",
      "text": "Hello World",
      "author_username": "elonmusk",
      "author_display_name": "Elon Musk",
      "created_at": "2026-02-06T09:31:48",
      "reference_type": "retweeted",
      "referenced_tweet_id": null,
      "has_summary": true,
      "media_count": 0
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "total_pages": 5
}
```

### 2. 获取推文详情

**端点**: `GET /api/tweets/{tweet_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/tweets/1234567890" \
  -H "X-API-Key: your_admin_api_key"
```

**响应**: 在列表项字段基础上，额外包含 `media`（媒体附件）、`summary`（摘要信息）。

---

## 抓取 API（管理员）

抓取 API 用于从 X（Twitter）平台获取推文数据。

### 1. 手动触发抓取

启动一个后台抓取任务。

**端点**: `POST /api/admin/scrape`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| usernames | string | 是 | 逗号分隔的用户名列表 |
| limit | integer | 否 | 每个用户抓取数量，默认 100，范围 1-1000 |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/admin/scrape" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_admin_api_key" \
  -d '{
    "usernames": "elonmusk,OpenAI,nvidia",
    "limit": 50
  }'
```

**响应** (202 Accepted):
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending"
}
```

### 2. 查询任务状态

查询抓取任务的执行状态和结果。

**端点**: `GET /api/admin/scrape/{task_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/admin/scrape/a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "X-API-Key: your_admin_api_key"
```

**响应**:
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "result": {
    "total_users": 3,
    "successful_users": 3,
    "failed_users": 0,
    "total_tweets": 150,
    "new_tweets": 140,
    "skipped_tweets": 10,
    "total_errors": 0,
    "elapsed_seconds": 8.5
  },
  "progress": {
    "current": 150,
    "total": 150,
    "percentage": 100.0
  },
  "created_at": "2025-01-15T10:30:00",
  "started_at": "2025-01-15T10:30:01",
  "completed_at": "2025-01-15T10:32:15"
}
```

**任务状态说明**:

| 状态 | 说明 |
|------|------|
| pending | 任务已创建，等待执行 |
| running | 任务正在执行 |
| completed | 任务执行成功 |
| failed | 任务执行失败 |

### 3. 列出所有任务

获取所有抓取任务列表。

**端点**: `GET /api/admin/scrape`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | 按状态过滤：pending, running, completed, failed |

**请求示例**:
```bash
# 获取所有任务
curl "http://localhost:8000/api/admin/scrape" \
  -H "X-API-Key: your_admin_api_key"

# 按状态过滤
curl "http://localhost:8000/api/admin/scrape?status=completed" \
  -H "X-API-Key: your_admin_api_key"
```

### 4. 删除任务

删除已完成的任务记录。

**端点**: `DELETE /api/admin/scrape/{task_id}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/admin/scrape/a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -H "X-API-Key: your_admin_api_key"
```

**响应**:
```json
{
  "message": "任务 a1b2c3d4-e5f6-7890-abcd-ef1234567890 已删除"
}
```

---

## 抓取配置 API（管理员）

抓取配置 API 用于管理平台级抓取账号。

### 1. 添加抓取账号

**端点**: `POST /api/admin/scraping/follows`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | Twitter 用户名 |
| reason | string | 是 | 添加理由（至少 5 个字符） |
| added_by | string | 否 | 添加者 |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/admin/scraping/follows" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_admin_api_key" \
  -d '{"username": "elonmusk", "reason": "Tesla CEO, AI leader", "added_by": "admin"}'
```

### 2. 获取抓取账号列表

**端点**: `GET /api/admin/scraping/follows`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| include_inactive | boolean | 否 | 是否包含非活跃账号，默认 false |

**请求示例**:
```bash
curl "http://localhost:8000/api/admin/scraping/follows" \
  -H "X-API-Key: your_admin_api_key"
```

### 3. 更新抓取账号

**端点**: `PUT /api/admin/scraping/follows/{username}`

**请求示例**:
```bash
curl -X PUT "http://localhost:8000/api/admin/scraping/follows/elonmusk" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_admin_api_key" \
  -d '{"reason": "Updated reason", "is_active": true}'
```

### 4. 删除抓取账号

软删除（标记为非活跃）。

**端点**: `DELETE /api/admin/scraping/follows/{username}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/admin/scraping/follows/elonmusk" \
  -H "X-API-Key: your_admin_api_key"
```

---

## 摘要 API（管理员）

摘要 API 用于生成推文的中文摘要和翻译。

### 1. 批量生成摘要

对指定推文列表生成摘要。

**端点**: `POST /api/summaries/batch`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tweet_ids | array[string] | 是 | 推文 ID 列表 |
| force_refresh | boolean | 否 | 是否强制刷新缓存，默认 false |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/summaries/batch" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_admin_api_key" \
  -d '{
    "tweet_ids": ["1234567890", "0987654321"],
    "force_refresh": false
  }'
```

**响应** (202 Accepted):
```json
{
  "task_id": "c3d4e5f6-g7h8-9012-cdef-gh3456789012",
  "status": "pending"
}
```

### 2. 查询推文摘要

获取单条推文的摘要。

**端点**: `GET /api/summaries/tweets/{tweet_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/summaries/tweets/1234567890" \
  -H "X-API-Key: your_admin_api_key"
```

**响应**:
```json
{
  "tweet_id": "1234567890",
  "summary_chinese": "这是一个关于 AI 技术的推文摘要...",
  "original_text": "Original tweet text here...",
  "created_at": "2025-01-15T12:00:00",
  "updated_at": "2025-01-15T12:00:05",
  "cache_hit": true
}
```

### 3. 重新生成摘要

强制重新生成推文摘要（忽略缓存）。

**端点**: `POST /api/summaries/tweets/{tweet_id}/regenerate`

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/summaries/tweets/1234567890/regenerate" \
  -H "X-API-Key: your_admin_api_key"
```

### 4. 查询成本统计

查询 LLM API 调用的成本和 token 使用统计。

**端点**: `GET /api/summaries/stats`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| start_date | string | 否 | 统计开始日期（ISO 8601 格式） |
| end_date | string | 否 | 统计结束日期（ISO 8601 格式） |

**请求示例**:
```bash
# 全部统计
curl "http://localhost:8000/api/summaries/stats" \
  -H "X-API-Key: your_admin_api_key"

# 按日期范围过滤
curl "http://localhost:8000/api/summaries/stats?start_date=2025-01-01&end_date=2025-01-31" \
  -H "X-API-Key: your_admin_api_key"
```

**响应**:
```json
{
  "start_date": "2025-01-01T00:00:00",
  "end_date": "2025-01-31T23:59:59",
  "total_cost_usd": 1.25,
  "total_tokens": 125000,
  "prompt_tokens": 100000,
  "completion_tokens": 25000,
  "provider_breakdown": {
    "minimax": {
      "cost_usd": 1.00,
      "tokens": 100000
    },
    "openrouter": {
      "cost_usd": 0.25,
      "tokens": 25000
    }
  }
}
```

### 5. 查询摘要任务状态

**端点**: `GET /api/summaries/tasks/{task_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/summaries/tasks/c3d4e5f6-g7h8-9012-cdef-gh3456789012" \
  -H "X-API-Key: your_admin_api_key"
```

### 6. 删除摘要任务

**端点**: `DELETE /api/summaries/tasks/{task_id}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/summaries/tasks/c3d4e5f6-g7h8-9012-cdef-gh3456789012" \
  -H "X-API-Key: your_admin_api_key"
```

---

## 监控 API（公开）

系统提供 Prometheus 格式的监控指标，无需认证即可访问。

### Prometheus 指标端点

**端点**: `GET /metrics`

**请求示例**:
```bash
curl http://localhost:8000/metrics
```

**可用指标**:

| 指标名称 | 类型 | 描述 |
|---------|------|------|
| http_requests_total | Counter | HTTP 请求总数（按方法、路径、状态码分类） |
| http_request_duration_seconds | Histogram | HTTP 请求延迟分布 |
| active_tasks | Gauge | 当前活跃任务数 |
| tasks_total | Counter | 任务总数（按状态分类） |
| db_pool_size | Gauge | 数据库连接池大小 |
| db_pool_available | Gauge | 可用数据库连接数 |

### Prometheus 配置示例

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'x-watcher'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

---

## 错误处理

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 201 | 资源创建成功 |
| 202 | 请求已接受，任务在后台执行 |
| 204 | 操作成功，无返回内容 |
| 400 | 请求参数错误 |
| 401 | 未认证（缺少或无效的 API Key / JWT） |
| 403 | 权限不足（普通用户访问管理员端点，或访问他人资源） |
| 404 | 资源不存在 |
| 409 | 请求冲突（如重复创建任务） |
| 422 | 参数校验失败（格式正确但值无效） |
| 500 | 服务器内部错误 |

### 错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

**示例**:
```json
{
  "detail": "任务不存在: a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

## 代码示例

### Python 示例

```python
import requests
import time

BASE_URL = "http://localhost:8000"
API_KEY = "your_api_key"
ADMIN_API_KEY = "your_admin_api_key"
HEADERS = {"X-API-Key": API_KEY}
ADMIN_HEADERS = {"X-API-Key": ADMIN_API_KEY}

# === 普通用户操作 ===

# 1. 浏览某天的推文
response = requests.get(
    f"{BASE_URL}/api/browse/tweets",
    params={"date": "2026-02-24", "page": 1, "page_size": 20},
    headers=HEADERS,
)
tweets = response.json()
print(f"今日推文: {tweets['total']} 条")

# 2. 搜索推文
response = requests.get(
    f"{BASE_URL}/api/search/tweets",
    params={"q": "AI", "page_size": 10},
    headers=HEADERS,
)
results = response.json()
print(f"搜索结果: {results['total']} 条")

# 3. 获取信息流
response = requests.get(
    f"{BASE_URL}/api/feed",
    params={"since": "2026-02-23T00:00:00Z"},
    headers=HEADERS,
)
feed = response.json()
print(f"信息流: {feed['count']} 条")

# === 管理员操作 ===

# 4. 启动抓取任务
response = requests.post(
    f"{BASE_URL}/api/admin/scrape",
    json={"usernames": "elonmusk,OpenAI", "limit": 10},
    headers=ADMIN_HEADERS,
)
task_id = response.json()["task_id"]
print(f"任务已创建: {task_id}")

# 5. 轮询任务状态
while True:
    response = requests.get(
        f"{BASE_URL}/api/admin/scrape/{task_id}",
        headers=ADMIN_HEADERS,
    )
    data = response.json()

    if data["status"] in ["completed", "failed"]:
        print(f"任务完成: {data}")
        break

    print(f"任务状态: {data['status']}, 进度: {data['progress']['percentage']}%")
    time.sleep(2)
```

### JavaScript/TypeScript 示例

```typescript
const BASE_URL = 'http://localhost:8000';
const API_KEY = 'your_api_key';
const ADMIN_API_KEY = 'your_admin_api_key';

// 普通用户 headers
const userHeaders = { 'X-API-Key': API_KEY };
const adminHeaders = { 'X-API-Key': ADMIN_API_KEY };

// 1. 浏览推文（普通用户）
async function browseTweets(date: string) {
  const response = await fetch(
    `${BASE_URL}/api/browse/tweets?date=${date}&page=1&page_size=20`,
    { headers: userHeaders }
  );
  return await response.json();
}

// 2. 搜索推文（普通用户）
async function searchTweets(query: string) {
  const response = await fetch(
    `${BASE_URL}/api/search/tweets?q=${encodeURIComponent(query)}`,
    { headers: userHeaders }
  );
  return await response.json();
}

// 3. 获取信息流（普通用户）
async function getFeed(since: string) {
  const response = await fetch(
    `${BASE_URL}/api/feed?since=${since}`,
    { headers: userHeaders }
  );
  return await response.json();
}

// 4. 启动抓取任务（管理员）
async function startScraping(usernames: string, limit = 10) {
  const response = await fetch(`${BASE_URL}/api/admin/scrape`, {
    method: 'POST',
    headers: { ...adminHeaders, 'Content-Type': 'application/json' },
    body: JSON.stringify({ usernames, limit })
  });
  return await response.json();
}

// 使用示例
(async () => {
  // 普通用户：浏览和搜索
  const tweets = await browseTweets('2026-02-24');
  console.log('今日推文:', tweets.total);

  const results = await searchTweets('AI');
  console.log('搜索结果:', results.total);

  // 管理员：抓取
  const { task_id } = await startScraping('elonmusk,OpenAI', 10);
  console.log('任务创建:', task_id);
})();
```

### curl 脚本示例

```bash
#!/bin/bash

BASE_URL="http://localhost:8000"
API_KEY="your_api_key"
ADMIN_API_KEY="your_admin_api_key"

# === 普通用户操作 ===

# 浏览今天的推文
echo "浏览推文..."
curl -s "$BASE_URL/api/browse/tweets?date=2026-02-24&page=1" \
  -H "X-API-Key: $API_KEY" | jq '.total'

# 搜索推文
echo "搜索推文..."
curl -s "$BASE_URL/api/search/tweets?q=AI" \
  -H "X-API-Key: $API_KEY" | jq '.total'

# === 管理员操作 ===

# 启动抓取任务
echo "启动抓取任务..."
RESPONSE=$(curl -s -X POST "$BASE_URL/api/admin/scrape" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{"usernames": "elonmusk", "limit": 10}')

TASK_ID=$(echo $RESPONSE | jq -r '.task_id')
echo "任务 ID: $TASK_ID"

# 轮询任务状态
while true; do
  RESPONSE=$(curl -s "$BASE_URL/api/admin/scrape/$TASK_ID" \
    -H "X-API-Key: $ADMIN_API_KEY")
  STATUS=$(echo $RESPONSE | jq -r '.status')

  echo "任务状态: $STATUS"

  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    echo "任务完成!"
    echo $RESPONSE | jq '.'
    break
  fi

  sleep 2
done
```

---

## 附录

### 用户名格式规则

- 长度：1-15 字符
- 允许字符：字母、数字、下划线
- 示例：`elonmusk`, `OpenAI`, `nvidia_news`

### 任务 ID 格式

任务 ID 是 UUID v4 格式：
```
a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### 日期时间格式

所有日期时间使用 ISO 8601 格式：
```
2025-01-15T10:30:00
```

### 分页支持

支持分页的端点：
- `GET /api/browse/tweets` — `page` + `page_size`
- `GET /api/search/tweets` — `page` + `page_size`
- `GET /api/tweets` — `page` + `page_size`（管理员）

### 权限速查表

| 端点 | 权限 | 说明 |
|------|------|------|
| `GET /health` | 公开 | 健康检查 |
| `GET /metrics` | 公开 | Prometheus 指标 |
| `/api/auth/*` | 公开 | 登录、注册 |
| `GET /api/browse/*` | 普通用户 | 按日期浏览推文 |
| `GET /api/feed` | 普通用户 | 时间区间信息流 |
| `GET /api/search/tweets` | 普通用户 | 全文搜索 |
| `/api/topics/*` | 普通用户 | 主题管理和摘要 |
| `GET /api/analytics/topics/*/posting-frequency` | 普通用户 | 发文频次分析 |
| `/api/users/*` | 普通用户 | 用户信息和 API Key 管理 |
| `GET /api/status` | 普通用户 | 系统状态 |
| `/api/tweets/*` | 管理员 | 原始推文查询 |
| `/api/summaries/*` | 管理员 | 推文摘要管理 |
| `/api/admin/*` | 管理员 | 抓取、配置、同步、用户管理等 |

---

## 获取帮助

如有问题或建议，请：
- 提交 Issue: [GitHub Issues]
- 查看项目文档: `docs/` 目录
- 查看 API 文档: `http://localhost:8000/docs`
