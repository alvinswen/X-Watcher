"""MCP 工作流配方资源。

提供面向 Agent 的分步工作流指南，Agent 可在初始化时读取获取操作指引。
"""

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

DAILY_SUMMARY_RECIPE = """\
# 每日摘要生成工作流

## 场景
围绕最近抓取的推文，完成数据补全、摘要/翻译回写和浏览验证。

## 默认参数
- 时间跨度：24 小时
- 抓取范围：默认所有活跃关注账号
- 摘要/翻译：由 Claude Code 读取缺口、生成内容并回写

## 分步流程

### Step 1：触发抓取
调用 `trigger_scrape()`（不传 usernames = 全量抓取）并记录 task_id。

### Step 2：等待抓取完成
轮询 `get_task_status(task_id)` 直到 status == "completed"
- 轮询间隔建议：15 秒
- 典型耗时：2-5 分钟（取决于账号数）

### Step 3：获取摘要缺口
调用 `get_unsummarized_tweets(limit=25, since=<start>, until=<end>)`
- 记录每条推文的 tweet_id：回写时必须从返回**原样复制**（字符串），勿手工拼装、凭记忆重构或改类型
- 如果返回 0 条 → 直接进入浏览验证
- 如果有待处理推文 → 在 Claude Code 上下文中生成中文摘要和翻译

### Step 4：保存结果
调用 `save_summaries(summaries=[...])` 回写生成结果。保存前检查摘要、翻译是否完整。
- tweet_id 必须从 `get_unsummarized_tweets` 返回原样复制（字符串），勿手工拼装、凭记忆重构或改类型
- `save_summaries` 对库内不存在的 tweet_id fail-closed，被拒条目在 `rejected` 数组完整返回
- 按 `rejected[].category` 分流：`transcription_error`=重抄 ID 后重提 / `not_found`=丢弃勿再构造 / `verification_failed`=重译后回灌

### Step 5：浏览验证
调用 `browse_tweets(date=<today>)` 或 `get_feed(since=<start>)`，确认最新推文和摘要可读。

### Step 6：交付
基于浏览到的推文与摘要，向用户输出关注账号的当日要点、重要链接和待跟进事项。

## 错误处理
- 抓取任务失败 → 检查网络连接，建议手动重试
- 没有可抓取账号 → 提示先通过 `manage_follows` 添加或启用关注账号
- 摘要仍缺失 → 继续使用 `get_unsummarized_tweets` 取原文，在 Claude Code 中生成后调用 `save_summaries`

## 工具调用速查
| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 触发抓取 | trigger_scrape | - |
| 监控抓取进度 | get_task_status | task_id |
| 获取摘要缺口 | get_unsummarized_tweets | limit, since, until |
| 保存摘要 | save_summaries | summaries (tweet_id 原样复制;被拒看 rejected[].category) |
| 浏览验证 | browse_tweets / get_feed | date / since |
"""


CLAUDE_CODE_SUMMARIZE_RECIPE = """\
# Claude Code 翻译工作流

## 场景
使用 Claude Code 阅读推文原文，生成中文摘要和翻译，并通过确定性验证门回写。

## 分步流程

### Step 1：抓取推文
调用 `trigger_scrape()` 并记录返回的 task_id。

### Step 2：等待抓取完成
轮询 `get_task_status(task_id)` 直到 status == "completed"
- 轮询间隔建议：15 秒

### Step 3：获取待翻译推文
调用 `get_unsummarized_tweets(limit=25)`
- 可选参数：since/until 时间过滤，author 作者过滤
- 返回推文原文、作者、引用类型等完整上下文
- tweet_id 后续回写必须从返回**原样复制**（字符串），勿手工拼装、凭记忆重构或改类型
- 如果输出被持久化到文件，用 Read 工具读取完整数据；严禁用脚本截断推文文本

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
调用 `save_summaries(summaries=[...])`
- 入参：原生数组 `[{"tweet_id": "...", "summary": "...", "translation": "..."}]`
  （推荐原生数组形态；为兼容旧调用方也接受 JSON 字符串，但不推荐——
  手工拼装 JSON 字符串容易出现引号转义错位类错误）
- 支持批量保存，单条失败不影响其他条目
- tweet_id 必须从 `get_unsummarized_tweets` 返回原样复制（字符串），勿手工拼装、凭记忆重构或改类型
- `save_summaries` 对库内不存在的 tweet_id fail-closed，被拒条目在 `rejected` 数组完整返回
- 按 `rejected[].category` 分流：`transcription_error`=重抄 ID 后重提 / `not_found`=丢弃勿再构造 / `verification_failed`=重译后回灌
- 结果以 model_provider="claude_code" 存储

### Step 6：验证
调用 `browse_tweets(date=<today>)` 确认摘要已生效

## 批量处理建议
- 单次 limit=25（确保输出可直接读取，避免截断）
- 循环执行 Step 3-5 直到返回 0 条
- 保存前自检：翻译不得以"……"结尾（除非原文如此）

## 工具调用速查
| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 抓取 | trigger_scrape | usernames, limit |
| 等待 | get_task_status | task_id |
| 获取待翻译 | get_unsummarized_tweets | limit, since, until |
| 保存结果 | save_summaries | summaries (原生数组,亦兼容 JSON 字符串;tweet_id 原样复制) |
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
