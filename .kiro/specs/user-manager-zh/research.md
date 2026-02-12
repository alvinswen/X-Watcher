# user-manager-zh 差距分析报告

## 摘要

- **推荐方案**: 创建独立 `src/user/` 模块（方案 B），遵循项目已有的六边形架构模式
- **工作量**: L（1-2 周）— 新建完整模块 + 迁移 15 个现有端点 + 新增 2 个外部依赖
- **风险等级**: 中等 — 主要风险来自 preference 模块认证迁移的回归测试
- **核心差距**: 无密码认证体系、无 API Key 表、无 JWT 支持、现有端点无用户认证
- **可复用资产**: User ORM 模型、PreferenceService.initialize_user_follows()、异步数据库架构、ADMIN_API_KEY 配置

---

## 1. 需求-资产映射表

### Req 1: 管理员邀请制用户注册

| 技术需求 | 现有资产 | 状态 | 差距说明 |
|----------|----------|------|----------|
| 创建用户记录 | User ORM (id, name, email, is_admin, created_at) | 需修改 | 缺少 `password_hash` 字段 |
| 生成临时密码 | 无 | 缺失 | 需引入 bcrypt 库 |
| 生成默认 API Key | 无 | 缺失 | 需新建 ApiKey ORM 模型 |
| 初始化关注列表 | `PreferenceService.initialize_user_follows()` | ✅ 可复用 | 已实现从 scraper_follows 复制的逻辑 |
| 管理员权限验证 | `verify_admin_api_key()` | 需替换 | 仅校验环境变量静态 Key |
| 邮箱唯一性检查 | `User.email unique=True` | ✅ 可复用 | 数据库层已有约束 |

### Req 2: API Key 认证

| 技术需求 | 现有资产 | 状态 | 差距说明 |
|----------|----------|------|----------|
| X-API-Key 请求头识别用户 | `verify_admin_api_key()` 读取 X-API-Key 头 | 需重写 | 现有只做环境变量比对，需查数据库 |
| SHA-256 哈希存储 | 无 | 缺失 | 需实现 Key 生成和哈希存储 |
| sna_ 前缀 | 无 | 缺失 | Key 生成时加前缀 |
| 更新 last_used_at | 无 | 缺失 | ApiKey 模型需含此字段 |
| 常量时间比较 | `verify_admin_api_key` 用 `!=` | 约束 | 需用 `hmac.compare_digest` |

### Req 3: JWT 认证

| 技术需求 | 现有资产 | 状态 | 差距说明 |
|----------|----------|------|----------|
| 邮箱+密码登录端点 | 无 | 缺失 | 需新建登录端点 |
| JWT Token 生成 | 无 | 缺失 | pyproject.toml 无 JWT 库 |
| Bearer Token 解析 | 无 | 缺失 | 需实现请求头解析 |
| 可配置密钥与过期时间 | `src/config.py` Settings 类 | 需扩展 | 需新增 JWT 相关配置 |

### Req 4: 统一认证中间件

| 技术需求 | 现有资产 | 状态 | 差距说明 |
|----------|----------|------|----------|
| `get_current_user` 依赖 | 无 | 缺失 | 需新建统一认证依赖 |
| `get_current_admin_user` 依赖 | `AdminAuthDep` 返回 bool | 需替换 | 需改为返回 User 对象 |
| ADMIN_API_KEY 引导机制 | `admin_api_key` 配置已存在 | ✅ 可复用 | 统一中间件需保留回退逻辑 |

### Req 5-6: API Key 管理 + 密码管理

全部缺失，需从零构建。

### Req 7: 用户信息查询

| 技术需求 | 现有资产 | 状态 |
|----------|----------|------|
| 用户基本信息 | User ORM 已有字段 | ✅ 可复用 |
| 查询端点 | 无 | 缺失 |

### Req 8: Preference 模块迁移（影响最大）

| 迁移项 | 范围 | 说明 |
|--------|------|------|
| preference_router.py | 11 个端点 | `user_id: Query(...)` → `Depends(get_current_user)` |
| scraper_config_router.py | 4 个端点 | `verify_admin_api_key` → `get_current_admin_user` |
| 测试文件 | ~13 个文件 | API 测试需改用认证头/mock 依赖 |

### Req 9: 管理员用户管理

全部缺失，需新建管理端点。

---

## 2. 实现方案评估

### 方案 B（推荐）: 创建独立 `src/user/` 模块

**理由**:
- 完全遵循项目六边形架构模式（与 scraper, deduplication, summarization, preference 平行）
- 认证是跨模块公共能力，独立模块使 import 路径自然
- 不膨胀已有 preference 模块（已有 13 个测试文件、6 个 Service/Repository）
- 独立可测试

**新建文件**: ~10 个（domain/models.py, infrastructure/repository.py, services/user_service.py, services/auth_service.py, api/auth.py, api/schemas.py, api/auth_router.py, api/user_router.py, api/routes.py, __init__.py）

**修改文件**: ~8 个（database/models.py, config.py, main.py, preference_router.py, scraper_config_router.py, preference/auth.py, pyproject.toml, .env.example）

---

## 3. 关键技术决策（待设计阶段确认）

| 决策 | 选项 | 倾向 |
|------|------|------|
| JWT 库 | PyJWT vs python-jose | PyJWT（更轻量，HS256 足够）|
| 密码哈希 | bcrypt 独立 vs passlib[bcrypt] | bcrypt 独立（项目追求精简）|
| ADMIN_API_KEY 返回值 | Optional[User] / 虚拟用户 / 仅限 admin 依赖 | 仅限 `get_current_admin_user`（最安全）|
| 迁移策略 | 一次性 vs 分阶段 | 一次性（避免两种认证共存）|

---

## 4. 设计阶段研究结论

### 4.1 技术选型确认

| 库 | 版本 | 选择理由 |
|---|---|---|
| **PyJWT** | 2.11.0 | 轻量，HS256 足够，API 简洁（`jwt.encode`/`jwt.decode`） |
| **bcrypt** | 5.0.0 | Rust 实现，独立库无额外依赖。注意 >72 字节密码需预哈希（SHA-256+base64） |

### 4.2 研究问题解答

1. **API Key 格式**: `sna_` + `secrets.token_hex(16)` = 36 字符。SHA-256 哈希后 64 字符 hex 存储。
2. **JWT Refresh Token**: 不纳入当前范围。Access Token 过期后用户重新登录。
3. **last_used_at 并发**: 直接 UPDATE，无需特殊并发处理。低频操作，竞态条件不影响业务。
4. **数据迁移**: `password_hash` 列设为 `nullable=True`。seed_admin.py 更新后设置初始密码。
5. **索引策略**: `key_hash` 列添加 UNIQUE 索引（同时满足查询性能和唯一约束）。

### 4.3 FastAPI 双认证模式

使用 `auto_error=False` 的 `APIKeyHeader` 和 `HTTPBearer` security scheme，实现优先 API Key、回退 JWT 的统一认证依赖。详见 design.md 的 get_current_user 设计。

### 4.4 bcrypt 异步注意事项

bcrypt 是 CPU 密集型操作，在 async 上下文中需使用 `asyncio.to_thread()` 避免阻塞事件循环。Python 3.11+ 原生支持。

### 4.5 安全措施

- API Key 哈希比较: `hmac.compare_digest`（Python 3.11+ CVE-2022-48566 已修复）
- JWT 解码: 必须传 `algorithms=["HS256"]` 列表防止算法混淆攻击
- 登录错误: 统一返回 401，不区分"邮箱不存在"和"密码错误"
