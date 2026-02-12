# 需求文档

## 简介

为 X-watcher 系统添加用户管理子模块，实现多用户访问控制。系统采用管理员邀请制注册，认证支持 API Key + JWT 双模式——API Key 面向 Agent/脚本的程序化访问，JWT 面向 Web UI 的人类用户登录。每个新用户默认继承系统当前抓取的所有账号作为关注列表，可自行编辑（取消/恢复关注），但不可关注系统未抓取的账号。同时需要将现有 preference 模块的 `user_id` 查询参数替换为基于认证的用户身份识别。

## 需求

### Requirement 1: 管理员邀请制用户注册

**Objective:** 作为系统管理员，我希望通过邀请制创建新用户，以便控制系统访问权限并确保只有授权人员能使用系统。

#### Acceptance Criteria
1. When 管理员提交创建用户请求（包含姓名和邮箱）, the UserManager shall 创建新用户记录并返回用户信息及初始 API Key。
2. When 管理员创建用户时提供的邮箱已存在, the UserManager shall 返回 409 冲突错误并提示邮箱已被注册。
3. The UserManager shall 仅允许已认证的管理员用户执行用户创建操作。
4. When 新用户被创建时, the UserManager shall 为该用户生成一个临时密码并包含在创建响应中（仅展示一次）。
5. When 新用户被创建时, the UserManager shall 自动生成一个默认 API Key 并包含在创建响应中（仅展示一次）。
6. When 新用户被创建时, the UserManager shall 自动从系统抓取列表（scraper_follows）复制所有活跃账号作为该用户的初始关注列表。

### Requirement 2: API Key 认证

**Objective:** 作为 Agent 或脚本开发者，我希望通过 API Key 认证访问系统，以便实现无状态的程序化访问。

#### Acceptance Criteria
1. When 请求携带有效的 `X-API-Key` 请求头, the UserManager shall 识别对应用户并允许访问。
2. When 请求携带无效或过期的 `X-API-Key` 请求头, the UserManager shall 返回 401 未授权错误。
3. When 请求未携带任何认证凭证, the UserManager shall 返回 401 未授权错误。
4. The UserManager shall 以 SHA-256 哈希形式存储 API Key，不存储明文。
5. The UserManager shall 为每个 API Key 生成可识别的前缀（如 `sna_`），便于用户区分不同 Key。
6. When API Key 被成功使用时, the UserManager shall 更新该 Key 的最后使用时间。

### Requirement 3: JWT 认证

**Objective:** 作为 Web UI 用户，我希望通过邮箱和密码登录获取 JWT Token，以便在浏览器中持续访问系统。

#### Acceptance Criteria
1. When 用户提交正确的邮箱和密码, the UserManager shall 返回 JWT Access Token。
2. When 用户提交错误的邮箱或密码, the UserManager shall 返回 401 未授权错误，不透露具体是邮箱还是密码错误。
3. When 请求携带有效的 `Authorization: Bearer <token>` 请求头, the UserManager shall 识别对应用户并允许访问。
4. When JWT Token 已过期, the UserManager shall 返回 401 未授权错误并提示 Token 已过期。
5. The UserManager shall 在 JWT Token 中包含用户 ID、邮箱和管理员标志。
6. The UserManager shall 支持通过环境变量配置 JWT 密钥和过期时间。

### Requirement 4: 统一认证中间件

**Objective:** 作为系统架构师，我希望有一个统一的认证依赖，以便所有需要认证的端点共享相同的认证逻辑。

#### Acceptance Criteria
1. The UserManager shall 提供统一的 `get_current_user` FastAPI 依赖，同时支持 API Key 和 JWT 两种认证方式。
2. When 请求同时携带 `X-API-Key` 和 `Authorization` 请求头, the UserManager shall 优先使用 API Key 认证。
3. The UserManager shall 提供 `get_current_admin_user` 依赖，在认证基础上额外验证管理员权限。
4. The UserManager shall 保留 `ADMIN_API_KEY` 环境变量作为系统初始化引导机制（系统无用户时可用）。
5. When 使用 `ADMIN_API_KEY` 环境变量进行认证时, the UserManager shall 授予管理员权限但不关联具体用户。

### Requirement 5: API Key 生命周期管理

**Objective:** 作为已认证用户，我希望管理自己的 API Key（创建、查看、撤销），以便控制不同应用或 Agent 的访问权限。

#### Acceptance Criteria
1. When 用户请求创建新 API Key（可选提供名称标签）, the UserManager shall 生成新 Key 并返回完整 Key（仅展示一次）。
2. When 用户查询自己的 API Key 列表, the UserManager shall 返回 Key 的元数据（前缀、名称、状态、创建时间、最后使用时间），不返回完整 Key。
3. When 用户撤销指定 API Key, the UserManager shall 将该 Key 标记为非活跃状态。
4. While API Key 处于非活跃状态, the UserManager shall 拒绝使用该 Key 的认证请求。
5. The UserManager shall 不允许用户撤销其他用户的 API Key。

### Requirement 6: 用户密码管理

**Objective:** 作为已认证用户，我希望能修改自己的密码，以便保持账户安全。

#### Acceptance Criteria
1. When 用户提交修改密码请求（包含旧密码和新密码）, the UserManager shall 验证旧密码正确后更新为新密码。
2. When 用户提交的旧密码不正确, the UserManager shall 返回 400 错误并提示旧密码错误。
3. The UserManager shall 使用 bcrypt 算法对密码进行哈希存储，不存储明文密码。
4. The UserManager shall 要求新密码长度不少于 8 个字符。

### Requirement 7: 用户信息查询

**Objective:** 作为已认证用户，我希望能查看自己的基本信息，以便确认身份和权限。

#### Acceptance Criteria
1. When 用户请求获取自身信息, the UserManager shall 返回用户的 ID、姓名、邮箱、管理员标志和创建时间。
2. When 管理员请求获取所有用户列表, the UserManager shall 返回系统中所有用户的基本信息。
3. The UserManager shall 不允许非管理员用户查看其他用户的信息。

### Requirement 8: 现有 Preference 模块认证迁移

**Objective:** 作为系统架构师，我希望将现有 preference 模块从 `user_id` 查询参数迁移到基于认证的用户识别，以便实现安全的用户隔离。

#### Acceptance Criteria
1. The UserManager shall 将 preference 模块所有端点的 `user_id: Query(...)` 参数替换为 `get_current_user` 认证依赖。
2. The UserManager shall 将 scraper_config 模块的 `verify_admin_api_key` 替换为 `get_current_admin_user` 依赖。
3. While 用户已通过认证, the preference 模块 shall 自动使用认证用户的 ID 进行所有操作，无需手动传递 user_id。
4. The UserManager shall 确保迁移后所有现有 preference 测试通过或适配为使用新认证方式。

### Requirement 9: 管理员用户管理

**Objective:** 作为系统管理员，我希望能查看和管理系统中的用户，以便维护系统安全。

#### Acceptance Criteria
1. When 管理员请求用户列表, the UserManager shall 返回所有用户的基本信息（不含密码和 Key）。
2. When 管理员重置指定用户的密码, the UserManager shall 生成新的临时密码并返回（仅展示一次）。
3. The UserManager shall 仅允许管理员执行用户管理操作。

## 非功能性需求

### NFR 1: 安全性
1. The UserManager shall 不在任何日志或错误响应中泄露密码或 API Key 明文。
2. The UserManager shall 使用常量时间比较（constant-time comparison）验证 API Key 哈希，防止时序攻击。
3. The UserManager shall 对 JWT Token 设置合理的过期时间（默认 24 小时，可配置）。

### NFR 2: 性能
1. The UserManager shall 在 100ms 内完成 API Key 认证（包含数据库查询）。
2. The UserManager shall 在 100ms 内完成 JWT Token 验证（不需要数据库查询）。

### NFR 3: 兼容性
1. The UserManager shall 对人类用户和 Agent 提供完全相同的 API 接口（仅认证方式不同）。
2. The UserManager shall 保持与现有 `ADMIN_API_KEY` 环境变量的向后兼容。
