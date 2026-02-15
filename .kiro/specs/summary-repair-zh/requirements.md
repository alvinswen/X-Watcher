# 需求文档

## 介绍

本规格定义"推文摘要修复"功能，为 X-watcher Web 管理界面新增两个批量操作：**摘要补缺**（为缺少摘要的推文生成摘要和翻译）和**摘要重置**（指定时间窗口内所有推文重新生成摘要和翻译）。同时统一全系统 API 权限管理，确保所有端点都需要认证，Feed API 使用普通用户权限，其他管理端点使用管理员权限。

## 需求

### 需求 1: 摘要补缺 API

**目标:** 作为管理员，我希望能够批量为缺少摘要的推文生成摘要和翻译，以便修复因 LLM 限流或错误导致的摘要缺失。

#### 验收标准

1. When 管理员请求摘要补缺预览, the Summarization API shall 查询数据库中没有关联摘要记录的推文数量并返回 `tweet_count`
2. When 管理员请求摘要补缺预览并提供可选的 `since`/`until` 时间范围参数, the Summarization API shall 仅统计该时间范围内（基于推文 `created_at`）缺少摘要的推文
3. When 管理员提交摘要补缺任务, the Summarization API shall 创建后台任务，对所有缺少摘要的推文调用现有摘要生成服务（`force_refresh=false`），并返回 `task_id`、`status` 和 `tweet_count`
4. If 没有找到需要补缺的推文, the Summarization API shall 返回 HTTP 404 和明确的错误信息
5. The Summarization API shall 通过现有的任务注册表（TaskRegistry）管理补缺任务的生命周期，支持通过已有的 `GET /api/summaries/tasks/{task_id}` 端点查询进度

### 需求 2: 摘要重置 API

**目标:** 作为管理员，我希望能够指定时间窗口重新生成所有推文的摘要和翻译，以便在模型降级或摘要质量不理想时进行修复。

#### 验收标准

1. When 管理员请求摘要重置预览并提供必填的 `since` 和 `until` 参数, the Summarization API shall 查询该时间范围内（基于推文 `created_at`）的所有推文数量并返回 `tweet_count`
2. When 管理员提交摘要重置任务, the Summarization API shall 创建后台任务，对时间范围内所有推文调用现有摘要生成服务（`force_refresh=true` 强制重新生成），并返回 `task_id`、`status` 和 `tweet_count`
3. If `since` 不早于 `until`, the Summarization API shall 返回 HTTP 422 和参数校验错误信息
4. If 指定时间范围内没有推文, the Summarization API shall 返回 HTTP 404 和明确的错误信息
5. The Summarization API shall 通过现有的任务注册表管理重置任务的生命周期，与补缺任务共享相同的任务查询机制

### 需求 3: API 权限统一

**目标:** 作为系统运维者，我希望所有 API 端点都有认证保护，以防止未授权访问。

#### 验收标准

1. The Feed API (`GET /api/feed`) shall 要求普通用户认证（`get_current_user`：JWT 或 API Key）
2. The Summarization API shall 要求管理员认证（`get_current_admin_user`）才能访问所有端点，包括批量摘要、单条查询、统计、重新生成、补缺和重置
3. The Admin API (`/api/admin/*`) shall 要求管理员认证才能访问所有抓取管理端点
4. The Tweets API (`/api/tweets/*`) shall 要求管理员认证才能访问推文列表和详情端点
5. The Deduplication API (`/api/deduplication/*`) shall 要求管理员认证才能访问所有去重管理端点
6. If 请求缺少认证凭证, the API shall 返回 HTTP 401 Unauthorized
7. If 认证用户不具备管理员权限, the API shall 返回 HTTP 403 Forbidden

### 需求 4: 前端摘要工具 UI

**目标:** 作为管理员，我希望在推文管理页面中通过可视化界面执行摘要补缺和重置操作，以便快速发现和修复摘要问题。

#### 验收标准

1. The Web Admin UI shall 在推文列表页的批量操作区域提供"摘要工具"下拉菜单，包含"摘要补缺"和"摘要重置"两个选项
2. When 管理员选择"摘要补缺", the Web Admin UI shall 弹出对话框，提供可选的时间范围选择器和"查询"按钮
3. When 管理员在补缺对话框中点击"查询", the Web Admin UI shall 调用补缺预览 API 并显示需要补缺的推文数量
4. When 管理员确认执行补缺, the Web Admin UI shall 调用补缺 API 并通过轮询机制跟踪任务进度，完成后刷新推文列表
5. When 管理员选择"摘要重置", the Web Admin UI shall 弹出对话框，要求必填时间范围，并使用醒目的警示样式（danger）提示这是覆盖性操作
6. When 管理员在重置对话框中点击"查询", the Web Admin UI shall 调用重置预览 API 并显示将被重置的推文数量
7. When 管理员确认执行重置, the Web Admin UI shall 调用重置 API 并通过轮询机制跟踪任务进度，完成后刷新推文列表
8. While 补缺或重置任务正在执行, the Web Admin UI shall 禁用对应的操作按钮以防止重复提交

### 需求 5: Agent 工具注册

**目标:** 作为 AI Agent，我希望能够通过工具调用触发摘要补缺和重置操作，以便实现自动化的摘要质量维护。

#### 验收标准

1. The Agent 工具元数据 shall 注册 `summary_backfill` 工具，描述补缺 API 的端点、参数和认证方式
2. The Agent 工具元数据 shall 注册 `summary_reset` 工具，描述重置 API 的端点、参数和认证方式
3. The Agent 系统提示 shall 包含摘要修复工具的使用说明，指导 Agent 在发现摘要缺失时自动触发补缺
