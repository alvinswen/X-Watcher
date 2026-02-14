# 实施任务

## Phase 0: 基础修复与基础设施

- [x] 1. 全局样式修复与基础工具
- [x] 1.1 (P) 替换全局样式文件，移除 Vite 脚手架默认暗色主题，仅保留最小化浏览器重置样式（body margin、font-family、background-color），移除 `#app` 的 max-width 和 text-align 约束，不覆盖 Element Plus 默认样式
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
- [x] 1.2 (P) 在应用入口注册 Pinia 状态管理插件
  - _Requirements: 3.1_
- [x] 1.3 (P) 创建通用时间格式化工具模块，提供相对时间（如"3分钟前"）、完整日期时间、本地化日期时间（zh-CN）、秒数可读描述（如"2 小时 30 分钟"）四个函数
  - _Requirements: 4.1, 4.2, 4.3, 4.4_
- [x] 1.4 将 TweetsView、FollowsView、TasksView、TweetDetailView 中重复的格式化函数替换为统一工具模块调用，删除组件内重复定义
  - _Requirements: 4.5_
- [x] 1.5 (P) 删除 Vite 脚手架残留的 HelloWorld 组件
  - _Requirements: 2.1_

- [x] 2. Auth Store 与 API 客户端适配
- [x] 2.1 创建 Auth Store（Pinia），管理 apiKey 状态和 isAuthenticated 计算属性，实现 setApiKey/clearApiKey/loadFromStorage 操作，loadFromStorage 在 store 初始化时自动从 localStorage 恢复状态
  - _Requirements: 3.2, 3.3, 3.4, 3.5_
- [x] 2.2 修改 API 客户端，导出 setApiKeyProvider 函数用于依赖注入；Auth Store 初始化时调用此函数注册 apiKey getter；请求拦截器通过已注册的 provider 获取 apiKey（IC-2 约束）
  - _Requirements: 3.6_

## Phase 1: 类型定义、API 模块与侧边栏布局

- [x] 3. TypeScript 类型定义
- [x] 3.1 (P) 创建调度类型定义（ScheduleConfig、UpdateIntervalRequest、UpdateNextRunRequest），JSDoc 注释 + snake_case 属性名
  - _Requirements: 12.7_
- [x] 3.2 (P) 创建用户类型定义（UserInfo、CreateUserRequest、CreateUserResponse、ResetPasswordResponse）
  - _Requirements: 12.7_
- [x] 3.3 (P) 创建健康检查类型定义（ComponentHealth、HealthResponse）和摘要成本统计类型定义（CostStats）
  - _Requirements: 12.7_
- [x] 3.4 更新类型统一导出文件，添加新增类型的 barrel export
  - _Requirements: 12.7_

- [x] 4. 新增 API 模块
- [x] 4.1 (P) 创建调度管理 API 模块，封装获取配置、更新间隔、更新下次运行时间、启用、禁用五个端点
  - _Requirements: 12.1, 12.6_
- [x] 4.2 (P) 创建用户管理 API 模块，封装列出用户、创建用户、重置密码三个端点
  - _Requirements: 12.2, 12.6_
- [x] 4.3 (P) 创建健康检查 API 模块，使用独立 axios 调用访问 /health 端点（IC-1 约束：不经过 client 实例）
  - _Requirements: 12.3, 12.6_
- [x] 4.4 (P) 创建摘要 API 模块，封装获取统计信息、批量摘要、重新生成单条摘要、查询任务状态四个端点
  - _Requirements: 12.4, 12.6_
- [x] 4.5 (P) 创建去重 API 模块，封装批量去重和查询任务状态两个端点
  - _Requirements: 12.5, 12.6_
- [x] 4.6 更新 API 统一导出文件，添加新增 API 模块的 barrel export
  - _Requirements: 12.6_

- [x] 5. 侧边栏布局组件
- [x] 5.1 创建 AdminLayout 组件，使用 el-container + el-aside + el-header + el-main 实现左侧固定侧边栏 + 右侧内容区双栏布局（展开 220px，折叠 64px）
  - _Requirements: 1.1, 1.8_
- [x] 5.2 添加六个菜单项（仪表盘、推文管理、关注管理、任务监控、调度管理、用户管理），每项显示对应图标，el-menu router 模式 + default-active 绑定当前路由路径实现自动高亮
  - _Requirements: 1.2, 1.3_
- [x] 5.3 实现折叠/展开切换按钮（Fold/Expand 图标），折叠后菜单项鼠标悬停显示 tooltip 提示
  - _Requirements: 1.4, 1.5_
- [x] 5.4 在侧边栏底部显示 API Key 配置状态指示器和设置入口，包含 API Key 设置对话框（从 App.vue 迁移），使用 Auth Store 读取/设置状态
  - _Requirements: 1.6_
- [x] 5.5 内容区顶部 el-header 显示当前页面名称（读取 route.meta.title）
  - _Requirements: 1.7_
- [x] 5.6 重构 App.vue，移除顶部导航栏和 API Key 相关逻辑，使用 AdminLayout 作为根布局组件包裹 RouterView
  - _Requirements: 1.8_

## Phase 2: 新增页面（6/7/8 可并行）

- [x] 6. 仪表盘页面
- [x] 6.1 (P) 创建仪表盘组件，使用 el-row + el-col 排列四个统计卡片（推文总数、活跃关注数、调度器状态、摘要总成本），使用 el-statistic 展示数值
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
- [x] 6.2 (P) 实现系统健康状态面板，调用 healthApi 获取各组件运行状态，使用 el-tag 区分 healthy/unhealthy
  - _Requirements: 5.6_
- [x] 6.3 (P) 实现最近 5 条任务记录列表，使用 el-table 展示任务状态
  - _Requirements: 5.7_
- [x] 6.4 实现并行数据加载（Promise.allSettled），每个数据源独立 loading/error 状态；加载中显示骨架屏；单源失败时对应卡片显示 el-alert 错误，不阻塞其他卡片
  - _Requirements: 5.8, 5.9, 5.10_

- [x] 7. 调度管理页面
- [x] 7.1 (P) 创建调度管理组件，显示当前配置：启用/禁用状态、抓取间隔（格式化为可读描述）、下次计划执行时间
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
- [x] 7.2 (P) 实现启用/禁用 el-switch 开关，操作成功后刷新配置并提示，失败时显示错误
  - _Requirements: 6.5, 6.10, 6.11_
- [x] 7.3 (P) 实现间隔修改：预设选项（el-radio-group: 30min/1h/2h/4h/8h/24h）+ 自定义输入（el-input-number, 300-604800）
  - _Requirements: 6.6, 6.7, 6.10, 6.11_
- [x] 7.4 (P) 实现下次执行时间设置：el-date-picker type="datetime"，disabled-date 排除过去日期
  - _Requirements: 6.8, 6.9, 6.10, 6.11_
- [x] 7.5 确保禁用状态下间隔和下次执行时间设置仍可编辑
  - _Requirements: 6.12_

- [x] 8. 用户管理页面
- [x] 8.1 (P) 创建用户管理组件，el-table 显示用户 ID、名称、邮箱、管理员标识（el-tag）、创建时间，加载中显示骨架屏
  - _Requirements: 7.1, 7.2, 7.11_
- [x] 8.2 (P) 实现创建用户功能："创建用户"按钮 → el-dialog 内 el-form（名称 required + 邮箱 required + email 校验）→ 调用后端 API
  - _Requirements: 7.3, 7.4, 7.5_
- [x] 8.3 实现创建成功后展示临时密码和 API Key（el-input readonly + 复制按钮），显示"此信息仅显示一次"警告，点击"确定"关闭并刷新列表
  - _Requirements: 7.6, 7.7_
- [x] 8.4 (P) 实现重置密码：ElMessageBox.confirm 确认 → 调用 API → ElMessageBox.alert 显示新临时密码
  - _Requirements: 7.8, 7.9_
- [x] 8.5 实现操作错误处理，显示后端返回的错误信息（含 409 邮箱重复）
  - _Requirements: 7.10_

## Phase 3: 现有页面增强与路由整合

- [x] 9. 摘要再生成功能
- [x] 9.1 在推文详情摘要卡片头部增加"重新生成"按钮，无摘要时在 el-empty 区域增加"生成摘要"按钮
  - _Requirements: 8.1, 8.2_
- [x] 9.2 点击后调用 summariesApi.regenerate，生成期间按钮加载状态且不可重复点击，成功后刷新详情并提示，失败时显示错误
  - _Requirements: 8.3, 8.4, 8.5, 8.6_

- [x] 10. 批量操作功能
- [x] 10.1 推文列表每条卡片添加 el-checkbox，管理 selectedTweetIds 选中状态集合
  - _Requirements: 9.1_
- [x] 10.2 筛选区域增加操作栏：显示"已选 N 条"+ "批量摘要"/"批量去重"按钮，未选中时禁用并提示
  - _Requirements: 9.2, 9.6_
- [x] 10.3 批量摘要调用 summariesApi.batchSummarize，批量去重调用 dedupApi.batchDeduplicate，返回 task_id 后显示进度提示，操作期间按钮加载状态
  - _Requirements: 9.3, 9.4, 9.5, 9.7_
- [x] 10.4 复用 TaskPollingService 轮询批量操作进度，完成后显示成功提示、清空选择、刷新列表
  - _Requirements: 9.5, 9.7_

- [x] 11. 任务监控增强
- [x] 11.1 (P) 任务历史表格增加"删除"按钮（仅非 running 状态），ElMessageBox.confirm 确认后调用 tasksApi.deleteTask 并刷新
  - _Requirements: 10.1, 10.2, 10.3_
- [x] 11.2 (P) 修复"立即抓取"：先调用 followsApi.list() 获取活跃账号拼接 usernames；无活跃账号则提示，不再发送空字符串
  - _Requirements: 10.4, 10.5, 10.6_

- [x] 12. 路由更新与整合
- [x] 12.1 新增 /dashboard、/scheduler、/users 三条路由，每条配置 meta.title，根路径重定向改为 /dashboard
  - _Requirements: 11.1, 11.2, 11.3_
- [x] 12.2 验证侧边栏菜单根据当前路由自动高亮
  - _Requirements: 11.4_

## Phase 4: 验证（可选）

- [x] 13. 测试与验收
- [x] 13.1 (P) Auth Store 单元测试：setApiKey/clearApiKey/loadFromStorage 状态变更和 localStorage 同步
- [x] 13.2 (P) format.ts 工具函数单元测试：正常输入、null 输入、边界值
- [x] 13.3 (P) 各新增 API 模块集成测试：mock Axios 验证请求路径、参数、响应解包
- [x] 13.4 全页面手动验收：所有路由、侧边栏折叠/高亮、仪表盘数据、调度管理操作、用户创建/密码重置、摘要再生成、批量操作、任务删除/立即抓取

---

## 实施约束

- **IC-1**: healthApi 使用独立 `axios.get('/health')` 调用，不经过 client.ts（/health 不在 /api 前缀下）
- **IC-2**: Auth Store 通过 `setApiKeyProvider()` 依赖注入与 client.ts 集成，避免循环依赖
