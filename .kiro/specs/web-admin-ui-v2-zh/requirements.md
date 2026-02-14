# Requirements Document

## Introduction

web-admin-ui-v2 是对 X-watcher 管理后台前端的迭代升级。v1 已实现推文浏览、关注管理、任务监控三个核心页面。本次升级聚焦三大方面：（1）将顶部导航布局升级为侧边栏管理后台布局，提升导航可扩展性；（2）新增仪表盘、调度管理、用户管理三个页面，对接后端已有但前端未使用的 API；（3）增强现有页面功能并修复基础代码问题。技术栈延续 Vue 3 + TypeScript + Element Plus，前端代码位于 `src/web/`。

**与 v1 的关系**：v1（web-admin-ui-zh）的需求（推文列表、推文详情、关注管理、认证、静态部署、手动抓取、任务历史、错误处理）保持不变，本文档仅描述 v2 新增和变更的需求。

## Requirements

### Requirement 1: 侧边栏布局升级

**Objective:** 作为管理员，我希望管理后台使用侧边栏导航布局，以便在页面数量增长时保持清晰的导航结构。

#### Acceptance Criteria

1. The Web管理界面 shall 使用左侧固定侧边栏 + 右侧内容区的双栏布局
2. The 侧边栏 shall 包含以下菜单项并显示对应图标：仪表盘、推文管理、关注管理、任务监控、调度管理、用户管理
3. When 用户点击侧边栏菜单项，the Web管理界面 shall 使用 Vue Router 导航到对应页面，且当前菜单项高亮
4. The 侧边栏 shall 提供折叠/展开切换按钮，折叠后仅显示图标
5. While 侧边栏处于折叠状态，the 菜单项 shall 在鼠标悬停时显示 tooltip 提示文字
6. The 侧边栏底部区域 shall 显示 API Key 配置状态指示器和设置入口
7. The 内容区顶部 shall 显示当前页面名称
8. The 布局 shall 替代当前的顶部导航栏布局

### Requirement 2: 全局样式修复

**Objective:** 作为开发者，我希望全局样式与 Element Plus 组件库兼容，以便界面渲染正确无冲突。

#### Acceptance Criteria

1. The 全局样式（style.css） shall 仅包含最小化的浏览器重置样式（body margin、font-family）
2. The 全局样式 shall 不包含 Vite 脚手架默认的暗色主题样式
3. The 全局样式 shall 不设置 `#app` 的 `text-align: center` 或 `max-width` 约束
4. The 全局样式 shall 不覆盖 Element Plus 的按钮、链接等组件默认样式
5. The `body` 元素 shall 使用 `background-color: #f5f5f5` 或类似浅色背景

### Requirement 3: Pinia 状态管理初始化

**Objective:** 作为开发者，我希望项目正确初始化 Pinia 状态管理库，以便各组件间共享状态。

#### Acceptance Criteria

1. The 应用入口（main.ts） shall 注册 Pinia 插件
2. The Web管理界面 shall 提供 Auth Store 管理 API Key 认证状态
3. The Auth Store shall 从 localStorage 加载已保存的 API Key
4. When 用户设置新的 API Key，the Auth Store shall 将其保存到 localStorage 并更新状态
5. When 用户清除 API Key，the Auth Store shall 从 localStorage 移除并更新状态
6. The Axios 请求拦截器 shall 从 Auth Store 读取 API Key 并注入请求头

### Requirement 4: 通用工具函数提取

**Objective:** 作为开发者，我希望重复的时间格式化等工具函数统一维护，以便减少代码重复和维护成本。

#### Acceptance Criteria

1. The Web管理界面 shall 提供统一的时间格式化工具模块（`utils/format.ts`）
2. The 工具模块 shall 提供相对时间格式化函数（如"3分钟前"、"2天前"）
3. The 工具模块 shall 提供完整日期时间格式化函数（如"2026-02-14 12:30"）
4. The 工具模块 shall 提供日期时间本地化格式化函数（zh-CN 格式）
5. The 各页面组件（TweetsView、FollowsView、TasksView 等） shall 使用统一工具模块替代组件内重复的格式化函数

### Requirement 5: 仪表盘页面

**Objective:** 作为管理员，我希望有一个仪表盘概览页面，以便快速了解系统整体运行状况。

#### Acceptance Criteria

1. When 用户访问仪表盘页面（/dashboard），the Web管理界面 shall 显示系统概览信息
2. The 仪表盘 shall 显示推文总数统计卡片
3. The 仪表盘 shall 显示活跃关注账号数统计卡片
4. The 仪表盘 shall 显示调度器当前状态卡片（启用/禁用、下次执行时间）
5. The 仪表盘 shall 显示摘要成本统计卡片（总成本 USD）
6. The 仪表盘 shall 显示系统健康状态面板，包含各组件（数据库、调度器）的运行状态
7. The 仪表盘 shall 显示最近 5 条任务记录及其状态
8. When 应用首页（/）被访问，the Web管理界面 shall 重定向到仪表盘页面
9. While 仪表盘数据正在加载，the Web管理界面 shall 显示骨架屏或加载状态
10. If 任一数据源加载失败，the 仪表盘 shall 在对应卡片显示错误提示，不影响其他卡片加载

### Requirement 6: 调度管理页面

**Objective:** 作为管理员，我希望能够查看和配置抓取调度器的运行参数，以便控制自动抓取的频率和时机。

#### Acceptance Criteria

1. When 用户访问调度管理页面（/scheduler），the Web管理界面 shall 显示当前调度配置信息
2. The 调度管理页面 shall 显示调度器启用/禁用状态
3. The 调度管理页面 shall 显示当前抓取间隔（格式化为可读的时间描述，如"每 2 小时"）
4. The 调度管理页面 shall 显示下次计划执行时间
5. When 用户点击启用/禁用开关，the Web管理界面 shall 调用对应 API 切换调度器状态
6. When 用户修改抓取间隔并提交，the Web管理界面 shall 调用 API 更新间隔配置
7. The 抓取间隔设置 shall 提供常用预设选项（30分钟、1小时、2小时、4小时、8小时、24小时）
8. When 用户设置下次执行时间并提交，the Web管理界面 shall 调用 API 更新下次执行时间
9. The 下次执行时间选择器 shall 仅允许选择未来的时间
10. Where 调度器状态变更成功，the Web管理界面 shall 显示成功提示并刷新显示
11. If 调度器操作失败，the Web管理界面 shall 显示错误提示信息
12. While 调度器处于禁用状态，the 间隔设置和下次执行时间设置 shall 仍可编辑（启用时自动生效）

### Requirement 7: 用户管理页面

**Objective:** 作为管理员，我希望能够管理系统用户（查看、创建、重置密码），以便控制谁能访问系统。

#### Acceptance Criteria

1. When 用户访问用户管理页面（/users），the Web管理界面 shall 显示所有用户的列表
2. The 用户列表 shall 显示用户 ID、名称、邮箱、管理员标识、创建时间
3. When 用户点击"创建用户"按钮，the Web管理界面 shall 打开创建用户对话框
4. The 创建用户对话框 shall 包含名称和邮箱输入字段，均为必填
5. When 用户提交创建用户表单，the Web管理界面 shall 调用后端 API 创建新用户
6. Where 用户创建成功，the Web管理界面 shall 在对话框中显示后端返回的临时密码和 API Key
7. The 临时密码和 API Key 显示 shall 包含复制按钮，并提示用户此信息仅显示一次
8. When 用户点击某用户的"重置密码"按钮，the Web管理界面 shall 弹出确认对话框
9. Where 密码重置确认后，the Web管理界面 shall 调用后端 API 并显示新的临时密码
10. If 用户管理操作失败，the Web管理界面 shall 显示错误提示信息
11. While 用户列表正在加载，the Web管理界面 shall 显示加载状态

### Requirement 8: 推文详情增强 — 摘要再生成

**Objective:** 作为管理员，我希望能够重新生成或首次生成推文的 AI 摘要，以便在摘要质量不佳时手动触发更新。

#### Acceptance Criteria

1. When 推文存在 AI 摘要，the 推文详情页面 shall 在摘要卡片头部显示"重新生成"按钮
2. When 推文不存在 AI 摘要，the 推文详情页面 shall 在空状态区域显示"生成摘要"按钮
3. When 用户点击"重新生成"或"生成摘要"按钮，the Web管理界面 shall 调用后端摘要再生成 API
4. While 摘要正在生成，the 按钮 shall 显示加载状态且不可重复点击
5. Where 摘要生成成功，the Web管理界面 shall 自动刷新摘要卡片内容并显示成功提示
6. If 摘要生成失败，the Web管理界面 shall 显示错误提示信息

### Requirement 9: 推文列表增强 — 批量操作

**Objective:** 作为管理员，我希望能够对多条推文执行批量摘要和批量去重操作，以便高效处理大量推文。

#### Acceptance Criteria

1. The 推文列表 shall 为每条推文提供复选框，支持多选
2. When 用户选中一条或多条推文，the 页面顶部 shall 显示已选数量和批量操作按钮
3. When 用户点击"批量摘要"按钮，the Web管理界面 shall 将选中推文的 ID 列表提交到后端批量摘要 API
4. When 用户点击"批量去重"按钮，the Web管理界面 shall 将选中推文的 ID 列表提交到后端批量去重 API
5. Where 批量操作被触发，the Web管理界面 shall 显示任务 ID 和进度提示
6. If 未选中任何推文时点击批量操作按钮，the Web管理界面 shall 提示用户先选择推文
7. While 批量操作正在执行，the 操作按钮 shall 显示加载状态

### Requirement 10: 任务监控增强

**Objective:** 作为管理员，我希望能够删除已完成的任务记录并更灵活地触发抓取，以便更好地管理任务历史。

#### Acceptance Criteria

1. The 任务历史列表 shall 为非运行中的任务提供"删除"操作按钮
2. When 用户点击任务"删除"按钮，the Web管理界面 shall 弹出确认对话框
3. Where 删除确认后，the Web管理界面 shall 调用后端 API 删除任务记录并刷新列表
4. When 用户点击"立即抓取"按钮，the Web管理界面 shall 自动获取所有活跃关注账号作为抓取目标
5. If 当前没有活跃的关注账号，the Web管理界面 shall 提示用户先添加关注账号
6. The "立即抓取"操作 shall 不再发送空 usernames 字符串到后端 API

### Requirement 11: 路由与导航更新

**Objective:** 作为开发者，我希望路由配置正确包含所有新增页面，以便所有页面可正常访问和导航。

#### Acceptance Criteria

1. The 路由配置 shall 包含以下路径：/dashboard, /tweets, /tweets/:id, /follows, /tasks, /scheduler, /users
2. When 用户访问根路径（/），the Web管理界面 shall 重定向到 /dashboard
3. The 每个路由 shall 配置 meta.title 属性，用于动态更新页面标题
4. The 侧边栏菜单 shall 根据当前路由自动高亮对应菜单项

### Requirement 12: 新增 API 集成

**Objective:** 作为开发者，我希望前端 API 层完整覆盖本次新增页面所需的后端端点，以便各页面正常获取和提交数据。

#### Acceptance Criteria

1. The 前端 API 层 shall 封装调度管理相关端点：获取配置、更新间隔、更新下次运行时间、启用、禁用
2. The 前端 API 层 shall 封装用户管理相关端点：列出用户、创建用户、重置密码
3. The 前端 API 层 shall 封装健康检查端点：获取系统健康状态
4. The 前端 API 层 shall 封装摘要相关端点：获取统计信息、批量摘要、重新生成单条摘要
5. The 前端 API 层 shall 封装去重相关端点：批量去重
6. The 所有新增 API 模块 shall 使用与现有 API 模块（tweets、tasks、follows）一致的架构模式
7. The 所有新增 API 模块 shall 定义完整的 TypeScript 请求/响应类型接口
