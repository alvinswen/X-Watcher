# 研究与设计决策日志

---
**用途**: 记录发现阶段的研究活动和设计决策依据。
---

## 概要
- **特性**: `tweets-date-range-filter`
- **发现范围**: Extension（扩展现有端点）
- **关键发现**:
  - Feed API (`src/feed/api/routes.py`) 已有完整的时间范围过滤模式，可直接复用
  - 现有 `list_tweets()` 的 `stmt` 和 `count_stmt` WHERE 条件分别构建，需同步添加
  - FastAPI `Query(None)` + `datetime` 类型自动提供 ISO 8601 格式校验

## 研究日志

### 现有时间过滤模式分析
- **背景**: 需要确认项目中是否已有时间范围过滤的实现模式
- **来源**: `src/feed/api/routes.py`、`src/feed/services/feed_service.py`
- **发现**:
  - Feed API 使用 `created_at >= since` 和 `created_at < until` 的半开区间 `[since, until)` 模式
  - naive datetime 通过 `dt.replace(tzinfo=timezone.utc)` 处理
  - 时间范围校验：`since >= until` 返回 HTTP 422
- **影响**: 直接复用相同的过滤模式和校验逻辑，保持项目一致性

### 查询条件构建模式分析
- **背景**: 了解现有端点如何构建动态 WHERE 条件
- **来源**: `src/api/routes/tweets.py` 的 `list_tweets()` 函数
- **发现**:
  - 使用条件式追加：`if author: stmt = stmt.where(TweetOrm.author_username == author)`
  - 数据查询（`stmt`）和计数查询（`count_stmt`）分别构建，需两处同步修改
  - 可使用内联辅助函数 `_apply_filters()` 消除重复
- **影响**: 选择提取辅助函数统一管理过滤条件，避免遗漏

## 架构模式评估

| 方案 | 描述 | 优势 | 风险/限制 | 备注 |
|------|------|------|-----------|------|
| 直接内联扩展 | 在 `list_tweets()` 中直接添加 WHERE 条件 | 最小改动，无新抽象 | stmt/count_stmt 重复过滤逻辑 | 简单但有重复风险 |
| 辅助函数提取 | 提取 `_apply_filters()` 统一添加条件 | 消除重复，DRY | 多一层间接 | **推荐**：平衡简洁和可维护性 |

## 设计决策

### 决策: 使用辅助函数统一过滤条件

- **背景**: 数据查询和 COUNT 查询需要相同的过滤条件（author + 时间范围），分别维护容易遗漏
- **备选方案**:
  1. 直接在两处分别添加 — 简单但有重复
  2. 提取 `_apply_filters()` 模块级辅助函数 — 统一管理
- **选择**: 方案 2，提取辅助函数
- **理由**: 过滤条件从 1 个（author）增加到 3 个（author + created_after + created_before），重复维护的风险明显增加
- **权衡**: 增加一个小函数的间接性，但换来更可靠的一致性
- **后续**: 函数保持模块私有（`_` 前缀），不暴露到模块外

## 风险与缓解

- 无显著技术风险。所有涉及的技术栈和模式均已在项目中充分验证。

## 参考

- `src/feed/api/routes.py` — Feed API 时间过滤参考实现
- `src/feed/services/feed_service.py` — SQLAlchemy 时间 WHERE 条件参考
- `src/api/routes/tweets.py` — 待修改的目标文件
