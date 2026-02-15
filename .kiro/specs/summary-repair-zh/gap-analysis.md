# 差距分析

## 1. 现有资产调查

### 需求-资产映射

| 需求 | 现有资产 | 差距 |
|------|---------|------|
| **需求 1: 摘要补缺 API** | | |
| 补缺预览（查询无摘要推文数量） | `TweetOrm`、`SummaryOrm` 已有 LEFT JOIN 模式（见 `tweets.py:103-121`、`feed_service.py`） | **缺失**：无现有端点执行此查询 |
| 补缺执行（后台任务） | `_run_summarization_task()` 可直接复用（`routes.py:51-131`），接受 `tweet_ids` + `force_refresh` | **缺失**：无端点触发"先查 ID 再执行"的编排逻辑 |
| 任务进度查询 | `TaskRegistry` + `GET /api/summaries/tasks/{task_id}` 完全可复用 | 无差距 |
| **需求 2: 摘要重置 API** | | |
| 重置预览（按时间范围查推文数量） | `TweetOrm.created_at` 已有索引和时间范围过滤模式（`feed_service.py`） | **缺失**：无现有端点 |
| 重置执行（force_refresh=true） | 同上，`_run_summarization_task()` 已支持 `force_refresh` 参数 | **缺失**：无端点触发 |
| **需求 3: API 权限统一** | | |
| Feed API 认证 | `get_current_user` 已在 `feed/api/routes.py` 中使用 | 无差距 |
| Summarization API 认证 | `get_current_admin_user` 已在 `user/api/auth.py:93` 定义，`scraper_config_router.py` 有参考模式 | **缺失**：`summarization/api/routes.py` 的 6 个端点无认证 |
| Admin API 认证 | 同上 | **缺失**：`api/routes/admin.py` 的 4 个端点无认证 |
| Tweets API 认证 | 同上 | **缺失**：`api/routes/tweets.py` 的 2 个端点无认证 |
| Deduplication API 认证 | 同上 | **缺失**：`deduplication/api/routes.py` 的 5 个端点无认证 |
| **需求 4: 前端 UI** | | |
| 摘要工具下拉菜单 | `el-dropdown` 未在现有页面使用过（`TweetsView.vue` 使用的是 `el-button` 和 `el-checkbox`） | **缺失**：需新增组件，但 Element Plus 已安装 |
| 对话框（补缺/重置） | `el-dialog` 已在 `FollowsView.vue`、`TasksView.vue`、`UsersView.vue` 中使用，有成熟模式 | 无差距（模式可复用） |
| 日期范围选择器 | `el-date-picker` 未在现有页面使用 | **缺失**：需新增，但 Element Plus 已内置 |
| 任务轮询 | `taskPollingService` + `summariesApi.getTaskStatus()` 在 `TweetsView.vue:253-274` 已有完整模式 | 无差距（模式可复用） |
| **需求 5: Agent 工具注册** | | |
| 工具元数据 | `src/agent/tools.py` 有 `FEED_TOOLS` 模式可参考 | **缺失**：需添加新工具定义 |
| 系统提示更新 | `src/agent/config.py` 有 `SYSTEM_PROMPT` 可扩展 | **缺失**：需添加摘要修复说明 |

### 现有模式总结

- **后台任务模式**：`BackgroundTasks` + `TaskRegistry` + 独立事件循环（`summarization/api/routes.py`、`deduplication/api/routes.py`、`api/routes/admin.py` 均使用相同模式）
- **认证模式**：`Depends(get_current_admin_user)` 注入参数（`scraper_config_router.py` 有 14 处使用，是最佳参考）
- **前端 API 调用模式**：`client.get/post` + TypeScript 类型定义（`summaries.ts` 可直接扩展）
- **前端对话框模式**：`el-dialog` + `v-model` + 表单 + 确认/取消按钮（`FollowsView.vue`、`UsersView.vue` 可参考）
- **前端轮询模式**：`taskPollingService.startPolling()` + `onComplete` 回调（`TweetsView.vue:253-274`）

## 2. 可行性分析

### 技术需求清单

| 类别 | 需求 | 复杂度 |
|------|------|--------|
| 数据模型 | `SummaryBackfillRequest/Response`、`SummaryResetRequest/Response`、`SummaryPreviewResponse` — Pydantic 模型 | 简单 CRUD |
| API | 4 个新端点 + 17 个现有端点添加认证参数 | 简单 CRUD |
| 查询逻辑 | LEFT JOIN 查无摘要推文、时间范围查询推文 ID — SQL 查询 | 简单 CRUD |
| 后台任务 | 直接复用 `_run_summarization_task()`，无需新逻辑 | 无新工作 |
| 前端 UI | `el-dropdown` + 2 个 `el-dialog` + `el-date-picker` | 工作流 |
| Agent | 工具元数据 JSON 定义 + 系统提示文本 | 简单 CRUD |

### 约束与风险

1. **推文数量无上限**：backfill/reset 可能查到数千条推文。现有 `_run_summarization_task()` 接收完整 `tweet_ids` 列表传给 `summarize_tweets()`，不经过 `BatchSummaryRequest` 的 `max_length=1000` 校验。内部的全局并发信号量 (`_GLOBAL_MAX_CONCURRENT_LLM=5`) 会自然限流。**风险：低** — 不会过载。
2. **认证添加的破坏性**：为 17 个现有端点添加认证参数是机械性修改，但需要同步更新前端 API 客户端的认证头。**风险：低** — 前端 `client.ts` 的请求拦截器已自动注入 `X-API-Key` header，现有前端代码无需修改。
3. **现有测试影响**：`tests/summarization/test_api_routes.py` 的测试用例在添加认证后会因缺少凭证而失败 (401)。**风险：中** — 需要在测试 fixture 中 mock 认证依赖或注入测试 API Key。

## 3. 实现方案选项

### 方案 A: 扩展现有组件

**适用性**：本功能自然契合现有结构。

- **`src/summarization/api/routes.py`**：追加 4 个端点 + 2 个辅助查询函数（~100 行）。当前文件 439 行，扩展后 ~540 行，仍在可管理范围。
- **`src/summarization/api/schemas.py`**：追加 5 个 Pydantic 模型（~60 行）。当前 162 行，扩展后 ~220 行。
- **`src/web/src/api/summaries.ts`**：追加 4 个 API 方法（~40 行）。当前 44 行。
- **`src/web/src/views/TweetsView.vue`**：追加下拉菜单 + 2 个对话框 + 处理函数（~150 行）。当前 465 行，扩展后 ~615 行。
- 4 个路由文件添加认证参数：每个文件 2-3 行导入 + 每个端点 1 行参数。

**优点**：
- ✅ 零新文件（除测试），复用所有现有基础设施
- ✅ 与现有代码模式完全一致
- ✅ 开发速度最快

**缺点**：
- ❌ `TweetsView.vue` 会增长到 ~615 行（仍可接受）

### 方案 B: 创建新组件

- 新建 `src/summarization/api/repair_routes.py` 独立路由文件
- 新建 `src/web/src/views/SummaryRepairView.vue` 独立页面
- 新建 `src/web/src/api/summaryRepair.ts` 独立 API 客户端

**优点**：
- ✅ 职责分离更清晰

**缺点**：
- ❌ 需要在 `main.py` 注册新路由、`router/index.ts` 添加新路由、`AdminLayout.vue` 添加导航菜单项
- ❌ 前端需要新页面跳转，增加用户操作步骤
- ❌ 与现有摘要 API 拆分后，`/api/summaries/` 前缀下的功能分散在两个文件中

### 方案 C: 混合方案（推荐）

- **后端**：扩展现有 `routes.py` 和 `schemas.py`（新端点自然属于 `/api/summaries/` 前缀）
- **前端**：扩展 `TweetsView.vue`（与"批量摘要"同属一个功能组，放在同一页面最自然）
- **认证**：直接修改现有 4 个路由文件（机械性修改，无需新抽象）
- **Agent**：扩展现有 `tools.py` 和 `config.py`

等同于**方案 A**，因为本功能的特点就是"少量新端点 + 大量复用"，不需要新组件。

## 4. 工作量与风险评估

- **工作量：S (1-3 天)** — 所有修改都是在现有模式上的直接扩展，无新技术、无数据库迁移、无新依赖。
- **风险：低** — 复用现有的后台任务、认证、轮询等成熟基础设施。唯一的中等风险是现有测试需要适配认证变更。

## 5. 设计阶段建议

- **首选方案**：方案 A/C（扩展现有组件）
- **关键决策**：
  1. 认证添加后的现有测试修复策略（mock vs 注入测试 Key）
  2. `TweetsView.vue` 的对话框是否需要抽取为独立组件（如果超过 600 行可考虑）
- **无需外部研究**：所有依赖（Element Plus、FastAPI、SQLAlchemy）均已在项目中使用
