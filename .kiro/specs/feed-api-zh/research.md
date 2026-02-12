# 研究与设计决策日志

---
**用途**: 记录设计发现阶段的研究活动和架构决策依据。
---

## 概要
- **Feature**: `feed-api-zh`
- **发现范围**: Extension（现有系统扩展）
- **关键发现**:
  - `tweets.db_created_at` 无数据库索引，需通过 Alembic 迁移添加
  - 项目有两套认证体系，Feed API 应使用 `src/user/api/auth.py` 的完整认证
  - 现有 LEFT JOIN 查询模式（`tweets.py:101-119`）可直接复用

## 研究日志

### db_created_at 索引缺失
- **背景**: Feed API 核心查询基于 `WHERE db_created_at >= :since`，需要索引支持
- **来源**: 分析 `alembic/versions/e69b6de02222_add_tweets_and_summary_tables.py`，确认只创建了 `ix_tweets_created_at`（推文发布时间）索引
- **发现**: `db_created_at` 字段在 `TweetOrm` 中定义但无 `index=True`，Alembic 迁移中也未创建索引
- **影响**: 需要新增 Alembic 迁移添加 `ix_tweets_db_created_at` 索引

### 认证体系选择
- **背景**: 项目有两套认证机制，需要为 Feed API 选择合适的方案
- **来源**: `src/preference/api/auth.py`（简单 ADMIN_API_KEY 比对）和 `src/user/api/auth.py`（完整 API Key + JWT 认证）
- **发现**:
  - `verify_admin_api_key` 返回 `bool`，HTTP 403，仅比对环境变量
  - `get_current_user` 返回 `UserDomain`，HTTP 401，支持 API Key hash 验证 + JWT
- **影响**: 选择 `get_current_user`（需求 5 要求 401 状态码；返回 UserDomain 便于未来用户级定制）

### 查询模式复用
- **背景**: Feed API 需要 LEFT JOIN tweets 和 summaries 表
- **来源**: `src/api/routes/tweets.py:101-119`
- **发现**: 现有查询使用 `select(...).outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)` 模式，Feed API 可复用但需调整 SELECT 列（添加 `summary_text` 和 `translation_text` 而非仅检查是否存在）
- **影响**: 查询结构复用，但 SELECT 列需要调整为获取实际摘要内容

## 架构模式评估

| 方案 | 描述 | 优势 | 风险/限制 | 备注 |
|------|------|------|-----------|------|
| A: 扩展 Tweets API | 在现有端点添加参数 | 最少新文件 | 职责混乱，响应结构冲突 | ❌ 不推荐 |
| B: 新建 Feed 模块 | 独立 `src/feed/` 模块 | 职责清晰，符合项目模式 | 多几个文件 | ✅ 推荐 |
| C: 混合方案 | 同时扩展+新建 | 覆盖全面 | 重复逻辑，违反 YAGNI | ❌ 不推荐 |

## 设计决策

### 决策: 新建独立 Feed 模块
- **背景**: 需要为外部 Agent 提供增量推文查询接口
- **考虑的替代方案**:
  1. 扩展现有 `GET /api/tweets` 端点
  2. 新建独立 `src/feed/` 模块
- **选择**: 方案 B — 新建 `src/feed/` 模块
- **理由**: tweets API 服务 Web UI 分页浏览（page/page_size），feed API 服务 Agent 增量拉取（since/until），两者响应结构和使用场景完全不同
- **权衡**: 多 5-6 个文件，但职责清晰、可独立测试
- **后续**: 无

### 决策: Feed API 不包含 Domain 和 Infrastructure 层
- **背景**: 按六边形架构，每个模块通常有 domain/infrastructure/service/api 四层
- **考虑的替代方案**:
  1. 完整四层结构（含 domain models 和 repository）
  2. 仅 API + Service 两层，复用现有 ORM
- **选择**: 仅 API + Service 两层
- **理由**: Feed 模块无自有领域模型和数据持久化需求，它是现有 tweets 和 summaries 数据的只读查询视图。YAGNI 原则。
- **权衡**: 如果未来需要 Feed 专属的业务逻辑（如用户级定制过滤），可能需要补充 domain 层
- **后续**: 无

## 风险与缓解

- **db_created_at 索引缺失** — 通过 Alembic 迁移添加，SQLite 添加索引无需锁表
- **大时间区间查询性能** — 通过 `limit` 参数和 `FEED_MAX_TWEETS` 配置项控制，`has_more` 标志告知客户端分批请求

## 参考

- 项目 steering 文档: `.kiro/steering/structure.md`（六边形架构定义）
- 现有查询模式: `src/api/routes/tweets.py:101-119`
- 认证实现: `src/user/api/auth.py:28-90`
