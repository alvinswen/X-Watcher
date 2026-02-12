# 需求文档

## 项目描述（输入）
实现 Feed API，为外部 Agent（nanobot）提供按时间区间查询推文的 HTTP 接口。用户运行独立的 nanobot 进程，每天多次访问本系统，通过 since/until 参数获取指定时间区间内的所有推文完整内容（含摘要和翻译），然后通过 Agent 自身的消息渠道推送给用户。

## 需求

### 需求 1: 按时间区间查询推文
**目标:** 作为外部 Agent（nanobot），我需要按时间区间获取推文列表，以便增量拉取自上次访问以来的新数据。

#### 验收标准
1. When 客户端发送 `GET /api/feed` 请求并携带 `since` 参数（ISO 8601 格式）, the Feed API shall 返回 `db_created_at >= since` 的所有推文。
2. When 客户端同时携带 `since` 和 `until` 参数, the Feed API shall 返回 `db_created_at >= since AND db_created_at < until` 的推文。
3. When 客户端未提供 `until` 参数, the Feed API shall 使用当前服务器时间作为默认截止时间。
4. When 客户端未提供 `since` 参数, the Feed API shall 返回 HTTP 422 错误，提示 `since` 为必填参数。
5. The Feed API shall 按 `created_at`（推文原始发布时间）倒序排列返回结果。

### 需求 2: 返回推文完整内容
**目标:** 作为外部 Agent，我需要一次获取每条推文的全部信息（正文、作者、媒体、摘要、翻译），以便直接格式化并推送给用户，无需二次请求。

#### 验收标准
1. The Feed API shall 为每条推文返回以下字段：`tweet_id`, `text`, `author_username`, `author_display_name`, `created_at`, `db_created_at`, `reference_type`, `referenced_tweet_id`, `media`。
2. When `include_summary` 参数为 `true`（默认值）, the Feed API shall 对每条推文 LEFT JOIN 摘要表，返回 `summary_text` 和 `translation_text` 字段。
3. When `include_summary` 参数为 `false`, the Feed API shall 不加载摘要数据，仅返回推文基础字段。
4. When 某条推文尚无摘要记录, the Feed API shall 将该推文的 `summary_text` 和 `translation_text` 返回为 `null`。

### 需求 3: 响应格式与元数据
**目标:** 作为外部 Agent，我需要清晰的响应结构和元数据，以便判断数据完整性和是否需要后续请求。

#### 验收标准
1. The Feed API shall 返回 JSON 响应，包含 `items`（推文列表）、`count`（本次返回条数）、`total`（满足条件的总条数）、`since`（实际起始时间）、`until`（实际截止时间）字段。
2. When 返回的 `count` 小于 `total`, the Feed API shall 在响应中设置 `has_more` 为 `true`。
3. When 返回的 `count` 等于 `total`, the Feed API shall 在响应中设置 `has_more` 为 `false`。
4. The Feed API shall 返回 `until` 字段的精确时间值，供客户端作为下次请求的 `since` 参数使用。

### 需求 4: 结果数量控制
**目标:** 作为系统管理员，我需要对单次返回的推文数量设置上限，以防止过大的响应负载影响系统性能。

#### 验收标准
1. The Feed API shall 支持 `limit` 可选参数，用于限制单次返回的最大推文数量。
2. When 客户端未提供 `limit` 参数, the Feed API shall 使用配置项 `FEED_MAX_TWEETS`（默认 200）作为上限。
3. When 满足条件的推文数量超过 `limit`, the Feed API shall 仅返回最新的 `limit` 条推文，并设置 `has_more` 为 `true`。
4. If 客户端提供的 `limit` 值超过系统配置上限, the Feed API shall 使用系统配置上限替代客户端提供的值。

### 需求 5: 认证与安全
**目标:** 作为系统管理员，我需要确保 Feed API 受到认证保护，防止未授权的数据访问。

#### 验收标准
1. The Feed API shall 要求请求携带有效的 API Key（通过 `X-API-Key` 请求头）。
2. If 请求未携带 API Key 或 API Key 无效, the Feed API shall 返回 HTTP 401 Unauthorized 错误。
3. The Feed API shall 复用现有的 API Key 认证机制（`src/user/api/auth.py`）。

### 需求 6: Agent 工具定义
**目标:** 作为 Agent 开发者，我需要 Feed API 的工具元数据描述，以便在 nanobot 中注册和调用。

#### 验收标准
1. The Agent 模块 shall 提供 Feed API 的工具元数据定义，包含工具名称、描述、端点 URL 和参数说明。
2. The Agent 模块 shall 更新系统提示（SYSTEM_PROMPT），说明 Agent 可通过 Feed API 获取增量推文。
3. The 工具元数据 shall 覆盖以下 API 端点：`GET /api/feed`（Feed 查询）、`GET /api/tweets/{tweet_id}`（推文详情）。

### 需求 7: 错误处理
**目标:** 作为外部 Agent，我需要明确的错误响应格式，以便程序化处理异常情况。

#### 验收标准
1. If `since` 或 `until` 参数格式不符合 ISO 8601, the Feed API shall 返回 HTTP 422 错误，包含具体的参数验证失败信息。
2. If `since` 时间晚于 `until` 时间, the Feed API shall 返回 HTTP 422 错误，提示时间区间无效。
3. If 数据库查询过程中发生异常, the Feed API shall 返回 HTTP 500 错误，并记录错误日志。
4. The Feed API shall 使用统一的错误响应格式 `{"detail": "错误描述"}`，与项目现有 API 风格保持一致。
