# API 使用指南

本文档详细介绍 SeriousNewsAgent 的 API 接口使用方法。

## 目录

- [快速开始](#快速开始)
- [推文 API](#推文-api)
- [抓取 API](#抓取-api)
- [抓取配置 API](#抓取配置-api)
- [去重 API](#去重-api)
- [摘要 API](#摘要-api)
- [偏好 API](#偏好-api)
- [监控 API](#监控-api)
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

大部分 API 端点无需认证即可访问。管理员抓取配置端点（`/api/admin/scraping/*`）需要通过 `X-API-Key` header 传递管理员 API Key 进行认证。

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

## 推文 API

推文 API 用于查询已抓取的推文列表和详情。

### 1. 获取推文列表

**端点**: `GET /api/tweets`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | integer | 否 | 页码，从 1 开始，默认 1 |
| page_size | integer | 否 | 每页数量，1-100，默认 20 |
| author | string | 否 | 按作者用户名筛选 |

**请求示例**:
```bash
# 获取第一页
curl "http://localhost:8000/api/tweets?page=1&page_size=20"

# 按作者筛选
curl "http://localhost:8000/api/tweets?author=elonmusk"
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
      "has_deduplication": false,
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
curl "http://localhost:8000/api/tweets/1234567890"
```

**响应**: 在列表项字段基础上，额外包含 `media`（媒体附件）、`summary`（摘要信息）、`deduplication`（去重信息）。

---

## 抓取 API

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
curl "http://localhost:8000/api/admin/scrape/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
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
curl "http://localhost:8000/api/admin/scrape"

# 按状态过滤
curl "http://localhost:8000/api/admin/scrape?status=completed"
```

### 4. 删除任务

删除已完成的任务记录。

**端点**: `DELETE /api/admin/scrape/{task_id}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/admin/scrape/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

**响应**:
```json
{
  "message": "任务 a1b2c3d4-e5f6-7890-abcd-ef1234567890 已删除"
}
```

---

## 抓取配置 API

抓取配置 API 用于管理平台级抓取账号。所有端点需要 `X-API-Key` header 认证。

### 认证方式

```bash
-H "X-API-Key: your_admin_api_key"
```

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

## 去重 API

去重 API 用于识别和合并重复或相似的推文内容。

### 1. 批量去重

对指定推文列表执行去重操作。

**端点**: `POST /api/deduplicate/batch`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tweet_ids | array[string] | 是 | 推文 ID 列表，最多 10000 条 |
| config | object | 否 | 去重配置（可选） |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/deduplicate/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "tweet_ids": [
      "1234567890",
      "0987654321",
      "1122334455"
    ]
  }'
```

**响应** (202 Accepted):
```json
{
  "task_id": "b2c3d4e5-f6g7-8901-bcde-fg2345678901",
  "status": "pending"
}
```

### 2. 查询去重组

查询指定去重组的详细信息。

**端点**: `GET /api/deduplicate/groups/{group_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/deduplicate/groups/grp_123456"
```

**响应**:
```json
{
  "group_id": "grp_123456",
  "representative_tweet_id": "1234567890",
  "deduplication_type": "similar_content",
  "similarity_score": 0.92,
  "tweet_ids": ["1234567890", "0987654321"],
  "created_at": "2025-01-15T11:00:00"
}
```

**去重类型说明**:

| 类型 | 说明 |
|------|------|
| exact_duplicate | 完全相同的推文 |
| similar_content | 相似内容的推文（基于文本相似度） |

### 3. 查询推文去重状态

查询指定推文的去重信息。

**端点**: `GET /api/deduplicate/tweets/{tweet_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/deduplicate/tweets/1234567890"
```

### 4. 撤销去重

删除去重组，恢复原始推文状态。

**端点**: `DELETE /api/deduplicate/groups/{group_id}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/deduplicate/groups/grp_123456"
```

### 5. 查询去重任务状态

**端点**: `GET /api/deduplicate/tasks/{task_id}`

**请求示例**:
```bash
curl "http://localhost:8000/api/deduplicate/tasks/b2c3d4e5-f6g7-8901-bcde-fg2345678901"
```

---

## 摘要 API

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
curl "http://localhost:8000/api/summaries/tweets/1234567890"
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
curl -X POST "http://localhost:8000/api/summaries/tweets/1234567890/regenerate"
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
curl "http://localhost:8000/api/summaries/stats"

# 按日期范围过滤
curl "http://localhost:8000/api/summaries/stats?start_date=2025-01-01&end_date=2025-01-31"
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
curl "http://localhost:8000/api/summaries/tasks/c3d4e5f6-g7h8-9012-cdef-gh3456789012"
```

### 6. 删除摘要任务

**端点**: `DELETE /api/summaries/tasks/{task_id}`

**请求示例**:
```bash
curl -X DELETE "http://localhost:8000/api/summaries/tasks/c3d4e5f6-g7h8-9012-cdef-gh3456789012"
```

---

## 偏好 API

偏好 API 用于管理用户的关注列表、过滤规则和排序偏好。

### 1. 关注管理

#### 添加关注

**端点**: `POST /api/preferences/follows?user_id={user_id}`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | Twitter 用户名 |
| priority | integer | 否 | 优先级（1-10） |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/preferences/follows?user_id=1" \
  -H "Content-Type: application/json" \
  -d '{"username": "elonmusk", "priority": 9}'
```

#### 获取关注列表

**端点**: `GET /api/preferences/follows?user_id={user_id}`

#### 删除关注

**端点**: `DELETE /api/preferences/follows/{username}?user_id={user_id}`

#### 更新优先级

**端点**: `PUT /api/preferences/follows/{username}/priority?user_id={user_id}`

### 2. 过滤规则

#### 添加过滤规则

**端点**: `POST /api/preferences/filters?user_id={user_id}`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| filter_type | string | 是 | 类型: keyword / hashtag / content_type |
| value | string | 是 | 规则值 |

**请求示例**:
```bash
curl -X POST "http://localhost:8000/api/preferences/filters?user_id=1" \
  -H "Content-Type: application/json" \
  -d '{"filter_type": "keyword", "value": "AI"}'
```

#### 获取过滤规则列表

**端点**: `GET /api/preferences/filters?user_id={user_id}`

#### 删除过滤规则

**端点**: `DELETE /api/preferences/filters/{rule_id}?user_id={user_id}`

### 3. 排序偏好

#### 设置排序方式

**端点**: `PUT /api/preferences/sorting?user_id={user_id}`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sort_type | string | 是 | 排序方式: time / relevance / priority |

#### 获取排序设置

**端点**: `GET /api/preferences/sorting?user_id={user_id}`

### 4. 获取综合偏好

**端点**: `GET /api/preferences?user_id={user_id}`

返回用户的关注列表、过滤规则和排序偏好的综合信息。

### 5. 个性化新闻流

**端点**: `GET /api/preferences/news?user_id={user_id}`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sort | string | 否 | 排序方式: time / relevance / priority |
| limit | integer | 否 | 返回数量，默认 20 |

**请求示例**:
```bash
curl "http://localhost:8000/api/preferences/news?user_id=1&sort=relevance&limit=20"
```

---

## 监控 API

系统提供 Prometheus 格式的监控指标。

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
  - job_name: 'serious-news-agent'
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
| 202 | 请求已接受，任务在后台执行 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 409 | 请求冲突（如重复创建任务） |
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

# 1. 启动抓取任务
response = requests.post(
    f"{BASE_URL}/api/admin/scrape",
    json={"usernames": "elonmusk,OpenAI", "limit": 10}
)
task_id = response.json()["task_id"]
print(f"任务已创建: {task_id}")

# 2. 轮询任务状态
while True:
    response = requests.get(f"{BASE_URL}/api/admin/scrape/{task_id}")
    data = response.json()

    if data["status"] in ["completed", "failed"]:
        print(f"任务完成: {data}")
        break

    print(f"任务状态: {data['status']}, 进度: {data['progress']['percentage']}%")
    time.sleep(2)

# 3. 批量去重
response = requests.post(
    f"{BASE_URL}/api/deduplicate/batch",
    json={"tweet_ids": ["1234567890", "0987654321"]}
)
dedup_task_id = response.json()["task_id"]

# 4. 生成摘要
response = requests.post(
    f"{BASE_URL}/api/summaries/batch",
    json={"tweet_ids": ["1234567890"], "force_refresh": False}
)
summary_task_id = response.json()["task_id"]

# 5. 查询推文摘要
response = requests.get(f"{BASE_URL}/api/summaries/tweets/1234567890")
summary = response.json()
print(f"摘要: {summary['summary_chinese']}")
```

### JavaScript/TypeScript 示例

```typescript
const BASE_URL = 'http://localhost:8000';

// 1. 启动抓取任务
async function startScraping(usernames: string, limit = 10) {
  const response = await fetch(`${BASE_URL}/api/admin/scrape`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ usernames, limit })
  });
  return await response.json();
}

// 2. 查询任务状态
async function getTaskStatus(taskId: string) {
  const response = await fetch(`${BASE_URL}/api/admin/scrape/${taskId}`);
  return await response.json();
}

// 3. 轮询任务完成
async function waitForTask(taskId: string) {
  while (true) {
    const task = await getTaskStatus(taskId);

    if (task.status === 'completed' || task.status === 'failed') {
      return task;
    }

    console.log(`任务状态: ${task.status}`);
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}

// 使用示例
(async () => {
  const { task_id } = await startScraping('elonmusk,OpenAI', 10);
  const result = await waitForTask(task_id);
  console.log('任务完成:', result);
})();
```

### curl 脚本示例

```bash
#!/bin/bash

BASE_URL="http://localhost:8000"

# 启动抓取任务
echo "启动抓取任务..."
RESPONSE=$(curl -s -X POST "$BASE_URL/api/admin/scrape" \
  -H "Content-Type: application/json" \
  -d '{"usernames": "elonmusk", "limit": 10}')

TASK_ID=$(echo $RESPONSE | jq -r '.task_id')
echo "任务 ID: $TASK_ID"

# 轮询任务状态
while true; do
  RESPONSE=$(curl -s "$BASE_URL/api/admin/scrape/$TASK_ID")
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

推文列表端点 (`GET /api/tweets`) 支持分页查询：
- `page`: 页码（从 1 开始，默认 1）
- `page_size`: 每页数量（1-100，默认 20）
- `author`: 按作者用户名筛选（可选）

---

## 获取帮助

如有问题或建议，请：
- 提交 Issue: [GitHub Issues]
- 查看项目文档: `docs/` 目录
- 查看 API 文档: `http://localhost:8000/docs`
