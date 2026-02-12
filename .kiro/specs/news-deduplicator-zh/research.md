# Research & Design Decisions Template

---

**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

---

## Summary
- **Feature**: `news-deduplicator`
- **Discovery Scope**: Extension（扩展现有抓取系统，添加去重功能）
- **Key Findings**:
  - scikit-learn 的 TF-IDF + 余弦相似度是成熟的文本相似度计算方案
  - FastAPI BackgroundTasks 适合轻量级异步去重处理
  - 去重服务可以作为独立模块集成到现有抓取流程中

## Research Log
Document notable investigation steps and their outcomes. Group entries by topic for readability.

### Text Similarity Algorithms
- **Context**: 需要选择合适的文本相似度算法来实现推文去重
- **Sources Consulted**:
  - [scikit-learn TfidfVectorizer documentation](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)
  - [Overview of Text Similarity Metrics in Python](https://medium.com/data-science/overview-of-text-similarity-metrics-3397c4601f50)
  - [How to Calculate Cosine Similarity in Python?](https://www.analyticsvidhya.com/blog/2024/06/cosine-similarity-in-python/)
  - [Product Matching using Sentence-BERT](https://everant.org/index.php/etj/article/download/1641/1191/4636)
- **Findings**:
  - TF-IDF + 余弦相似度是经典的文本相似度计算方法，sklearn 实现成熟稳定
  - Sentence-BERT 等深度学习方法精度更高但需要额外依赖和计算资源
  - 对于推文这种短文本，TF-IDF 方案足够有效且成本低
- **Implications**:
  - 初期使用 TF-IDF 方案，后续可按需升级到嵌入模型
  - 相似度阈值默认设为 0.85，可根据实际效果调整

### FastAPI Background Task Patterns
- **Context**: 去重需要在抓取完成后异步执行，不能阻塞抓取流程
- **Sources Consulted**:
  - [FastAPI Background Tasks Tutorial](https://www.getorchestra.io/guides/fastapi-background-tasks-a-detailed-tutorial)
  - [How to Implement Background Tasks in FastAPI](https://oneuptime.com/blog/post/2026-02-02-fastapi-background-tasks/view)
  - [FastAPI and Background Tasks](https://unfoldai.com/fastapi-background-tasks/)
- **Findings**:
  - FastAPI BackgroundTasks 适合轻量级后台任务
  - 任务需要设计为幂等性，避免重复执行导致的数据问题
  - 对于分布式环境，Celery + Redis 是更健壮的选择
- **Implications**:
  - 初期使用 FastAPI BackgroundTasks
  - 去重操作需要支持重试和幂等性

### Existing Codebase Patterns
- **Context**: 需要与现有抓取服务保持一致的架构模式
- **Sources Consulted**:
  - `src/scraper/scraping_service.py` - 现有抓取服务编排模式
  - `src/scraper/infrastructure/repository.py` - 数据仓库模式
  - `src/scraper/domain/models.py` - 领域模型定义
- **Findings**:
  - 使用 Service-Repository 模式进行分层
  - 使用 Pydantic 模型进行数据验证
  - 使用 `returns` 库的 Result 类型进行错误处理
  - 支持依赖注入便于测试
- **Implications**:
  - 去重服务应遵循相同的架构模式
  - 使用 Pydantic 定义去重相关的数据模型

## Architecture Pattern Evaluation
List candidate patterns or approaches that were considered. Use the table format where helpful.

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Service Layer Extension | 在现有服务层添加去重服务 | 遵循现有模式，易于集成 | 需要协调抓取和去重的时序 | 与 ScrapingService 保持一致 |
| Inline Deduplication | 在抓取保存前直接去重 | 实现简单，延迟低 | 增加抓取流程复杂度 | 不推荐，违反单一职责原则 |
| Event-Driven | 抓取完成后发送事件触发去重 | 解耦合，易于扩展 | 需要消息队列组件 | 过度设计，暂不需要 |

## Design Decisions
Record major decisions that influence `design.md`. Focus on choices with significant trade-offs.

### Decision: 文本相似度算法选择
- **Context**: 需要在精确度和成本之间权衡
- **Alternatives Considered**:
  1. TF-IDF + 余弦相似度 — 成熟稳定，计算成本低
  2. Sentence-BERT 嵌入 — 精度更高，但需要额外 API 调用和成本
  3. Levenshtein 距离 — 适合短文本，但对语义相似度不敏感
- **Selected Approach**: TF-IDF + 余弦相似度作为主要方案，预留嵌入模型接口
- **Rationale**:
  - 推文是短文本，TF-IDF 方案足够有效
  - sklearn 库成熟稳定，无额外 API 成本
  - 预留接口便于未来按需升级
- **Trade-offs**:
  - 精度略低于嵌入模型，但成本和复杂度大幅降低
  - 后续升级需要迁移去重结果
- **Follow-up**:
  - 监控去重效果（误报率和漏报率）
  - 根据用户反馈决定是否升级到嵌入模型

### Decision: 去重执行时机
- **Context**: 需要决定去重在抓取流程中的执行时机
- **Alternatives Considered**:
  1. 保存前去重 — 在保存到数据库前过滤重复推文
  2. 保存后去重 — 保存所有推文，然后异步去重
  3. 定时去重 — 定期对已有数据进行批量去重
- **Selected Approach**: 保存后异步去重（抓取流程保存后触发）
- **Rationale**:
  - 不阻塞抓取流程，保证抓取性能
  - 保留原始数据便于审计和调试
  - 支持重新去重（re-deduplication）
- **Trade-offs**:
  - 短期内数据库会有重复数据
  - 需要额外的去重状态标记
- **Follow-up**:
  - 添加去重状态字段到 tweets 表
  - API 层返回数据时过滤已标记为重复的推文

### Decision: 去重结果存储结构
- **Context**: 需要设计高效的去重结果存储结构
- **Alternatives Considered**:
  1. 新建 deduplication_groups 表 + tweets 表外键
  2. 在 tweets 表中直接添加 deduplication_group_id 字段
  3. 使用 JSON 字段存储去重关系
- **Selected Approach**: 新建 deduplication_groups 表 + tweets 表添加 deduplication_group_id 外键
- **Rationale**:
  - 符合关系型数据库设计规范
  - 支持高效查询和索引
  - 便于扩展（如添加相似度分数等元数据）
- **Trade-offs**:
  - 需要额外的表和迁移
  - 查询时需要 JOIN 操作
- **Follow-up**:
  - 设计 Alembic 迁移脚本
  - 添加必要的索引优化查询性能

## Risks & Mitigations
- **相似度阈值不准确** — 通过配置支持动态调整，收集用户反馈优化
- **大规模数据性能问题** — 分批处理，添加数据库索引，后续可升级为分布式处理
- **去重结果可解释性差** — 记录去重决策依据（相似度分数、匹配字段），支持用户审查
- **误删重要内容** — 保留原始推文记录，只标记为重复而非物理删除，支持撤销操作

## References
Provide canonical links and citations (official docs, standards, ADRs, internal guidelines).
- [scikit-learn: TfidfVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html) — TF-IDF 向量化 API 文档
- [scikit-learn: cosine_similarity](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html) — 余弦相似度计算 API
- [FastAPI: Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) — FastAPI 后台任务官方文档
- [Product Matching using Sentence-BERT](https://everant.org/index.php/etj/article/download/1641/1191/4636) — 深度学习文本相似度方法参考
