# Feed API — Gap 分析报告

## 1. 现有代码库调查

### 1.1 可复用的关键组件

| 组件 | 文件路径 | 可复用性 |
|------|----------|----------|
| **TweetOrm** | `src/scraper/infrastructure/models.py` | ✅ 直接使用，含 `db_created_at` 字段 |
| **SummaryOrm** | `src/summarization/infrastructure/models.py` | ✅ LEFT JOIN 目标 |
| **推文+摘要 LEFT JOIN 查询** | `src/api/routes/tweets.py:101-119` | ✅ 可复用查询模式 |
| **统一认证中间件** | `src/user/api/auth.py` | ✅ `get_current_user` / `get_current_admin_user` |
| **异步会话管理** | `src/database/async_session.py` | ✅ `get_db_session` / `get_async_session` |
| **Agent 工具注册** | `src/agent/config.py` | ✅ `register_tool()` / `_tools` 注册表 |
| **conftest fixtures** | `tests/conftest.py` | ✅ `async_session` / `async_client` |

### 1.2 架构模式与约定

- **路由定义**: `APIRouter(prefix="/api/xxx", tags=["xxx"])` → `app.include_router()`
- **认证方式**:
  - `src/preference/api/auth.py`: 简单 `ADMIN_API_KEY` 环境变量比对，返回 `bool`（403）
  - `src/user/api/auth.py`: 完整的 API Key + JWT 认证，返回 `UserDomain`（401）
- **依赖注入**: `Depends(get_db_session)` 获取异步会话
- **响应模型**: Pydantic BaseModel，直接在路由函数返回
- **错误格式**: `HTTPException(status_code=xxx, detail="描述")`
- **测试模式**: `async_session` fixture + `async_client` fixture，`dependency_overrides` 覆盖数据库会话

### 1.3 数据库索引现状

| 表 | 已有索引 | 缺失索引 |
|----|----------|----------|
| `tweets` | `ix_tweets_created_at`, `ix_tweets_author_username`, `ix_tweets_deduplication_group_id` | ⚠️ **`db_created_at` 无索引** |
| `summaries` | `ix_summaries_tweet_id`, `ix_summaries_content_hash`, `ix_summaries_cached` | — |

**关键发现**: Feed API 的核心查询基于 `db_created_at` 过滤，但该字段当前**没有数据库索引**。需要新增索引以保证查询性能。

---

## 2. 需求可行性分析

### 需求 → 资产映射

| 需求 | 所需技术能力 | 现有资产 | Gap 状态 |
|------|-------------|----------|----------|
| **需求 1: 时间区间查询** | WHERE `db_created_at` 过滤 + ORDER BY | TweetOrm 有 `db_created_at` 字段 | ⚠️ 缺少索引 |
| **需求 2: 返回完整内容** | LEFT JOIN tweets + summaries | `tweets.py:101-119` 有参考模式 | ✅ 可复用模式 |
| **需求 3: 响应格式** | Pydantic 响应模型 + COUNT 查询 | 项目通用模式 | ✅ Missing: 新建 schemas |
| **需求 4: 数量控制** | `limit` 参数 + 配置项 | `src/config.py` Settings 类 | ✅ Missing: 新增配置字段 |
| **需求 5: 认证** | API Key / JWT 认证 | `src/user/api/auth.py` 完整实现 | ✅ 直接复用 |
| **需求 6: Agent 工具** | 工具元数据 + 系统提示 | `src/agent/config.py` 占位代码 | ✅ Missing: 新建 tools.py |
| **需求 7: 错误处理** | HTTPException + 参数验证 | FastAPI 内置验证 + 项目现有模式 | ✅ 直接复用 |

### 复杂度信号

- **类型**: 简单 CRUD 查询 + API 封装
- **外部依赖**: 无新增（不涉及外部 API 或新库）
- **数据库变更**: 仅新增索引（非结构变更）
- **业务逻辑**: 最小化（时间过滤 + JOIN + 序列化）

---

## 3. 实现方案选项

### 方案 A: 扩展现有 Tweets API

在 `src/api/routes/tweets.py` 的 `list_tweets()` 中直接添加 `since`/`until` 参数。

**改动范围**:
- 修改 `src/api/routes/tweets.py` — 添加参数和查询逻辑
- 修改响应模型添加 `db_created_at`、`summary_text`、`translation_text` 字段

**权衡**:
- ✅ 最少新文件，改动最小
- ✅ 复用现有 LEFT JOIN 查询
- ❌ 现有端点返回格式与 Feed 需求不同（分页 vs 全量、字段集不同）
- ❌ 违背单职责原则：tweets API 服务于 Web UI 分页浏览，feed API 服务于 Agent 增量拉取
- ❌ `TweetListItem` 模型需要大量条件字段（`include_summary` 时才有摘要字段）

**评估**: ❌ 不推荐 — 两个场景的响应结构差异较大，强行合并会增加复杂度。

### 方案 B: 新建 Feed 模块（推荐）

创建独立的 `src/feed/` 模块，遵循项目六边形架构。

**新增文件**:
```
src/feed/
    __init__.py
    api/
        __init__.py
        routes.py       # GET /api/feed 路由
        schemas.py      # FeedTweetItem, FeedResponse
    services/
        __init__.py
        feed_service.py # FeedService（查询编排）
```

**集成点**:
- `src/main.py` — 注册 `feed_router`
- `src/config.py` — 添加 `feed_max_tweets` 配置项
- 复用: `TweetOrm`, `SummaryOrm`, `get_db_session`, `get_current_user`

**权衡**:
- ✅ 清晰的职责分离（Feed 独立于 Tweets 浏览）
- ✅ 符合项目六边形架构模式
- ✅ 易于独立测试
- ✅ 不影响现有 API 行为
- ❌ 多几个文件

**评估**: ✅ **推荐** — 与项目已有模块（scraper, deduplication, summarization, preference）模式一致。

### 方案 C: 混合方案

在 tweets 路由中添加 `since`/`until` 参数（方案 A），同时新建 `src/feed/` 模块提供 Feed 专用端点（方案 B）。

**权衡**:
- ✅ 两种场景都有最优端点
- ❌ 重复的查询逻辑
- ❌ 过度工程化（YAGNI）

**评估**: ❌ 不推荐 — 当前无需在 tweets API 添加时间过滤，Feed 端点已完全覆盖需求。

---

## 4. 认证方案选择

项目中有两套认证：

| 认证方式 | 文件 | HTTP 状态码 | 返回值 | 适用场景 |
|----------|------|-------------|--------|----------|
| `verify_admin_api_key` | `src/preference/api/auth.py` | 403 | `bool` | 简单管理端点 |
| `get_current_user` | `src/user/api/auth.py` | 401 | `UserDomain` | 完整用户认证 |

**Feed API 认证选择**: 使用 `get_current_user`（`src/user/api/auth.py`）

**理由**:
- 需求 5 要求 HTTP 401（而非 403）
- 支持 API Key 和 JWT 两种方式，对 Agent 更友好
- 返回 `UserDomain`，未来可扩展为用户级别的 Feed 定制

---

## 5. 需要研究的问题

| 问题 | 阶段 | 描述 |
|------|------|------|
| `db_created_at` 索引 | 设计阶段 | 需要通过 Alembic 迁移添加索引，评估对现有数据的影响 |
| 大数据量性能 | 设计阶段 | 当时间区间内推文数量很大（>1000）时，一次性返回全部数据的内存和网络开销 |

---

## 6. 复杂度与风险评估

### 工作量: **S**（1-3 天）

- 查询模式完全复用现有代码
- 无新增外部依赖
- 无数据库结构变更（仅新增索引）
- 模块结构遵循已有模式

### 风险: **低**

- 技术栈完全已知（FastAPI + SQLAlchemy + Pydantic）
- 与现有代码集成点清晰
- 不影响任何现有功能
- 测试模式可直接复用

---

## 7. 设计阶段建议

### 推荐方案: 方案 B（新建 Feed 模块）

### 关键设计决策
1. **认证**: 使用 `get_current_user`（`src/user/api/auth.py`）
2. **数据库索引**: 通过 Alembic 迁移为 `tweets.db_created_at` 添加索引
3. **查询模式**: 参考 `src/api/routes/tweets.py:101-119` 的 LEFT JOIN 模式
4. **配置**: 在 `Settings` 中添加 `feed_max_tweets` 字段

### 需要带入设计阶段的研究项
- 是否需要对大时间区间的请求添加安全阀（如最长区间限制）
- `include_summary=false` 时是否需要完全不同的 SQL 查询路径
