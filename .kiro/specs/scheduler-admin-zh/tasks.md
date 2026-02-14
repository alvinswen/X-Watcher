# 实现计划

- [x] 1. 调度器访问模块
- [x] 1.1 (P) 创建调度器引用管理模块
  - 实现全局引用的注册、获取、注销三个函数
  - 注册函数接收 BackgroundScheduler 实例并存储为模块级变量
  - 获取函数返回已注册的调度器实例，未注册时返回 None
  - 注销函数清除引用，确保获取函数后续返回 None
  - 编写单元测试覆盖完整生命周期：注册→获取→注销→再获取返回 None
  - 测试未注册状态下获取返回 None
  - _Requirements: 2.1, 3.1_

- [x] 2. 数据模型层
- [x] 2.1 (P) 添加调度配置 ORM 模型
  - 在现有数据库模型文件中新增调度配置表映射
  - 表名 `scraper_schedule_config`，singleton 模式（id=1 固定主键）
  - 字段：interval_seconds（整型，默认 43200）、next_run_time（可空日期时间）、updated_at（日期时间）、updated_by（字符串）
  - 无外键、无索引（单行表）
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 2.2 (P) 添加调度配置领域模型
  - 在现有领域模型文件中新增调度配置的 Pydantic 领域模型
  - 包含 from_orm 类方法将 ORM 对象转换为领域模型
  - 字段与 ORM 模型对应：id、interval_seconds、next_run_time、updated_at、updated_by
  - _Requirements: 4.4_

- [x] 2.3 创建数据库迁移
  - 使用 Alembic 生成迁移脚本创建 `scraper_schedule_config` 表
  - upgrade：创建表，interval_seconds 设 server_default='43200'
  - downgrade：删除表
  - 纯增量操作，不影响现有表
  - 依赖 2.1 完成后才能自动生成迁移
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 3. Repository 层
- [x] 3.1 实现调度配置 Repository
  - 创建独立的调度配置 Repository 类，接收 AsyncSession
  - 实现获取配置方法：查询 id=1 的记录，返回领域模型或 None
  - 实现 upsert 配置方法：先查询 id=1，存在则更新指定字段，不存在则创建新记录
  - upsert 支持按需更新 interval_seconds 和/或 next_run_time，每次更新 updated_at 和 updated_by
  - 使用 flush 而非 commit，由调用方控制事务
  - 参考现有 ScraperConfigRepository 的错误处理模式
  - 编写单元测试：空表查询返回 None、创建新配置、更新已有配置、仅更新部分字段
  - 依赖 2.1、2.2 完成
  - _Requirements: 2.1, 3.1, 4.1, 4.2, 4.3, 4.4_

- [x] 4. API Schema 层
- [x] 4.1 (P) 添加调度配置请求和响应 Schema
  - 在现有 schemas 文件中新增三个 Pydantic 模型
  - 更新间隔请求模型：interval_seconds 字段，范围约束 300-604800
  - 更新下次触发时间请求模型：next_run_time 日期时间字段
  - 配置响应模型：interval_seconds、next_run_time、scheduler_running、updated_at、updated_by、message 字段
  - 利用 Pydantic Field 的 ge/le 约束自动生成 422 验证错误
  - _Requirements: 2.2, 2.3, 3.2_
  - _Contracts: UpdateScheduleIntervalRequest, UpdateScheduleNextRunRequest, ScheduleConfigResponse_

- [x] 5. Service 层
- [x] 5.1 实现调度配置 Service
  - 创建独立的调度配置 Service 类，接收 Repository 依赖
  - 实现查看配置方法：合并 DB 配置 + 调度器运行状态 + 环境变量默认值
  - 无 DB 配置时使用环境变量默认间隔值，通过调度器获取下次触发时间
  - 实现更新间隔方法：持久化到 DB，然后通过调度器访问模块调用 reschedule_job 更新运行中的任务
  - 实现更新下次触发时间方法：验证时间有效性（未来时间 -30s 容差，不超 30 天），持久化后通过 modify_job 更新调度器
  - 调度器未运行时仍正常持久化配置，在响应中标注 scheduler_running=false 并附加提示信息
  - 编写单元测试（mock Repository 和 scheduler_accessor）：
    - 有/无 DB 配置时查看配置
    - 调度器运行/未运行时查看配置
    - 正常更新间隔 + 调度器同步
    - 调度器未运行时更新间隔仍持久化
    - 正常设置下次触发时间
    - 过去时间验证拒绝
    - 超 30 天验证拒绝
    - 调度器未运行时设置触发时间仍持久化
  - 依赖 1.1、3.1、4.1 完成
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_
  - _Contracts: ScraperScheduleService API_

- [x] 6. API 端点层
- [x] 6.1 扩展管理员路由添加调度配置端点
  - 在现有 scraper_config_router 中新增三个管理员端点
  - GET /schedule：查看当前配置，复用 get_current_admin_user 认证
  - PUT /schedule/interval：更新间隔，接收 UpdateScheduleIntervalRequest body
  - PUT /schedule/next-run：设置下次触发时间，接收 UpdateScheduleNextRunRequest body
  - 创建 Service 依赖注入函数（参考现有 _get_scraper_config_service 模式）
  - 端点从认证用户提取 admin 名称传给 Service
  - 编写集成测试（参考 test_admin_api.py 模式）：
    - GET /schedule 返回默认配置
    - PUT /schedule/interval 正常更新
    - PUT /schedule/interval 无效值 422
    - PUT /schedule/next-run 正常更新
    - PUT /schedule/next-run 过去时间 422
    - PUT /schedule/next-run 超 30 天 422
    - 未认证请求 401
    - 非管理员请求 403
  - 依赖 5.1 完成
  - _Requirements: 1.4, 2.3, 2.5, 2.6, 3.3, 3.4, 3.7, 5.1, 5.2, 5.3_
  - _Contracts: scraper_config_router API_

- [x] 7. 应用生命周期集成
- [x] 7.1 集成调度器访问模块到应用启动/关闭流程
  - 修改 main.py lifespan 函数，在创建调度器后调用 register_scheduler 注册引用
  - 在 shutdown 阶段调用 unregister_scheduler 注销引用
  - 添加启动时从 DB 加载调度配置的逻辑（复用 _get_active_follows_from_db 的同步→异步桥接模式）
  - DB 有配置时：使用 DB 间隔值初始化 job，使用 DB 的 next_run_time 作为首次执行时间
  - DB 无配置时：保持现有行为（使用环境变量间隔 + 立即执行）
  - DB 读取失败时降级到环境变量默认值（try/except 保护）
  - 依赖 1.1、2.3 完成
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 8. 全量回归验证
- [x] 8.1 运行全量测试确保无破坏
  - 执行 pytest 全量测试套件
  - 确认所有新测试通过
  - 确认所有现有测试未被破坏
  - 验证 Alembic 迁移可正常 upgrade/downgrade
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3_

- [x] 9. 惰性调度启动改造
- [x] 9.1 提取定时任务函数到独立模块
  - 创建 `src/scraper/scheduled_job.py`，从 `main.py` 提取 `scheduled_scrape_job()` 和 `get_active_follows_from_db()`
  - 解决 `main.py` 与 `schedule_service.py` 之间的循环导入问题
  - 更新 `tests/scraper/test_integration.py` 的导入路径和 mock 路径
  - _Requirements: 6.1_

- [x] 9.2 新增 `is_enabled` 字段
  - ORM 模型 `src/database/models.py` 新增 `is_enabled: Mapped[bool]` 列
  - 领域模型 `src/preference/domain/models.py` 新增 `is_enabled: bool` 字段
  - Repository `upsert_schedule_config()` 新增 `is_enabled: bool | None = None` 参数
  - API Schema `ScheduleConfigResponse` 新增 `job_active` 和 `is_enabled` 字段
  - `main.py` lifespan 中执行 `ALTER TABLE` 幂等迁移
  - _Requirements: 4.1, 4.2, 4.3, 6.1, 6.2_

- [x] 9.3 Service 层惰性 job 管理
  - 新增 `_ensure_job_exists()` 辅助方法：检查 job 是否存在，不存在则创建
  - 新增 `_remove_job_if_exists()` 辅助方法：移除 job（如存在）
  - 修改 `update_interval()`: 设 `is_enabled=True`，job 不存在时创建
  - 修改 `update_next_run_time()`: 设 `is_enabled=True`，job 不存在时创建
  - 新增 `enable_schedule()`: DB 有配置时启用，无配置返回 422
  - 新增 `disable_schedule()`: 暂停调度，移除 job，保留配置
  - _Requirements: 2.1, 3.1, 6.1, 6.2, 6.3_

- [x] 9.4 API 端点新增启用/暂停
  - `POST /api/admin/scraping/schedule/enable` — 启用调度
  - `POST /api/admin/scraping/schedule/disable` — 暂停调度
  - 复用 `get_current_admin_user` 认证
  - _Requirements: 6.1, 6.2, 6.4_

- [x] 9.5 Lifespan 惰性启动改造
  - 始终创建并启动 scheduler + register，但仅在 DB 有 `is_enabled=True` 时 `add_job`
  - `_get_schedule_config_from_db()` 返回 3-tuple `(interval, next_run, is_enabled)`
  - 删除 `main.py` 中旧的 `_scheduled_scrape_job` 和 `_get_active_follows_from_db` 定义
  - Health check 新增 `scraper_job_active` 字段
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 9.6 测试更新与全量回归
  - `test_schedule_service.py`: 新增 enable/disable/job 创建测试（共 39 个调度相关测试通过）
  - `test_schedule_api.py`: 新增 enable/disable 端点测试和认证测试
  - `test_schedule_repository.py`: 新增 `is_enabled` 字段测试
  - `test_integration.py`: 修复导入路径（从 `src.main` → `src.scraper.scheduled_job`）
  - 全量回归：587 passed, 2 skipped, 0 failed
  - _Requirements: 所有_
