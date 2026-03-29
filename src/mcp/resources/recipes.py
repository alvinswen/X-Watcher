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


def register(mcp: FastMCP) -> None:
    """注册工作流配方资源。"""

    @mcp.resource("xwatcher://recipes/daily-summary")
    async def daily_summary_recipe() -> str:
        """每日摘要生成工作流配方。

        提供面向 Agent 的分步操作指南，包含时间计算、
        数据就绪检查、摘要生成和交付的完整流程。
        """
        return DAILY_SUMMARY_RECIPE
