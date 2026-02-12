# Implementation Plan

- [ ] 1. 项目依赖与配置基础设施
- [ ] 1.1 添加认证相关依赖并扩展全局配置
  - 在 pyproject.toml 中添加 bcrypt>=5.0.0 和 PyJWT>=2.11.0 依赖
  - 在 Settings 类中新增 jwt_secret_key（必填）和 jwt_expire_hours（默认 24）配置字段
  - 更新 .env.example 添加 JWT_SECRET_KEY 和 JWT_EXPIRE_HOURS 示例值
  - 安装新依赖并验证导入正常
  - _Requirements: 3.6_

- [ ] 1.2 扩展数据库模型并生成 Alembic 迁移
  - User ORM 模型新增 password_hash 字段（nullable=True，兼容现有无密码用户）
  - 新增 ApiKey ORM 模型，包含 id、user_id（外键级联删除）、key_hash（唯一）、key_prefix、name、is_active、created_at、last_used_at
  - 建立 User ↔ ApiKey 双向关系（一对多，级联删除孤儿）
  - 添加 key_hash 唯一索引和 user_id 索引以满足认证查询性能要求
  - 更新 alembic/env.py 确保新模型被导入
  - 生成并执行 Alembic 迁移脚本
  - _Requirements: 2.4, 2.5, 2.6_

- [ ] 2. 领域模型与认证服务
- [ ] 2.1 (P) 定义用户领域模型和 API 请求/响应 Schema
  - 创建 UserDomain Pydantic 模型（id, name, email, is_admin, created_at），带 from_orm 类方法
  - 创建 ApiKeyInfo Pydantic 模型（id, user_id, key_prefix, name, is_active, created_at, last_used_at），带 from_orm 类方法
  - 定义 BOOTSTRAP_ADMIN 虚拟管理员常量（id=0, name="bootstrap", email="bootstrap@system", is_admin=True）
  - 创建请求 Schema：LoginRequest、CreateUserRequest、CreateApiKeyRequest、ChangePasswordRequest（密码最少 8 字符校验）
  - 创建响应 Schema：LoginResponse、UserResponse、CreateUserResponse、CreateApiKeyResponse、ApiKeyResponse、ResetPasswordResponse
  - _Requirements: 4.5, 6.4_

- [ ] 2.2 (P) 实现 AuthService 认证原语服务
  - 实现密码哈希（bcrypt rounds=12）和验证，>72 字节密码预先 SHA-256+base64 处理，使用 asyncio.to_thread 避免阻塞
  - 实现 API Key 生成（sna_ + secrets.token_hex(16) = 36 字符）、SHA-256 哈希、hmac.compare_digest 常量时间比较
  - 实现 JWT Token 生成（HS256 算法，payload 含 sub/email/is_admin/exp/iat）和解码验证（强制 algorithms=["HS256"]）
  - 实现临时密码生成（12 字符，字母+数字）
  - 所有方法为纯函数式设计，不持有数据库访问权限
  - _Requirements: 2.4, 2.5, 3.1, 3.5, 6.3_

- [ ] 2.3 编写 AuthService 单元测试
  - 测试密码哈希和验证的正确性（包括 >72 字节密码预哈希场景）
  - 测试 API Key 生成格式（sna_ 前缀、36 字符长度）、SHA-256 哈希输出、常量时间比较
  - 测试 JWT Token 生成包含正确 payload 字段，解码返回正确数据
  - 测试 JWT 过期 Token 抛出 ExpiredSignatureError
  - 测试临时密码格式和长度
  - _Requirements: 2.4, 2.5, 3.4, 3.5, 6.3_

- [ ] 3. 数据访问层
- [ ] 3.1 实现 UserRepository 用户和 API Key 数据操作
  - 实现用户 CRUD：创建用户（IntegrityError → DuplicateError）、按 ID/邮箱查询、获取全部用户、更新密码哈希
  - 实现 API Key CRUD：创建 Key、按哈希查活跃 Key（返回 key_info + user_id）、按用户列出 Key、去活 Key、更新 last_used_at
  - 所有操作通过注入的 AsyncSession 执行，遵循现有 preference 模块的 Repository 模式
  - 错误映射：IntegrityError → DuplicateError，未找到 → NotFoundError
  - _Requirements: 1.2, 2.1, 2.6, 5.2, 5.3, 7.1, 7.2, 9.1_

- [ ] 3.2 编写 UserRepository 集成测试
  - 测试用户创建和邮箱唯一约束（重复邮箱抛出 DuplicateError）
  - 测试按 ID 和邮箱查询用户、获取全部用户列表
  - 测试 API Key 创建、按哈希查询活跃 Key、按用户列出 Key
  - 测试 Key 去活后不再被哈希查询返回
  - 测试 last_used_at 更新
  - 测试密码哈希更新
  - _Requirements: 1.2, 2.1, 2.6, 5.2, 5.3, 5.4_

- [ ] 4. 业务编排层
- [ ] 4.1 实现 UserService 用户生命周期编排
  - 实现用户创建事务：生成临时密码 → 哈希密码 → 创建用户记录 → 生成 API Key → 保存 Key → 初始化关注列表（调用 PreferenceService），所有操作共享同一 AsyncSession 事务
  - 实现 API Key 创建和撤销（撤销时验证 key.user_id == current_user.id，不属于自己则抛出 NotFoundError 不透露归属）
  - 实现 Key 列表查询
  - 实现密码修改（验证旧密码 → 更新新密码哈希），旧密码错误抛出 ValueError
  - 实现管理员重置密码（生成新临时密码 → 更新哈希 → 返回临时密码）
  - 实现用户信息查询和全部用户列表
  - _Requirements: 1.1, 1.4, 1.5, 1.6, 5.1, 5.5, 6.1, 6.2, 9.2_

- [ ] 4.2 编写 UserService 集成测试
  - 测试 create_user 完整流程：返回用户信息 + 临时密码 + API Key，验证关注列表已初始化
  - 测试邮箱重复时 create_user 抛出 DuplicateError
  - 测试 create_api_key 和 list_api_keys
  - 测试 revoke_api_key 权限隔离（撤销他人 Key 返回 NotFoundError）
  - 测试 change_password 成功和旧密码错误场景
  - 测试 reset_password 返回新临时密码
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.6, 5.1, 5.5, 6.1, 6.2, 9.2_

- [ ] 5. 统一认证中间件
- [ ] 5.1 实现 get_current_user 和 get_current_admin_user 认证依赖
  - 实现 get_current_user：优先从 X-API-Key 头提取 Key → SHA-256 哈希 → 查数据库匹配活跃 Key → 返回用户并更新 last_used_at；无 API Key 则尝试 Bearer JWT → 解码验证 → 按 user_id 返回用户；均无则返回 401
  - 实现 get_current_admin_user：先尝试 get_current_user 逻辑 → 验证 is_admin；回退到 ADMIN_API_KEY 环境变量比对 → 匹配时返回 BOOTSTRAP_ADMIN 虚拟用户（id=0）；非管理员返回 403
  - 使用 APIKeyHeader(auto_error=False) 和 HTTPBearer(auto_error=False) 作为 FastAPI security scheme
  - 确保 API Key 路径更新 last_used_at，JWT 路径不访问数据库
  - 认证失败记录 WARNING 日志，成功记录 DEBUG 日志，日志中不记录密码/Key/Token 明文
  - _Requirements: 2.1, 2.2, 2.3, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 5.2 编写认证依赖测试
  - 测试 API Key 认证成功和失败（无效 Key、非活跃 Key）
  - 测试 JWT 认证成功和失败（过期 Token、无效 Token）
  - 测试 API Key 优先于 JWT 的优先级逻辑
  - 测试无任何凭证返回 401
  - 测试 get_current_admin_user 对管理员用户放行、非管理员返回 403
  - 测试 ADMIN_API_KEY 环境变量回退返回 BOOTSTRAP_ADMIN 虚拟用户
  - 测试 ADMIN_API_KEY 不可用于 get_current_user
  - _Requirements: 2.1, 2.2, 2.3, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 5.4_

- [ ] 6. API 端点与路由注册
- [ ] 6.1 (P) 实现 AuthRouter 登录端点
  - 实现 POST /api/auth/login：接收邮箱和密码 → 查询用户 → 验证密码 → 生成 JWT Token 返回
  - 错误凭证统一返回 401，不区分"邮箱不存在"和"密码错误"
  - _Requirements: 3.1, 3.2_

- [ ] 6.2 (P) 实现 UserRouter 用户自身操作端点
  - 实现 GET /api/users/me：返回当前认证用户信息
  - 实现 POST /api/users/me/api-keys：创建新 API Key，返回完整 Key（仅一次）
  - 实现 GET /api/users/me/api-keys：列出当前用户的 API Key 元数据
  - 实现 DELETE /api/users/me/api-keys/{key_id}：撤销指定 Key，不属于自己返回 404
  - 实现 PUT /api/users/me/password：修改密码，旧密码错误返回 400
  - 所有端点使用 get_current_user 认证依赖
  - _Requirements: 5.1, 5.2, 5.3, 5.5, 6.1, 6.2, 6.4, 7.1_

- [ ] 6.3 (P) 实现 AdminUserRouter 管理员端点
  - 实现 POST /api/admin/users：创建用户，返回用户信息 + 临时密码 + API Key（仅展示一次），邮箱重复返回 409
  - 实现 GET /api/admin/users：列出所有用户基本信息（不含密码和 Key）
  - 实现 POST /api/admin/users/{user_id}/reset-password：重置指定用户密码，返回新临时密码
  - 所有端点使用 get_current_admin_user 认证依赖
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 7.2, 7.3, 9.1, 9.2, 9.3_

- [ ] 6.4 注册路由并验证端到端
  - 在 main.py 中注册 AuthRouter、UserRouter、AdminUserRouter
  - 创建路由汇总模块整合三个 Router
  - 启动应用验证所有端点在 OpenAPI 文档中正确显示
  - _Requirements: 3.1, 4.1_

- [ ] 7. API 端点测试
- [ ] 7.1 (P) 编写登录 API 测试
  - 测试正确邮箱+密码返回 JWT Token（包含 access_token 和 token_type）
  - 测试错误邮箱或密码返回 401
  - 测试返回的 JWT Token 可用于后续请求认证
  - _Requirements: 3.1, 3.2_

- [ ] 7.2 (P) 编写用户操作 API 测试
  - 测试 GET /me 返回当前用户信息（API Key 和 JWT 两种认证方式）
  - 测试 API Key 创建、列出、撤销完整生命周期
  - 测试撤销他人 Key 返回 404
  - 测试密码修改成功和旧密码错误
  - 测试未认证访问返回 401
  - _Requirements: 5.1, 5.2, 5.3, 5.5, 6.1, 6.2, 7.1_

- [ ] 7.3 (P) 编写管理员 API 测试
  - 测试管理员创建用户返回用户信息 + 临时密码 + API Key
  - 测试邮箱重复创建返回 409
  - 测试非管理员创建用户返回 403
  - 测试管理员列出用户返回完整列表
  - 测试管理员重置密码返回新临时密码
  - 测试 ADMIN_API_KEY 环境变量可执行管理操作
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 7.2, 7.3, 9.1, 9.2, 9.3_

- [ ] 8. Preference 模块认证迁移
- [ ] 8.1 迁移 preference_router.py 11 个端点至认证依赖
  - 将所有端点的 user_id: Query(...) 参数替换为 Depends(get_current_user)
  - 端点内部自动使用认证用户的 ID，无需手动传递 user_id
  - 确保端点签名变更后功能行为不变
  - _Requirements: 8.1, 8.3_

- [ ] 8.2 迁移 scraper_config_router.py 4 个管理端点至认证依赖
  - 将 verify_admin_api_key 依赖替换为 get_current_admin_user
  - 废弃 src/preference/api/auth.py 中的旧认证方法（可保留重导出以兼容）
  - _Requirements: 8.2_

- [ ] 8.3 适配 Preference 模块测试套件
  - 适配 tests/preference/ 中约 13 个测试文件，将 ?user_id=X 查询参数改为 mock get_current_user 依赖
  - 适配管理端点测试从 X-API-Key 头改为 mock get_current_admin_user 依赖
  - 运行全量 preference 测试确保无回归
  - _Requirements: 8.4_

- [ ] 9. 种子数据与最终集成验证
- [ ] 9.1 更新种子脚本设置管理员初始密码
  - 更新 scripts/seed_admin.py，在创建管理员用户时设置初始密码哈希
  - 确保种子脚本与新 User 模型（password_hash 字段）兼容
  - _Requirements: 1.4_

- [ ] 9.2 全量测试和安全验证
  - 运行全量 pytest 确保所有 user 模块和 preference 模块测试通过
  - 验证安全要求：日志中无密码/Key/Token 明文泄露，认证错误响应不透露内部信息
  - 验证 ADMIN_API_KEY 向后兼容：环境变量可用于管理操作，但不可用于普通用户 get_current_user
  - 验证人类用户（JWT）和 Agent（API Key）访问相同 API 接口的兼容性
  - _Requirements: NFR 1.1, NFR 1.2, NFR 1.3, NFR 2.1, NFR 2.2, NFR 3.1, NFR 3.2_
