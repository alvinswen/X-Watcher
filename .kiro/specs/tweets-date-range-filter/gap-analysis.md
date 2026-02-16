# Gap 分析报告

## 概述

分析 `tweets-date-range-filter` 需求与现有代码库之间的实现差距。

## 1. 现有状态调查

### 1.1 关键文件与模块

| 文件 | 职责 | 与本需求的关系 |
|------|------|---------------|
| `src/api/routes/tweets.py` | 推文列表/详情 API 端点 | **主要修改目标** |
| `src/feed/api/routes.py` | Feed 时间范围查询 | 可参考的时间过滤模式 |
| `src/feed/services/feed_service.py` | Feed 查询服务（时间 WHERE 条件） | 可参考的 SQLAlchemy 时间过滤写法 |
| `src/scraper/infrastructure/models.py` | TweetOrm 模型 | `created_at` 字段已有 `DateTime(timezone=True)` |
| `src/shared/schemas.py` | UTCDatetimeModel 基类 | 已被 TweetListItem 继承，处理 UTC 序列化 |
| `tests/api/test_tweets_routes.py` | 推文 API 测试 | 需要扩展测试覆盖 |

### 1.2 已有的可复用模式

**时间范围过滤模式（来自 Feed API）：**
- `FeedService.get_feed()` 已实现 `created_at >= since` 和 `created_at < until` 的 WHERE 条件
- Feed API 路由层已有 naive datetime → UTC 的时区处理逻辑
- Feed API 已有 `since >= until` 的时间范围校验（返回 422）

**查询构建模式（来自 tweets.py `list_tweets()`）：**
- 条件式 WHERE 追加：`if author: stmt = stmt.where(...)`
- 分离的 COUNT 查询：`count_stmt` 独立于数据查询
- LEFT JOIN 摘要存在性检查

**测试模式（来自 test_tweets_routes.py）：**
- `seed_test_tweets` fixture 创建带时间差的测试推文
- 使用 `async_client` + `AsyncSession` 的异步测试模式
- 分类测试类：`TestTweetListAPI`、`TestTweetDetailAPI`

### 1.3 当前 `list_tweets()` 端点分析

当前端点（`GET /api/tweets`）的查询逻辑：
1. 数据查询：SELECT + LEFT JOIN summaries
2. 条件过滤：仅 `author`（精确匹配）
3. COUNT 查询：独立构建，也仅有 `author` 过滤
4. 排序：`created_at DESC`
5. 分页：`offset + limit`

**关键观察**：数据查询和 COUNT 查询的 WHERE 条件是分别构建的（没有共享 filter 函数），这意味着添加新过滤条件需要在两处同时修改。

## 2. 需求可行性分析

### 2.1 需求-资产映射

| 需求 | 现有资产 | 差距 |
|------|---------|------|
| R1: `created_after`/`created_before` 参数 | FastAPI `Query()` 参数模式已有（`author` 参数） | **Missing**: 需新增两个 `datetime` 类型 Query 参数 |
| R1: 时间 WHERE 条件 | FeedService 已有 `>= since` / `< until` 模式 | **Missing**: 需在 tweets.py 的 stmt 和 count_stmt 中添加 |
| R2: 组合过滤（AND 逻辑） | 已有 `if author:` 条件追加模式 | **Missing**: 需以相同模式追加时间条件 |
| R2: 分页+过滤正确性 | 已有分页逻辑 | 无差距，现有模式天然支持 |
| R3: ISO 8601 格式校验 | FastAPI `datetime` 类型自动校验 | 无差距，FastAPI/Pydantic 自动处理 |
| R3: 时间范围逻辑校验 | Feed API 已有类似校验 | **Missing**: 需在 tweets.py 中添加 |
| R3: naive datetime → UTC | Feed API 已有处理逻辑 | **Missing**: 需在 tweets.py 中添加 |
| R4: 响应结构不变 | `TweetListResponse` 模型 | 无差距，不修改响应模型 |
| R4: 向后兼容 | 新参数可选 | 无差距，`Query(None)` 天然兼容 |

### 2.2 复杂度信号

- **简单 CRUD 扩展**：仅需在现有查询中追加 WHERE 条件
- **无新外部集成**：纯数据库查询扩展
- **无新数据模型**：使用现有 TweetOrm.created_at 字段
- **无架构变更**：在现有端点函数内修改

## 3. 实现方案选项

### 方案 A: 直接扩展现有端点（推荐）

**适用理由**：功能简单，完全契合现有端点职责，无需新模块。

**修改文件**：
1. `src/api/routes/tweets.py` — 在 `list_tweets()` 函数中：
   - 新增 `created_after`、`created_before` 两个 `Query(None)` 参数
   - 在 `stmt` 和 `count_stmt` 中追加时间 WHERE 条件
   - 添加时间范围校验（`created_after >= created_before` → 422）
   - 添加 naive datetime → UTC 处理

2. `tests/api/test_tweets_routes.py` — 扩展 `TestTweetListAPI` 类：
   - 修改 `seed_test_tweets` fixture，使推文时间间隔更大（便于范围测试）
   - 新增时间范围过滤测试
   - 新增组合过滤测试
   - 新增校验错误测试

**权衡**：
- ✅ 改动最小（1 个源文件 + 1 个测试文件）
- ✅ 复用已有查询构建模式
- ✅ 不引入新的抽象层
- ✅ 向后兼容（新参数可选）
- ❌ `list_tweets()` 函数会略微变长（但仍在可控范围内）

### 方案 B: 提取共享过滤器函数

**适用理由**：如果未来需要在多个端点共享过滤逻辑。

**修改**：提取 `apply_tweet_filters(stmt, author, created_after, created_before)` 辅助函数，同时用于 `stmt` 和 `count_stmt`。

**权衡**：
- ✅ 消除 stmt/count_stmt 的重复过滤逻辑
- ✅ 未来扩展更方便
- ❌ 当前仅 1 个端点使用，过度设计
- ❌ 增加间接性

### 方案 C: 创建独立 Service 层

**不推荐**：本次需求纯粹是查询参数扩展，不涉及业务逻辑编排。引入 Service 层违反 YAGNI 原则。

## 4. 实现复杂度与风险

**工作量**：**S（1-3 天）**
- 仅扩展现有模式，无新依赖
- 修改范围明确（1 个路由文件 + 1 个测试文件）
- 可参考的成熟模式（Feed API）

**风险**：**低**
- 使用已验证的技术栈（FastAPI + SQLAlchemy）
- 向后兼容设计（新参数可选）
- 测试覆盖明确

## 5. 设计阶段建议

### 推荐方案

**方案 A（直接扩展现有端点）** — 最符合 YAGNI 原则和现有代码风格。

### 关键设计决策

1. **WHERE 条件重复**：数据查询和 COUNT 查询需要相同的过滤条件。可以考虑方案 B 的辅助函数来消除重复，但鉴于条件数量少（3 个），内联也可接受。
2. **时区处理**：参考 Feed API 的 naive datetime → UTC 逻辑，确保一致性。
3. **测试 fixture 调整**：现有 `seed_test_tweets` 的时间间隔仅 1-2 秒，需要调整为更大间隔（如小时或天）以便于时间范围测试。

### 待研究项

无需额外技术研究。所有技术栈和模式均已在项目中验证。
