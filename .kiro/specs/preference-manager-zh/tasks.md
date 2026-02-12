# Implementation Plan

## Task List

- [x] 1. 数据库层实现

- [x] 1.1 (P) 扩展 User 表并创建平台抓取账号表
  - 添加 is_admin 字段到 User 表
  - 创建 scraper_follows 表，包含 username、added_at、reason、added_by、is_active 字段
  - 设置 username 唯一约束和 is_active 索引
  - 创建数据库迁移脚本
  - _Requirements: 4.1, 4.2_

- [x] 1.2 (P) 创建用户关注列表和过滤规则表
  - 创建 twitter_follows 表，包含 user_id、username、priority、时间戳字段
  - 设置 (user_id, username) 复合唯一约束
  - 创建 filter_rules 表，包含 UUID 主键、user_id、filter_type、value 字段
  - 添加外键级联删除约束
  - 创建性能优化索引（user_id、username、priority 等）
  - _Requirements: 4.1, 4.2, 4.3, 5.1_

- [x] 1.3 (P) 创建 Preference 简单配置表
  - 创建或扩展 preferences 表用于存储排序偏好等简单配置
  - 使用 key-value 结构存储配置项
  - 添加必要索引
  - _Requirements: 2.1, 2.4_

- [x] 1.4 插入默认管理员种子数据
  - 创建种子数据脚本
  - 插入默认管理员记录（xi.sun@metalight.ai，is_admin=True）
  - 验证种子数据插入正确性
  - _Requirements: 4.1, 4.2_

- [x] 2. 领域模型与验证层实现

- [x] 2.1 (P) 定义 Pydantic 请求/响应模型
  - 创建关注管理相关模型（CreateFollowRequest、FollowResponse、UpdatePriorityRequest）
  - 创建过滤规则模型（CreateFilterRequest、FilterResponse）
  - 创建排序偏好模型（UpdateSortingRequest、SortingPreferenceResponse）
  - 创建管理员抓取配置模型（CreateScraperFollowRequest、ScraperFollowResponse、UpdateScraperFollowRequest）
  - 创建个性化新闻流模型（TweetWithRelevance）
  - _Requirements: 1.1-1.5, 2.1-2.5, 3.1-3.3, 5.1-5.5, 6.1-6.7, 7.1-7.5_

- [x] 2.2 (P) 定义领域模型和枚举类型
  - 创建 ScraperFollow 领域模型
  - 创建 TwitterFollow 领域模型
  - 创建 FilterRule 领域模型
  - 创建 FilterType 枚举（KEYWORD、HASHTAG、CONTENT_TYPE）
  - 创建 SortType 枚举（TIME、RELEVANCE、PRIORITY）
  - 实现 ORM 模型与领域模型的转换方法（to_domain/from_domain）
  - _Requirements: 1.1-1.5, 2.1-2.5, 3.1-3.6, 5.1-5.5_

- [x] 2.3 (P) 实现 Twitter 用户名格式验证器
  - 创建 Pydantic 验证器验证 Twitter 用户名格式
  - 验证规则：1-15 字符，仅包含字母数字下划线
  - 返回清晰的验证错误信息
  - _Requirements: 1.5, 7.1, 7.5_

- [x] 2.4 实现优先级范围验证器
  - 创建 Pydantic 验证器验证优先级范围（1-10）
  - 返回友好错误信息
  - _Requirements: 5.4, 7.1, 7.2_

- [ ] 3. 数据访问层实现

- [x] 3.1 (P) 实现 PreferenceRepository
  - 实现 TwitterFollow CRUD 操作方法
  - 实现 FilterRule CRUD 操作方法
  - 实现 Preference 读写操作方法
  - 实现用户初始化状态检查方法
  - 处理唯一约束冲突并返回友好错误
  - 使用数据库事务确保批量更新原子性
  - _Requirements: 1.1-1.4, 3.1-3.6, 4.1-4.5, 5.1-5.3_

- [x] 3.2 (P) 实现 ScraperConfigRepository
  - 实现 ScraperFollow CRUD 操作方法
  - 实现按 is_active 筛选的方法
  - 实现检查用户名是否在抓取列表中的方法
  - 处理 username 唯一约束冲突
  - _Requirements: 1.1, 4.1-4.2_

- [x] 3.3 (P) 扩展 TweetRepository 支持用户名列表查询
  - 实现按用户名列表查询推文的方法
  - 支持分页和限制参数
  - _Requirements: 2.1-2.3_

- [ ] 4. 服务层实现

- [x] 4.1 (P) 实现 ScraperConfigService
  - 实现添加抓取账号业务逻辑
  - 实现查询所有抓取账号列表（支持 include_inactive 参数）
  - 实现更新抓取账号（reason、is_active）
  - 实现软删除抓取账号
  - 实现检查用户名是否在抓取列表中的方法
  - _Requirements: NEW (管理员添加抓取账号)_

- [x] 4.2 (P) 实现 RelevanceService
  - 定义相关性计算抽象接口
  - 实现 MVP 版本：关键词匹配算法
  - 计算推文内容与关键词列表的相关性分数（0.0-1.0）
  - 实现降级处理：服务异常时返回默认分数
  - _Requirements: 2.2, 2.6_

- [x] 4.3 实现 PreferenceService 核心业务逻辑
  - 实现用户关注列表初始化逻辑（首次调用时复制 scraper_follows）
  - 实现添加/恢复关注业务逻辑（验证账号在抓取列表中）
  - 实现移除关注业务逻辑
  - 实现查询关注列表业务逻辑（支持排序）
  - 实现更新优先级业务逻辑
  - 实现过滤规则 CRUD 业务逻辑
  - 实现排序偏好 CRUD 业务逻辑
  - 实现事务边界管理
  - _Requirements: 1.1-1.3, 2.4, 3.1-3.6, 4.5, 5.1-5.3_

- [x] 4.4 实现个性化新闻流排序业务逻辑
  - 实现获取排序后新闻流方法（get_sorted_news）
  - 实现时间排序逻辑
  - 实现优先级排序逻辑（按人物优先级分组）
  - 实现相关性排序逻辑（调用 RelevanceService 计算分数）
  - 实现过滤规则应用逻辑
  - 实现相关性服务不可用时的降级逻辑（回退到时间排序）
  - _Requirements: 2.1-2.3, 2.6, 3.4_

- [x] 5. API 层实现

- [x] 5.1 (P) 实现管理员 API Key 认证依赖
  - 创建 verify_admin_api_key 依赖函数
  - 从环境变量读取 ADMIN_API_KEY
  - 验证 X-API-Key 请求头
  - 返回 403 Forbidden 当 API Key 无效
  - _Requirements: NEW (管理员 API 认证)_

- [x] 5.2 (P) 实现 ScraperConfigRouter 管理员 API 及公共只读端点
  - 创建 POST /api/admin/scraping/follows 端点
  - 创建 GET /api/admin/scraping/follows 端点（支持 include_inactive 查询参数）
  - 创建 PUT /api/admin/scraping/follows/{username} 端点
  - 创建 DELETE /api/admin/scraping/follows/{username} 端点
  - 所有管理端点应用管理员认证（`get_current_admin_user`）
  - 实现异常处理和 HTTP 状态码映射（400, 403, 404, 409, 500）
  - [x] 创建 `public_router` (prefix=/api/scraping, tags=["scraping"]) 作为公共只读路由器
  - [x] 创建 GET /api/scraping/follows 端点（使用 `get_current_user` 认证，仅返回活跃账号）
  - _Requirements: NEW (管理员添加抓取账号), 8.1-8.5, 6.1-6.7, 7.3-7.5_

- [x] 5.3 实现 PreferenceRouter 用户偏好 API
  - 创建 POST /api/preferences/follows 端点（添加/恢复关注）
  - 创建 GET /api/preferences/follows 端点
  - 创建 DELETE /api/preferences/follows/{username} 端点
  - 创建 PUT /api/preferences/follows/{username}/priority 端点
  - 创建 POST /api/preferences/filters 端点
  - 创建 GET /api/preferences/filters 端点
  - 创建 DELETE /api/preferences/filters/{rule_id} 端点
  - 创建 PUT /api/preferences/sorting 端点
  - 创建 GET /api/preferences 端点（返回所有偏好配置）
  - 创建 GET /api/preferences/news 端点（个性化新闻流）
  - 实现异常处理和 HTTP 状态码映射（400, 404, 409, 422, 500）
  - 实现账号不在抓取列表时的特定错误响应
  - _Requirements: 1.1-1.5, 2.1-2.5, 3.1-3.6, 5.1-5.5, 6.1-6.7, 7.1-7.5_

- [x] 5.4 集成路由到主应用
  - 在 FastAPI 主应用中注册 PreferenceRouter
  - 在 FastAPI 主应用中注册 ScraperConfigRouter
  - 验证 API 端点可访问
  - _Requirements: 6.1-6.7_

- [x] 6. 环境配置

- [x] 6. 添加环境变量配置
  - 添加 ADMIN_API_KEY 环境变量到 .env.example
  - 更新配置加载逻辑读取新的环境变量
  - _Requirements: NEW (管理员 API 认证)_

- [x] 7. 测试实现

- [x] 7.1 (P) 编写领域模型单元测试
  - 测试 Twitter 用户名格式验证器（有效和无效格式）
  - 测试优先级范围验证器（边界值测试）
  - 测试枚举类型（FilterType、SortType）
  - 测试领域模型序列化/反序列化
  - _Requirements: 1.5, 5.4, 7.1-7.5_

- [x] 7.2 (P) 编写 RelevanceService 单元测试
  - 测试关键词匹配算法正确性
  - 测试相关性分数计算（0.0-1.0 范围）
  - 测试降级处理逻辑
  - _Requirements: 2.2, 2.6_

- [x] 7.3 (P) 编写 Repository 单元测试
  - 测试 PreferenceRepository CRUD 操作
  - 测试 ScraperConfigRepository CRUD 操作
  - 测试唯一约束冲突处理
  - 测试数据库事务回滚
  - _Requirements: 4.1-4.5_

- [x] 7.4 (P) 编写 Service 层集成测试
  - 测试用户关注列表初始化流程
  - 测试添加关注验证（账号必须在抓取列表中）
  - 测试移除关注流程
  - 测试过滤规则 CRUD
  - 测试排序偏好 CRUD
  - 测试个性化新闻流排序（三种排序类型）
  - _Requirements: 1.1-1.4, 2.1-2.6, 3.1-3.6, 4.5, 5.1-5.3_

- [x] 7.5 (P) 编写管理员 API 集成测试
  - 测试管理员 API Key 认证（有效和无效 Key）
  - 测试添加抓取账号端点
  - 测试查询抓取列表端点
  - 测试更新和软删除端点
  - _Requirements: NEW (管理员添加抓取账号), 6.1-6.7, 7.3-7.5_

- [x] 7.6 编写用户偏好 API 集成测试
  - 测试所有 PreferenceRouter 端点
  - 测试各种错误场景（400, 404, 409, 422 响应）
  - 测试账号不在抓取列表的错误响应
  - 测试 GET /api/preferences/news 端点（三种排序类型）
  - _Requirements: 1.1-1.5, 2.1-2.6, 3.1-3.6, 5.1-5.5, 6.1-6.7, 7.1-7.5_

- [x] 7.7 编写公共只读抓取列表端点测试
  - 文件：`tests/preference/test_scraper_config_router.py`
  - 测试认证用户可访问公共端点（200）
  - 测试未认证用户返回 401
  - 测试普通用户无法访问管理员端点（403）
  - 测试仅返回活跃账号
  - _Requirements: 8.1-8.5_

- [x] 8. 验收与集成

- [x] 8. 运行完整测试套件并修复问题
  - 运行所有单元测试
  - 运行所有集成测试
  - 验证测试覆盖率 >= 80%
  - 修复发现的问题
  - 验证所有需求覆盖
  - _Requirements: ALL_
