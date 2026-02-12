# Research Log

## Summary

对 Web 管理界面功能进行了轻量级发现（Light Discovery），因为这是对现有系统的扩展。分析了现有 API 模式、数据库模型和集成点。发现现有系统已有完整的抓取任务 API (`/api/admin/scrape`)，可以直接复用。

## Discovery Scope

**类型**: 扩展功能（Extension） - 为现有系统添加 Web 前端
**发现级别**: 轻量级（Light Discovery） - 专注于集成点和现有模式

## Research Log

### Existing API Patterns (已完成)

**来源**: 代码库分析
**关键发现**:
- 现有 `src/api/routes/admin.py` 已实现抓取任务管理 API
- API 端点模式: `/api/admin/scrape` (POST), `/api/admin/scrape/{task_id}` (GET), `/api/admin/scrape` (GET list)
- 使用 BackgroundTasks 执行异步任务
- TaskRegistry 管理任务状态（pending/running/completed/failed）
- 响应模型: ScrapeResponse, TaskStatusResponse
- 认证方式: API Key (X-API-Key header) 用于管理端点

**集成点**:
1. **抓取任务 API** - 复用现有端点，无需新增后端逻辑
2. **抓取账号管理 API** - 复用 `/api/admin/scraping/follows` 端点
3. **去重 API** - 复用 `/api/deduplication/*` 端点
4. **摘要 API** - 复用 `/api/summaries/*` 端点

### Frontend Technology Stack (已确认)

**来源**: 项目 steering 文档 + 用户需求
**技术选型**:
- **前端框架**: Vue 3 (Composition API)
- **语言**: TypeScript (严格类型安全)
- **构建工具**: Vite
- **UI 组件库**: Element Plus
- **路由**: Vue Router 4
- **状态管理**: Pinia
- **HTTP 客户端**: Axios

**理由**: 与项目技术栈一致，Element Plus 提供完整的企业级 UI 组件

### Static File Serving Strategy (已确定)

**来源**: FastAPI 文档 + 最佳实践
**决策**:
- **开发环境**: Vite dev server 代理 `/api` 到后端
- **生产环境**: FastAPI StaticFiles 挂载 `src/web/dist/` 到根路径
- **SPA 路由**: StaticFiles 配置 `html=True` 支持前端路由

**关键代码** (参考):
```python
from fastapi.staticfiles import StaticFiles
web_dir = os.path.join(os.path.dirname(__file__), "web", "dist")
if os.path.exists(web_dir):
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
```

### Task Polling Strategy (已确定)

**来源**: Requirement 7.5 - 定期轮询任务状态
**决策**:
- **轮询间隔**: 2-3 秒（平衡实时性和服务器负载）
- **轮询停止条件**: 任务状态为 completed 或 failed
- **实现方式**: 前端 `setInterval` + Axios 轮询 `/api/admin/scrape/{task_id}`

### Component Architecture (已规划)

**来源**: Vue 3 最佳实践 + Element Plus 模式
**组件结构**:
- **布局**: App.vue (导航栏 + 路由视图)
- **页面**: Tweets.vue, TweetDetail.vue, Follows.vue, Tasks.vue
- **可复用组件**: TweetCard, SummaryCard, TaskStatus, Pagination
- **状态管理**: Pinia stores (tweets, tasks, auth)
- **API 客户端**: 集中式 axios 拦截器处理认证和错误

## Architecture Pattern Evaluation

### Chosen Pattern: Client-Side SPA with REST API Integration

**理由**:
1. **简单直接**: 前后端分离，API 作为集成边界
2. **易于部署**: 单一 FastAPI 服务同时提供 API 和静态文件
3. **渐进增强**: 可后续添加 WebSocket 或 Server-Sent Events 实现实时推送
4. **符合现有架构**: 不改变后端服务结构，仅新增前端层

### Alternative Considered: Server-Side Rendering (SSR)

**未选择原因**:
- 增加部署复杂度（需要 Node.js 运行时）
- 对于管理后台，SEO 不是关键需求
- 开发成本更高（需要 Next.js/Nuxt.js 等框架）

## Design Decisions

### Decision 1: API Authentication

**选择**: localStorage 存储 API Key，请求头携带
**理由**:
- 简单易实现，适合单用户管理后台
- Element Plus 不会自动处理认证，需手动注入
- 后续可升级为 JWT + Refresh Token

### Decision 2: Task Status Polling

**选择**: 前端定时轮询
**理由**:
- 实现简单，不依赖 WebSocket
- 适合低频操作（手动触发抓取任务）
- 后续可升级为 WebSocket 或 SSE

### Decision 3: Type Safety Strategy

**选择**:
- 后端: Pydantic 模型定义所有 API 请求/响应
- 前端: TypeScript 接口同步 Pydantic 模型
- 工具: 可考虑使用 openapi-ts 从 OpenAPI 规范生成前端类型

### Decision 4: Error Handling

**选择**:
- Axios 拦截器统一处理 HTTP 错误
- Element Plus Message 组件显示用户友好提示
- 控制台记录详细错误日志（开发调试）

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| API 兼容性变更 | 高 | 后端使用 Pydantic 验证，前端类型检查 |
| 任务轮询性能 | 中 | 合理设置轮询间隔，任务完成后停止轮询 |
| API Key 泄露 | 中 | 生产环境使用环境变量，不在代码中硬编码 |
| 大数据量渲染 | 中 | 分页加载推文，虚拟滚动（可选） |

## Open Questions

### Resolved

**Q1: 是否需要实时推送任务状态？**
- **A**: 否，使用轮询方案（简单优先，后续可升级）

**Q2: 前端路由如何处理？**
- **A**: Vue Router hash 模式或 history 模式均可，推荐 history 模式 + FastAPI SPA 支持

**Q3: 如何处理 API 认证？**
- **A**: localStorage 存储 API Key，axios 拦截器注入请求头

## Supporting Decisions

### Frontend Testing Strategy

**单元测试**:
- Vue 组件: Vitest + Vue Test Utils
- API 客户端: Vitest + vi.mock() axios

**集成测试**:
- API 端点: Playwright 或 Cypress（可选）

**E2E 测试**:
- 关键用户路径: 手动测试（优先级较低）

### Deployment Strategy

**开发环境**:
- 前端: `npm run dev` (Vite dev server @ localhost:5173)
- 后端: `python -m src.main` (FastAPI @ localhost:8000)
- 代理: Vite proxy 配置转发 `/api` 到后端

**生产环境**:
- 前端: `npm run build` 生成静态文件到 `src/web/dist/`
- 后端: FastAPI 挂载静态文件服务
- 单一进程: `python -m src.main` 同时服务 API 和前端
