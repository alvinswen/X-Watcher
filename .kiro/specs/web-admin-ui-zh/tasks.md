# Implementation Tasks

## 1. Frontend Project Setup

- [x] 1.1 (P) 初始化 Vue 3 + TypeScript + Vite 前端项目
  - 在 `src/web/` 目录创建前端项目结构
  - 安装核心依赖：Vue 3.5+、TypeScript 5.7+、Vite 6.0+、Element Plus 2.9+、Vue Router 4.5+、Pinia 2.2+、Axios 1.7+
  - 配置 TypeScript 严格模式（禁用 `any`）
  - 设置构建输出目录为 `src/web/dist/`
  - 配置开发服务器代理 `/api` 请求到后端（开发环境）
  - _Requirements: 5.1, 5.5_

- [x] 1.2 (P) 创建前端项目基础结构和类型定义
  - 创建目录结构：`src/`、`views/`、`components/`、`services/`、`types/`
  - 创建 TypeScript 类型定义文件，定义 API 响应数据结构（TweetListItem、TweetDetailResponse、Summary、DeduplicationInfo、TaskStatusResponse）
  - 配置 Element Plus 按需导入或全量导入
  - 设置全局样式和 CSS 变量（配色方案、间距）
  - _Requirements: 1.6, 2.2, 2.3, 6.5, 6.6_

## 2. Backend API Implementation

- [x] 2.1 创建推文列表查询 API 端点
  - 在 `src/api/routes/` 中创建推文相关路由模块
  - 实现 `GET /api/tweets` 端点，支持分页参数（page、page_size）和作者筛选（author）
  - 联合查询 `tweets` 和 `summaries` 表，设置 `has_summary` 标志
  - 实现 Pydantic 响应模型（TweetListResponse、TweetListItem）
  - 按创建时间倒序排列推文，计算总页数
  - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7_

- [x] 2.2 创建推文详情查询 API 端点
  - 实现 `GET /api/tweets/{tweet_id}` 端点
  - 根据推文 ID 查询完整推文内容
  - 联合查询摘要信息（使用 SummarizationRepository）
  - 联合查询去重信息（使用 DeduplicationRepository.find_by_tweet）
  - 实现 Pydantic 响应模型（TweetDetailResponse），包含摘要和去重详情
  - 处理 404 错误（推文不存在）
  - _Requirements: 2.1, 2.2, 2.6, 2.7, 2.8, 2.11_

- [x] 2.3 添加数据库索引优化查询性能
  - 创建 Alembic 迁移脚本，为 `tweets.author_username` 添加索引
  - 定义升级操作（创建索引）和降级操作（删除索引）
  - 在开发环境执行迁移并验证索引创建成功
  - _Requirements: 1.3_

- [x] 2.4 (P) 配置 FastAPI 静态文件服务
  - 在 FastAPI 应用中检测 `src/web/dist/` 目录是否存在
  - 挂载 StaticFiles 到根路径，提供 SPA 路由支持（所有路由返回 index.html）
  - 确保静态文件服务仅在构建产物存在时启用
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

## 3. Frontend Core Services

- [x] 3.1 (P) 实现 API Client（Axios 封装）
  - 创建 Axios 实例，配置基础 URL 和 30 秒超时
  - 实现请求拦截器，从 localStorage 读取 `admin_api_key` 并注入 `X-API-Key` 请求头
  - 实现响应拦截器，统一处理错误（403、404、500、超时）
  - 显示用户友好的错误提示（使用 Element Plus Message 组件）
  - 在控制台记录详细错误信息
  - 提供类型安全的请求方法（get、post、put、delete）
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 9.1, 9.2, 9.3, 9.4_

- [x] 3.2 (P) 实现任务状态轮询服务
  - 创建 TaskPollingService，封装轮询逻辑
  - 实现启动轮询方法，返回可取消的轮询句柄
  - 实现停止轮询方法，清理定时器和 pending Promise
  - 设置 2 秒轮询间隔
  - 实现停止条件：任务状态为 `completed` 或 `failed` 时自动停止
  - 处理任务不存在（404）场景，显示"服务可能已重启"提示
  - _Requirements: 7.5, 7.6, 7.9_

## 4. Frontend UI Components - Layout & Navigation

- [x] 4.1 (P) 创建根组件和路由配置
  - 创建 App.vue，包含全局导航栏和内容区域
  - 导航栏包含"推文"和"抓取账号"链接，支持 Vue Router 导航
  - 配置 Vue Router，设置路由模式为 history
  - 定义路由：`/tweets`（推文列表）、`/tweets/:id`（推文详情）、`/follows`（抓取账号）、`/tasks`（任务监控）
  - 实现路由导航守卫，动态更新页面标题
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 4.2 (P) 实现响应式布局和全局样式
  - 创建居中布局，最大宽度 1200px
  - 实现一致的配色方案和间距（使用 CSS 变量）
  - 确保布局在不同屏幕尺寸下正常显示
  - _Requirements: 6.5, 6.6_

## 5. Frontend UI Components - Tweet Management

- [x] 5.1 (P) 实现推文列表页面（Tweets.vue）
  - 创建 Tweets.vue 组件，使用 Composition API 和 `<script setup lang="ts">`
  - 实现推文列表加载逻辑，调用推文列表 API
  - 实现分页控件（ElPagination），支持页码切换和每页条数调整
  - 实现作者筛选功能（输入框或下拉选择）
  - 显示加载动画（ElSkeleton）和空状态提示（ElEmpty）
  - 实现刷新按钮，重新加载推文数据
  - 推文列表项显示：作者名称、用户名、发布时间、推文内容预览
  - 使用标签显示摘要状态（已摘要/未摘要）和去重状态（已去重/未去重）
  - 点击推文项跳转到详情页（router.push）
  - 禁用加载中的操作按钮
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 9.5_

- [x] 5.2 (P) 实现推文详情页面（TweetDetail.vue）
  - 创建 TweetDetail.vue 组件
  - 从路由参数获取推文 ID，调用推文详情 API 加载数据
  - 显示推文完整内容（作者、时间、文本、媒体）
  - 创建"AI 摘要"卡片组件（SummaryCard），条件渲染（v-if）
  - AI 摘要卡片显示：摘要文本、中文翻译、模型信息、生成成本、缓存标签
  - 创建"去重信息"卡片组件，条件渲染
  - 去重信息卡片显示：去重组 ID、去重类型、代表推文 ID、相似度百分比、包含推文数量
  - 摘要不存在时显示"此推文暂无摘要"提示
  - 实现返回按钮（router.back() 或导航到列表页）
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12_

## 6. Frontend UI Components - Scraping Account Management

- [x] 6.1 (P) 实现抓取账号管理页面（Follows.vue）
  - 创建 Follows.vue 组件，显示抓取账号列表
  - 账号列表显示：用户名、添加理由、添加人、添加时间、状态（活跃/禁用）
  - 实现"添加账号"按钮，打开添加对话框
  - 创建 FollowForm 对话框组件，支持添加和编辑模式
  - 实现表单验证和提交逻辑，调用后端 `/api/admin/scraping/follows` API
  - 实现"编辑"按钮，打开编辑对话框并预填数据
  - 实现"禁用/启用"按钮，切换账号活跃状态
  - 表单提交时禁用按钮并显示加载状态
  - 显示操作成功/失败提示（Element Plus Message）
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 4.1, 4.4_

## 7. Frontend UI Components - Task Monitoring

- [x] 7.1 (P) 实现任务监控页面（Tasks.vue）
  - 创建 Tasks.vue 组件，显示抓取任务历史列表
  - 任务列表按创建时间倒序排列
  - 任务列表项显示：任务 ID、创建时间、当前状态、执行进度
  - 状态映射：pending → 等待中、running → 执行中、completed → 已完成、failed → 失败
  - completed 任务显示执行结果摘要
  - failed 任务显示错误信息
  - 实现任务详情对话框，点击任务项显示详情
  - 任务详情显示：各阶段执行时间、处理数据量、错误日志
  - _Requirements: 7.10, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

- [x] 7.2 实现手动触发抓取工作流功能
  - 在 Tasks.vue 中添加"立即抓取"按钮
  - 点击按钮调用 `POST /api/admin/scrape` API 创建抓取任务
  - 显示返回的任务 ID 和初始状态
  - 使用 TaskPollingService 启动状态轮询
  - 显示任务进度指示器，当前执行阶段（抓取/去重/摘要）
  - 任务完成时停止轮询，显示成功提示和统计信息（抓取推文数、去重组数、摘要数）
  - 任务失败时显示错误详情和失败阶段
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 9.6_

## 8. Testing

- [x] 8.1 (P) 编写后端 API 单元测试
  - 创建 `test_tweets_routes.py`，测试推文列表 API（分页、筛选、空结果）
  - 测试推文详情 API（存在/不存在、包含摘要、包含去重信息）
  - 创建 Pydantic 模型验证测试（`test_schemas.py`）
  - _Requirements: 1.1-1.9, 2.1-2.12_

- [x] 8.2 (P) 编写前端服务单元测试
  - 创建 `test_api_client.ts`，测试 Axios 拦截器、认证注入、错误处理
  - 创建 `test_task_polling.ts`，测试轮询服务启动/停止逻辑、错误处理
  - _Requirements: 4.1-4.4, 7.5-7.9, 9.1-9.6_

- [x] 8.3 编写后端 API 集成测试
  - 创建 `test_api_integration.py`，测试 API 端到端集成
  - 验证推文列表查询与数据库交互
  - 验证推文详情查询与摘要/去重信息关联
  - _Requirements: 1.1-1.9, 2.1-2.12_

- [x] 8.4 编写前端组件测试
  - 创建 `test_Tweets.vue.test.ts`，测试组件挂载、数据加载、分页交互
  - 测试加载状态和空状态渲染
  - _Requirements: 1.1-1.9_

- [x] 8.5 编写抓取工作流端到端测试
  - 创建 `test_workflow_e2e.ts`，测试抓取工作流完整流程（触发→轮询→完成）
  - 模拟任务状态变化，验证轮询停止条件和 UI 更新
  - _Requirements: 7.1-7.10_

- [ ] 8.6* 执行手动 UI 测试
  - 浏览推文列表，验证分页、筛选、加载状态正常工作
  - 点击推文详情，验证摘要和去重信息正确显示
  - 管理抓取账号，测试添加、编辑、禁用功能
  - 触发抓取任务，观察状态轮询和结果显示
  - 查看任务历史和详情对话框
  - _Requirements: 1.1-1.9, 2.1-2.12, 3.1-3.10, 7.1-7.10, 8.1-8.8, 9.1-9.6_

## 9. Integration & Deployment

- [x] 9.1 构建前端生产版本并验证静态文件服务
  - 执行 `npm run build`，验证构建产物输出到 `src/web/dist/`
  - 启动 FastAPI 应用，验证静态文件服务正常工作
  - 访问根路径，确认 SPA 路由正确返回 index.html
  - 测试所有前端路由（/tweets、/follows、/tasks）可正常访问
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 9.2 端到端验证 API 认证和错误处理
  - 配置 localStorage 中的 `admin_api_key`
  - 验证管理端点请求包含正确的认证头
  - 测试认证失败场景（无效 API Key），验证错误提示显示
  - 测试网络超时场景，验证超时提示显示
  - _Requirements: 4.1-4.4, 9.1-9.6_

- [ ] 9.3 完整功能验收测试
  - 执行完整的用户操作流程：浏览推文→查看详情→管理账号→触发抓取→查看任务历史
  - 验证所有验收标准满足
  - 确认响应式布局在不同屏幕尺寸下正常工作
  - _Requirements: 1.1-1.9, 2.1-2.12, 3.1-3.10, 4.1-4.4, 5.1-5.5, 6.1-6.6, 7.1-7.10, 8.1-8.8, 9.1-9.6_
