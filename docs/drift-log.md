# DRIFT 登记台账

> append-only · 每次发现「CLAUDE.md / README / docs 与代码实际行为偏离」时追加一行
> 灵感来源：[ai_workspace_pm 框架](https://github.com/ayouaiyouwei-arch/claude-product-pipeline) 的 P006 DRIFT 流程，单人项目轻量版

---

## 用途

记录"文档说 A、代码实际 B"的偏离事件。目的是：

- 把隐性知识显性化（避免再次踩同样的坑）
- 让 Claude 在协作中能主动核查"上次 DRIFT 在哪儿"
- 不强求当场修文档，但偏离事件本身要留痕

## 触发条件

发现以下任一情况立即追加一行：

- CLAUDE.md / README 描述的字段名 / 接口 / 端口 / 路径与实际代码不一致
- 已知陷阱（CLAUDE.md § 已知陷阱）出现新变体
- Claude 凭印象做了某事，事后 grep 发现假设不成立
- 测试通过但实际行为与预期不符

## 字段格式

```
| 日期 | 偏离点 | 文档/记忆声称 | 代码/事实 | 处理方式 | 后续 |
```

- **处理方式**：`已改文档` / `已改代码` / `登记待处理` / `仅记录`
- **后续**：如果是 `登记待处理`，写明截止日期或触发条件

## 台账

| 日期 | 偏离点 | 文档/记忆声称 | 代码/事实 | 处理方式 | 后续 |
|---|---|---|---|---|---|
| 2026-06-07 | MCP 启动依赖 Postgres 先就绪 + 抓取前置检查清单 | CLAUDE.md「MCP 优先（在 x-watcher 目录启动 Claude Code 才有）」隐含"在该目录启动即可用"；memory 环境配置把 Postgres(Docker) 当作常驻 | 会话启动时若 Postgres(Docker)/OrbStack 未先起来，x-watcher MCP 在 `claude mcp list` 握手阶段超时静默失败（✗ Failed to connect），该会话内 MCP 工具（trigger_scrape 等）全程不可用且无法中途重连；把 Postgres 拉起后重测握手正常（✓ Connected，serverInfo x-watcher v1.27.1，24 工具齐全） | 仅记录 | 启动顺序固定为"先起 OrbStack+Postgres → 再启 Claude Code 会话"；本次已改走直接脚本兜底（ScrapingService + session_maker + SummarizationRepository）完成 57 条抓取+翻译，零 openrouter |
| 2026-06-20 | MCP server 进程不随会话内代码编辑热更 | 会话内编辑 `src/mcp/tools/summarization_tools.py`（新增验证门 + `rejected`）后，默认同会话调用 MCP `save_summaries` 会走新逻辑 | 运行中的 x-watcher MCP 是**会话启动时加载的长驻 stdio 进程**，仍执行旧代码——live 调用无验证门、无 `rejected` 字段，且把一条故意截断的译文写进了库（覆盖原正确译文，已即时 re-save 恢复并查库核对）| 仅记录 | 会话内对 MCP 工具源码的改动只在**下次启动 Claude Code 会话**（重载 MCP stdio 进程）后生效；本次靠 78 项单测验证新逻辑，live 验证需新会话。教训：改完 MCP 工具源码后**不要**在同会话用 live MCP 调用做"非破坏性验证"——它跑的是旧代码 |
| 2026-06-22 | scrape-and-translate 抓取链路的 DB 直连兜底 + follows.json 脏数据 | CLAUDE.md「抓取前置检查清单」Step 4/5/6（`session_maker` 直查 `tweets LEFT JOIN summaries` / 写 `SummaryOrm` / `model_name="claude-opus-4-7"`）+ 已知陷阱 3（`import TweetOrm`）均假定数据在 PG | `.env` 已切 `XWATCHER_DATA_LAYER=file`（`XWATCHER_DATA_ROOT=data_migrated`），tweets/summaries/follows 全在文件层；MCP 工具（`get_unsummarized_tweets`/`save_summaries`）走 `data_layer.provider` 路由到 `File*Store`，DB 直连兜底会查空表、`SummaryOrm`/`TweetOrm` 路径不经过；`model_name` 实际读 `config.py:103` `claude_code_model_name`。另：`data_migrated/follows/follows.json` 混入 alice(78)/bob(79) 测试种子（缺 `added_at`），file 层 `ScraperFollow(**rec)` 严格校验直接令 `trigger_scrape` 崩溃 | 已改代码 + 已改文档（CLAUDE.md 已加 file 模式标注） | 【2026-06-24 闭环】CLAUDE.md LOCKED 段（实测 64-99 / 166-200）已由 owner 加 file 模式标注：顶部「数据层模式（2026-06-22 起）」说明（L79）+ 抓取清单 Step 4/5/6 标「仅 `sqlalchemy` 模式兜底」（L81-83）+ 已知陷阱 3 标「适用范围：仅 `sqlalchemy`」（L186）；脏数据备份 `follows.json.bak-e7aad43` 已清理（现仅 `follows.json`）。命令文件只调 MCP 工具、架构无关，无需改 |
