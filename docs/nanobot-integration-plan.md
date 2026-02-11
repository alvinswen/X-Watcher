# Nanobot × Feed API 集成计划

## Context

SeriousNewsAgent 的 Feed API（`GET /api/feed`）已开发完成并验证通过（803 条推文，200 OK）。现在需要让 nanobot 定时调用此接口，实现：
1. **增量拉取**推文数据（含摘要和翻译）
2. **存入记忆**供后续对话查询
3. **推送摘要**到聊天渠道（本阶段暂不配置渠道，预留接口）

**核心设计原则**：
- **纯配置驱动** — 不修改 nanobot 源码，仅创建 workspace skill + 脚本
- **可移植** — 核心 Python 脚本独立于 nanobot，可被任何 agent 框架复用
- **分层架构** — `fetch_feed.py`（通用脚本）→ `SKILL.md`（nanobot 适配层）

---

## 架构

```
┌─────────────────────────────────────────────────┐
│  nanobot agent                                  │
│  ┌───────────┐    ┌───────────────────────┐     │
│  │ cron 定时  │───→│ sna-feed SKILL.md     │     │
│  │ 每60分钟   │    │ (指导 agent 使用脚本)  │     │
│  └───────────┘    └───────┬───────────────┘     │
│                           │ exec() 调用          │
│                   ┌───────▼───────────────┐     │
│                   │ scripts/fetch_feed.py  │     │
│                   │ (独立可移植 CLI 工具)    │     │
│                   └───────┬───────────────┘     │
└───────────────────────────┼─────────────────────┘
                            │ HTTP GET + X-API-Key
                    ┌───────▼───────────────┐
                    │ SeriousNewsAgent       │
                    │ GET /api/feed          │
                    │ localhost:8000         │
                    └───────────────────────┘
```

---

## 现有环境

- **SeriousNewsAgent** 运行在 `http://localhost:8000`
- **nanobot** 已安装在 `C:\Development\nanobot`，配置在 `~/.nanobot/config.json`
- **nanobot 用户 API Key**：`sna_fb4fedfc801a37f3a5e587aa7155bc89`
- **nanobot workspace**：`C:\Development\nanobot\workspace\`（或 `~/.nanobot/workspace/`）
- **nanobot LLM Provider**：OpenRouter（已配置）

---

## 实现步骤

### 步骤 1：创建独立 Feed 拉取脚本（可移植核心）

**新建：** `~/.nanobot/workspace/skills/sna-feed/scripts/fetch_feed.py`

这是与 nanobot 无关的独立 CLI 工具，任何 Python 环境可直接运行。

**功能**：
- 读取配置（`--config` 文件或环境变量 `SNA_API_URL` / `SNA_API_KEY`）
- 维护增量状态：`state.json` 记录 `last_pulled_at` 时间戳
- 调用 Feed API：`GET /api/feed?since=<last>&until=<now>&include_summary=true`
- 处理分页：如 `has_more=true` 且未达上限，自动翻页
- 输出结构化 JSON 到 stdout
- 更新 `state.json`

**CLI 接口**：
```bash
# 增量拉取（自动续上次）
python fetch_feed.py --config sna-feed.json

# 首次/指定起始时间
python fetch_feed.py --config sna-feed.json --since 2026-02-11T00:00:00Z

# 也支持环境变量（方便容器化部署）
SNA_API_URL=http://localhost:8000 SNA_API_KEY=sna_xxx python fetch_feed.py
```

**输出 JSON 格式**：
```json
{
  "status": "ok",
  "new_items": 12,
  "total_in_range": 45,
  "since": "2026-02-11T05:00:00Z",
  "until": "2026-02-11T05:30:00Z",
  "items": [
    {
      "tweet_id": "...",
      "author_username": "elonmusk",
      "text": "...",
      "summary_text": "中文摘要",
      "translation_text": "中文翻译",
      "created_at": "..."
    }
  ]
}
```

**关键设计**：
- 仅依赖 `httpx`（nanobot 已安装）+ 标准库
- 内部逻辑封装为 `FeedClient` 类，可被 `import` 复用
- 错误返回 `{"status": "error", "message": "...", "code": 401}` 结构

---

### 步骤 2：创建配置和参考文件

**新建：** `~/.nanobot/workspace/skills/sna-feed/scripts/sna-feed.json`
```json
{
  "api_url": "http://localhost:8000",
  "api_key": "sna_fb4fedfc801a37f3a5e587aa7155bc89",
  "max_items_per_pull": 50
}
```

**新建：** `~/.nanobot/workspace/skills/sna-feed/references/api-docs.md`

Feed API 精简参考文档（供 agent 按需查阅）：
- `GET /api/feed` 端点说明、参数（since/until/limit/include_summary）
- 认证方式（X-API-Key header）
- 响应字段：items[], count, total, has_more, since, until
- FeedTweetItem 字段：tweet_id, text, author_username, author_display_name, created_at, db_created_at, summary_text, translation_text, media
- 错误码：401 未认证、422 参数错误、500 服务器错误

---

### 步骤 3：创建 SKILL.md（nanobot 适配层）

**新建：** `~/.nanobot/workspace/skills/sna-feed/SKILL.md`

**Frontmatter**：
```yaml
---
name: sna-feed
description: >
  Fetch and analyze news from SeriousNewsAgent Feed API.
  Use when: (1) the user asks about recent news, tech trends, or tweet summaries,
  (2) a scheduled cron job triggers periodic news pull,
  (3) the user wants to set up or manage news monitoring.
  Provides incremental data pull, memory storage, and optional channel push.
---
```

**Body 要点**（保持简洁，< 200 行）：

1. **Quick Start** — 单次拉取：
   ```
   exec(command="python <skill_path>/scripts/fetch_feed.py --config <skill_path>/scripts/sna-feed.json")
   ```
   解析 stdout JSON，处理 items。

2. **拉取后处理**（两步）：
   - **写入日记** — 将新 items 追加到 `memory/YYYY-MM-DD.md`，格式：
     ```markdown
     ## 新闻更新 HH:MM (N 条新推文)

     **@author** - summary_text
     > translation_text (前 150 字)
     ```
   - **推送通知**（预留） — 如用户配置了聊天渠道：
     ```
     message(content="N 条新推文\n\n1. @author: summary...", channel="telegram", chat_id="xxx")
     ```

3. **Cron 设置** — 定时拉取指令示例：
   ```
   cron(action="add", message="Execute sna-feed skill: pull latest news from SeriousNewsAgent, save to daily memory file", every_seconds=3600)
   ```

4. **配置说明** — `sna-feed.json` 字段含义，如何切换生产环境 URL

5. **API 详情** — 指向 `references/api-docs.md`：
   > 完整 API 参数和响应格式见 `references/api-docs.md`

---

### 步骤 4：验证

1. **脚本独立验证**：
   ```bash
   python fetch_feed.py --config sna-feed.json --since 2026-02-11T00:00:00Z
   ```
   确认输出 JSON 格式正确，items 非空。

2. **nanobot 对话验证**：
   启动 `nanobot agent`，输入"拉取最新新闻"，验证 skill 触发、脚本执行、日记写入。

3. **Cron 验证**：
   在 nanobot 中设置 60 分钟间隔 cron，观察自动拉取和记忆写入。

4. **增量验证**：
   连续拉取两次，确认第二次 `since` 自动从 `state.json` 续接，不重复拉取。

---

## 文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `~/.nanobot/workspace/skills/sna-feed/SKILL.md` | 新建 | Skill 定义（nanobot 适配层） |
| `~/.nanobot/workspace/skills/sna-feed/scripts/fetch_feed.py` | 新建 | 独立 Feed 拉取脚本（**可移植核心**） |
| `~/.nanobot/workspace/skills/sna-feed/scripts/sna-feed.json` | 新建 | API 连接配置 |
| `~/.nanobot/workspace/skills/sna-feed/references/api-docs.md` | 新建 | Feed API 参考文档 |

- `state.json` 由脚本首次运行时自动创建
- **nanobot 源码** — 零修改
- **SeriousNewsAgent** — 零修改

---

## 可移植性

| 目标场景 | 操作 |
|----------|------|
| 其他 nanobot 实例 | 复制 `skills/sna-feed/` → 修改 `sna-feed.json` 中 `api_url` / `api_key` |
| 其他 Agent 框架 | 直接用 `python fetch_feed.py --config ...` 或 `from fetch_feed import FeedClient` |
| Docker / CI | `SNA_API_URL=... SNA_API_KEY=... python fetch_feed.py`（环境变量模式） |

---

## 关键参考

- **Feed API 路由实现**：`src/feed/api/routes.py`
- **Feed API 数据模型**：`src/feed/api/schemas.py`（FeedTweetItem, FeedResponse）
- **nanobot skill 创建指南**：`C:\Development\nanobot\nanobot\skills\skill-creator\SKILL.md`
- **nanobot cron skill**：`C:\Development\nanobot\nanobot\skills\cron\SKILL.md`
- **nanobot tools**：`C:\Development\nanobot\nanobot\agent\tools\web.py`（web_fetch）、`shell.py`（exec）
- **nanobot workspace**：`C:\Development\nanobot\workspace\`（AGENTS.md, TOOLS.md, HEARTBEAT.md）
- **nanobot 配置**：`~/.nanobot/config.json`（LLM provider: OpenRouter）
