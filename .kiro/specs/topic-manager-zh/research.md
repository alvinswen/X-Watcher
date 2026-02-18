# 研究与设计决策

## 摘要
- **Feature**: `topic-manager-zh`
- **Discovery Scope**: Extension（在现有六边形架构中新增独立模块）
- **关键发现**:
  - LLM provider 构建逻辑可从 `create_summarization_service()` 中提取为公共函数 `build_llm_providers()`
  - 推文聚合查询可组合现有的 `TweetOrm.author_username.in_()` + `created_at.between()` + LEFT JOIN `SummaryOrm`
  - 异步任务生命周期使用 `asyncio.create_task()` + DB 持久化即可，无需复用 `SummarizationQueue`

## 研究日志

### LLM Provider 复用策略
- **背景**: TopicSummaryService 需要调用 LLM 生成摘要，现有 `create_summarization_service()` 包含 provider 构建逻辑但返回的是 `SummarizationService` 实例
- **来源**: `src/summarization/services/summarization_service.py:1326-1390`
- **发现**: provider 构建逻辑（读取 config → 实例化 OpenRouterProvider/MiniMaxProvider）约 30 行，可提取为独立函数
- **影响**: 提取 `build_llm_providers(config) -> list[LLMProvider]` 公共函数，TopicSummaryService 和 SummarizationService 均可调用

### 上下文窗口管理
- **背景**: 主题可能包含大量推文，需要评估 LLM 上下文限制
- **来源**: OpenRouter 文档、MiniMax 文档
- **发现**:
  - Claude Sonnet 4.5 via OpenRouter: 200K tokens 上下文
  - MiniMax M2.1: 128K tokens 上下文
  - 粗略估算：1 中文字符 ≈ 1 token，1 英文单词 ≈ 1.3 tokens
  - 7 天周期内，20 个账号可能产生 200-2000 条推文
  - 使用已有中文翻译（平均 100 字/条）代替原文（平均 200 字/条）可减少约 50% token
- **影响**: 设置 80K token 作为安全上限（为输出预留空间），超出时按时间正序截断最旧推文

### 异步任务模式选择
- **背景**: 需要在不阻塞 API 的情况下执行 LLM 摘要
- **来源**: 现有 `TaskRegistry` 和 `SummarizationQueue` 模式
- **发现**:
  - `TaskRegistry`: 内存态任务追踪，完成后持久化到 `TaskExecutionLog`，适合短生命周期任务
  - `SummarizationQueue`: 优先级队列 + 单 worker，适合大量小任务的批处理
  - 主题摘要任务是低频、长生命周期任务，每次只处理一个主题
- **影响**: 使用 `asyncio.create_task()` 直接启动后台协程，状态持久化到专用的 `topic_summary_tasks` 表，不依赖 TaskRegistry 或 SummarizationQueue

## 架构模式评估

| 方案 | 描述 | 优势 | 劣势 |
|------|------|------|------|
| 独立 `src/topic/` 模块 | 遵循现有六边形架构，新建完整的 domain/infrastructure/services/api 分层 | 职责清晰、独立可测、不污染现有模块 | 新文件数量较多 |
| 扩展 `src/summarization/` | 在现有摘要模块中添加主题摘要逻辑 | 复用更多现有代码 | 职责混杂，摘要模块已 2000+ 行 |

**选择**: 独立模块。理由：主题摘要与推文摘要在数据流、提示词、输出格式上完全不同。

## 设计决策

### 决策: Provider 构建逻辑提取
- **背景**: TopicSummaryService 和 SummarizationService 都需要构建 LLM providers
- **备选方案**:
  1. 在 TopicSummaryService 中内联 provider 构建代码
  2. 提取 `build_llm_providers()` 到 `src/summarization/llm/config.py`
- **选择**: 方案 2 — 提取为公共函数
- **理由**: 避免代码重复，config.py 已是 provider 配置的自然归属地
- **权衡**: 需要修改 config.py（新增约 25 行），但这是合理的内聚

### 决策: 推文数据使用已有翻译优先
- **背景**: 构建聚合 prompt 时，可使用推文原文或已有的中文翻译
- **选择**: LEFT JOIN summaries，优先使用 `translation_text`，仅在无翻译时使用原文 `text`
- **理由**: 中文翻译更紧凑（token 消耗更少），且已经过语义处理，减少 LLM 负担

### 决策: 任务状态 DB 持久化
- **背景**: 任务状态需要在服务重启后可查
- **选择**: 专用 `topic_summary_tasks` 表，不依赖 `TaskRegistry`
- **理由**: TaskRegistry 是内存态单例，重启后丢失；主题摘要任务需要完整的生命周期追踪和关联摘要结果

## 风险与缓解

- **LLM 上下文溢出** — 设置 80K token 安全上限，超出时截断最旧推文并在摘要中注明
- **LLM 所有提供商不可用** — 标记任务为 failed，记录错误信息，管理员可手动重新创建任务
- **大量并发摘要任务** — 共享全局 LLM 信号量（`_get_global_llm_semaphore()`，最大 3 并发），避免压垮 API
- **数据库级联删除** — 使用 `ondelete="CASCADE"` 确保主题删除时清理所有关联数据
