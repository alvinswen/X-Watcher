# 研究与设计决策日志

---
**目的**: 记录发现阶段的调研结果和影响技术设计的架构决策。
---

## 摘要
- **特性**: `scheduler-admin-zh`
- **发现范围**: Extension（扩展现有系统）
- **关键发现**:
  - APScheduler 提供线程安全的 `reschedule_job()` 和 `modify_job()` API，可从 async 上下文直接调用
  - 现有 preference 模块的六边形架构模式完整（API → Service → Domain → Repository），可直接复用
  - `_scheduler` 是 `main.py` 的模块级私有变量，需通过 accessor 模块暴露给 Service 层

## 研究日志

### APScheduler 运行时 Job 修改 API

- **背景**: 需要验证 APScheduler 3.x 是否支持运行时修改 interval trigger 的 job
- **来源**: APScheduler 3.10 官方文档、源码
- **发现**:
  - `scheduler.reschedule_job(job_id, trigger, **trigger_args)` — 替换 job 的 trigger，支持 interval trigger
  - `scheduler.modify_job(job_id, **changes)` — 修改 job 属性，包括 `next_run_time`
  - `scheduler.get_job(job_id)` — 获取 job 对象，可读取 `next_run_time` 属性
  - 所有操作均为线程安全（内部使用锁），从 async 函数直接调用不会阻塞事件循环（操作为内存操作，无 I/O）
- **影响**: 无需 `asyncio.to_thread()` 包装，Service 层可直接调用 APScheduler 同步 API

### 调度器引用访问模式

- **背景**: `_scheduler` 是 `main.py` 的私有变量，Service 层无法直接 import（会导致循环依赖）
- **来源**: 项目现有代码分析
- **发现**:
  - 项目已有类似的"模块级引用注册"模式（如 `TaskRegistry.get_instance()` 单例）
  - 创建独立的 `scheduler_accessor.py` 模块可避免循环依赖
  - `main.py` 在 lifespan 中调用 `register_scheduler()`，Service 通过 `get_scheduler()` 获取
- **影响**: 新建一个轻量级模块，符合项目现有的模块化设计原则

### Singleton DB 表模式

- **背景**: 调度配置是全局唯一的，需要决定 DB 存储模式
- **来源**: 项目现有模型分析
- **发现**:
  - 项目中没有现有的 singleton 表模式，但 SQLAlchemy 支持 `id=1` 固定主键的 upsert 操作
  - SQLite 支持 `INSERT OR REPLACE`，但为保持 DB 无关性，使用先查询再创建/更新的标准模式
  - Alembic 迁移可以包含 `server_default` 为默认值
- **影响**: Repository 使用"查询 → 创建或更新"模式，保持与项目现有 CRUD 模式一致

## 架构模式评估

| 方案 | 描述 | 优势 | 风险/限制 | 备注 |
|------|------|------|-----------|------|
| 扩展 preference 模块 | 在现有 preference 模块中新建 Repository/Service，扩展 Router/Schema | 复用现有六边形架构模式，最小化新代码 | 无显著风险 | **推荐** |
| 新建独立模块 | 创建 `src/scheduler/` 独立模块 | 完全隔离 | 过度设计，重复基础设施代码 | 不推荐 |
| 直接在 admin.py 中实现 | 在现有 `src/api/routes/admin.py` 中添加端点 | 最快实现 | 违反六边形架构，无 Service/Repository 层 | 不推荐 |

## 设计决策

### 决策: 调度器访问采用 Accessor 模块模式

- **背景**: Service 层需要访问 `main.py` 中的 APScheduler 实例
- **候选方案**:
  1. 在 `main.py` 中暴露 `get_scheduler()` 函数 — 可能导致循环依赖
  2. 新建 `src/scheduler_accessor.py` 独立模块 — 干净解耦
  3. 通过 FastAPI app.state 传递 — 需要在 API 层获取再传入 Service
- **选定方案**: 方案 2（独立 accessor 模块）
- **理由**: 无循环依赖风险，符合项目模块化原则，与 `TaskRegistry.get_instance()` 模式一致
- **权衡**: 多一个文件 vs 干净的依赖关系
- **后续**: 需在 `main.py` lifespan 中集成 register/unregister 调用

### 决策: 调度配置存储采用 Singleton DB 表

- **背景**: 调度配置是全局唯一的，需要持久化
- **候选方案**:
  1. Key-Value 表 — 灵活但类型不安全
  2. Singleton 表（id=1）— 类型安全，结构化
  3. 扩展环境变量 + 文件 — 不适合运行时修改
- **选定方案**: 方案 2（Singleton 表）
- **理由**: 类型安全，与项目现有 ORM 模式一致，查询简单
- **权衡**: 略显"过度设计"（只存一行），但结构清晰且迁移方便

## 风险与缓解

- **风险 1**: APScheduler job 不存在时调用 `reschedule_job()` 会抛异常 → **缓解**: Service 层先调用 `get_job()` 检查，异常时返回明确错误信息
- **风险 2**: 应用启动时 DB 还未初始化完成就尝试读取调度配置 → **缓解**: 使用 try/except 降级到环境变量默认值（与现有 `_get_active_follows_from_db()` 模式一致）
- **风险 3**: 并发修改调度配置（多个管理员同时操作）→ **缓解**: APScheduler 内部锁保证线程安全；DB 层面使用 flush + commit 保证一致性

## 参考

- APScheduler 3.x 文档: `BackgroundScheduler.reschedule_job()`, `modify_job()`, `get_job()`
- 项目参考文件:
  - `src/preference/infrastructure/scraper_config_repository.py` — Repository 模式
  - `src/preference/services/scraper_config_service.py` — Service 模式
  - `src/preference/api/scraper_config_router.py` — API 端点模式
  - `tests/preference/test_admin_api.py` — 测试模式
