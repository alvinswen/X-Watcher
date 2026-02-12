# Requirements Document

## Introduction

Web管理界面是 X-watcher 项目的管理后台，为管理员提供可视化的推文浏览、摘要查看和抓取账号管理功能。该界面通过 FastAPI 静态文件服务部署，使用 Vue 3 + TypeScript 构建，与现有 RESTful API 集成。

## Requirements

### Requirement 1: 推文列表浏览

**Objective:** 作为管理员，我希望能够分页浏览所有已抓取的推文，以便快速了解系统中的内容概况。

#### Acceptance Criteria

1. When 用户访问推文列表页面，the Web管理界面 shall 显示推文列表，每页默认显示 20 条
2. When 用户点击"刷新"按钮，the Web管理界面 shall 重新加载最新的推文数据
3. When 用户选择特定作者进行筛选，the Web管理界面 shall 仅显示该作者的推文
4. While 推文数据正在加载，the Web管理界面 shall 显示加载动画或骨架屏
5. If 推文列表为空，the Web管理界面 shall 显示"暂无推文数据"提示
6. The 推文列表项 shall 显示作者名称、用户名、发布时间、推文内容预览
7. The 推文列表项 shall 使用标签显示摘要状态（已摘要/未摘要）
8. The 推文列表项 shall 使用标签显示去重状态（已去重/未去重）
9. When 用户点击推文列表项，the Web管理界面 shall 导航到推文详情页面

### Requirement 2: 推文详情查看

**Objective:** 作为管理员，我希望能够查看单条推文的完整信息，包括 AI 摘要和去重信息，以便深入了解推文内容。

#### Acceptance Criteria

1. When 用户访问推文详情页面，the Web管理界面 shall 显示推文的完整内容
2. When 推文存在 AI 摘要，the Web管理界面 shall 在"AI 摘要"卡片中显示摘要文本
3. When 摘要包含翻译内容，the Web管理界面 shall 显示中文翻译
4. The AI 摘要卡片 shall 显示模型信息（提供商/模型名称）
5. The AI 摘要卡片 shall 显示生成成本（美元）
6. When 摘要来自缓存，the Web管理界面 shall 显示"缓存"标签
7. When 推文存在去重信息，the Web管理界面 shall 在"去重信息"卡片中显示详情
8. The 去重信息卡片 shall 显示去重组 ID、去重类型、代表推文 ID
9. Where 去重类型为相似内容，the Web管理界面 shall 显示相似度百分比
10. The 去重信息卡片 shall 显示去重组包含的推文数量
11. When 推文不存在摘要，the Web管理界面 shall 显示"此推文暂无摘要"提示
12. When 用户点击"返回"按钮，the Web管理界面 shall 返回上一页

### Requirement 3: 抓取账号管理

**Objective:** 作为管理员，我希望能够管理平台抓取账号列表（添加、编辑、启用/禁用），以便控制数据抓取源。

#### Acceptance Criteria

1. When 用户访问抓取账号管理页面，the Web管理界面 shall 显示所有抓取账号列表
2. The 抓取账号列表 shall 显示用户名、添加理由、添加人、添加时间、状态
3. When 用户点击"添加账号"按钮，the Web管理界面 shall 打开添加账号对话框
4. When 用户提交添加账号表单，the Web管理界面 shall 调用后端 API 创建新账号
5. When 用户点击"编辑"按钮，the Web管理界面 shall 打开编辑账号对话框
6. When 用户修改账号信息并提交，the Web管理界面 shall 调用后端 API 更新账号
7. When 用户点击"禁用/启用"按钮，the Web管理界面 shall 切换账号的活跃状态
8. Where 操作成功完成，the Web管理界面 shall 显示成功提示消息
9. If API 返回错误，the Web管理界面 shall 显示错误提示消息
10. While 表单正在提交，the Web管理界面 shall 禁用提交按钮并显示加载状态

### Requirement 4: API 认证集成

**Objective:** 作为管理员，我希望界面能够支持 API Key 认证，以便安全地访问管理端点。

#### Acceptance Criteria

1. Where 后端 API 端点需要认证，the Web管理界面 shall 在请求头中包含 API Key
2. The API Key shall 从浏览器 localStorage 中读取（键名: `admin_api_key`）
3. If API 认证失败（403），the Web管理界面 shall 显示认证失败提示
4. The API 认证 shall 适用于抓取账号管理相关的所有 API 请求

### Requirement 5: 静态文件服务部署

**Objective:** 作为开发者，我希望前端构建产物能够由 FastAPI 直接提供，以便简化部署流程。

#### Acceptance Criteria

1. When 前端执行 `npm run build` 构建完成，the 构建产物 shall 输出到 `src/web/dist/` 目录
2. When FastAPI 应用启动，the 后端 shall 检测 `src/web/dist/` 目录是否存在
3. Where 静态文件目录存在，the FastAPI 应用 shall 挂载静态文件服务到根路径
4. The 静态文件服务 shall 支持 SPA 路由（所有路由返回 index.html）
5. When 开发环境运行 `npm run dev`，the 前端开发服务器 shall 代理 `/api` 请求到后端

### Requirement 6: 响应式布局与导航

**Objective:** 作为用户，我希望界面具有良好的导航结构和响应式布局，以便在不同设备上使用。

#### Acceptance Criteria

1. The Web管理界面 shall 在顶部显示全局导航栏
2. The 导航栏 shall 包含"推文"和"抓取账号"导航链接
3. When 用户点击导航链接，the Web管理界面 shall 使用 Vue Router 进行页面导航
4. The 页面标题 shall 动态更新为当前页面名称
5. The 界面 shall 使用居中布局，最大宽度 1200px
6. The 界面 shall 使用一致的配色方案和间距

### Requirement 7: 手动触发抓取工作流

**Objective:** 作为管理员，我希望能够手动触发完整的抓取工作流，以便按需获取最新数据。

#### Acceptance Criteria

1. When 用户点击"立即抓取"按钮，the Web管理界面 shall 调用后端 API 触发抓取工作流
2. The 抓取工作流 shall 包含以下步骤：抓取、去重、入库、自动摘要
3. The 抓取工作流 shall 不包括向用户推送通知
4. When 抓取任务被触发，the Web管理界面 shall 显示任务 ID 和初始状态
5. While 抓取任务正在执行，the Web管理界面 shall 定期轮询任务状态
6. The 任务状态 shall 显示当前执行阶段（抓取/去重/摘要）
7. Where 任务执行成功，the Web管理界面 shall 显示成功提示和统计信息（抓取推文数、去重组数、摘要数）
8. If 任务执行失败，the Web管理界面 shall 显示错误详情和失败阶段
9. The 任务状态轮询 shall 在任务完成后自动停止
10. The 用户 shall 能够查看历史抓取任务列表及其状态

### Requirement 8: 任务历史与监控

**Objective:** 作为管理员，我希望能够查看历史抓取任务的执行状态和结果，以便监控系统运行状况。

#### Acceptance Criteria

1. When 用户访问任务监控页面，the Web管理界面 shall 显示抓取任务历史列表
2. The 任务列表 shall 按创建时间倒序排列
3. The 任务列表项 shall 显示任务 ID、创建时间、当前状态、执行进度
4. The 任务状态 shall 包含：pending（待执行）、running（执行中）、completed（已完成）、failed（失败）
5. When 任务状态为 completed，the 任务列表项 shall 显示执行结果摘要
6. When 任务状态为 failed，the 任务列表项 shall 显示错误信息
7. When 用户点击任务列表项，the Web管理界面 shall 显示任务详情
8. The 任务详情 shall 显示各阶段的执行时间、处理数据量、错误日志

### Requirement 9: 错误处理与用户反馈

**Objective:** 作为用户，我希望在操作失败时能够获得清晰的错误提示，以便了解问题所在。

#### Acceptance Criteria

1. If API 请求失败，the Web管理界面 shall 在控制台记录错误详情
2. If API 请求失败，the Web管理界面 shall 显示用户友好的错误提示
3. When 网络超时发生，the Web管理界面 shall 显示"请求超时"提示
4. The 错误提示 shall 使用 Element Plus 的 Message 组件显示
5. While 数据加载中，the Web管理界面 shall 禁用相关操作按钮
6. While 抓取任务正在执行，the Web管理界面 shall 显示任务进度指示器
