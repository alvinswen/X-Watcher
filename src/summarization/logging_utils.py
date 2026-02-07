"""摘要服务结构化日志工具。

提供结构化日志记录功能，包含上下文信息。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SummaryLogger:
    """摘要服务结构化日志记录器。

    提供带有上下文信息的结构化日志记录。
    """

    def __init__(self, component: str = "summarization"):
        """初始化日志记录器。

        Args:
            component: 组件名称
        """
        self.component = component
        self._logger = logging.getLogger(f"src.summarization.{component}")

    def log_summary_generated(
        self,
        tweet_id: str,
        provider: str,
        model: str,
        tokens: int,
        cost_usd: float,
        cached: bool = False,
    ) -> None:
        """记录摘要生成事件。

        Args:
            tweet_id: 推文 ID
            provider: 提供商名称
            model: 模型名称
            tokens: token 数量
            cost_usd: 成本（美元）
            cached: 是否来自缓存
        """
        self._logger.info(
            "摘要生成成功",
            extra={
                "event": "summary_generated",
                "tweet_id": tweet_id,
                "provider": provider,
                "model": model,
                "tokens": tokens,
                "cost_usd": cost_usd,
                "cached": cached,
            },
        )

    def log_summary_batch_completed(
        self,
        total_tweets: int,
        total_groups: int,
        cache_hits: int,
        cache_misses: int,
        total_tokens: int,
        total_cost_usd: float,
        processing_time_ms: int,
        providers_used: dict[str, int],
    ) -> None:
        """记录批量摘要完成事件。

        Args:
            total_tweets: 总推文数
            total_groups: 总去重组数
            cache_hits: 缓存命中数
            cache_misses: 缓存未命中数
            total_tokens: 总 token 数
            total_cost_usd: 总成本
            processing_time_ms: 处理耗时（毫秒）
            providers_used: 提供商使用统计
        """
        self._logger.info(
            "批量摘要完成",
            extra={
                "event": "batch_completed",
                "total_tweets": total_tweets,
                "total_groups": total_groups,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost_usd,
                "processing_time_ms": processing_time_ms,
                "providers_used": providers_used,
            },
        )

    def log_provider_degradation(
        self,
        from_provider: str,
        to_provider: str | None,
        error_type: str,
        error_message: str,
    ) -> None:
        """记录提供商降级事件。

        Args:
            from_provider: 原提供商
            to_provider: 降级到的提供商
            error_type: 错误类型
            error_message: 错误信息
        """
        self._logger.warning(
            "提供商降级",
            extra={
                "event": "provider_degradation",
                "from_provider": from_provider,
                "to_provider": to_provider,
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    def log_cache_hit(
        self,
        tweet_id: str,
        content_hash: str,
    ) -> None:
        """记录缓存命中事件。

        Args:
            tweet_id: 推文 ID
            content_hash: 内容哈希
        """
        self._logger.info(
            "缓存命中",
            extra={
                "event": "cache_hit",
                "tweet_id": tweet_id,
                "content_hash": content_hash[:8] + "...",
            },
        )

    def log_cache_miss(
        self,
        tweet_id: str,
        content_hash: str,
    ) -> None:
        """记录缓存未命中事件。

        Args:
            tweet_id: 推文 ID
            content_hash: 内容哈希
        """
        self._logger.debug(
            "缓存未命中",
            extra={
                "event": "cache_miss",
                "tweet_id": tweet_id,
                "content_hash": content_hash[:8] + "...",
            },
        )

    def log_summary_error(
        self,
        tweet_id: str | None,
        error_type: str,
        error_message: str,
        provider: str | None = None,
    ) -> None:
        """记录摘要错误事件。

        Args:
            tweet_id: 推文 ID（可能为 None）
            error_type: 错误类型
            error_message: 错误信息
            provider: 提供商（可能为 None）
        """
        self._logger.error(
            "摘要生成失败",
            extra={
                "event": "summary_error",
                "tweet_id": tweet_id,
                "error_type": error_type,
                "error_message": error_message,
                "provider": provider,
            },
        )

    def log_provider_call_start(
        self,
        provider: str,
        model: str,
        tweet_id: str,
    ) -> None:
        """记录提供商调用开始事件。

        Args:
            provider: 提供商名称
            model: 模型名称
            tweet_id: 推文 ID
        """
        self._logger.debug(
            "LLM 调用开始",
            extra={
                "event": "provider_call_start",
                "provider": provider,
                "model": model,
                "tweet_id": tweet_id,
            },
        )

    def log_provider_call_success(
        self,
        provider: str,
        model: str,
        tweet_id: str,
        tokens: int,
        cost_usd: float,
    ) -> None:
        """记录提供商调用成功事件。

        Args:
            provider: 提供商名称
            model: 模型名称
            tweet_id: 推文 ID
            tokens: token 数量
            cost_usd: 成本
        """
        self._logger.info(
            "LLM 调用成功",
            extra={
                "event": "provider_call_success",
                "provider": provider,
                "model": model,
                "tweet_id": tweet_id,
                "tokens": tokens,
                "cost_usd": cost_usd,
            },
        )

    def log_summary_skipped(
        self,
        tweet_id: str,
        reason: str,
        tweet_length: int,
        threshold: int,
    ) -> None:
        """记录摘要跳过事件（如推文太短）。

        Args:
            tweet_id: 推文 ID
            reason: 跳过原因
            tweet_length: 推文长度
            threshold: 阈值
        """
        self._logger.info(
            "摘要生成跳过",
            extra={
                "event": "summary_skipped",
                "tweet_id": tweet_id,
                "reason": reason,
                "tweet_length": tweet_length,
                "threshold": threshold,
            },
        )


# 全局日志记录器实例
_summary_logger = SummaryLogger()


def get_summary_logger() -> SummaryLogger:
    """获取摘要服务日志记录器实例。

    Returns:
        SummaryLogger: 日志记录器实例
    """
    return _summary_logger
