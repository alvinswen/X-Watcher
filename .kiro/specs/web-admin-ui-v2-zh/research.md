# Research & Design Decisions

## Summary
- **Feature**: web-admin-ui-v2
- **Discovery Scope**: Extension（在已有 Vue 3 + Element Plus 前端基础上扩展）
- **Key Findings**:
  - 后端所有 API schema 已确认，无需额外研究；前端只需创建对应的 TypeScript 类型和 API 模块
  - 现有前端代码模式高度一致（API 模块、类型定义、服务模式），新代码完全可照搬
  - 无新外部依赖引入——所有 UI 需求 Element Plus 已覆盖，Pinia 已安装只需注册

## Research Log

### Element Plus 侧边栏布局方案
- **Context**: 需求 1 要求从顶部导航升级为侧边栏布局
- **Sources Consulted**: Element Plus Container/Aside/Menu 组件文档
- **Findings**:
  - `el-container` + `el-aside` + `el-main` 提供标准双栏布局
  - `el-menu` 的 `collapse` 属性原生支持折叠/展开
  - `el-menu` 的 `router` 属性设为 true 时，直接用 `index` 绑定路由路径即可导航
  - `el-menu` 的 `default-active` 可绑定到 `$route.path` 实现自动高亮
- **Implications**: 无需自定义布局组件库，Element Plus 原生能力完全覆盖

### Pinia + Axios 集成模式
- **Context**: 需求 3 要求将 API Key 管理迁移到 Pinia store
- **Sources Consulted**: Pinia 官方文档、Axios 拦截器模式
- **Findings**:
  - Pinia store 的 `$subscribe` 或 action 可同步到 localStorage
  - Axios 拦截器内可直接 import store 实例（Vue 3 setup 模式）
  - 注意：不能在 store 定义文件顶层调用 `useAuthStore()`，需在拦截器函数体内调用
- **Implications**: client.ts 拦截器需改为在请求时动态获取 store 状态，而非模块顶层

### 后端调度管理 API Schema
- **Context**: 需求 6 调度管理页面需要对接 5 个后端端点
- **Sources Consulted**: `src/preference/api/scraper_config_router.py`, `src/preference/api/schemas.py`
- **Findings**:
  - GET `/api/admin/scraping/schedule` 返回统一的 `ScheduleConfigResponse`
  - PUT interval 接收 `{ interval_seconds: int }`，范围 300-604800
  - PUT next-run 接收 `{ next_run_time: datetime }`，必须为未来时间
  - POST enable/disable 无请求体，返回同一个 ScheduleConfigResponse
  - 所有端点要求 Admin 认证
- **Implications**: 前端类型定义可完全映射后端 Pydantic schema

### 后端用户管理 API Schema
- **Context**: 需求 7 用户管理页面需要对接 3 个后端端点
- **Sources Consulted**: `src/user/api/admin_user_router.py`, `src/user/domain/schemas.py`
- **Findings**:
  - POST `/api/admin/users` 接收 `{ name, email }`，返回 `{ user, temp_password, api_key }`
  - GET `/api/admin/users` 返回 `UserResponse[]`（id, name, email, is_admin, created_at）
  - POST `/api/admin/users/{id}/reset-password` 返回 `{ temp_password }`
  - 邮箱重复返回 409 Conflict
- **Implications**: 创建用户后需特殊 UI 展示临时密码和 API Key（一次性信息）

### 后端摘要/去重批量 API Schema
- **Context**: 需求 8-9 需要对接摘要再生成和批量操作端点
- **Sources Consulted**: `src/summarization/api/routes.py`, `src/deduplication/api/routes.py`
- **Findings**:
  - POST `/api/summaries/tweets/{id}/regenerate` 无请求体，返回 SummaryResponse
  - POST `/api/summaries/batch` 接收 `{ tweet_ids: str[], force_refresh: bool }`，返回 `{ task_id, status }`（202）
  - POST `/api/deduplicate/batch` 接收 `{ tweet_ids: str[] }`，返回 `{ task_id, status }`（202）
  - GET `/api/summaries/stats` 返回 `{ total_cost_usd, total_tokens, provider_breakdown }`
  - 所有摘要/去重端点无需 Admin 认证
- **Implications**: 批量操作返回 task_id，可复用现有 TaskPollingService 轮询进度

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks | Notes |
|--------|-------------|-----------|-------|-------|
| Option B: 新建组件 | 为每个功能模块创建独立文件 | 职责清晰，独立可测试，模式一致 | 文件数增加约 15 个 | 推荐方案，详见 gap-analysis.md |

## Design Decisions

### Decision: 侧边栏布局使用独立 AdminLayout 组件
- **Context**: App.vue 当前直接包含顶部导航，需要升级为侧边栏
- **Alternatives Considered**:
  1. 在 App.vue 中直接写侧边栏 — 会使 App.vue 膨胀
  2. 创建独立 AdminLayout.vue — 职责分离
- **Selected Approach**: 创建 `layouts/AdminLayout.vue`，App.vue 仅作路由容器
- **Rationale**: AdminLayout 承担布局职责，App.vue 保持精简，未来扩展登录页时可用不同布局
- **Trade-offs**: 多一个文件层级，但未来扩展更灵活

### Decision: Auth Store 取代直接 localStorage 操作
- **Context**: API Key 管理散落在 App.vue 和 client.ts 中
- **Alternatives Considered**:
  1. 保持 localStorage 直接操作 — 最小改动
  2. 迁移到 Pinia store — 统一状态管理
- **Selected Approach**: 创建 `stores/auth.ts` Pinia store
- **Rationale**: 为 Step 2 JWT 登录升级做准备；统一认证状态便于多组件访问
- **Trade-offs**: 需修改 client.ts 拦截器的 API Key 读取方式

### Decision: 仪表盘数据并行加载 + 独立错误处理
- **Context**: 仪表盘需要从 5+ 个 API 获取数据
- **Alternatives Considered**:
  1. 串行加载 — 简单但慢
  2. Promise.allSettled 并行加载 — 快且容错
- **Selected Approach**: Promise.allSettled 并行加载，每个数据源独立错误处理
- **Rationale**: 需求 5.10 明确要求"任一数据源加载失败不影响其他卡片"
- **Trade-offs**: 需要为每个数据源维护独立的 loading/error 状态

### Decision: 批量操作复用 TaskPollingService
- **Context**: 批量摘要/去重返回 task_id，需要轮询进度
- **Selected Approach**: 复用现有 `TaskPollingService`
- **Rationale**: 已有成熟的 2 秒轮询 + 回调机制，无需重复实现

## Risks & Mitigations
- **style.css 替换可能影响现有页面样式** — 逐步替换，替换后回归测试所有页面
- **App.vue 重构可能引入回退** — 确保所有路由和导航功能保持不变
- **Pinia store 引入需修改 client.ts** — 兼容模式：store 有值用 store，否则降级 localStorage

## References
- Element Plus Container 文档
- Element Plus Menu 文档
- Pinia 官方文档
- Vue Router 导航守卫文档
