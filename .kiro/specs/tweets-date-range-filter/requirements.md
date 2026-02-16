# 需求文档

## 简介

增强现有的 `GET /api/tweets` 管理端点，添加按推文创建日期/时间范围过滤的能力。当前该端点仅支持按 `author` 用户名过滤和分页，需要新增 `created_after` 和 `created_before` 查询参数，支持与现有 `author` 参数组合使用，实现灵活的推文查询。

本次增强使管理员能够按时间维度精确查询推文，满足数据排查、bad case 检测等管理场景的需求。

## 需求

### 需求 1: 日期范围过滤参数

**目标:** 作为管理员，我希望在查询推文列表时能够指定时间范围，以便快速定位特定时间段内的推文。

#### 验收标准

1. The Tweets API shall 接受可选的 `created_after` 查询参数（ISO 8601 格式的 datetime），表示推文创建时间的起始边界（含）。
2. The Tweets API shall 接受可选的 `created_before` 查询参数（ISO 8601 格式的 datetime），表示推文创建时间的截止边界（不含）。
3. When `created_after` 被提供时, the Tweets API shall 仅返回 `created_at >= created_after` 的推文。
4. When `created_before` 被提供时, the Tweets API shall 仅返回 `created_at < created_before` 的推文。
5. When `created_after` 和 `created_before` 同时被提供时, the Tweets API shall 仅返回满足 `created_after <= created_at < created_before` 的推文。
6. When 仅提供 `created_after` 或仅提供 `created_before` 时, the Tweets API shall 将其作为单边范围过滤条件正常工作。

### 需求 2: 组合过滤

**目标:** 作为管理员，我希望时间范围过滤能够与现有的作者筛选参数组合使用，以便进行更精确的查询。

#### 验收标准

1. When `created_after`、`created_before` 与 `author` 同时提供时, the Tweets API shall 同时应用所有过滤条件（AND 逻辑）。
2. The Tweets API shall 确保分页参数（`page`、`page_size`）在加入时间范围过滤后仍然正确工作。
3. The Tweets API shall 确保 `total` 字段反映所有过滤条件应用后的总数量，而非未过滤的总数量。
4. The Tweets API shall 确保 `total_pages` 字段基于过滤后的 `total` 正确计算。

### 需求 3: 输入验证与错误处理

**目标:** 作为管理员，我希望在提供无效的时间参数时获得清晰的错误提示，以便快速修正请求。

#### 验收标准

1. If `created_after` 的值不是有效的 ISO 8601 datetime 格式, then the Tweets API shall 返回 HTTP 422 错误，并包含参数名和格式说明。
2. If `created_before` 的值不是有效的 ISO 8601 datetime 格式, then the Tweets API shall 返回 HTTP 422 错误，并包含参数名和格式说明。
3. If `created_after` 晚于或等于 `created_before`, then the Tweets API shall 返回 HTTP 422 错误，提示时间范围无效。
4. When 时间参数未提供时区信息（naive datetime）时, the Tweets API shall 将其视为 UTC 时间处理。

### 需求 4: 响应一致性

**目标:** 作为 API 消费者，我希望新增的过滤参数不会改变现有响应结构，以确保向后兼容。

#### 验收标准

1. The Tweets API shall 保持现有的 `TweetListResponse` 响应结构不变（`items`、`total`、`page`、`page_size`、`total_pages`）。
2. When 未提供任何时间范围参数时, the Tweets API shall 保持与当前完全相同的行为（向后兼容）。
3. The Tweets API shall 保持 `created_at` 倒序排列的默认排序方式不变。
