# Requirements Document

## Introduction

新闻摘要翻译模块（News Summarizer）是 X-watcher 的核心组件之一，负责对推文进行智能摘要提取和英译中翻译。该模块独立于去重服务运行，可处理任意推文。当推文属于去重组时，利用去重信息优化处理（同组共享摘要）；当推文无去重组时，独立生成摘要。确保高管用户能够快速获取推文的关键信息，并提供中文翻译以降低阅读成本。

## Requirements

### Requirement 1: 智能摘要生成

**Objective:** 作为系统，我需要使用 LLM 从推文中提取关键信息生成简明摘要，以便用户快速了解推文核心内容。

#### Acceptance Criteria

1. When 接收到推文时（无论是否经过去重），NewsSummarizer shall 使用 LLM 提取推文的关键信息并生成摘要
2. When 生成摘要时，NewsSummarizer shall 保留原始推文中的关键实体（人名、公司名、产品名等）
3. When 推文包含链接时，NewsSummarizer shall 在摘要中标注需要访问链接获取的详细信息
4. When 推文为非英文内容时，NewsSummarizer shall 跳过摘要生成或标记为"无需摘要"
5. When 推文长度 < 30 字时，NewsSummarizer shall 直接返回原文作为摘要，并标记 `is_generated_summary=False`
6. When 推文长度 ≥ 30 字时，NewsSummarizer shall 生成摘要，长度为原文长度的 50%-150%
7. The 摘要长度 shall 支持动态范围（1-500 字），根据原文长度自适应

### Requirement 2: 英译中翻译

**Objective:** 作为系统，我需要将英文推文及其摘要翻译为中文，以便中文用户能够无障碍阅读英文内容。

#### Acceptance Criteria

1. When 推文原始语言为英文时，NewsSummarizer shall 将推文全文翻译为中文
2. When 推文已有英文摘要时，NewsSummarizer shall 将摘要翻译为中文
3. When 推文包含技术术语或专有名词时，NewsSummarizer shall 保留原文或提供中英文对照
4. When 推文包含 URL 时，NewsSummarizer shall 保持 URL 不变，不翻译链接内容
5. The 翻译结果 shall 保持原文的语气和情感倾向

### Requirement 3: 多模型支持与降级策略

**Objective:** 作为系统，我需要支持多个 LLM 提供商并实现自动降级，以便在主模型失败时仍能提供服务。

#### Acceptance Criteria

1. When 执行摘要或翻译任务时，NewsSummarizer shall 优先使用 Claude Sonnet via OpenRouter
2. When OpenRouter 请求失败或超时（超过 30 秒）时，NewsSummarizer shall 自动切换到 MiniMax 中国版
3. When MiniMax 中国版也失败时，NewsSummarizer shall 切换到开源模型（如 Qwen 或 DeepSeek）
4. When 所有模型都失败时，NewsSummarizer shall 标记该推文为"处理失败"并记录错误信息
5. The 模型切换 shall 对调用方透明，不影响业务流程

### Requirement 4: 结果缓存

**Objective:** 作为系统，我需要缓存摘要和翻译结果，以便避免对相同内容重复调用 LLM API。

#### Acceptance Criteria

1. When 推文内容已有缓存摘要时，NewsSummarizer shall 直接返回缓存结果而不调用 LLM
2. When 推文属于同一去重组时，NewsSummarizer shall 共享同一份摘要和翻译结果（作为优化策略，非前提条件）
3. When 缓存命中时，NewsSummarizer shall 记录缓存命中统计
4. The 缓存 shall 基于推文内容哈希（而非 tweet_id）作为键值
5. When 缓存超过 7 天时，NewsSummarizer shall 考虑缓存失效并允许重新生成

### Requirement 5: 批量处理与并发控制

**Objective:** 作为系统，我需要支持批量处理推文并控制并发数量，以便高效利用 API 资源同时避免速率限制。

#### Acceptance Criteria

1. When 接收一批推文进行摘要翻译时，NewsSummarizer shall 支持批量异步处理
2. When 执行批量处理时，NewsSummarizer shall 控制并发请求数不超过 5 个
3. When 检测到 API 速率限制（429 状态码）时，NewsSummarizer shall 自动退避并重试
4. When 单批推文数量超过 50 条时，NewsSummarizer shall 分批处理以避免超时
5. The 批量处理 shall 支持进度跟踪和部分失败处理

### Requirement 6: 成本统计

**Objective:** 作为系统，我需要记录每次 API 调用的 token 使用和成本，以便用户了解服务使用情况并优化成本。

#### Acceptance Criteria

1. When 调用 LLM API 时，NewsSummarizer shall 记录输入 token 数和输出 token 数
2. When 记录 token 使用时，NewsSummarizer shall 根据模型定价计算实际成本
3. When 批量处理完成时，NewsSummarizer shall 汇总本批次的总 token 使用和总成本
4. The 成本统计 shall 按模型类型分别记录
5. When 查询成本统计时，NewsSummarizer shall 支持按日期范围筛选

### Requirement 7: 数据模型与存储

**Objective:** 作为系统，我需要将摘要和翻译结果持久化存储，以便用户查询和历史记录追溯。

#### Acceptance Criteria

1. When 生成摘要或翻译完成时，NewsSummarizer shall 在 `tweets` 表中更新以下字段：
   - `summary`: 摘要内容（中文）
   - `translation`: 翻译内容（中文）
   - `summary_model`: 使用的模型名称
   - `summary_cached`: 是否来自缓存
2. When 记录处理结果时，NewsSummarizer shall 在 `summaries` 表中创建详细记录：
   - `summary_id`: 唯一标识（UUID）
   - `tweet_id`: 关联的推文 ID
   - `summary_text`: 摘要内容（中文），允许 1-500 字符
   - `translation_text`: 翻译内容（中文）
   - `model_provider`: 模型提供商（openrouter, minimax, open_source）
   - `model_name`: 模型名称
   - `prompt_tokens`: 输入 token 数
   - `completion_tokens`: 输出 token 数
   - `total_tokens`: 总 token 数
   - `cost_usd`: 成本（美元）
   - `cached`: 是否缓存命中
   - `is_generated_summary`: 是否为生成的摘要（False 表示原文太短直接返回）
   - `created_at`: 创建时间
3. When 更新推文摘要时，NewsSummarizer shall 使用事务确保数据一致性
4. When 处理失败时，NewsSummarizer shall 在 `summary_errors` 表中记录错误信息

### Requirement 8: API 集成

**Objective:** 作为系统，我需要提供 API 端点以便与现有工作流（抓取、去重等）集成。

#### Acceptance Criteria

1. When 推文入库后（通过抓取或去重流程），NewsSummarizer shall 可被触发进行摘要翻译处理
2. When 调用摘要翻译 API 时，NewsSummarizer shall 提供 `POST /api/summaries/batch` 端点接受推文 ID 列表
3. When 查询推文摘要时，NewsSummarizer shall 提供 `GET /api/summaries/tweets/{tweet_id}` 端点返回摘要详情
4. When 查询成本统计时，NewsSummarizer shall 提供 `GET /api/summaries/stats` 端点返回成本汇总
5. When 重新生成摘要时，NewsSummarizer shall 提供 `POST /api/summaries/tweets/{tweet_id}/regenerate` 端点强制重新生成

### Requirement 9: 配置管理

**Objective:** 作为系统，我需要支持灵活的配置管理，以便适配不同环境和用户需求。

#### Acceptance Criteria

1. When 配置 LLM 提供商时，NewsSummarizer shall 支持以下配置项：
   - OpenRouter: API Key、Base URL、Model Name
   - MiniMax 中国版: API Key、Base URL、Model Name、Group ID
   - 开源模型: API Key、Base URL、Model Name
2. When 配置摘要策略时，NewsSummarizer shall 支持以下参数：
   - `summary_enabled`: 是否启用摘要（默认 true）
   - `translation_enabled`: 是否启用翻译（默认 true）
   - `min_tweet_length_for_summary`: 推文最小长度阈值（默认 30 字）
   - `summary_min_length_ratio`: 摘要最小长度比例（默认 0.5）
   - `summary_max_length_ratio`: 摘要最大长度比例（默认 1.5）
   - `max_concurrent_requests`: 最大并发数（默认 5）
   - `cache_ttl_seconds`: 缓存有效期（默认 604800 秒，即 7 天）
3. When 未配置 API Key 时，NewsSummarizer shall 跳过对应提供商并尝试下一个
4. The 配置 shall 支持环境变量和配置文件两种方式

### Requirement 10: 性能要求

**Objective:** 作为系统，我需要确保摘要翻译处理在合理时间内完成。

#### Acceptance Criteria

1. When 处理单条推文时，NewsSummarizer shall 在 10 秒内完成摘要和翻译
2. When 批量处理 10 条推文时，NewsSummarizer shall 在 30 秒内完成
3. When 批量处理 50 条推文时，NewsSummarizer shall 在 120 秒内完成
4. When 使用缓存时，NewsSummarizer shall 在 100 毫秒内返回结果
5. The 内存占用 shall 在批量处理 50 条推文时不超过 200MB

---

## Requirement Coverage Summary

| Requirement ID | Title | Priority |
|----------------|-------|----------|
| 1 | 智能摘要生成 | High |
| 2 | 英译中翻译 | High |
| 3 | 多模型支持与降级策略 | High |
| 4 | 结果缓存 | Medium |
| 5 | 批量处理与并发控制 | High |
| 6 | 成本统计 | Medium |
| 7 | 数据模型与存储 | High |
| 8 | API 集成 | High |
| 9 | 配置管理 | Medium |
| 10 | 性能要求 | Medium |

## Notes

- 摘要和翻译处理可在去重后自动执行，也可独立触发。去重组内的推文共享同一份结果（优化策略），无去重组的推文独立处理
- LLM 模型的 prompt 需要精心设计，确保摘要质量和翻译准确性
- 成本统计对用户透明，帮助用户了解服务使用情况
- 支持手动重新生成摘要，当用户对自动生成结果不满意时可以触发
- 初期可以只实现 OpenRouter 和 MiniMax 两个提供商，开源模型作为后续扩展
