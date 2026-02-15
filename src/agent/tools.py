"""Feed API 工具元数据定义。

为 nanobot Agent 提供工具注册信息，描述可用的 API 端点。
"""

from typing import Any

FEED_TOOLS: list[dict[str, Any]] = [
    {
        "name": "fetch_feed",
        "description": "按时间区间获取推文列表（含摘要和翻译），支持增量拉取",
        "endpoint": "GET /api/feed",
        "parameters": {
            "since": {
                "type": "string",
                "format": "ISO 8601 datetime",
                "required": True,
                "description": "推文发布时间起始（含），ISO 8601 格式",
            },
            "until": {
                "type": "string",
                "format": "ISO 8601 datetime",
                "required": False,
                "description": "推文发布时间截止（不含），默认当前服务器时间",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "description": "最大返回条数，默认使用系统配置上限（200）",
            },
            "include_summary": {
                "type": "boolean",
                "required": False,
                "default": True,
                "description": "是否包含摘要和翻译内容",
            },
        },
        "authentication": "X-API-Key header",
        "response_fields": [
            "items",
            "count",
            "total",
            "since",
            "until",
            "has_more",
        ],
    },
    {
        "name": "fetch_tweet_detail",
        "description": "获取单条推文详情，包含完整信息、摘要和去重信息",
        "endpoint": "GET /api/tweets/{tweet_id}",
        "parameters": {
            "tweet_id": {
                "type": "string",
                "required": True,
                "description": "推文唯一 ID",
            },
        },
        "authentication": "None (public endpoint)",
    },
]


SUMMARY_REPAIR_TOOLS: list[dict[str, Any]] = [
    {
        "name": "summary_backfill",
        "description": "批量为缺少摘要的推文生成摘要和翻译",
        "endpoint": "POST /api/summaries/backfill",
        "parameters": {
            "since": {
                "type": "string",
                "format": "ISO 8601 datetime",
                "required": False,
                "description": "起始时间（含），ISO 8601 格式，可选",
            },
            "until": {
                "type": "string",
                "format": "ISO 8601 datetime",
                "required": False,
                "description": "截止时间（不含），ISO 8601 格式，可选",
            },
        },
        "authentication": "X-API-Key header (admin)",
    },
    {
        "name": "summary_reset",
        "description": "指定时间范围重新生成所有推文的摘要和翻译",
        "endpoint": "POST /api/summaries/reset",
        "parameters": {
            "since": {
                "type": "string",
                "format": "ISO 8601 datetime",
                "required": True,
                "description": "起始时间（含），ISO 8601 格式",
            },
            "until": {
                "type": "string",
                "format": "ISO 8601 datetime",
                "required": True,
                "description": "截止时间（不含），ISO 8601 格式",
            },
        },
        "authentication": "X-API-Key header (admin)",
    },
]


def get_feed_tools() -> list[dict[str, Any]]:
    """获取 Feed API 工具元数据列表。"""
    return FEED_TOOLS.copy()


def get_summary_repair_tools() -> list[dict[str, Any]]:
    """获取摘要修复工具元数据列表。"""
    return SUMMARY_REPAIR_TOOLS.copy()
