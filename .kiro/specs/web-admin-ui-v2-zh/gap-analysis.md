# Gap Analysis: web-admin-ui-v2

## 1. 现状调查

### 1.1 现有前端资产

| 类别 | 文件 | 说明 |
|------|------|------|
| **API 模块** | `api/client.ts` | Axios 实例 + API Key 拦截器 + 统一错误处理 |
| | `api/tweets.ts` | `tweetsApi.getList()`, `getDetail()` |
| | `api/tasks.ts` | `tasksApi.triggerScraping()`, `getStatus()`, `listTasks()`, `deleteTask()` |
| | `api/follows.ts` | `followsApi.list()`, `add()`, `update()`, `delete()`, `toggleActive()` |
| **类型** | `types/tweet.ts` | `TweetListItem`, `TweetDetail`, `Summary`, `DeduplicationInfo`, `MediaItem` |
| | `types/task.ts` | `TaskStatusResponse`, `TaskListItem`, `TaskProgress`, `ScrapeTriggerRequest/Response`, `ScrapingFollow` |
| | `types/index.ts` | `ApiError`, `PaginationParams` + barrel export |
| **视图** | `views/TweetsView.vue` | 推文列表（分页/筛选/卡片布局） |
| | `views/TweetDetailView.vue` | 推文详情（摘要/去重/媒体） |
| | `views/FollowsView.vue` | 关注账号 CRUD 表格 |
| | `views/TasksView.vue` | 任务监控（轮询/触发/历史） |
| **服务** | `services/polling.ts` | `TaskPollingService` 类（2秒轮询 + 回调） |
| | `services/message.ts` | Element Plus Message 封装 |
| **布局** | `App.vue` | 顶部导航栏 + API Key 对话框 + RouterView |
| **路由** | `router/index.ts` | 4 条路由（/tweets, /tweets/:id, /follows, /tasks），`/` 重定向到 `/tweets` |
| **入口** | `main.ts` | createApp + ElementPlus + router（**无 Pinia**） |
| **样式** | `style.css` | Vite 脚手架默认（暗色主题，**与 Element Plus 冲突**） |
| **未用** | `components/HelloWorld.vue` | Vite 脚手架残留 |

### 1.2 现有代码规约

| 规约 | 模式 |
|------|------|
| API 模块导出 | `export const xxxApi = { async method(): Promise<Type> { ... } }` |
| API 请求 | `client.get<T>(path, { params })`，返回 `response.data` |
| 路径常量 | 模块顶部 `const PREFIX = "/xxx"`，模板字符串拼路径 |
| 类型定义 | 每个 interface/property 都有 JSDoc 注释，属性名 snake_case |
| 类型导出 | barrel export：`types/index.ts` 和 `api/index.ts` 统一 re-export |
| 服务模式 | 类 + 单例导出（polling）或对象聚合（message） |
| 错误处理 | 集中在 client.ts 拦截器，通过 messageService 显示 |
| 组件模式 | Vue 3 Composition API `<script setup lang="ts">`，无 Pinia store |
| 时间格式化 | 各组件内重复定义 `formatTime()`、`formatFullTime()` |

### 1.3 后端已有但前端未对接的 API

| 模块 | 端点 | 方法 | 认证要求 |
|------|------|------|----------|
| **调度管理** | `/api/admin/scraping/schedule` | GET | Admin |
| | `/api/admin/scraping/schedule/interval` | PUT | Admin |
| | `/api/admin/scraping/schedule/next-run` | PUT | Admin |
| | `/api/admin/scraping/schedule/enable` | POST | Admin |
| | `/api/admin/scraping/schedule/disable` | POST | Admin |
| **用户管理** | `/api/admin/users` | POST, GET | Admin |
| | `/api/admin/users/{id}/reset-password` | POST | Admin |
| **用户自助** | `/api/users/me` | GET | User |
| | `/api/users/me/api-keys` | POST, GET | User |
| | `/api/users/me/api-keys/{id}` | DELETE | User |
| | `/api/users/me/password` | PUT | User |
| **认证** | `/api/auth/login` | POST | 无 |
| **摘要** | `/api/summaries/batch` | POST | 无 |
| | `/api/summaries/stats` | GET | 无 |
| | `/api/summaries/tweets/{id}/regenerate` | POST | 无 |
| | `/api/summaries/tasks/{id}` | GET, DELETE | 无 |
| **去重** | `/api/deduplicate/batch` | POST | 无 |
| | `/api/deduplicate/tasks/{id}` | GET | 无 |
| **健康检查** | `/health` | GET | 无 |

---

## 2. 需求可行性分析

### 需求-资产映射表

| 需求 | 现有资产 | 缺失 | 复杂度 |
|------|----------|------|--------|
| **Req 1: 侧边栏布局** | App.vue（需重构） | AdminLayout.vue 组件 | 中 — 需重构 App.vue，创建新布局组件 |
| **Req 2: 样式修复** | style.css（需替换） | 无 | 低 — 直接替换文件内容 |
| **Req 3: Pinia 初始化** | package.json 已有 pinia 依赖 | main.ts 未注册；stores/ 目录和 auth.ts 不存在 | 低 — 标准初始化 |
| **Req 4: 工具函数** | 各组件内重复定义 | utils/format.ts 统一模块 | 低 — 提取并替换引用 |
| **Req 5: 仪表盘** | tweets/tasks/follows API 可复用 | DashboardView.vue, api/health.ts, api/summaries.ts | 中 — 新页面 + 2个新 API 模块 |
| **Req 6: 调度管理** | 无 | SchedulerView.vue, api/scheduler.ts, types/scheduler.ts | 中 — 新页面 + 新 API 模块 |
| **Req 7: 用户管理** | 无 | UsersView.vue, api/users.ts, types/user.ts | 中 — 新页面 + 新 API 模块 |
| **Req 8: 摘要再生成** | TweetDetailView.vue（需扩展） | api/summaries.ts（regenerate 端点） | 低 — 增加按钮 + 1 个 API 调用 |
| **Req 9: 批量操作** | TweetsView.vue（需扩展） | 复选框逻辑 + api/summaries.ts + api/dedup.ts（batch 端点） | 中 — 需修改列表 UI + 多选状态管理 |
| **Req 10: 任务增强** | TasksView.vue（需扩展）, tasksApi.deleteTask() 已存在 | 修复空 usernames bug | 低 — 小幅修改 |
| **Req 11: 路由更新** | router/index.ts（需扩展） | 3 条新路由 + 默认重定向变更 | 低 — 标准路由添加 |
| **Req 12: API 集成** | 现有 API 模式可复用 | 5 个新 API 模块 | 中 — 量大但模式成熟 |

### 技术需求清单

| 类别 | 需求 | 说明 |
|------|------|------|
| **数据模型/类型** | ScheduleConfig, HealthResponse, CostStats, UserInfo, CreateUserResponse | 后端 Pydantic schema 已完整定义 |
| **API 客户端** | scheduler, users, health, summaries, dedup | 完全遵循现有 tweetsApi/tasksApi 模式 |
| **UI 组件** | AdminLayout, DashboardView, SchedulerView, UsersView | Element Plus 组件库完全覆盖所需 UI 元素 |
| **状态管理** | Auth Store (Pinia) | 将 App.vue 中 localStorage 逻辑迁移到 store |
| **业务规则** | 间隔范围 300-604800s, 下次运行时间必须未来, 邮箱唯一性 | 后端已有验证，前端做基本校验 |
| **安全** | Admin API Key 注入 | 现有拦截器机制完全适用 |

### 约束与已知问题

1. **Bug**: TasksView.vue L189 `usernames: ""` 导致后端 400 错误（admin.py L62-63 ScrapeRequest 验证空字符串）
2. **冲突**: style.css 暗色主题与 Element Plus 组件冲突
3. **遗漏**: Pinia 已安装未注册，无法使用 store
4. **重复**: `formatTime` 在 3 个视图组件中重复定义

### 无需额外研究的项

所有后端 API 的请求/响应 schema 已通过代码阅读完整确认。Element Plus 组件库覆盖所有 UI 需求（el-container/el-aside/el-menu 用于布局，el-switch 用于调度开关，el-date-picker 用于时间选择，el-statistic 用于统计卡片）。无需外部依赖研究。

---

## 3. 实施方案选项

### Option A: 扩展现有组件（不推荐）

将所有新功能直接塞入现有文件：在 App.vue 中直接写侧边栏、在 TasksView 中加仪表盘统计等。

**Trade-offs:**
- ✅ 文件数量不增加
- ❌ App.vue 会膨胀到 300+ 行
- ❌ 违反单一职责原则
- ❌ 仪表盘/调度/用户逻辑无处安放

### Option B: 创建新组件（推荐）

为每个需求创建独立的新文件，完全遵循现有模式。

**具体方案：**
- 新建 `layouts/AdminLayout.vue` 独立布局组件
- 新建 3 个 View 组件：Dashboard, Scheduler, Users
- 新建 5 个 API 模块：scheduler, users, health, summaries, dedup
- 新建对应 TypeScript 类型文件
- 新建 `stores/auth.ts` Pinia store
- 新建 `utils/format.ts` 工具模块
- 修改 App.vue 为精简的布局切换器
- 修改现有 View 使用 format utils + 新 API

**Trade-offs:**
- ✅ 清晰的职责分离，每个文件职责明确
- ✅ 完全复用现有 API/类型模式，无学习成本
- ✅ 各模块独立可测试
- ✅ 增量可交付（Phase 0→1→2→3 逐步完成）
- ❌ 新增约 15 个文件
- ❌ 需要修改约 9 个现有文件

### Option C: 混合方案（不需要）

本场景不适用。所有新增功能都是独立的新页面或清晰的基础设施改进，Option B 已是最自然的方案。

### 推荐方案：Option B

理由：
1. 所有新增功能（仪表盘、调度管理、用户管理）都是独立页面，天然需要独立 View 组件
2. 后端 API 已按模块组织（scheduler、users、summaries、dedup），前端 API 模块一一对应最清晰
3. 布局升级是架构级变更，需要独立的 AdminLayout 组件，不应塞入 App.vue
4. 现有代码模式成熟且一致，新文件只需照搬模式

---

## 4. 复杂度与风险评估

### 总体评估

| 维度 | 评级 | 理由 |
|------|------|------|
| **工作量** | **M (3-7 天)** | 15 个新文件 + 9 个修改文件，但全部遵循已有模式，无新技术引入 |
| **风险** | **低** | 纯前端变更，扩展已有模式，后端 API 全部已就绪，无未知技术 |

### 分需求评估

| 需求 | 工作量 | 风险 | 说明 |
|------|--------|------|------|
| Req 1: 侧边栏布局 | M | 低 | Element Plus el-aside/el-menu 标准用法，但涉及 App.vue 重构 |
| Req 2: 样式修复 | S | 低 | 直接替换 style.css |
| Req 3: Pinia 初始化 | S | 低 | 标准初始化 + 迁移 localStorage 逻辑 |
| Req 4: 工具函数 | S | 低 | 提取 + 替换引用 |
| Req 5: 仪表盘 | M | 低 | 新页面，但只是多个 API 数据的聚合展示 |
| Req 6: 调度管理 | M | 低 | 新页面 + 新 API，后端 schema 已确认 |
| Req 7: 用户管理 | M | 低 | 新页面 + 新 API，后端 schema 已确认 |
| Req 8: 摘要再生成 | S | 低 | 在现有页面增加 1 个按钮 + 1 个 API 调用 |
| Req 9: 批量操作 | M | 中 | 需要在卡片列表中添加复选框 + 多选状态管理，UI 改动较大 |
| Req 10: 任务增强 | S | 低 | 小幅修改 + bug 修复 |
| Req 11: 路由更新 | S | 低 | 添加路由条目 |
| Req 12: API 集成 | M | 低 | 5 个新模块，但模式完全一致 |

---

## 5. 设计阶段建议

### 关键设计决策

1. **AdminLayout 组件结构**：el-container 嵌套方式、折叠状态管理（ref vs store）、API Key 对话框放置位置
2. **仪表盘数据加载策略**：并行加载多个 API（Promise.allSettled）vs 按需加载 vs 统一 store
3. **批量操作 UI**：推文卡片中嵌入 checkbox vs 改为列表模式支持批量选择
4. **Auth Store 与 client.ts 的集成**：store 直接操作 localStorage + 拦截器从 store 读取，还是保持现有 localStorage 方式不变

### 需要在设计文档中明确的

- AdminLayout 的具体 HTML 结构和 CSS 布局
- 仪表盘各统计卡片的数据来源 API 映射
- 调度管理页面的表单交互流程
- 用户管理的创建成功弹窗流程（临时密码一次性展示）
- 批量操作与 TaskPollingService 的集成方式
