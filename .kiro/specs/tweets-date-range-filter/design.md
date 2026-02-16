# 技术设计文档

## 概述

**用途**: 为 `GET /api/tweets` 管理端点添加 `created_after` 和 `created_before` 时间范围过滤参数，使管理员能够按推文创建时间精确查询推文。

**用户**: 管理员通过该端点进行数据排查、bad case 检测和推文管理。

**影响**: 在现有端点函数中追加可选查询参数和对应的 WHERE 条件，不改变现有响应结构和默认行为。

### 目标

- 支持按 `created_at` 时间范围过滤推文（半开区间 `[created_after, created_before)`）
- 时间范围可与现有 `author` 参数组合使用（AND 逻辑）
- 完全向后兼容：新参数可选，不提供时行为与当前一致

### 非目标

- 不引入新的 Service 层或 Repository 方法
- 不修改 `TweetListResponse` 响应结构
- 不添加排序方向参数（保持 `created_at DESC`）
- 不扩展到 Feed API 或其他端点

## 架构

### 现有架构分析

当前 `list_tweets()` 端点直接在路由函数内构建 SQLAlchemy 查询，包含：
- 数据查询（`stmt`）：SELECT + LEFT JOIN summaries + WHERE + ORDER BY + OFFSET/LIMIT
- 计数查询（`count_stmt`）：SELECT COUNT + WHERE

两个查询的 WHERE 条件分别构建，仅支持 `author` 过滤。

### 架构模式与边界

- **选择模式**: 直接扩展现有端点 + 提取过滤辅助函数
- **职责分离**: 过滤条件构建提取为模块级私有函数 `_apply_filters()`，统一应用于 `stmt` 和 `count_stmt`
- **保持现有模式**: 路由层直接操作 SQLAlchemy，无 Service/Repository 层介入
- **Steering 合规**: 符合 YAGNI 原则，不引入不必要的抽象

### 技术栈

| 层级 | 选择/版本 | 在本特性中的角色 | 备注 |
|------|----------|----------------|------|
| 后端/服务 | FastAPI + SQLAlchemy | 路由参数解析 + ORM 查询构建 | 复用现有 |
| 数据/存储 | SQLite (TweetOrm.created_at) | WHERE 条件过滤 | 已有 `DateTime(timezone=True)` |

无新增依赖。

## 需求追踪

| 需求 | 摘要 | 组件 | 接口 |
|------|------|------|------|
| 1.1 | `created_after` 参数（可选，ISO 8601） | list_tweets 路由 | API Contract |
| 1.2 | `created_before` 参数（可选，ISO 8601） | list_tweets 路由 | API Contract |
| 1.3 | `created_at >= created_after` 过滤 | _apply_filters | Service Interface |
| 1.4 | `created_at < created_before` 过滤 | _apply_filters | Service Interface |
| 1.5 | 双边范围过滤 | _apply_filters | Service Interface |
| 1.6 | 单边范围过滤 | _apply_filters | Service Interface |
| 2.1 | 组合 AND 过滤 | _apply_filters | Service Interface |
| 2.2 | 分页正确性 | list_tweets 路由 | API Contract |
| 2.3 | total 反映过滤后数量 | list_tweets 路由 | API Contract |
| 2.4 | total_pages 正确计算 | list_tweets 路由 | API Contract |
| 3.1 | ISO 8601 格式校验 | FastAPI 自动 | API Contract |
| 3.2 | ISO 8601 格式校验 | FastAPI 自动 | API Contract |
| 3.3 | 时间范围逻辑校验 | list_tweets 路由 | API Contract |
| 3.4 | naive datetime → UTC | _ensure_utc | Service Interface |
| 4.1 | 响应结构不变 | TweetListResponse | — |
| 4.2 | 向后兼容 | list_tweets 路由 | API Contract |
| 4.3 | 排序不变 | list_tweets 路由 | — |

## 组件与接口

### 组件概览

| 组件 | 层级 | 职责 | 需求覆盖 | 关键依赖 | 契约 |
|------|------|------|---------|---------|------|
| list_tweets 路由 | API | 接收参数、校验、编排查询 | 1.1, 1.2, 2.2–2.4, 3.3, 4.1–4.3 | TweetOrm (P0), SummaryOrm (P1) | API |
| _apply_filters | API (私有) | 统一构建 WHERE 条件 | 1.3–1.6, 2.1 | TweetOrm (P0) | Service |
| _ensure_utc | API (私有) | naive datetime → UTC 转换 | 3.4 | 无 | Service |

### API 层

#### list_tweets 路由（扩展）

| 字段 | 详情 |
|------|------|
| 职责 | 接收时间范围参数，校验后委托 _apply_filters 构建查询条件 |
| 需求 | 1.1, 1.2, 2.2, 2.3, 2.4, 3.3, 4.1, 4.2, 4.3 |

**约束与职责**
- 新增两个可选 `datetime` 查询参数，不影响现有参数
- 在查询执行前进行时间范围逻辑校验
- 将 `stmt` 和 `count_stmt` 的过滤逻辑委托给 `_apply_filters()`
- 保持现有响应模型 `TweetListResponse` 不变

**契约**: API [x]

##### API 契约

| 方法 | 端点 | 请求参数 | 响应 | 错误 |
|------|------|---------|------|------|
| GET | /api/tweets | page, page_size, author, **created_after**, **created_before** | TweetListResponse | 422, 500 |

**新增查询参数**:

| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| created_after | datetime (ISO 8601) | 否 | 推文创建时间起始边界（含），`created_at >= created_after` |
| created_before | datetime (ISO 8601) | 否 | 推文创建时间截止边界（不含），`created_at < created_before` |

**实现说明**
- 校验: 当两个时间参数都提供时，验证 `created_after < created_before`，否则返回 HTTP 422
- 时区: naive datetime 自动视为 UTC（通过 `_ensure_utc` 处理）
- 兼容: 参数默认 `None`，不提供时不添加 WHERE 条件

#### _apply_filters（新增）

| 字段 | 详情 |
|------|------|
| 职责 | 统一为 SQLAlchemy Select 语句追加 WHERE 条件 |
| 需求 | 1.3, 1.4, 1.5, 1.6, 2.1 |

**约束与职责**
- 模块级私有函数（`_` 前缀）
- 接收 SQLAlchemy Select 对象和过滤参数，返回修改后的 Select 对象
- 按条件式追加 WHERE 子句（仅非 None 参数生效）

**契约**: Service [x]

##### 服务接口

```python
def _apply_filters(
    stmt: Select,
    *,
    author: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
) -> Select:
    """为查询语句追加过滤条件。

    Args:
        stmt: SQLAlchemy Select 语句
        author: 作者用户名筛选
        created_after: 创建时间起始（含）
        created_before: 创建时间截止（不含）

    Returns:
        追加了 WHERE 条件的 Select 语句
    """
```

- 前置条件: `stmt` 为有效的 SQLAlchemy Select 对象
- 后置条件: 返回的 Select 包含所有非 None 参数对应的 WHERE 条件（AND 逻辑）
- 不变量: 不修改原始 `stmt`，返回新的 Select 对象

#### _ensure_utc（新增）

| 字段 | 详情 |
|------|------|
| 职责 | 将 naive datetime 转换为 UTC aware datetime |
| 需求 | 3.4 |

**契约**: Service [x]

##### 服务接口

```python
def _ensure_utc(dt: datetime) -> datetime:
    """确保 datetime 带有 UTC 时区信息。

    Args:
        dt: 可能是 naive 或 aware 的 datetime

    Returns:
        带 UTC 时区的 datetime
    """
```

- 前置条件: `dt` 为有效的 datetime 对象
- 后置条件: 返回的 datetime 总是 timezone-aware（UTC）
- 不变量: 已有时区信息的 datetime 不被修改

## 错误处理

### 错误类别与响应

| 错误场景 | HTTP 状态码 | 响应体 | 需求 |
|---------|------------|--------|------|
| `created_after` 格式无效 | 422 | FastAPI 自动校验错误（含字段名和格式说明） | 3.1 |
| `created_before` 格式无效 | 422 | FastAPI 自动校验错误（含字段名和格式说明） | 3.2 |
| `created_after >= created_before` | 422 | `{"detail": "时间范围无效: created_after 必须早于 created_before"}` | 3.3 |
| 数据库查询异常 | 500 | `{"detail": "<error message>"}` | 现有行为 |

### 校验流程

1. FastAPI/Pydantic 自动校验参数类型（ISO 8601 格式）→ 不通过则返回 422
2. `_ensure_utc` 处理 naive datetime → 不产生错误
3. 时间范围逻辑校验（`created_after >= created_before`）→ 不通过则返回 422
4. 执行数据库查询 → 异常捕获返回 500

## 测试策略

### 单元测试

测试范围集中在 `tests/api/test_tweets_routes.py`，扩展 `TestTweetListAPI` 类：

1. **`test_list_tweets_filter_by_created_after`** — 验证 `created_after` 单边过滤（需求 1.3）
2. **`test_list_tweets_filter_by_created_before`** — 验证 `created_before` 单边过滤（需求 1.4）
3. **`test_list_tweets_filter_by_date_range`** — 验证双边时间范围过滤（需求 1.5）
4. **`test_list_tweets_filter_combined_author_and_date_range`** — 验证组合过滤（需求 2.1）
5. **`test_list_tweets_date_range_with_pagination`** — 验证分页与时间过滤组合（需求 2.2, 2.3, 2.4）
6. **`test_list_tweets_invalid_date_range`** — 验证 `created_after >= created_before` 返回 422（需求 3.3）
7. **`test_list_tweets_invalid_date_format`** — 验证无效日期格式返回 422（需求 3.1, 3.2）
8. **`test_list_tweets_no_date_params_backward_compatible`** — 验证不提供时间参数时行为不变（需求 4.2）

### 测试 Fixture 调整

现有 `seed_test_tweets` 的时间间隔仅 1-2 秒，需调整为更大间隔（如天级别），以支持时间范围边界测试。建议：
- tweet1: `now`
- tweet2: `now - 1 day`
- tweet3: `now - 2 days`
- 可选增加 tweet4/tweet5 以覆盖更多场景
