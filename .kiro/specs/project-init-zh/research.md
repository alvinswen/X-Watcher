# Research & Design Decisions

## Summary
- **Feature**: project-init
- **Discovery Scope**: New Feature（项目基础架构初始化）
- **Key Findings**:
  - Python 3.11+ 类型注解完全支持，可强制类型检查
  - FastAPI 0.100+ 版本变更需注意（Pydantic v2 迁移）
  - Nanobot 使用 MCP 协议，需要明确工具函数注册方式
  - SQLAlchemy 2.0 采用新式语法（async/await）
  - Ruff 替代 Flake8+isort，性能显著提升

## Research Log

### Python 版本选择
- **Context**: 项目需要确定最低 Python 版本
- **Sources Consulted**: [Python Release Schedule](https://devguide.python.org/versions/), PEP 604
- **Findings**:
  - Python 3.11 性能提升 10-60%
  - 完全支持 `|` 联合类型语法（PEP 604）
  - 3.12 引入 `type` 语句（可选）
- **Implications**: 选择 3.11+ 作为基线，可获得性能和类型系统优势

### FastAPI 和 Pydantic 版本兼容性
- **Context**: FastAPI 0.100+ 迁移到 Pydantic v2，需要确认兼容性
- **Sources Consulted**: [FastAPI Migration Guide](https://fastapi.tiangolo.com/release-notes/#01000), [Pydantic v2 Docs](https://docs.pydantic.dev/latest/migration/)
- **Findings**:
  - Pydantic v2 有破坏性变更（`BaseModel.parse_obj` 已移除）
  - FastAPI 0.100+ 完全兼容 Pydantic v2
  - 推荐使用 `model_validate()` 替代 `parse_obj()`
- **Implications**: 指定 FastAPI >= 0.104, Pydantic >= 2.0

### Nanobot Agent 集成
- **Context**: Nanobot 使用 MCP 协议，需要了解工具函数注册方式
- **Sources Consulted**: [HKUDS/nanobot README](https://github.com/HKUDS/nanobot), [MCP Protocol](https://modelcontextprotocol.io/)
- **Findings**:
  - Nanobot 支持通过 MCP 服务器注册工具
  - 工具函数需要 JSON Schema 描述参数
  - MiniMax 兼容 OpenAI 格式，可直接使用
- **Implications**: 在 `src/agent/config.py` 中定义工具注册逻辑

### SQLAlchemy 2.0 变更
- **Context**: SQLAlchemy 2.0 引入新的查询语法
- **Sources Consulted**: [SQLAlchemy 2.0 Migration](https://docs.sqlalchemy.org/en/20/changelog/migration_20.html)
- **Findings**:
  - `Session.query()` 已弃用，改用 `select()`
  - 异步支持成为一等公民
  - 类型注解支持增强
- **Implications**: 使用新式语法，指定 SQLAlchemy >= 2.0

### MiniMax API 配置
- **Context**: 用户确认 MiniMax BASE_URL 为 `api.minimaxi.com`
- **Sources**: 用户实际使用配置
- **Findings**:
  - 正确地址：`https://api.minimaxi.com`
  - 兼容 OpenAI SDK 格式
  - 需要配置 `api_key` 和 `base_url`
- **Implications**: 在 `.env.example` 中使用正确 URL

### 测试工具选择
- **Context**: 需要选择测试框架和覆盖率工具
- **Sources Consulted**: [pytest docs](https://docs.pytest.org/), [Ruff vs Ruff](https://docs.astral.sh/ruff/)
- **Findings**:
  - pytest 仍是 Python 测试事实标准
  - pytest-asyncio 支持异步测试
  - Ruff 可替代 Flake8 + isort + Black（部分）
  - 保留 Black 用于代码格式化（更成熟）
- **Implications**: 使用 pytest + pytest-asyncio + pytest-cov，Ruff 用于 lint

### 日志库选择
- **Context**: 需要统一日志方案
- **Sources Consulted**: [Loguru Docs](https://loguru.readthedocs.io/)
- **Findings**:
  - Loguru 比标准 logging 更简洁
  - 内置日志轮转和格式化
  - 异常捕获更友好
- **Implications**: 使用 Loguru 替代标准 logging

## Architecture Pattern Evaluation

| 选项 | 描述 | 优势 | 风险 | 备注 |
|------|------|------|------|------|
| 分层架构 | API → Agent → Tools → Data | 清晰边界，易于理解 | 层次过多可能影响性能 | 已在 steering 中确定 |
| 六边形架构 | 端口-适配器模式 | 高度解耦，可测试 | 过度设计，增加复杂度 | 不适用于初期 |
| 单体模块 | 所有代码放一起 | 简单直接 | 难以扩展和测试 | 不推荐 |

## Design Decisions

### 决策：使用 Ruff 替代 Flake8 + isort
- **Context**: 需要快速 lint 工具
- **备选方案**:
  1. Flake8 + isort —— 传统方案，成熟但慢
  2. Ruff —— Rust 实现，快 10-100 倍
- **选择方案**: Ruff
- **理由**: 性能显著提升，功能覆盖全面，配置更简单
- **权衡**: 生态较新，但已广泛采用
- **后续**: 保留 Black 用于格式化（Ruff 格式化仍不如 Black 成熟）

### 决策：Pydantic v2 专用语法
- **Context**: FastAPI + Pydantic v2 迁移
- **备选方案**:
  1. 使用 Pydantic v1 兼容模式
  2. 直接使用 v2 语法
- **选择方案**: Pydantic v2 原生语法
- **理由**: v1 兼容模式未来会被移除
- **权衡**: 需要学习新语法，但长期更优
- **后续**: 在 `models/schemas.py` 中使用 `model_validate()`

### 决策：SQLite 开发，PostgreSQL 生产
- **Context**: 数据库选择
- **备选方案**:
  1. 全部使用 PostgreSQL
  2. 开发用 SQLite，生产用 PostgreSQL
- **选择方案**: SQLite → PostgreSQL 渐进路径
- **理由**: 本地开发无需额外服务，生产可横向扩展
- **权衡**: 需要注意方言差异（如 JSON 类型）
- **后续**: 使用 SQLAlchemy 抽象差异

### 决策：环境变量优先于配置文件
- **Context**: 敏感信息管理
- **备选方案**:
  1. config.yaml + .env
  2. 仅 .env
- **选择方案**: .env + python-dotenv
- **理由**: 12-factor app 原则，简单且安全
- **权衡**: 缺少分层配置能力
- **后续**: 将模板写入 `.env.example`

## Risks & Mitigations
- **Nanobot 文档不足** —— 先实现基础工具注册，后续按需扩展
- **MiniMax API 变更** —— 使用兼容 OpenAI 的 SDK，降低耦合
- **Pydantic v2 迁移** —— 指定明确的最低版本要求
- **测试覆盖不足** —— 配置 pytest-cov 强制覆盖率检查

## References
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 文档](https://docs.sqlalchemy.org/en/20/)
- [Pydantic v2 迁移指南](https://docs.pydantic.dev/latest/migration/)
- [HKUDS/nanobot GitHub](https://github.com/HKUDS/nanobot)
- [Ruff 文档](https://docs.astral.sh/ruff/)
- [MiniMax 开放平台](https://www.minimaxi.com/)
