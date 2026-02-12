# 研究日志

## 概述

本文档记录 Preference Manager 模块的设计发现和研究过程。

### 发现范围
- **类型**: Extension (扩展现有系统)
- **发现级别**: Light - 聚焦于集成点和现有模式分析
- **关键决策点**: 数据模型设计、相关性服务抽象

### 关键发现摘要
1. 现有 `Preference` 模型过于简单（key-value 存储），需要扩展支持结构化偏好
2. 需要新增 `TwitterFollow` 和 `FilterRule` 表来存储关注列表和过滤规则
3. 相关性计算应设计为独立服务接口，便于未来替换算法
4. API 设计遵循现有模块模式（如 summarization）

---

## 研究日志

### 主题 1: 数据库模型设计

**问题**: 现有 `Preference` 模型使用 key-value 存储，是否足够支持结构化偏好？

**调查**:
- 分析 `src/database/models.py` 中的 `Preference` 模型
- 分析 `src/scraper/infrastructure/models.py` 和 `src/summarization/infrastructure/models.py` 的表设计模式

**结论**:
- 现有 `Preference` 模型适用于简单配置（如排序类型）
- 需要新增专用表来存储复杂结构：
  - `twitter_follows`: 存储关注的 Twitter 用户名和优先级
  - `filter_rules`: 存储关键词、话题标签和内容类型过滤规则

**影响**:
- 数据库迁移脚本需要创建新表
- 现有 `Preference` 表保留用于简单配置（排序类型）

---

### 主题 2: 相关性服务接口设计

**问题**: 如何设计相关性计算接口，以便未来从关键词匹配切换到嵌入模型？

**调查**:
- 分析需求文档中的"相关性"定义（基于关键词匹配）
- 研究抽象接口设计模式（Strategy Pattern）

**结论**:
- 定义 `RelevanceService` 抽象接口
- MVP 实现：`KeywordRelevanceService`（关键词匹配算法）
- 未来实现：`EmbeddingRelevanceService`（向量相似度）

**接口设计**:
```python
class RelevanceService(ABC):
    @abstractmethod
    async def calculate_relevance(
        self, tweet: Tweet, keywords: list[str]
    ) -> float:
        """计算推文与关键词的相关性分数 (0.0-1.0)"""
```

**影响**:
- 模块可以独立演进相关性算法
- 单元测试可以 mock 此接口

---

### 主题 3: API 路由设计模式

**问题**: 如何与现有 API 模式保持一致？

**调查**:
- 分析 `src/summarization/api/routes.py` 的路由设计
- 分析 `src/summarization/api/schemas.py` 的 Pydantic 模型设计

**结论**:
- 使用 FastAPI 的 `APIRouter` 模块
- 路由前缀：`/api/preferences`
- 使用 Pydantic 模型进行请求/响应验证
- 遵循 RESTful 约定（POST/GET/PUT/DELETE）

**端点设计**:
| 方法 | 端点 | 功能 |
|------|------|------|
| POST | `/api/preferences/follows` | 添加关注 |
| GET | `/api/preferences/follows` | 查询关注列表 |
| DELETE | `/api/preferences/follows/{username}` | 移除关注 |
| PUT | `/api/preferences/follows/{username}/priority` | 设置优先级 |
| PUT | `/api/preferences/sorting` | 更新排序偏好 |
| GET | `/api/preferences` | 查询所有偏好 |
| POST | `/api/preferences/filters` | 添加过滤规则 |
| GET | `/api/preferences/filters` | 查询过滤规则 |
| DELETE | `/api/preferences/filters/{rule_id}` | 移除过滤规则 |

**影响**:
- 与现有模块保持一致的 API 风格
- 便于未来集成到前端和 Agent 工具

---

### 主题 4: Twitter 用户名验证规则

**问题**: Twitter 用户名的有效格式是什么？

**调查**:
- Twitter 官方文档：用户名必须为 1-15 字符
- 仅允许字母数字和下划线
- 不能以数字开头（可选限制）

**结论**:
- 使用正则表达式验证：`^[a-zA-Z0-9_]{1,15}$`
- 在 Pydantic 模型中添加自定义验证器

**影响**:
- 在 API 层提供清晰的验证错误信息

---

### 主题 5: 并发控制和数据一致性

**问题**: 如何防止并发更新导致的数据冲突？

**调查**:
- 分析需求 NFR 2（数据一致性）
- SQLAlchemy 的并发控制机制

**结论**:
- 使用 SQLAlchemy 的乐观锁（version 字段）
- 或使用数据库级别的唯一约束防止重复记录

**实现**:
- `twitter_follows` 表添加唯一约束：`(user_id, username)`
- 过滤规则表添加唯一约束：`(user_id, keyword)`

**影响**:
- 确保数据完整性
- 防止重复关注和重复过滤规则

---

## 设计决策

### 决策 1: 数据模型分离
**选择**: 新增专用表而非复用 key-value 存储
**理由**:
- 支持复杂查询（如按优先级排序）
- 支持外键关系和级联删除
- 更好的数据完整性和性能

### 决策 2: 相关性服务抽象
**选择**: 使用抽象接口 + 多态实现
**理由**:
- 满足可扩展性需求
- 便于单元测试
- 未来可无缝切换到嵌入模型

### 决策 3: RESTful API 设计
**选择**: 遵循现有模块模式
**理由**:
- 保持代码风格一致
- 降低学习成本
- 便于集成到现有系统

---

## 风险和缓解策略

| 风险 | 影响 | 缓解策略 |
|------|------|----------|
| 数据库迁移失败 | 高 | 编写回滚脚本，测试迁移流程 |
| 相关性算法性能问题 | 中 | 添加缓存机制，设置超时限制 |
| API 接口变更导致兼容性问题 | 低 | 使用语义化版本控制，保持向后兼容 |

---

## 待调查事项
- 无
