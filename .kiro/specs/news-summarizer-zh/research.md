# Research & Design Decisions

---

**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

---

## Summary
- **Feature**: `news-summarizer` - 新闻摘要翻译模块
- **Discovery Scope**: 独立功能模块，可选利用去重服务优化
- **Key Findings**:
  - OpenRouter 模型名使用 `anthropic/claude-sonnet-4.5` 格式
  - MiniMax 中国版和海外版使用不同的 Base URL（国内为 `api.minimaxi.com`）
  - 使用 OpenAI SDK 兼容接口可统一调用多个提供商
  - 基于内容哈希的内存缓存策略可显著降低 API 成本
  - 需区分临时错误（429/超时）和永久错误（401/402），优化降级策略

## Research Log

### OpenRouter API 调查
- **Context**: 需要确认 OpenRouter 上 Claude Sonnet 模型的准确命名格式
- **Sources Consulted**:
  - [OpenRouter Models Page](https://openrouter.ai/models)
  - [Claude Sonnet on OpenRouter](https://openrouter.ai/anthropic)
  - [2026年 OpenRouter API 调用全攻略](https://juejin.cn/post/7602252722373263411)
- **Findings**:
  - 当前推荐模型为 `anthropic/claude-sonnet-4.5`（最新 Sonnet 版本）
  - 模型命名格式为 `提供商/模型名`，例如 `anthropic/claude-sonnet-4.5`
  - OpenRouter 提供标准 OpenAI 兼容接口，Base URL 为 `https://openrouter.ai/api/v1`
  - 支持流式和非流式响应
- **Implications**:
  - 使用 `openai` SDK 的 `base_url` 参数即可接入 OpenRouter
  - 模型配置需使用完整路径格式
  - 后续可无缝切换到更新的 Sonnet 版本

### MiniMax 中国版 API 调查
- **Context**: 项目使用 MiniMax 作为后备模型，需确认国内版 API 端点
- **Sources Consulted**:
  - [通过AI 编程工具接入 - MiniMax 开放平台文档中心](https://platform.minimaxi.com/docs/guides/text-ai-coding-tools)
  - [OpenClaw - MiniMax 开放平台文档中心](https://platform.minimaxi.com/docs/coding-plan/openclaw)
  - [MiniMax 聊天 Spring AI Reference](https://doc.spring4all.com/spring-ai/reference/api/embeddings/minimax-embeddings.html)
  - [GitHub Issue: MiniMax provider missing China mainland baseUrl](https://github.com/openclaw/openclaw/issues/4647)
- **Findings**:
  - **中国版 Base URL**: `https://api.minimaxi.com`
  - **海外版 Base URL**: `https://api.minimax.io`
  - 两个版本使用不同的 API Key，不能混用
  - 国内版支持 OpenAI 兼容接口格式
  - 推荐模型：M2.1（高性价比，支持中文优化）
- **Implications**:
  - 配置时需根据用户地区选择正确的 Base URL
  - 使用国内用户时必须使用 `api.minimaxi.com`
  - 可使用 `openai` SDK 统一调用接口

### 多提供商统一接口方案
- **Context**: 需要设计一个可支持多个 LLM 提供商的统一调用接口
- **Sources Consulted**:
  - 现有项目技术栈配置
  - OpenAI SDK 文档（官方）
- **Findings**:
  - OpenAI SDK 支持自定义 `base_url` 和 `api_key`
  - 大多数主流提供商（OpenRouter、MiniMax、Together AI）都提供 OpenAI 兼容接口
  - 响应格式基本统一（`ChatCompletion` 格式）
- **Implications**:
  - 创建 `LLMProvider` 抽象接口，统一封装各提供商调用
  - 降级策略：主 → 后备1 → 后备2
  - 成本统计需要根据不同提供商的定价模型分别计算

### 缓存策略研究
- **Context**: 避免对相同内容重复调用 LLM API，降低成本
- **Sources Consulted**:
  - 项目需求分析
  - 去重组设计（同一去重组可共享摘要）
- **Findings**:
  - 去重后的推文本应相同，可共享摘要和翻译结果
  - 使用内容哈希（SHA-256）而非 tweet_id 作为缓存键
  - 缓存有效期建议 7 天，避免过时内容
  - 独立推文（无去重组）使用 `standalone:tweet_id` 作为缓存键
- **Implications**:
  - 去重组缓存键：`hash(dedup_type + ":" + representative_id)`
  - 独立推文缓存键：`hash("standalone:" + tweet_id)`
  - 去重组内所有推文关联到同一缓存条目（优化策略）
  - 无去重组的推文独立缓存
  - 需要在数据库中记录缓存命中统计

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Service-Repository 扩展 | 沿用现有去重模块的分层模式 | 与现有架构一致，易于维护；团队熟悉 | 服务层可能变重 | 与 news-deduplicator 模式保持一致 |
| Strategy Pattern | 将不同 LLM 提供商封装为策略 | 易于扩展新提供商；符合开闭原则 | 增加抽象层复杂度 | 适合多提供商切换场景 |
| Provider Pattern | 提供商抽象 + 统一调用接口 | 简化调用代码；便于降级 | 需要统一响应格式 | 推荐：结合 Strategy 使用 |

## Design Decisions

### Decision: LLM 提供商抽象层设计
- **Context**: 需要支持 OpenRouter、MiniMax 中国版、开源模型三个提供商，并实现自动降级
- **Alternatives Considered**:
  1. 直接使用 OpenAI SDK，手动切换配置 — 简单但代码重复
  2. 使用 LangChain 等框架 — 功能全面但过重
  3. 自定义 Provider 抽象层 — 轻量且灵活
- **Selected Approach**: 自定义 `LLMProvider` 接口 + 具体实现类
  ```python
  class LLMProvider(ABC):
      async def complete(self, prompt: str) -> LLMResponse: ...

  class OpenRouterProvider(LLMProvider): ...
  class MiniMaxProvider(LLMProvider): ...
  class OpenSourceProvider(LLMProvider): ...
  ```
- **Rationale**: 符合项目 YAGNI 原则，不引入重型框架；与现有 Service-Repository 架构一致
- **Trade-offs**: 需要手动维护提供商适配器，但保持了代码轻量和可控性
- **Follow-up**: 初期实现 OpenRouter 和 MiniMax，开源模型作为扩展预留

### Decision: 缓存键设计
- **Context**: 需要为摘要和翻译结果设计缓存键，支持有去重组和无去重组两种场景
- **Alternatives Considered**:
  1. 使用 `tweet_id` 作为键 — 简单但相同内容不同推文无法共享
  2. 使用 `deduplication_group_id` 作为键 — 与去重模块强耦合，无去重组时无法使用
  3. 使用内容哈希作为键 — 解耦且灵活
- **Selected Approach**: 双策略缓存键
  - 有去重组：`SHA256(dedup_type + ":" + representative_id)` — 组内共享
  - 无去重组：`SHA256("standalone:" + tweet_id)` — 独立缓存
  - 两种缓存键不冲突
- **Rationale**: 解耦设计；去重组是优化策略而非前提条件；支持独立推文处理
- **Trade-offs**: 需要计算哈希，但计算开销可忽略
- **Follow-up**: 在实现中验证缓存命中率

### Decision: 批量处理并发控制
- **Context**: 需要对多条约 50 条推文进行批量处理
- **Alternatives Considered**:
  1. 全并发处理 — 可能触发速率限制
  2. 串行处理 — 太慢
  3. 信号量控制并发 — 平衡性能和限制
- **Selected Approach**: 使用 `asyncio.Semaphore` 限制并发数为 5
  - 配合指数退避重试处理 429 错误
- **Rationale**: 避免触发 API 速率限制；平衡处理速度
- **Trade-offs**: 增加代码复杂度，但提高了可靠性
- **Follow-up**: 监控 429 错误频率，动态调整并发数

### Decision: Prompt 设计策略
- **Context**: 需要为摘要和翻译设计有效的 Prompt
- **Alternatives Considered**:
  1. 每次硬编码 Prompt — 不灵活
  2. 使用 Prompt 模板库 — 过重
  3. 简单模板字符串 + 配置 — 轻量实用
- **Selected Approach**: 配置文件中定义 Prompt 模板，支持变量替换
  ```python
  SUMMARY_PROMPT = """
  请提取以下推文的关键信息，生成 50-150 字的中文摘要。
  保留人名、公司名等关键实体。
  推文内容：{tweet_text}
  """
  ```
- **Rationale**: 符合项目轻量原则；便于迭代优化
- **Trade-offs**: 缺少高级 Prompt 管理功能，但初期足够
- **Follow-up**: 根据实际效果调整 Prompt 模板

## Risks & Mitigations

- **风险 1**: OpenRouter 或 MiniMax API 频繁变更导致适配失败
  - **缓解措施**: 使用版本化接口；定期测试各提供商连通性；记录详细的错误日志

- **风险 2**: LLM 生成质量不稳定（摘要过长/翻译不准）
  - **缓解措施**: 添加输出长度限制；使用结构化输出（JSON）；支持手动重新生成

- **风险 3**: API 成本超出预期
  - **缓解措施**: 实施严格的缓存策略；记录详细的成本统计；设置每日成本上限告警

- **风险 4**: 批量处理时部分失败导致数据不一致
  - **缓解措施**: 使用事务确保原子性；记录失败条目支持重试；提供部分成功报告

- **风险 5**: 降级策略无法正常工作
  - **缓解措施**: 单元测试覆盖所有降级路径；定期进行故障演练

## References

### API 文档
- [OpenRouter Models](https://openrouter.ai/models) - 查看所有可用模型和定价
- [OpenRouter API Documentation](https://openrouter.ai/docs) - API 调用指南
- [MiniMax 开放平台文档中心](https://platform.minimaxi.com/docs) - MiniMax API 官方文档

### 项目内部
- `.kiro/specs/news-deduplicator-zh/design.md` - 去重模块设计，作为架构参考
- `.kiro/steering/tech.md` - 项目技术栈说明
- `.kiro/steering/structure.md` - 项目结构约定

### 外部资源
- [OpenAI Python SDK Documentation](https://github.com/openai/openai-python) - SDK 使用参考
- [2026年 OpenRouter API 调用全攻略](https://juejin.cn/post/7602252722373263411) - 接入最佳实践
