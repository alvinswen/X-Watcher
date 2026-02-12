# 需求文档

## 项目概述

X-watcher 是一个面向科技公司高管的智能新闻助理系统。本项目初始化规格旨在建立项目的基础架构，包括目录结构、依赖配置、开发环境和核心组件骨架，为后续功能开发提供坚实基础。

## 需求

### Requirement 1: 项目目录结构
**目标**：作为开发者，我需要清晰的项目目录结构，以便代码组织和维护。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建完整的目录结构
2. **The** `src/` 目录 **shall** 包含以下子目录：
   - `api/routes/` - API 路由
   - `agent/` - Nanobot Agent 配置
   - `tools/` - 工具函数
   - `models/` - 数据模型
   - `database/` - 数据库操作
   - `services/` - 业务服务
3. **The** `tests/` 目录 **shall** 包含 `unit/` 和 `integration/` 子目录
4. **The** `docs/` 目录 **shall** 用于存放项目文档
5. **The** `scripts/` 目录 **shall** 用于存放脚本文件

### Requirement 2: 依赖管理配置
**目标**：作为开发者，我需要明确的依赖声明，以便环境复现和部署。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `pyproject.toml` 文件
2. **The** `pyproject.toml` **shall** 声明以下核心依赖：
   - `nanobot-ai` - Agent 框架
   - `fastapi` - Web 框架
   - `uvicorn` - ASGI 服务器
   - `pydantic` - 数据验证
   - `sqlalchemy` - ORM
   - `httpx` - 异步 HTTP 客户端
   - `apscheduler` - 任务调度
3. **The** `pyproject.toml` **shall** 声明以下开发依赖：
   - `pytest` - 测试框架
   - `pytest-asyncio` - 异步测试支持
   - `black` - 代码格式化
   - `ruff` - Lint 工具
4. **The** 项目 **shall** 支持通过 `pip install -e .` 安装

### Requirement 3: FastAPI 应用骨架
**目标**：作为开发者，我需要可运行的 FastAPI 应用骨架，以便快速启动开发。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `src/main.py` 入口文件
2. **The** FastAPI 应用 **shall** 配置以下中间件：
   - CORS 中间件
   - 异常处理中间件
3. **When** 运行 `uvicorn src.main:app --reload`，**the** 应用 **shall** 成功启动
4. **The** 应用 **shall** 提供 `/health` 健康检查端点
5. **The** 应用 **shall** 自动生成 API 文档（Swagger UI）

### Requirement 4: 环境配置管理
**目标**：作为开发者，我需要安全的环境变量配置，以便管理敏感信息。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `.env.example` 模板文件
2. **The** `.env.example` **shall** 包含以下环境变量：
   - `MINIMAX_API_KEY` - MiniMax API 密钥
   - `MINIMAX_BASE_URL` - MiniMax API 地址
   - `TWITTER_API_KEY` - X 平台 API 密钥
   - `DATABASE_URL` - 数据库连接地址
3. **The** 项目 **shall** 使用 `python-dotenv` 加载环境变量
4. **The** `.gitignore` **shall** 排除 `.env` 文件
5. **If** 环境变量缺失，**the** 应用启动时 **shall** 报错并提示

### Requirement 5: 数据库初始化
**目标**：作为开发者，我需要数据库架构和迁移支持，以便数据持久化。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `src/database/models.py` 模型文件
2. **The** 模型文件 **shall** 定义基础表结构（用户、偏好、新闻）
3. **The** 项目 **shall** 使用 SQLAlchemy ORM
4. **When** 应用首次启动，**the** 系统 **shall** 自动创建数据库表
5. **The** 项目 **shall** 配置 Alembic 用于数据库迁移

### Requirement 6: Nanobot Agent 配置
**目标**：作为开发者，我需要 Nanobot Agent 基础配置，以便集成 AI 能力。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `src/agent/config.py` 配置文件
2. **The** 配置文件 **shall** 定义 Agent 系统提示
3. **The** 配置文件 **shall** 注册工具函数接口
4. **The** Agent **shall** 配置 MiniMax M2.1 作为 LLM 后端
5. **The** Agent **shall** 支持函数调用（Function Calling）

### Requirement 7: 测试框架配置
**目标**：作为开发者，我需要测试框架配置，以便进行 TDD 开发。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `tests/conftest.py` 配置文件
2. **The** `conftest.py` **shall** 配置测试数据库（SQLite 内存模式）
3. **The** `conftest.py` **shall** 提供测试 Fixtures（如应用实例、数据库会话）
4. **When** 运行 `pytest`，**the** 测试 **shall** 成功执行
5. **The** 项目 **shall** 配置测试覆盖率报告

### Requirement 8: 日志和错误处理
**目标**：作为开发者，我需要统一的日志和错误处理机制，以便调试和监控。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 配置 Loguru 日志库
2. **The** 日志 **shall** 输出到控制台和文件
3. **The** 日志级别 **shall** 可通过环境变量配置
4. **The** 应用 **shall** 定义统一异常类
5. **When** 发生未捕获异常，**the** 系统 **shall** 记录错误日志并返回友好错误响应

### Requirement 9: Git 配置
**目标**：作为开发者，我需要 Git 版本控制配置，以便团队协作。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `.gitignore` 文件
2. **The** `.gitignore` **shall** 排除以下内容：
   - `__pycache__/` - Python 缓存
   - `.env` - 环境变量
   - `*.db` - 数据库文件
   - `.pytest_cache/` - 测试缓存
   - `.coverage` - 覆盖率报告
3. **The** `.gitignore` **shall** 排除 IDE 配置目录
4. **The** 项目 **shall** 初始化 Git 仓库（如不存在）

### Requirement 10: 文档和 README
**目标**：作为开发者，我需要项目文档，以便了解和使用项目。

#### 验收标准

1. **When** 项目初始化完成，**X-watcher** **shall** 创建 `README.md` 文件
2. **The** `README.md` **shall** 包含以下内容：
   - 项目简介
   - 技术栈说明
   - 安装步骤
   - 运行方法
   - 环境变量配置
3. **The** 项目 **shall** 创建 `docs/` 目录用于存放详细文档
4. **The** `docs/` 目录 **shall** 包含 `architecture.md` 架构说明
5. **The** API 文档 **shall** 通过 FastAPI 自动生成

---

_本需求文档遵循 EARS 格式，所有验收标准均可测试和验证_
