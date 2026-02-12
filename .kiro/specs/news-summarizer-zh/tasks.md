# Implementation Plan

## Overview

本实现计划将新闻摘要翻译模块（News Summarizer）分解为可执行的任务。任务遵循 Service-Repository 架构模式，与现有去重模块保持一致，并按依赖顺序组织。

**任务进度跟踪**: 使用 `- [x]` 标记已完成任务

---

## Phase 1: 数据模型与基础设施

### 1. 数据模型与数据库迁移

- [x] 1.1 创建摘要领域模型
  - 定义 `SummaryRecord` 聚合根（summary_id, tweet_id, summary_text, translation_text, model_provider, model_name, tokens, cost, cached, content_hash, created_at, updated_at）
  - 定义 `SummaryResult` 值对象（total_tweets, total_groups, cache_hits, cache_misses, total_tokens, total_cost_usd, providers_used, processing_time_ms）
  - 定义 `LLMResponse` 值对象（content, model, provider, prompt_tokens, completion_tokens, total_tokens, cost_usd）
  - 定义 `LLMErrorType` 枚举（temporary, permanent）
  - 所有模型使用 Pydantic BaseModel，添加字段验证和文档
  - _Requirements: 7_

- [x] 1.2 创建数据库 ORM 模型
  - 创建 `SummaryOrm` SQLAlchemy 模型，映射到 summaries 表
  - 定义字段：summary_id (UUID PK), tweet_id (FK), summary_text, translation_text, model_provider, model_name, prompt_tokens, completion_tokens, total_tokens, cost_usd, cached, content_hash, created_at, updated_at
  - 添加外键约束：tweet_id → tweets.tweet_id ON DELETE CASCADE
  - 添加唯一约束：uq_tweet_summary (tweet_id)
  - 实现 `to_domain()` 方法转换 ORM → SummaryRecord
  - _Requirements: 7_

- [x] 1.3 编写数据库迁移脚本
  - 创建 Alembic 迁移脚本，创建 summaries 表
  - 添加 tweets 表扩展字段：summary_cached, content_hash
  - 创建索引：idx_summaries_tweet, idx_summaries_cached, idx_summaries_created, idx_summaries_provider
  - 添加回滚逻辑（DROP TABLE, DROP COLUMN）
  - _Requirements: 7_

- [x] 1.4 (P) 创建 Prompt 配置模型
  - 定义 `PromptConfig` Pydantic 模型（summary_prompt, translation_prompt）
  - 实现默认 Prompt 模板（摘要：动态长度，保留实体；翻译：保持语气，URL 不变）
  - 实现 `format_summary(tweet_text)` 和 `format_translation(tweet_text)` 方法
  - 支持从配置文件或环境变量加载自定义 Prompt
  - 添加智能摘要长度配置：
    - `min_tweet_length_for_summary: int = 30`
    - `summary_min_length_ratio: float = 0.5`
    - `summary_max_length_ratio: float = 1.5`
  - 更新 `format_summary()` 方法支持动态长度参数
  - _Requirements: 1, 2, 9_

- [x] 1.5 实现智能摘要长度策略
  - 在 `SummaryRecord` 中添加 `is_generated_summary: bool = True` 字段
  - 修改 `summary_text` 验证：从 50-150 字改为 1-500 字
  - 在 `SummaryOrm` 中添加 `is_generated_summary` 字段
  - 更新 `to_domain()` 和 `from_domain()` 方法
  - 添加结构化日志方法 `log_summary_skipped()`
  - _Requirements: 1_

---

## Phase 2: LLM 提供商适配层

### 2. LLM 提供商接口与实现

- [x] 2.1 定义 LLM 提供商抽象接口
  - 创建 `LLMProvider` 抽象基类，定义 `complete(prompt, max_tokens, temperature)` 方法
  - 定义 `LLMResponse` 响应模型（content, model, provider, tokens, cost）
  - 定义返回类型：`Result[LLMResponse, Exception]`
  - 定义错误分类常量：TEMPORARY_ERRORS (429, 503, 504), PERMANENT_ERRORS (401, 402)
  - _Requirements: 3_

- [x] 2.2 实现 OpenRouter 提供商
  - 创建 `OpenRouterProvider` 类，实现 `LLMProvider` 接口
  - 配置：Base URL `https://openrouter.ai/api/v1`，模型 `anthropic/claude-sonnet-4.5`
  - 使用 OpenAI AsyncClient，设置 timeout 和 max_retries=1
  - 实现错误分类：429/503/504 → temporary, 401/402 → permanent
  - 实现 token 统计和成本计算（基于 OpenRouter 定价）
  - 返回 `LLMResponse` 包含 provider="openrouter"
  - _Requirements: 3_

- [x] 2.3 (P) 实现 MiniMax 中国版提供商
  - 创建 `MiniMaxProvider` 类，实现 `LLMProvider` 接口
  - 配置：Base URL `https://api.minimaxi.com`（中国版），模型 `m2.1`
  - 使用 OpenAI AsyncClient，设置 timeout 和 max_retries=1
  - 实现错误分类：同 OpenRouterProvider
  - 实现 token 统计和成本计算（基于 MiniMax 定价）
  - 返回 `LLMResponse` 包含 provider="minimax"
  - _Requirements: 3_

- [x] 2.4 (P) 创建 LLM 提供商配置
  - 定义 `OpenRouterConfig` 模型（api_key, base_url, model, timeout_seconds, max_retries）
  - 定义 `MiniMaxConfig` 模型（api_key, base_url, model, group_id, timeout_seconds, max_retries）
  - 定义 `OpenSourceConfig` 模型（预留扩展）
  - 定义 `LLMProviderConfig` 聚合模型，包含上述配置（可选字段）
  - 实现 `from_env()` 类方法，从环境变量加载配置
  - _Requirements: 9_

---

## Phase 3: 数据持久化层

### 3. 摘要仓储实现

- [x] 3.1 实现 SummarizationRepository
  - 创建 `SummarizationRepository` 类，接受 AsyncSession 依赖注入
  - 实现 `save_summary_record(record: SummaryRecord)` 方法：创建或更新摘要记录
  - 实现 `get_summary_by_tweet(tweet_id: str)` 方法：查询推文的摘要
  - 实现 `get_cost_stats(start_date, end_date)` 方法：按日期范围统计成本
  - 使用事务确保数据一致性
  - 定义 `RepositoryError` 和 `NotFoundError` 异常类
  - _Requirements: 6, 7_

- [x] 3.2 (P) 创建单元测试 - 仓储层
  - 测试 `save_summary_record`：创建新记录、更新已存在记录
  - 测试 `get_summary_by_tweet`：存在返回、不存在返回 None
  - 测试 `get_cost_stats`：聚合计算正确性
  - 测试事务回滚：异常时数据不污染
  - 使用 pytest-asyncio 和内存数据库
  - _Requirements: 7_

---

## Phase 4: 摘要服务核心逻辑

### 4. 摘要服务实现

- [x] 4.1 实现 SummarizationService - 核心编排逻辑
  - 创建 `SummarizationService` 类，注入 `LLMProvider`, `SummarizationRepository`, `PromptConfig`
  - 实现内存缓存：`_cache: dict[str, LLMResponse]` 和 `_cache_lock: asyncio.Lock`
  - 实现 `compute_hash(text, model, task)` 方法：SHA256 哈希
  - 实现 `_get_from_cache(content_hash)` 和 `_set_cache(content_hash, response)`
  - _Requirements: 4, 5_

- [x] 4.2 实现推文摘要生成（去重组 + 独立推文）
  - 实现 `_process_deduplication_group(group, force_refresh)` 方法（去重组内共享摘要）
  - 实现 `_process_single_tweet(tweet_id, force_refresh)` 方法（独立推文单独处理）
  - 实现 `_process_independent_tweets_concurrent(tweet_ids, force_refresh)` 方法（并发处理独立推文）
  - 实现 `_load_tweets(tweet_ids)` 方法：从数据库加载真实推文文本
  - 检查缓存：计算 content_hash，从内存缓存获取
    - 去重组缓存键：`dedup_type:representative_id`
    - 独立推文缓存键：`standalone:tweet_id`
  - 如果缓存未命中或 force_refresh：
    - 检查推文长度：
      - < 30 字：直接返回原文，标记 `is_generated_summary=False`
      - ≥ 30 字：计算动态长度范围（原文的 50%-150%），调用 LLM 生成摘要
    - 使用 PromptConfig 生成摘要 Prompt（支持动态长度）和翻译 Prompt
    - 保存到缓存和数据库
  - 返回 `SummaryRecord`
  - _Requirements: 1, 2, 4_

- [x] 4.3 实现批量处理与并发控制
  - 实现 `summarize_tweets(tweet_ids, force_refresh)` 主方法
  - 从数据库批量加载推文数据
  - 分区处理：有去重组的推文 vs 独立推文（无去重组）
  - 使用 `asyncio.Semaphore(5)` 控制并发
  - 并发调用 `_process_deduplication_group`（去重组）和 `_process_independent_tweets_concurrent`（独立推文）
  - 收集统计：总推文数、去重组数、独立推文数、缓存命中/未命中、token 使用、成本、提供商分布
  - 更新 tweets 表：summary_cached=True, content_hash
  - 返回 `SummaryResult`（含 `independent_tweets` 字段）
  - _Requirements: 4, 5, 10_

- [x] 4.4 实现 LLM 调用与降级逻辑
  - 实现 `_call_llm_with_fallback(prompt, provider_chain)` 方法
  - 按顺序尝试提供商：OpenRouter → MiniMax → OpenSource
  - 区分临时/永久错误：
    - 临时错误：重试 1 次后降级
    - 永久错误：立即降级
  - 记录降级日志和失败原因
  - 所有提供商失败时返回 `Result[LLMResponse, Exception]`
  - _Requirements: 3_

- [x] 4.5 (P) 创建单元测试 - 摘要服务
  - 测试缓存逻辑：首次调用 LLM，第二次命中缓存
  - 测试并发控制：Semaphore 限制并发数
  - 测试降级逻辑：OpenRouter 失败 → MiniMax 成功
  - 测试错误分类：临时错误重试，永久错误立即降级
  - 测试按去重组分组：同一去重组共享摘要
  - 测试独立推文处理：无去重组的推文独立生成摘要
  - 测试混合处理：同时处理有去重组和无去重组的推文
  - 测试 regenerate 不依赖去重组
  - 使用 mock LLMProvider
  - _Requirements: 3, 4, 5_

---

## Phase 5: API 集成层

### 5. FastAPI 端点实现

- [x] 5.1 创建 API 请求/响应模型
  - 定义 `BatchSummaryRequest` 模型（tweet_ids: list[str], force_refresh: bool）
  - 定义 `BatchSummaryResponse` 模型（task_id: str, status: str）
  - 定义 `SummaryResponse` 模型（基于 SummaryRecord）
  - 定义 `CostStatsResponse` 模型（total_cost, token_breakdown, provider_breakdown）
  - _Requirements: 8_

- [x] 5.2 实现 Admin API 端点
  - 实现 `POST /api/summaries/batch`：接收推文 ID 列表，触发后台任务
  - 实现 `GET /api/summaries/tweets/{tweet_id}`：查询单条推文的摘要
  - 实现 `GET /api/summaries/stats`：查询成本统计（支持日期范围筛选）
  - 实现 `POST /api/summaries/tweets/{tweet_id}/regenerate`：强制重新生成摘要
  - 使用 FastAPI BackgroundTasks 异步执行批量处理
  - 添加 Pydantic 验证和错误处理
  - _Requirements: 8_

- [x] 5.3 (P) 创建集成测试 - API 端点
  - 测试 POST /batch：创建任务，返回 task_id
  - 测试 GET /tweets/{id}：存在返回摘要，不存在返回 404
  - 测试 GET /stats：聚合统计数据正确
  - 测试 POST /regenerate：强制刷新缓存
  - 使用 TestClient 和依赖覆盖
  - _Requirements: 8_

---

## Phase 6: 系统集成与测试

### 6. 去重服务集成

- [x] 6.1 集成摘要服务触发
  - 摘要服务可由去重服务、抓取服务或 API 直接触发
  - 不依赖去重组的存在，独立推文也可处理
  - 传递推文 ID 列表，摘要服务自动检测去重组（有则共享，无则独立处理）
  - 使用后台任务模式，不阻塞调用方流程
  - 记录摘要任务启动日志
  - _Requirements: 8_

- [x] 6.2 创建端到端集成测试
  - 测试完整流程：抓取 → 去重 → 摘要 → 数据库验证
  - 验证去重组内推文共享同一摘要
  - 验证无去重组的推文独立生成摘要
  - 验证缓存机制：第二次处理相同内容使用缓存
  - 验证降级策略：模拟 OpenRouter 失败
  - 验证事务一致性：摘要失败时不影响去重结果
  - **测试智能摘要长度策略**：
    - 测试短推文（< 30 字）直接返回原文
    - 测试长推文生成动态长度摘要
    - 验证 `is_generated_summary` 标记正确性
  - _Requirements: 1, 2, 3, 4, 5_

- [x] 6.3 (P) 性能测试与优化验证
  - 测试单条推文处理时间 < 10 秒
  - 测试 10 条推文批量处理 < 30 秒
  - 测试 50 条推文批量处理 < 120 秒
  - 测试缓存查询时间 < 100 毫秒
  - 测试内存占用 < 200MB（50 条推文）
  - 使用 pytest-benchmark 记录性能指标
  - _Requirements: 10_

---

## Phase 7: 可选增强（MVP 后）

### 7. 监控与可观测性

- [x] 7.1 添加结构化日志记录
  - 使用 loguru 记录关键事件：摘要生成、降级、缓存命中
  - 添加上下文信息：tweet_id, provider, tokens, cost
  - 区分日志级别：INFO（正常），WARNING（降级），ERROR（失败）
  - _Requirements: 6_

- [ ] 7.2 (P*) 添加 Prometheus 指标
  - 定义 Counter：summary_generated_total（按 provider 分类）
  - 定义 Histogram：summary_processing_seconds（按 provider 分类）
  - 定义 Gauge：cache_size, cache_hit_rate
  - 添加 /metrics 端点暴露指标
  - _Requirements: 6, 10_

- [ ] 7.3 (P*) 实现健康检查端点
  - 实现 GET /health/summaries：检查服务状态
  - 验证 LLM 提供商连通性（可选，超时保护）
  - 返回数据库连接状态
  - 返回缓存状态
  - _Requirements: 8_

---

## Requirements Coverage Matrix

| Requirement ID | Description | Tasks |
|----------------|-------------|-------|
| 1 | 智能摘要生成 | 1.4, 4.2, 6.2 |
| 2 | 英译中翻译 | 1.4, 4.2, 6.2 |
| 3 | 多模型支持与降级策略 | 2.1, 2.2, 2.3, 4.4, 4.5, 6.2 |
| 4 | 结果缓存 | 4.1, 4.2, 4.3, 4.5, 6.2 |
| 5 | 批量处理与并发控制 | 4.3, 4.5, 6.3 |
| 6 | 成本统计 | 3.1, 3.2, 4.3, 5.1, 5.2, 7.1, 7.2 |
| 7 | 数据模型与存储 | 1.1, 1.2, 1.3, 3.1, 3.2 |
| 8 | API 集成 | 5.1, 5.2, 5.3, 6.1, 7.3 |
| 9 | 配置管理 | 1.4, 2.4 |
| 10 | 性能要求 | 4.3, 6.3 |

**All requirements covered**: ✅ (10/10)

---

## Parallel Execution Opportunities

以下任务可以并行执行（标记为 `(P)`），前提是满足依赖关系：

**Phase 1 内部并行**:
- 1.4 (Prompt 配置) 可与 1.1-1.3 并行

**Phase 2 内部并行**:
- 2.3 (MiniMax 提供商) 可与 2.2 (OpenRouter 提供商) 并行
- 2.4 (配置) 可与 2.2/2.3 并行

**Phase 3 内部并行**:
- 3.2 (单元测试) 可与 3.1 之后并行

**Phase 4 内部并行**:
- 4.5 (单元测试) 可与 4.1-4.4 之后并行

**Phase 5 内部并行**:
- 5.3 (集成测试) 可与 5.1-5.2 之后并行

**Phase 6 内部并行**:
- 6.3 (性能测试) 可与 6.1-6.2 之后并行

**Phase 7 全部可选**:
- 所有 Phase 7 任务为 MVP 后增强，可按需并行

---

## Implementation Notes

### 依赖关系概览

```
Phase 1 (数据模型)
    ↓
Phase 2 (LLM 提供商) ← Phase 1.4 (Prompt 配置)
    ↓
Phase 3 (仓储) ← Phase 1.2 (ORM)
    ↓
Phase 4 (服务) ← Phase 2 + Phase 3
    ↓
Phase 5 (API) ← Phase 4
    ↓
Phase 6 (集成) ← Phase 4 + Phase 5
    ↓
Phase 7 (增强，可选)
```

### 关键集成点

1. **触发 → 摘要**: Phase 6.1 将摘要服务集成到工作流（可由抓取、去重或 API 触发，不依赖去重组）
2. **缓存策略**: 使用内存缓存（dict + asyncio.Lock），避免 Redis 依赖
3. **降级逻辑**: Phase 4.4 实现智能降级，区分临时/永久错误
4. **模型名称**: OpenRouter 使用 `anthropic/claude-sonnet-4.5`

### 测试策略

- **单元测试**: Phase 3.2 (仓储), Phase 4.5 (服务)
- **集成测试**: Phase 5.3 (API), Phase 6.2 (E2E)
- **性能测试**: Phase 6.3 (性能基准)
- **可选测试**: Phase 7.2-7.3 (MVP 后增强)

### 迁移建议

1. 先运行迁移脚本（Phase 1.3）创建数据库表
2. 部署新代码（Phase 1-5）
3. 验证 API 端点可用（Phase 5.2）
4. 启用去重集成（Phase 6.1）
5. 监控性能和成本（Phase 6.3）
