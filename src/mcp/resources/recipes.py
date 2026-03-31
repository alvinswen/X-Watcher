"""MCP 工作流配方资源。

提供面向 Agent 的分步工作流指南，Agent 可在初始化时读取获取操作指引。
"""

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

DAILY_SUMMARY_RECIPE = """\
# 每日摘要生成工作流

## 场景
为指定主题生成覆盖过去 24 小时的 AI 聚合摘要报告。

## 默认参数
- 摘要截止时间：当天 18:00 北京时间（UTC+8）= 当天 10:00:00 UTC
- 时间跨度：24 小时
- 覆盖区间：[昨天 10:00 UTC, 今天 10:00 UTC]
- 默认主题：「精选账号」（发布到公众号上的摘要覆盖的账号集合）
- 时区偏移：-480（UTC+8）

## 分步流程

### Step 1：确定时间参数
根据当前北京时间计算 deadline：
- 如果当前 >= 18:00 → deadline = 今天 18:00 北京时间 = 今天 10:00:00Z
- 如果当前 < 18:00 → deadline = 昨天 18:00 北京时间 = 昨天 10:00:00Z
  （或提示用户当天数据尚未就绪）

### Step 2：检查数据就绪状态

#### 2a. 检查抓取状态
调用 `manage_scheduler(action="status")`
- 检查 `last_execution.executed_at` 是否晚于 deadline
- 如果是 → 数据已就绪，跳到 Step 2b
- 如果否 → 需要触发抓取（见 Step 3）

#### 2b. 检查推文翻译完整性（可选，影响摘要质量）
调用 `batch_summarize(action="preview", since=<deadline-24h>, until=<deadline>)`
- 如果 `pending_count == 0` → 翻译完整，跳到 Step 4
- 如果 `pending_count > 0` 但较少（<20）→ 可接受，跳到 Step 4 并通知用户
- 如果 `pending_count` 较多 → 建议等待翻译完成或继续（LLM 可处理原文）

### Step 3：触发数据补全（仅在数据不就绪时）

#### 3a. 触发抓取
调用 `trigger_scrape()`（不传 usernames = 全量抓取）
返回 task_id

#### 3b. 等待抓取完成
轮询 `get_task_status(task_id)` 直到 status == "completed"
- 轮询间隔建议：15 秒
- 典型耗时：2-5 分钟（取决于账号数）

#### 3c. 触发翻译补全（可选）
调用 `batch_summarize(action="backfill", since=<deadline-24h>, until=<deadline>)`
注意：trigger_scrape 已自动处理新抓取推文的摘要生成，此步仅用于补全历史遗漏

### Step 4：确定目标主题

如果用户指定了主题名称：
  调用 `list_topics()` → 在返回列表中匹配 name，获取 topic_id
如果用户未指定主题：
  调用 `list_topics()` → 找到名为「精选账号」的主题，获取其 topic_id

### Step 5：创建主题摘要任务
调用 `get_topic_summary(
    topic_id=<id>,
    action="create",
    time_span_hours=24,
    deadline="<计算好的 ISO 8601 时间>",
    tz_offset=-480
)`
记录返回的 task.id

### Step 6：等待摘要生成完成
轮询 `get_topic_summary(topic_id=<id>, action="list")`
- 检查最新任务（列表第一项）的 status 字段
- 等待 status 变为 "completed" 或 "failed"
- 轮询间隔建议：10 秒
- 典型耗时：30-120 秒

### Step 7：获取并交付摘要
调用 `get_topic_summary(topic_id=<id>, action="latest")`
获取 summary.content（完整摘要文本）

交付策略（根据上下文选择）：
- **直接输出**：摘要 < 3000 字，直接展示全文
- **分段输出**：摘要较长时，先展示「综合观察」部分，再按话题分段
- **摘要 + 链接**：在有 Web UI 的场景下，展示关键要点 + 链接到完整报告

## 错误处理
- 主题不存在 → 提示用户检查主题名称，列出可用主题
- 主题无关联账号 → 提示用户先添加账号到主题
- 摘要生成失败（status="failed"）→ 展示 error_message，建议重试
- 抓取任务失败 → 检查网络连接，建议手动重试

## 工具调用速查
| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 检查调度状态 | manage_scheduler | action="status" |
| 检查翻译完整性 | batch_summarize | action="preview", since, until |
| 触发抓取 | trigger_scrape | - |
| 监控抓取进度 | get_task_status | task_id |
| 触发翻译补全 | batch_summarize | action="backfill", since, until |
| 查找主题 | list_topics | - |
| 创建摘要 | get_topic_summary | action="create", deadline, time_span_hours=24 |
| 轮询摘要状态 | get_topic_summary | action="list" |
| 获取摘要内容 | get_topic_summary | action="latest" |
"""


CLAUDE_CODE_SUMMARIZE_RECIPE = """\
# Claude Code 翻译工作流

## 场景
使用 Claude Code 替代外部 LLM API 完成推文翻译和摘要生成。
Claude Code 本身就是 LLM，直接阅读推文原文并生成中文摘要和翻译。

## 分步流程

### Step 1：抓取推文（跳过自动翻译）
调用 `trigger_scrape(skip_summarization=true)`
- 设置 `skip_summarization=true` 确保抓取后不自动调用 LLM API 翻译
- 记录返回的 task_id

### Step 2：等待抓取完成
轮询 `get_task_status(task_id)` 直到 status == "completed"
- 轮询间隔建议：15 秒

### Step 3：获取待翻译推文
调用 `get_unsummarized_tweets(limit=100)`
- 可选参数：since/until 时间过滤，author 作者过滤
- 返回推文原文、作者、引用类型等完整上下文

### Step 4：生成摘要和翻译
对返回的每条推文，在 Claude Code 上下文中生成：
- **summary**：中文摘要（≤500 字符）
  - 原创推文：提取核心观点
  - 转推：格式「@用户 转推 @原作者: (内容摘要)」
  - 引用推文：格式「@用户 引用 @原作者: (内容)，并评论：(态度)」
- **translation**：中文翻译（保留专有名词和 URL）
  - 纯中文推文：可省略翻译
  - 混合语言：完整翻译

### Step 5：保存结果
调用 `save_summaries(summaries=<JSON>)`
- JSON 格式：`[{"tweet_id": "...", "summary": "...", "translation": "..."}]`
- 支持批量保存，单条失败不影响其他条目
- 结果以 model_provider="claude_code" 存储

### Step 6：验证
调用 `browse_tweets(date=<today>)` 确认摘要已生效

## 批量处理建议
- 单次 limit=100~200（1M context window 轻松处理）
- 如有大量积压，循环执行 Step 3-5 直到返回 0 条

## 工具调用速查
| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 抓取 | trigger_scrape | skip_summarization=true |
| 等待 | get_task_status | task_id |
| 获取待翻译 | get_unsummarized_tweets | limit, since, until |
| 保存结果 | save_summaries | summaries (JSON) |
| 验证 | browse_tweets | date |
"""


def register(mcp: FastMCP) -> None:
    """注册工作流配方资源。"""

    @mcp.resource("xwatcher://recipes/daily-summary")
    async def daily_summary_recipe() -> str:
        """每日摘要生成工作流配方。

        提供面向 Agent 的分步操作指南，包含时间计算、
        数据就绪检查、摘要生成和交付的完整流程。
        """
        return DAILY_SUMMARY_RECIPE

    @mcp.resource("xwatcher://recipes/claude-code-summarize")
    async def claude_code_summarize_recipe() -> str:
        """Claude Code 翻译工作流配方。

        使用 Claude Code 替代外部 LLM API，
        直接在上下文中完成推文翻译和摘要生成。
        """
        return CLAUDE_CODE_SUMMARIZE_RECIPE
