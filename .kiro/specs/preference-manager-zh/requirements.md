# 需求文档

## 简介

Preference Manager（偏好管理模块）是 X-watcher 的核心组件之一，为科技公司高管提供根据公司战略动态调整新闻关注重点的能力。与通用新闻聚合器的个人兴趣驱动不同，本模块专注于"战略驱动"的场景，支持用户灵活管理 Twitter 关注列表、新闻排序偏好和内容过滤规则，确保新闻流始终与公司战略方向保持一致。

## 功能范围

本需求文档涵盖以下核心功能领域：

1. **关注列表管理** - 动态添加、移除和查看关注的 Twitter 人物
2. **排序偏好管理** - 配置新闻流的排序规则（时间、相关性、优先级）
3. **过滤规则管理** - 设置内容过滤条件（关键词、话题标签、内容类型）
4. **偏好配置持久化** - 将用户偏好存储到数据库并支持查询

## 需求

### Requirement 1: 关注列表管理

**目标：** 作为科技公司高管，我希望能够动态管理关注列表，以便根据公司战略变化快速调整关注重点。

#### 验收标准

1. When 用户添加新的 Twitter 用户名到关注列表，Preference Manager 验证用户名格式有效后将该用户名添加到关注列表
2. When 用户从关注列表移除 Twitter 用户名，Preference Manager 从关注列表中删除该用户名
3. When 用户查询关注列表，Preference Manager 返回完整的关注列表包含用户名和添加时间
4. If 用户添加已存在的 Twitter 用户名，Preference Manager 返回"用户已存在"提示且不创建重复记录
5. If 用户添加的 Twitter 用户名格式无效（超过 15 字符或包含非法字符），Preference Manager 返回 400 错误和具体验证错误信息

### Requirement 2: 排序偏好管理

**目标：** 作为科技公司高管，我希望配置新闻排序规则，以便按战略优先级获取新闻。

#### 验收标准

1. When 用户设置排序偏好为"时间"，Preference Manager 将新闻按发布时间倒序排列
2. When 用户设置排序偏好为"相关性"，Preference Manager 调用相关性服务计算每条推文与用户配置关键词的相关性分数并按分数降序排列
3. When 用户设置排序偏好为"优先级"，Preference Manager 根据用户配置的人物优先级排序
4. When 用户查询当前排序偏好，Preference Manager 返回当前有效的排序类型和配置参数
5. If 用户设置了无效的排序类型，Preference Manager 返回 400 错误并列出有效的排序选项
6. Where 相关性服务不可用或返回错误，Preference Manager 记录日志并回退到按时间排序

### Requirement 3: 过滤规则管理

**目标：** 作为科技公司高管，我希望设置内容过滤规则，以便过滤掉与战略无关的干扰性新闻。

#### 验收标准

1. When 用户添加关键词过滤规则，Preference Manager 存储该关键词并标记为过滤条件
2. When 用户移除关键词过滤规则，Preference Manager 从过滤规则列表中删除该关键词
3. When 用户添加话题标签过滤规则，Preference Manager 存储该标签（不含 # 符号）并标记为过滤条件
4. When 用户设置内容类型过滤（如过滤转推、过滤含媒体内容），Preference Manager 存储该过滤类型
5. When 用户查询过滤规则，Preference Manager 返回所有有效的关键词、话题标签和内容类型过滤规则
6. If 用户添加已存在的过滤规则，Preference Manager 返回"规则已存在"提示且不创建重复记录

### Requirement 4: 偏好配置持久化

**目标：** 作为系统，我需要将用户偏好持久化存储，以便在服务重启后保持配置有效。

#### 验收标准

1. When 用户创建或更新偏好配置，Preference Manager 将配置保存到数据库的 preferences 表
2. When 用户查询偏好配置，Preference Manager 从数据库读取并返回最新配置
3. When 用户删除偏好配置，Preference Manager 从数据库中删除对应记录
4. While 数据库连接失败，Preference Manager 返回 500 错误并记录日志
5. While 批量更新偏好配置，Preference Manager 使用数据库事务确保所有更新原子性成功或全部回滚

### Requirement 5: 人物优先级配置

**目标：** 作为科技公司高管，我希望为关注的 Twitter 人物设置优先级，以便优先获取重要人物的相关新闻。

#### 验收标准

1. When 用户为 Twitter 用户名设置优先级（1-10），Preference Manager 存储该优先级配置
2. When 用户查询关注列表，Preference Manager 返回每个用户名的优先级（默认为 5）
3. When 用户修改已有用户名的优先级，Preference Manager 更新该优先级配置
4. If 用户设置的优先级超出 1-10 范围，Preference Manager 返回 400 错误并提示有效范围
5. Where 用户未设置优先级，Preference Manager 使用默认优先级值 5

### Requirement 6: RESTful API 接口

**目标：** 作为系统，我需要提供标准的 RESTful API 接口，以便前端应用和 Agent 工具调用偏好管理功能。

#### 验收标准

1. When 客户端发送 POST 请求到 `/api/preferences/follows`，Preference Manager 创建新的关注记录并返回 201 状态码
2. When 客户端发送 GET 请求到 `/api/preferences/follows`，Preference Manager 返回关注列表和 200 状态码
3. When 客户端发送 DELETE 请求到 `/api/preferences/follows/{username}`，Preference Manager 删除对应关注记录并返回 204 状态码
4. When 客户端发送 PUT 请求到 `/api/preferences/sorting`，Preference Manager 更新排序偏好并返回 200 状态码
5. When 客户端发送 GET 请求到 `/api/preferences`，Preference Manager 返回所有偏好配置和 200 状态码
6. If 客户端请求不存在的资源，Preference Manager 返回 404 错误和具体错误信息
7. If 客户端发送无效的请求体，Preference Manager 返回 422 错误并详细列出验证错误

### Requirement 7: 数据验证与错误处理

**目标：** 作为系统，我需要验证所有输入数据并提供清晰的错误信息，以便用户快速修正错误操作。

#### 验收标准

1. When 用户提交包含非法字符的 Twitter 用户名，Preference Manager 拒绝请求并返回具体验证错误
2. When 用户提交超过最大长度的字符串字段，Preference Manager 返回 400 错误并提示最大长度限制
3. When 数据库约束违反（如唯一性约束），Preference Manager 捕获异常并返回友好的业务错误信息
4. While 发生未预期的系统错误，Preference Manager 返回 500 错误但不暴露敏感系统信息
5. The Preference Manager 使用 Pydantic 模型验证所有输入数据并自动返回详细的验证错误

### Requirement 8: 普通用户查看抓取账号列表

**目标：** 作为普通用户，我希望查看平台当前抓取的账号列表，以便了解可选的关注对象及其添加理由。

#### 验收标准

1. When 认证用户发送 GET 请求到 `/api/scraping/follows`，Preference Manager 返回所有活跃抓取账号列表和 200 状态码
2. The 响应包含 id、username、added_at、reason、added_by、is_active 字段
3. The 端点仅返回 is_active=True 的账号
4. If 用户未认证（无有效 JWT 或 API Key），返回 401 Unauthorized
5. The 端点仅支持只读访问，不提供增删改操作

---

## 非功能性需求

### NFR 1: 性能

- When 用户查询关注列表，Preference Manager 应在 100ms 内返回结果（最多 1000 个关注）
- When 用户更新偏好配置，Preference Manager 应在 200ms 内完成数据库更新

### NFR 2: 数据一致性

- When 并发请求更新同一偏好配置，Preference Manager 应使用乐观锁或悲观锁确保数据一致性

### NFR 3: 可扩展性

- The Preference Manager 数据模型设计应支持未来扩展新的偏好类型（如 Newsletter 源管理）

---

## 约束与依赖

### 约束

1. Twitter 用户名必须符合 Twitter 命名规则（1-15 字符，仅含字母数字下划线）
2. 优先级范围为 1-10 的整数
3. 关键词过滤规则最多支持 100 条

### 依赖

1. 依赖 `src/database/models.py` 中的 `User` 和 `Preference` 模型
2. 依赖 FastAPI 提供 RESTful API 接口
3. 依赖 SQLAlchemy 进行数据库操作
4. 依赖相关性服务（`RelevanceService`）计算推文与关键词的相关性分数
   - MVP 阶段使用关键词匹配算法
   - 未来可替换为嵌入模型语义相似度计算，接口保持不变
