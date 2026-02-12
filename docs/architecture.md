# 架构文档

## 概述

X-watcher 采用分层架构设计，结合 AI 摘要能力，为 Agent 提供结构化的 X 平台信息监控服务。

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                         客户端                                │
│                  (Web SPA / API / curl)                      │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      API 层 (FastAPI)                         │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │ CORS 中间件 │  │ Prometheus │  │    路由 (7 个模块)    │  │
│  └────────────┘  └────────────┘  └──────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Service 层 (业务编排)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Scraping │ │ Dedup    │ │Summarize │ │ Preference   │  │
│  │ Service  │ │ Service  │ │ Service  │ │ Service      │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      Data 层                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  数据库  │ │ MiniMax  │ │OpenRouter│ │  X 平台 API  │  │
│  │(SQLite/PG)│ │ API(LLM)│ │ API(LLM) │ │(TwitterAPI.io)│  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 数据模型

### 基础模型（src/database/models.py）

#### User (用户)
- `id`: 主键
- `name`: 用户名
- `email`: 邮箱（唯一）
- `is_admin`: 是否管理员
- `created_at`: 创建时间

#### Preference (偏好)
- `id`: 主键
- `user_id`: 用户 ID（外键）
- `key`: 偏好键
- `value`: 偏好值

#### NewsItem (新闻)
- `id`: 主键
- `user_id`: 用户 ID（外键）
- `content`: 新闻内容
- `source`: 来源
- `created_at`: 创建时间

#### ScraperFollow (平台抓取账号)
- `id`: 主键
- `username`: Twitter 用户名（唯一）
- `added_at`: 添加时间
- `reason`: 添加理由
- `added_by`: 添加者
- `is_active`: 是否活跃

#### TwitterFollow (用户关注)
- `id`: 主键
- `user_id`: 用户 ID（外键）
- `username`: Twitter 用户名
- `priority`: 优先级（1-10）
- `created_at`, `updated_at`: 时间戳

#### FilterRule (过滤规则)
- `id`: UUID 主键
- `user_id`: 用户 ID（外键）
- `filter_type`: 类型（keyword/hashtag/content_type）
- `value`: 规则值
- `created_at`: 创建时间

### 抓取模型（src/scraper/infrastructure/models.py）

#### TweetOrm (推文)
- `tweet_id`: 主键
- `text`: 推文内容
- `created_at`: 推文创建时间
- `author_username`: 作者用户名
- `author_display_name`: 作者显示名称
- `referenced_tweet_id`: 引用的推文 ID
- `reference_type`: 引用类型
- `media`: JSON 媒体附件
- `deduplication_group_id`: 去重组 ID
- `db_created_at`, `db_updated_at`: 数据库时间戳

#### DeduplicationGroupOrm (去重组)
- `group_id`: 主键
- `representative_tweet_id`: 代表推文 ID
- `deduplication_type`: 去重类型
- `similarity_score`: 相似度分数
- `tweet_ids`: JSON 推文 ID 列表
- `created_at`: 创建时间

## 数据流

```
用户请求 (Web / API)
    ↓
API 层接收请求 (FastAPI 路由)
    ↓
Service 层编排业务逻辑
    ↓
Infrastructure 层执行操作 (数据库 / 外部 API)
    ↓
结果返回给用户
```

## 部署架构

### 开发环境
- 数据库: SQLite (本地文件)
- LLM: MiniMax M2.1 / OpenRouter (Claude Sonnet 4.5)
- Web 服务器: Uvicorn 开发模式

### 生产环境 (计划)
- 数据库: PostgreSQL
- LLM: MiniMax M2.1 / OpenRouter (Claude Sonnet 4.5)
- Web 服务器: Uvicorn + Gunicorn
- 容器化: Docker
- 反向代理: Nginx

## 扩展性设计

### 当前阶段: API + Service 层
- FastAPI 路由直接调用 Service 层
- Service 层编排业务逻辑（抓取、去重、摘要、偏好）
- 支持双 LLM 提供商（MiniMax / OpenRouter）

### 未来阶段: Agent 集成 (按需)
当出现以下需求时，考虑引入 Agent 层：
- 需要自然语言意图理解和多步推理
- 不同功能需要使用不同 LLM（成本优化）
- 需要动态工具调度

演进方式：
```
当前: API → Service → Infrastructure
未来: API → Agent (意图理解) → Service → Infrastructure
```

## 安全考虑

- API 密钥通过环境变量配置
- `.env` 文件被 `.gitignore` 排除
- 生产环境 CORS 应限制具体域名
- 敏感信息不记录日志
