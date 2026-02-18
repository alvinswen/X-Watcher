# 实现差距分析

## 1. 现有资产盘点

### 可直接复用的组件

| 需求领域 | 现有资产 | 复用方式 |
|---------|---------|---------|
| LLM 调用 | `LLMProvider.complete()` 接口 + `LLMProviderConfig.from_env()` + `create_summarization_service()` 中的 provider 初始化逻辑 | 提取 provider 构建逻辑为独立函数，TopicSummaryService 直接调用 |
| LLM 降级 | `_call_llm_with_fallback()` 模式（OpenRouter → MiniMax → OpenSource） | 在 TopicSummaryService 中实现类似的 failover 循环 |
| LLM 并发控制 | `_get_global_llm_semaphore()` 全局信号量（最大 3 并发） | 共享同一信号量，避免主题摘要与推文摘要同时压垮 LLM API |
| 推文查询 | `TweetOrm` + `get_tweets_by_usernames()` + 时间范围 WHERE 子句 | 组合 `author_username.in_()` 和 `created_at.between()` |
| 已有摘要 | `SummaryOrm` LEFT JOIN 模式（feed_service/browse_service） | 查询推文时 LEFT JOIN summaries 获取已有翻译 |
| 账号验证 | `ScraperFollow` 模型 + `get_follow_by_username()` 查询 | 验证主题账号是否在 scraper_follows 中 |
| 认证 | `get_current_admin_user` 依赖注入 | 所有主题 API 端点直接使用 |
| 数据库会话 | `get_db_session` + `get_async_session_maker()` | 标准依赖注入模式 |
| 异步任务跟踪 | `TaskRegistry` 单例（create_task/update_status/update_progress） | 可选复用，但主题摘要任务有自己的数据库持久化，可不依赖 |
| 前端 CRUD | FollowsView.vue 完整模式（dialog + form + table + validation） | 直接参考构建 TopicsView.vue |
| 前端轮询 | `TaskPollingService`（2 秒间隔，自动停止） | 直接复用监控摘要任务状态 |
| 前端布局 | AdminLayout.vue menuItems 数组 | 添加两个菜单项 |
| 时间格式化 | `utils/format.ts`（formatFullDateTime, formatCostUsd 等） | 直接使用 |

### 需要新建的组件

| 组件 | 说明 | 复杂度 |
|------|------|--------|
| `src/topic/` 完整模块 | domain + infrastructure + services + api 四层 | 中等 |
| 4 张数据库表 | topics, topic_accounts, topic_summary_tasks, topic_summaries | 低 |
| TopicSummaryService | 核心编排：查询推文 → 构建 prompt → 调用 LLM → 保存结果 | 高 |
| 聚合 prompt 构建逻辑 | 将多账号多推文组织成结构化输入 | 中等 |
| TopicsView.vue | 主题 CRUD + 账号管理 | 中等 |
| TopicSummariesView.vue | 摘要任务创建 + 状态监控 + 结果展示 | 中等 |
| Alembic 迁移 | 新建 4 张表 | 低 |
| 测试套件 | repository + service + API 测试 | 中等 |

## 2. 需求-资产映射与差距标注

| 需求 | 需要的能力 | 现有状态 | 差距 |
|------|-----------|---------|------|
| 需求 1: 主题 CRUD | 新数据模型 + Repository + Service + API | **Missing** — 无主题概念 | 需全新创建 |
| 需求 2: 账号管理 | 多对多关联 + ScraperFollow 验证 | **Partial** — ScraperFollow 查询已有 | 需新建关联表和验证逻辑 |
| 需求 3: 任务创建 | 任务数据模型 + 异步启动 | **Partial** — TaskRegistry 可参考 | 需自建 DB 持久化任务模型 |
| 需求 4: 异步执行 | 推文聚合 + prompt 构建 + LLM 调用 | **Partial** — LLM 体系可复用 | 需新建聚合 prompt 逻辑 |
| 需求 5: 提示词管理 | 默认模板 + 自定义覆盖 | **Missing** — 现有 PromptConfig 面向单推文 | 需新建主题级 prompt 模板 |
| 需求 6: 状态查询 | 任务列表 + 详情 + 结果关联 | **Missing** — 需新建 API | 需全新创建 |
| 需求 7: 前端界面 | 两个新页面 + 路由 + 菜单 | **Missing** — 但模式成熟 | 需全新创建，模式可复用 |

## 3. 实现方案评估

### 方案 B: 创建独立模块（推荐）

**理由**:
- 主题管理是一个独立的业务领域，与现有摘要（per-tweet）在语义和数据流上截然不同
- 现有模块（scraper, summarization, preference）均已独立，遵循六边形架构
- 独立模块便于测试、维护和未来扩展

**新建清单**:
```
src/topic/
├── __init__.py
├── domain/
│   ├── __init__.py
│   └── models.py              # 域模型 + 状态枚举
├── infrastructure/
│   ├── __init__.py
│   ├── models.py              # 4 个 ORM 模型
│   └── repository.py          # TopicRepository + TopicSummaryTaskRepository
├── services/
│   ├── __init__.py
│   ├── topic_service.py       # 主题 CRUD 编排
│   └── topic_summary_service.py  # 摘要任务执行编排（核心）
└── api/
    ├── __init__.py
    ├── schemas.py             # Pydantic 请求/响应模型
    └── routes.py              # FastAPI 路由
```

**集成点**:
- `src/main.py` — 注册新 router
- `alembic/env.py` — 导入新 ORM 模型
- `tests/conftest.py` — 导入新 ORM 模型以注册到 Base.metadata
- `src/summarization/llm/` — 复用 LLMProvider 和 config，不修改

**优势**:
- ✅ 清晰的职责边界，不污染现有模块
- ✅ 独立可测试
- ✅ 遵循项目已有的模块化模式
- ✅ LLM 基础设施通过导入复用，无需修改

**劣势**:
- ❌ 更多新文件（约 12 个 Python 文件 + 6 个前端文件 + 测试）
- ❌ provider 构建逻辑存在一定代码重复（可通过提取公共函数解决）

## 4. 复杂度与风险评估

### 工作量: M（3-7 天）

**理由**: 主要是标准 CRUD + 异步任务编排，核心复杂点在 TopicSummaryService 的 prompt 构建和上下文窗口管理。LLM 基础设施可复用，前端模式成熟。

### 风险: 低-中

| 风险项 | 等级 | 说明 |
|--------|------|------|
| LLM 上下文窗口 | 中 | 大量推文可能超出模型限制，需要截断或分段策略 |
| 异步任务生命周期 | 低 | 使用 asyncio.create_task + DB 持久化，模式清晰 |
| Provider 构建代码重复 | 低 | 可提取 `build_llm_providers()` 公共函数 |
| 前端复杂度 | 低 | 直接复用 FollowsView + TasksView 模式 |
| 数据库迁移 | 低 | 新建表，无修改现有表 |

## 5. 待研究项（设计阶段解决）

1. **上下文窗口管理策略**: 当推文总 token 数超出模型限制时，选择截断还是分段摘要？需确认各 LLM 模型的具体上下文窗口大小
2. **Provider 构建逻辑提取**: 是否从 `create_summarization_service()` 中提取 provider 构建为公共函数，还是在 TopicSummaryService 中直接内联
3. **Token 估算算法**: 如何高效估算中英混合内容的 token 数，以决定是否需要截断

## 6. 设计阶段建议

- **推荐方案**: 方案 B（独立模块）
- **关键决策**: provider 构建逻辑的复用方式（提取公共函数 vs 内联）
- **优先实现**: 先完成后端（域模型 → ORM → Repository → Service → API），再实现前端
- **测试策略**: 以 TopicSummaryService 为核心测试对象，mock LLM provider
