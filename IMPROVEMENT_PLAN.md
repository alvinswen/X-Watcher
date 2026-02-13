# X-watcher 项目持续改进评估报告

> 最后更新: 2026-02-13
> 项目版本: 0.1.0
> 总体评级: **8.5/10**

## 项目概况

X-watcher 是一个面向 AI Agent 的 X 平台（Twitter）智能信息监控服务，提供推文抓取、内容去重、AI 摘要、偏好管理、Feed API 等核心能力。项目采用六边形架构（Hexagonal Architecture），具备完善的测试体系和文档。

### 核心指标

| 指标 | 数值 |
|------|------|
| Python 源文件 | ~105 个 |
| 测试文件 | 68 个 |
| 测试用例 | 677 个 |
| 核心模块 | 8 个（全部已实现） |
| 规格文档 | 9 套（7 套已完全批准） |
| TODO 项 | 5 个 |
| 架构模式 | 六边形架构 + DDD |

### 已完成的核心模块

| 模块 | 测试覆盖 | API | 说明 |
|------|---------|-----|------|
| 推文抓取 (scraper) | 11+ 测试文件 | 4 端点 | TwitterAPI.io 集成，引用关系处理，动态 limit（EMA） |
| 内容去重 (deduplication) | 5+ 测试文件 | 5 端点 | 基于 scikit-learn 文本相似度检测 |
| AI 摘要 (summarization) | 8+ 测试文件 | 6 端点 | 双 LLM（MiniMax / OpenRouter），智能长度策略 |
| 用户偏好 (preference) | 6+ 测试文件 | 10+ 端点 | 关注管理、过滤规则、相关性排序 |
| Feed API (feed) | 2+ 测试文件 | 1 端点 | 增量拉取，时间范围查询 |
| 用户管理 (user) | 4+ 测试文件 | 6 端点 | JWT + API Key + bcrypt |
| Web 管理界面 (web) | 3+ 测试文件 | — | Vue 3 + Element Plus，4 个页面 |
| 调度管理 (scheduler) | 3+ 测试文件 | 3 端点 | 运行时调整抓取间隔 |

---

## 一、生产化运维

### 1.1 ~~Docker 容器化~~ ✅ 已完成

- 多阶段构建 Dockerfile（Node.js → Python → 精简运行时）
- docker-compose.yml 支持 SQLite（默认）和 PostgreSQL（`--profile prod`）
- docker-entrypoint.sh 自动迁移、种子数据、PostgreSQL 等待
- 非 root 用户运行，内置健康检查

### 1.2 API 速率限制 ❌ 未实现

- **现状**: 所有 API 端点无速率限制，仅靠 JWT/API Key 认证
- **风险**: 单用户可无限制调用，导致资源耗尽或上游 API 配额浪费（TwitterAPI.io、MiniMax）
- **建议**: 引入 `slowapi` 或自定义中间件，按用户/IP 限流
- **涉及文件**: `src/main.py`、`pyproject.toml`
- **优先级**: P0 高
- **工作量**: 1 天

### 1.3 CORS 配置过于宽松 ❌ 未修复

- **现状**: `src/main.py:220` — `allow_origins=["*"]`，配置未外部化
- **风险**: 任何域名均可跨域调用 API
- **建议**: 在 `src/config.py` 添加 `cors_allowed_origins` 配置项，通过环境变量 `CORS_ALLOWED_ORIGINS` 控制
- **优先级**: P0 高
- **工作量**: 0.5 天

### 1.4 数据保留/清理策略 ❌ 缺失

- **现状**: 仅有手动 `scripts/cleanup_summaries.py` 脚本，无自动清理
- **风险**: 数据库无限增长（推文、摘要、任务历史、抓取统计）
- **建议**:
  - 在 APScheduler 中添加定时清理任务
  - 可配置保留策略（推文 30 天、摘要 90 天、任务记录 7 天）
  - 添加 `DATA_RETENTION_DAYS` 等环境变量
- **优先级**: P1 中
- **工作量**: 1-2 天

### 1.5 CI/CD 流水线 ❌ 缺失

- **现状**: 无 GitHub Actions、无 pre-commit hooks
- **风险**: 代码质量依赖人工执行 lint/test
- **建议**:
  - 添加 `.github/workflows/ci.yml`：lint (ruff) + format check (black) + type check (mypy) + test (pytest)
  - 添加 `.pre-commit-config.yaml`
- **优先级**: P1 中
- **工作量**: 1 天

### 1.6 ~~健康检查增强~~ ✅ 已完成

- **实现**: `/health` 端点增加数据库连接检查（`SELECT 1`）和调度器状态检查，返回结构化组件健康信息
- **响应格式**: `{"status": "healthy|degraded", "components": {"database": {...}, "scheduler": {...}}}`
- **兼容性**: 始终返回 HTTP 200，兼容 Docker HEALTHCHECK

---

## 二、代码质量与技术债务

### 2.1 ~~日志库不一致~~ ✅ 已修复

- **操作**: 从 `pyproject.toml` 移除未使用的 `loguru>=0.7.2` 依赖，保持 stdlib `logging` 统一性

### 2.2 空的遗留模块 ⚠️

- **现状**: `src/models/`、`src/services/`、`src/tools/` 均为空的 `__init__.py`
- **建议**: 已迁移到六边形架构下各模块，可安全删除
- **优先级**: P2 低
- **工作量**: 0.5 天

### 2.3 monitoring 模块无测试 ❌

- **现状**: `src/monitoring/` 包含 3 个文件（metrics.py、middleware.py、routes.py），功能已实现但无对应测试
- **内容**:
  - `metrics.py` — Prometheus 指标定义（HTTP 请求计数/延迟、任务状态、连接池）
  - `middleware.py` — PrometheusMiddleware，记录请求计数和延迟
  - `routes.py` — `/metrics` 端点
- **建议**: 补充单元测试（中间件行为、指标收集、路由响应格式）
- **优先级**: P1 中
- **工作量**: 1 天

### 2.4 agent 模块占位代码 ⚠️

- **现状**: `src/agent/` 有 config.py 和 tools.py，包含 3 个 TODO 占位，无实际功能
- **建议**: 在 Nanobot 集成前保持现状；集成时补充实现和测试
- **优先级**: P2 低

### 2.5 依赖版本锁定不足 ⚠️

- **现状**: 所有依赖使用 `>=` 最低版本约束，无 lockfile
- **风险**: 不同时间安装可能获得不同版本
- **建议**: 使用 `pip freeze > requirements.lock` 或迁移到 Poetry/uv 管理依赖
- **优先级**: P1 中
- **工作量**: 0.5 天

### 2.6 安全扫描工具缺失 ❌

- **现状**: 未配置 `bandit`（安全 lint）或 `safety`/`pip-audit`（依赖漏洞扫描）
- **建议**: 添加到开发依赖和 CI 流程中
- **优先级**: P1 中
- **工作量**: 0.5 天

### 2.7 TODO 项目清单

| 位置 | 内容 |
|------|------|
| `src/agent/config.py:8` | 安装 nanobot-ai |
| `src/agent/config.py:72` | 实现 Nanobot 集成 |
| `src/agent/config.py:77` | 实现 Nanobot Agent 创建逻辑 |
| `src/api/routes/tweets.py:278` | 通过查询 deduplication_groups 表获取去重信息 |
| `src/summarization/services/summarization_service.py:1168` | 实现开源模型提供商 |

---

## 三、规格与功能完善

### 3.1 规格批准状态

| 规格 | 阶段 | Requirements | Design | Tasks | 状态 |
|------|------|-------------|--------|-------|------|
| project-init-zh | implemented | ✅ | ✅ | ✅ | 完成 |
| news-scraper-zh | completed | ✅ | ✅ | ✅ | 完成 |
| news-deduplicator-zh | completed | ✅ | ✅ | ✅ | 完成 |
| news-summarizer-zh | completed | ✅ | ✅ | ✅ | 完成 |
| preference-manager-zh | completed | ✅ | ✅ | ✅ | 完成 |
| scheduler-admin-zh | completed | ✅ | ✅ | ✅ | 完成 |
| web-admin-ui-zh | tasks-generated | ✅ | ✅ | ✅ | 完成 |
| **user-manager-zh** | tasks-generated | ✅ | ✅ | **❌ 未批准** | **需审查** |
| **feed-api-zh** | tasks-generated | ✅ | ✅ | **❌ 未批准** | **需审查** |

**行动项**: 审查并批准 user-manager-zh 和 feed-api-zh 的 tasks 阶段，确保规格闭环。

### 3.2 Nanobot Agent 集成 ❌ 未实施

- **现状**: 有详细计划文档 `docs/nanobot-integration-plan.md`，但未实施
- **规划内容**: fetch_feed.py 脚本、SKILL.md 适配层、增量拉取、日记写入
- **优先级**: P2 低
- **工作量**: 3-5 天

### 3.3 Webhook 推送能力 ❌ 未实现

- **现状**: 仅支持 Agent 轮询（Pull 模式）
- **建议**: 实现 Webhook 回调，当有新推文/摘要时主动通知 Agent
- **优先级**: P2 低
- **工作量**: 2-3 天

### 3.4 MCP 协议集成 ❌ 未实现

- **现状**: 产品规划中提及，未实施
- **建议**: 提供 MCP Server 接口，便于 LLM 应用直接调用
- **优先级**: P2 低
- **工作量**: 2-3 天

### 3.5 Web 前端功能缺口

当前前端有 4 个页面：推文列表、推文详情、关注管理、任务监控。

**缺失功能**:
- 无用户登录界面（仅 Settings 面板配置 API Key）
- 无偏好管理界面（过滤规则、排序配置需通过 API）
- 无 Feed 数据浏览界面
- 无摘要管理界面（查看/重新生成摘要）

**优先级**: P2 低
**工作量**: 3-5 天

---

## 四、可观测性与可靠性

### 4.1 日志轮转 ❌

- **现状**: 日志输出到 stdout，无文件轮转配置
- **建议**: 生产环境配置日志文件轮转（按大小/时间），或依赖 Docker 日志驱动
- **优先级**: P2 低

### 4.2 报警机制 ❌

- **现状**: 有 Prometheus 指标采集，无报警规则
- **建议**: 配套 Alertmanager 规则（抓取连续失败、API 错误率过高、数据库连接池耗尽）
- **优先级**: P2 低

### 4.3 数据库备份 ❌

- **现状**: 无备份脚本或策略
- **建议**:
  - SQLite: 定时 `.backup` 命令或文件复制
  - PostgreSQL: `pg_dump` 定时备份到对象存储
- **优先级**: P2 低

---

## 五、安全性评估

### 已做好的部分 ✅

| 方面 | 实现 |
|------|------|
| 密码存储 | bcrypt 12 rounds + SHA-256 预处理 |
| API Key | SHA-256 哈希存储，前缀可追溯 |
| JWT | HS256 签名，可配置过期时间 |
| SQL 注入 | 全部使用 SQLAlchemy ORM，无原始 SQL |
| 敏感配置 | 环境变量管理，`.env` 已 gitignore |
| 常量时间比较 | `hmac.compare_digest` 用于 API Key 验证 |

### 待改进 ⚠️

| 方面 | 现状 | 建议 |
|------|------|------|
| CORS | `allow_origins=["*"]` | 环境变量配置具体域名 |
| 速率限制 | 无 | 引入 slowapi |
| JWT 默认密钥 | `"change-me-in-production"` | 启动时检查是否为默认值并警告 |
| 安全扫描 | 无 | 添加 bandit + pip-audit |

---

## 六、性能优化（低优先级）

### 6.1 缓存层

- **现状**: 无应用级缓存
- **建议**: 对 Feed API 高频查询引入内存缓存或 Redis
- **工作量**: 2-3 天

### 6.2 PostgreSQL 生产验证

- **现状**: 开发使用 SQLite，PostgreSQL 仅在文档和 docker-compose 中配置
- **建议**: 进行 PostgreSQL 实际运行验证，优化连接池和索引
- **工作量**: 1-2 天

---

## 改进优先级总览

| 优先级 | 改进项 | 工作量 | 状态 |
|--------|--------|--------|------|
| **P0** | ~~Docker 容器化~~ | ~~1-2 天~~ | ✅ 已完成 |
| **P0** | API 速率限制 | 1 天 | ❌ 待实施 |
| **P0** | CORS 配置收紧 | 0.5 天 | ❌ 待实施 |
| **P1** | CI/CD 流水线 | 1 天 | ❌ 待实施 |
| **P1** | 数据保留自动清理 | 1-2 天 | ❌ 待实施 |
| **P1** | ~~日志库统一（移除 loguru）~~ | ~~0.5 天~~ | ✅ 已完成 |
| **P1** | monitoring 模块测试 | 1 天 | ❌ 待实施 |
| **P1** | 依赖版本锁定 | 0.5 天 | ❌ 待实施 |
| **P1** | 规格批准闭环 | 0.5 天 | ❌ 待审查 |
| **P1** | ~~健康检查增强~~ | ~~0.5 天~~ | ✅ 已完成 |
| **P1** | 安全扫描工具 | 0.5 天 | ❌ 待实施 |
| **P2** | Nanobot Agent 集成 | 3-5 天 | ❌ 待实施 |
| **P2** | Webhook 推送 | 2-3 天 | ❌ 待实施 |
| **P2** | MCP 协议集成 | 2-3 天 | ❌ 待实施 |
| **P2** | Web 前端功能补全 | 3-5 天 | ❌ 待实施 |
| **P2** | 遗留模块清理 | 0.5 天 | ❌ 待实施 |
| **P2** | 缓存层 / PostgreSQL 优化 | 2-3 天 | ❌ 待实施 |
| **P2** | 生产部署文档 | 1 天 | ❌ 待实施 |

---

## 变更记录

| 日期 | 变更内容 |
|------|---------|
| 2026-02-13 | 初始评估报告 |
| 2026-02-13 | Docker 容器化完成（Dockerfile、docker-compose.yml、docker-entrypoint.sh、.dockerignore、.env.docker.example） |
| 2026-02-13 | 日志库统一：移除未使用的 loguru 依赖，保持 stdlib logging |
| 2026-02-13 | 健康检查增强：`/health` 端点增加数据库连接和调度器状态检查 |
| 2026-02-14 | 测试性能优化：631s → 145s（-77%），详见 `docs/test-performance-optimization.md` |
