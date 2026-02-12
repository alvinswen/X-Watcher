# Requirements Document

## Introduction

新闻去重模块（News Deduplicator）是 X-watcher 的核心组件之一，负责自动识别和合并重复或相似的推文内容。该模块在新闻抓取后、摘要生成前执行，确保用户接收到的新闻流具有高信噪比，避免因同一新闻被多个关注人物转发/引用而导致的重复内容。

## Requirements

### Requirement 1: 精确重复检测

**Objective:** 作为系统，我需要检测内容完全相同的推文（如转发），以便将这些重复内容合并为一条新闻记录。

#### Acceptance Criteria

1. When 多条推文的 `text` 字段完全相同时，NewsDeduplicator shall 将这些推文标记为精确重复
2. When 推文之间存在 `referenced_tweet_id` 引用关系且引用类型为 `retweeted` 时，NewsDeduplicator shall 将被引用推文和引用推文识别为重复组
3. When 检测到精确重复时，NewsDeduplicator shall 保留最早创建的推文作为主记录（representative）
4. When 将重复推文合并时，NewsDeduplicator shall 记录所有重复推文的 `tweet_id` 和 `author_username` 到主记录的元数据中
5. The 重复检测算法 shall 具有O(n)的时间复杂度，其中 n 为待检测推文数量

### Requirement 2: 相似内容检测

**Objective:** 作为系统，我需要检测内容相似但不完全相同的推文（如相同新闻的不同表述），以便将这些相似内容推荐给用户合并或自动去重。

#### Acceptance Criteria

1. When 两条推文的文本相似度超过配置阈值（默认 0.85）时，NewsDeduplicator shall 将这些推文标记为相似内容
2. When 计算文本相似度时，NewsDeduplicator shall 使用以下预处理步骤：
   - 移除 URL 链接
   - 移除提及（@username）
   - 移除多余空格和换行
   - 转换为小写
3. When 使用嵌入模型计算相似度时，NewsDeduplicator shall 支持 MiniMax 或 OpenAI 的嵌入 API
4. When 不使用嵌入模型时，NewsDeduplicator shall 使用 TF-IDF + 余弦相似度作为降级方案
5. When 检测到相似内容时，NewsDeduplicator shall 返回相似度分数供后续处理决策

### Requirement 3: 去重结果存储

**Objective:** 作为系统，我需要将去重结果持久化存储，以便用户可以查询和审计去重决策。

#### Acceptance Criteria

1. When 完成去重处理后，NewsDeduplicator shall 创建或更新 `deduplication_groups` 表记录
2. The `deduplication_groups` 表 shall 包含以下字段：
   - `group_id`: 去重组唯一标识（UUID）
   - `representative_tweet_id`: 主推文 ID（保留的推文）
   - `deduplication_type`: 去重类型（exact_duplicate, similar_content）
   - `similarity_score`: 相似度分数（0-1）
   - `tweet_ids`: 组内所有推文 ID 列表（JSON）
   - `created_at`: 去重组创建时间
3. When 推文被标记为重复时，NewsDeduplicator shall 在 `tweets` 表中添加 `deduplication_group_id` 外键关联
4. When 更新去重结果时，NewsDeduplicator shall 使用事务确保数据一致性
5. The 去重结果 shall 支持通过 API 查询和撤销

### Requirement 4: 批量去重处理

**Objective:** 作为系统，我需要支持批量处理抓取的推文，以便高效地执行去重操作。

#### Acceptance Criteria

1. When 接收到一批新抓取的推文时，NewsDeduplicator shall 在该批推文内部进行去重
2. When 接收到一批新抓取的推文时，NewsDeduplicator shall 在新推文与数据库已有推文之间进行去重
3. When 执行批量去重时，NewsDeduplicator shall 使用索引优化查询性能
4. When 批量处理超过 1000 条推文时，NewsDeduplicator shall 分批处理以避免内存溢出
5. When 批量去重完成时，NewsDeduplicator shall 返回去重统计信息（总推文数、重复组数、保留推文数）

### Requirement 5: 去重策略配置

**Objective:** 作为系统，我需要支持灵活的去重策略配置，以便适应不同用户的去重需求。

#### Acceptance Criteria

1. When 配置去重策略时，NewsDeduplicator shall 支持以下可配置参数：
   - `similarity_threshold`: 相似度阈值（默认 0.85）
   - `enable_exact_duplicate`: 是否启用精确重复检测（默认 true）
   - `enable_similar_content`: 是否启用相似内容检测（默认 true）
   - `deduplication_method`: 去重方法（auto, manual, hybrid）
   - `use_embedding_model`: 是否使用嵌入模型（默认 false）
2. When 用户未配置时，NewsDeduplicator shall 使用默认策略
3. When 策略变更时，NewsDeduplicator shall 支持重新运行去重（re-deduplication）
4. The 去重策略 shall 支持按用户或全局配置
5. When 使用嵌入模型时，NewsDeduplicator shall 验证 API 密钥可用性

### Requirement 6: API 集成

**Objective:** 作为系统，我需要提供 API 端点以便与现有抓取服务和工作流集成。

#### Acceptance Criteria

1. When 抓取服务完成推文保存后，NewsDeduplicator shall 自动触发去重处理
2. When 调用去重 API 时，NewsDeduplicator shall 提供 `POST /api/deduplicate/batch` 端点接受推文 ID 列表
3. When 查询去重结果时，NewsDeduplicator shall 提供 `GET /api/deduplicate/groups/{group_id}` 端点返回去重组详情
4. When 查询推文去重状态时，NewsDeduplicator shall 提供 `GET /api/deduplicate/tweets/{tweet_id}` 端点返回该推文所属的去重组
5. When 撤销去重决策时，NewsDeduplicator shall 提供 `DELETE /api/deduplicate/groups/{group_id}` 端点删除去重关联

### Requirement 7: 性能要求

**Objective:** 作为系统，我需要确保去重处理不成为系统性能瓶颈。

#### Acceptance Criteria

1. When 处理 100 条推文时，NewsDeduplicator shall 在 5 秒内完成去重
2. When 处理 1000 条推文时，NewsDeduplicator shall 在 30 秒内完成去重
3. When 使用嵌入模型时，NewsDeduplicator shall 支持并发请求以减少总处理时间
4. The 内存占用 shall 在处理 1000 条推文时不超过 500MB
5. When 数据库中已有超过 10,000 条推文时，NewsDeduplicator shall 使用增量比较而非全量比较

---

## Requirement Coverage Summary

| Requirement ID | Title | Priority |
|----------------|-------|----------|
| 1 | 精确重复检测 | High |
| 2 | 相似内容检测 | High |
| 3 | 去重结果存储 | High |
| 4 | 批量去重处理 | Medium |
| 5 | 去重策略配置 | Medium |
| 6 | API 集成 | High |
| 7 | 性能要求 | Medium |

## Notes

- 去重处理应该在新闻抓取后自动执行，无需用户手动触发
- 去重结果应该可追溯，用户可以查看哪些推文被判定为重复
- 支持手动调整去重决策，允许用户撤销自动去重结果
- 嵌入模型为可选功能，初期可以使用简单的 TF-IDF 方案
