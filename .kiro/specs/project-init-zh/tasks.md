# Implementation Plan

## Task Summary

本计划将项目初始化工作分解为可执行的任务，涵盖目录结构、依赖配置、应用骨架、数据库、Agent 配置、测试框架和文档。

## Tasks

- [x] 1. 创建项目目录结构
  - 创建完整的源代码、测试、文档和脚本目录
  - 为每个目录添加 `__init__.py` 保持 Python 包结构
  - _Requirements: 1_

- [x] 2. 配置项目依赖和元数据
  - 创建 `pyproject.toml` 声明核心依赖（FastAPI, Nanobot, SQLAlchemy 等）
  - 声明开发依赖（pytest, Ruff, Black 等）
  - 配置 Python 最低版本要求（>=3.11）
  - 配置 Ruff 和 Black 的格式化规则
  - _Requirements: 2_

- [x] 3. 创建环境配置系统
  - 创建 `.env.example` 模板文件，包含所有必需环境变量
  - 实现 `config.py` 配置加载模块，使用 Pydantic 验证环境变量
  - 配置 MiniMax API 连接参数
  - 配置数据库连接字符串
  - 实现启动时环境变量验证，缺失时明确报错
  - _Requirements: 4_

- [x] 4. 实现数据模型和数据库层
  - 创建 SQLAlchemy 模型文件，定义用户、偏好、新闻表
  - 使用 SQLAlchemy 2.0 新式语法（async/await 支持）
  - 实现数据库初始化逻辑，首次启动时自动建表
  - 配置 Alembic 用于数据库迁移
  - _Requirements: 5_

- [x] 5. 构建FastAPI应用骨架
  - 创建 `main.py` 应用入口，初始化 FastAPI 实例
  - 配置 CORS 中间件允许跨域请求
  - 配置全局异常处理中间件
  - 实现 `/health` 健康检查端点
  - 集成 Loguru 日志系统
  - _Requirements: 3, 8_

- [x] 6. 配置Nanobot Agent
  - 创建 Agent 配置模块，定义系统提示
  - 实现工具函数注册接口
  - 配置 MiniMax M2.1 作为 LLM 后端
  - 实现 Agent 初始化逻辑
  - _Requirements: 6_

- [x] 7. 配置测试框架
  - 创建 `conftest.py` 配置 pytest
  - 配置测试数据库（SQLite 内存模式）
  - 提供应用实例 Fixture
  - 提供数据库会话 Fixture
  - 配置 pytest-cov 覆盖率报告
  - _Requirements: 7_

- [x] 8. 设置代码质量工具
  - 配置 Ruff lint 规则
  - 配置 Black 代码格式化
  - 创建 `.gitignore` 排除缓存、环境变量、数据库文件
  - 初始化 Git 仓库（如不存在）
  - _Requirements: 8, 9_

- [x] 9. 编写项目文档
  - 创建 `README.md` 包含项目简介、技术栈、安装步骤
  - 创建 `docs/architecture.md` 架构说明文档
  - 验证 API 文档通过 FastAPI 自动生成
  - _Requirements: 10_

- [x] 10. 验证应用启动和健康检查
  - 运行应用启动命令验证无错误
  - 访问 `/health` 端点确认返回健康状态
  - 验证 Swagger UI 文档可访问
  - 确认日志输出正常
  - _Requirements: 3, 8_

## Requirements Coverage

| Requirement ID | Covered By Tasks |
|----------------|------------------|
| 1 | 1 |
| 2 | 2 |
| 3 | 5, 10 |
| 4 | 3 |
| 5 | 4 |
| 6 | 6 |
| 7 | 7 |
| 8 | 5, 8, 10 |
| 9 | 8 |
| 10 | 9 |

**All 10 requirements covered.**
