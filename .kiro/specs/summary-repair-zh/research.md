# 研究与设计决策日志

---
**用途**: 记录发现阶段的研究成果、架构调研和决策依据，为技术设计提供支撑。
---

## Summary
- **Feature**: `summary-repair-zh`
- **Discovery Scope**: Extension（扩展现有系统）
- **Key Findings**:
  - 后台任务基础设施完全可复用：`_run_summarization_task()` + `TaskRegistry` + 独立事件循环模式
  - 认证依赖 `get_current_admin_user` 已成熟且有 14 处使用参考（`scraper_config_router.py`），机械性添加即可
  - 前端 `client.ts` 的请求拦截器已自动注入 `X-API-Key` header，后端添加认证不影响前端现有功能

## Research Log

### 后台任务模式分析
- **Context**: 补缺/重置操作需要异步执行大批量 LLM 调用，需要评估现有后台任务模式的可复用性
- **Sources Consulted**: `src/summarization/api/routes.py:51-131`、`src/deduplication/api/routes.py:104-168`、`src/api/routes/admin.py`
- **Findings**:
  - 所有模块使用相同模式：`BackgroundTasks.add_task()` → 同步包装函数 → `asyncio.new_event_loop()` → 异步执行体
  - `_run_summarization_task(task_id, tweet_ids, force_refresh)` 完全满足补缺（`force_refresh=False`）和重置（`force_refresh=True`）的需求
  - 全局 LLM 并发信号量 `_GLOBAL_MAX_CONCURRENT_LLM=5` 自然限流，无需额外限制
  - `TaskRegistry` 是单例，管理任务生命周期（pending → running → completed/failed），已有 `create_task()`、`update_task_status()`、`get_task_status()` 完整 API
- **Implications**: 新端点只需调用已有函数，零后台任务新逻辑

### 认证体系分析
- **Context**: 需要统一所有 API 权限，17 个端点需要添加认证
- **Sources Consulted**: `src/user/api/auth.py`、`src/preference/api/scraper_config_router.py`、`src/feed/api/routes.py`
- **Findings**:
  - `get_current_user`（L28）：JWT 或 API Key 认证，返回 `UserDomain`
  - `get_current_admin_user`（L93）：先调用 `get_current_user`，再检查 `is_admin`；支持 `ADMIN_API_KEY` 环境变量引导模式
  - 添加方式：导入 + 端点函数签名添加 `admin: UserDomain = Depends(get_current_admin_user)`
  - `scraper_config_router.py` 有 14 处使用参考，是最佳模板
  - 前端 `client.ts` 已有全局请求拦截器注入 `X-API-Key` header，后端添加认证对前端透明
- **Implications**: 机械性修改，每个端点添加 1 行参数 + 文件顶部 2-3 行导入

### LEFT JOIN 查询无摘要推文
- **Context**: 补缺功能需要查询没有关联摘要记录的推文
- **Sources Consulted**: `src/feed/services/feed_service.py`（tweets LEFT JOIN summaries 模式）、`src/scraper/infrastructure/models.py`（TweetOrm）、`src/summarization/infrastructure/models.py`（SummaryOrm）
- **Findings**:
  - `feed_service.py` 已有 LEFT JOIN 模式：`outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)`
  - 补缺查询：在 LEFT JOIN 基础上添加 `WHERE SummaryOrm.tweet_id IS NULL`
  - 可选时间过滤：`TweetOrm.created_at >= since AND TweetOrm.created_at < until`
  - `TweetOrm.created_at` 已有索引（DateTime with timezone）
- **Implications**: 查询逻辑简单直接，无需新增 ORM 模型或仓库方法

### 前端 UI 模式分析
- **Context**: 需要在推文列表页添加摘要工具 UI
- **Sources Consulted**: `src/web/src/views/TweetsView.vue`、`src/web/src/api/summaries.ts`、`src/web/src/services/polling.ts`
- **Findings**:
  - Element Plus 已安装，`el-dropdown`、`el-dialog`、`el-date-picker` 均可直接使用
  - `TweetsView.vue` 已有完整的批量摘要 + 轮询模式（L242-280），可直接复用
  - `taskPollingService.startPolling(taskId, fetchStatus, onStatusUpdate, onComplete, onError)` 返回 `PollingHandle`
  - `summariesApi` 客户端可直接扩展新方法
- **Implications**: 前端开发遵循已有模式，无需学习新组件或引入新依赖

## Architecture Pattern Evaluation

| 选项 | 描述 | 优势 | 风险/限制 | 备注 |
|------|------|------|-----------|------|
| 扩展现有组件 | 在现有 routes.py/schemas.py/TweetsView.vue 中追加代码 | 零新文件、最快开发、完全一致的模式 | routes.py ~540 行、TweetsView.vue ~615 行（仍可接受） | 推荐方案 |
| 创建新组件 | 新建 repair_routes.py、SummaryRepairView.vue 等 | 职责分离更清晰 | 需要注册新路由/导航、功能分散、增加用户操作步骤 | 过度设计 |

## Design Decisions

### Decision: 扩展现有组件而非创建新组件
- **Context**: 新增 4 个 API 端点和 2 个对话框，可以放在现有文件中也可以新建文件
- **Alternatives Considered**:
  1. 扩展现有 `routes.py`/`schemas.py`/`TweetsView.vue` — 追加约 100/60/150 行
  2. 新建 `repair_routes.py`/`SummaryRepairView.vue` — 独立文件
- **Selected Approach**: 扩展现有组件
- **Rationale**: 新端点自然属于 `/api/summaries/` 前缀，与现有摘要功能同域；前端操作在推文列表页完成更自然；文件大小增长在可控范围内
- **Trade-offs**: 文件略增长 vs 保持一致性和开发速度
- **Follow-up**: 如果 TweetsView.vue 超过 700 行，考虑抽取对话框为独立组件

### Decision: 补缺/重置使用 preview + execute 双端点模式
- **Context**: 批量操作需要让用户先确认影响范围再执行
- **Alternatives Considered**:
  1. 单个 POST 端点，body 中 `dry_run` 参数控制 — 简单但语义不清晰
  2. 独立 preview GET + execute POST — 语义清晰，前端流程自然
- **Selected Approach**: 独立 preview GET + execute POST
- **Rationale**: preview 是幂等查询（GET），execute 是有副作用操作（POST），RESTful 语义更清晰；前端对话框流程自然：打开 → 查询 → 确认 → 执行
- **Trade-offs**: 多 2 个端点 vs 清晰的 API 语义
- **Follow-up**: 无

### Decision: 认证添加策略
- **Context**: 17 个现有端点需要添加认证，需要统一且安全的修改方式
- **Alternatives Considered**:
  1. 路由级中间件 — 一次性添加，但粒度粗（无法区分 admin/user）
  2. 端点级 `Depends()` 注入 — 每个端点单独添加参数
- **Selected Approach**: 端点级 `Depends()` 注入
- **Rationale**: 与项目现有模式一致（`scraper_config_router.py`）；不同路由组需要不同权限级别（Feed 用 `get_current_user`，其他用 `get_current_admin_user`）
- **Trade-offs**: 机械性重复 vs 灵活性和一致性
- **Follow-up**: 现有测试需要适配认证变更（添加 mock 或测试 API Key）

## Risks & Mitigations
- 现有测试认证适配 — 在测试 fixture 中 mock `get_current_admin_user` 依赖或注入测试 API Key
- 大批量补缺/重置可能产生大量 LLM 调用 — 全局信号量 `_GLOBAL_MAX_CONCURRENT_LLM=5` 自然限流，无需额外措施
- TweetsView.vue 代码量增长 — 监控文件行数，超过 700 行时抽取对话框组件

## References
- FastAPI 依赖注入文档 — `Depends()` 模式
- Element Plus `el-dropdown` / `el-dialog` / `el-date-picker` — 组件 API
- SQLAlchemy `outerjoin` — LEFT JOIN 查询模式
