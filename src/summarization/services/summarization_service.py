"""摘要翻译编排服务。

协调缓存、LLM 调用、数据持久化，实现完整的摘要翻译流程。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from returns.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.data_layer.provider import get_summary_repo
from src.summarization.domain.language_utils import is_chinese_dominant
from src.summarization.domain.models import (
    CostStats,
    LLMErrorType,
    LLMResponse,
    PromptConfig,
    SummaryRecord,
    SummaryResult,
    TweetFailure,
    TweetType,
)
from src.summarization.llm.base import LLMProvider, classify_error
from src.summarization.logging_utils import get_summary_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.summarization.llm.config import LLMProviderConfig

logger = logging.getLogger(__name__)
structured_logger = get_summary_logger()


# 内存缓存类型
_CacheEntry = tuple[LLMResponse, datetime]  # (响应, 缓存时间)

# 全局 LLM 并发限制（进程级别，所有 SummarizationService 实例共享）
# 防止多个后台摘要任务同时发起过多 LLM 请求导致限流
_global_llm_semaphore: asyncio.Semaphore | None = None
_GLOBAL_MAX_CONCURRENT_LLM = 3


class LLMResponseParseError(ValueError):
    """LLM 响应彻底无法解析为摘要字段。"""


def _get_global_llm_semaphore() -> asyncio.Semaphore:
    """获取全局 LLM 并发限制 Semaphore（懒初始化）。"""
    global _global_llm_semaphore
    if _global_llm_semaphore is None:
        _global_llm_semaphore = asyncio.Semaphore(_GLOBAL_MAX_CONCURRENT_LLM)
    return _global_llm_semaphore


class SummarizationService:
    """摘要翻译编排服务。

    协调整个摘要翻译流程，包括：
    - 处理推文摘要
    - 内存缓存管理
    - LLM 调用与降级
    - 结果持久化
    - 并发控制
    """

    # 默认配置
    DEFAULT_MAX_CONCURRENT = 5
    DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 天
    DEFAULT_MAX_TOKENS = 2048
    TRUNCATION_RETRY_MAX_TOKENS = 4096

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        providers: Sequence[LLMProvider],
        prompt_config: PromptConfig | None = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        """初始化摘要服务。

        Args:
            session_factory: 异步会话工厂，每个并发协程会创建独立的 session
            providers: LLM 提供商列表（按优先级排序）
            prompt_config: Prompt 配置
            max_concurrent: 最大并发数
            cache_ttl_seconds: 缓存有效期（秒）
        """
        self._session_factory = session_factory
        self._providers = list(providers)
        self._prompt_config = prompt_config or PromptConfig()
        self._max_concurrent = max_concurrent
        self._cache_ttl_seconds = cache_ttl_seconds

        # 内存缓存
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = asyncio.Lock()
        self._non_retryable_failed_tweet_ids: set[str] | None = None

    async def summarize_tweets(
        self,
        tweet_ids: list[str],
        force_refresh: bool = False,
    ) -> Result[SummaryResult, Exception]:
        """对指定推文执行摘要和翻译。

        Args:
            tweet_ids: 推文 ID 列表
            force_refresh: 是否强制刷新缓存

        Returns:
            Result[SummaryResult, Exception]: 处理统计结果
        """
        start_time = time.time()

        try:
            all_results, all_failures = (
                await self._process_independent_tweets_concurrent(
                    tweet_ids, force_refresh
                )
            )

            # 检查是否有任何成功的摘要生成
            if tweet_ids and not all_results:
                if tweet_ids:
                    return Failure(
                        Exception("所有 LLM 提供商调用失败，无法生成摘要")
                    )

            # 汇总统计
            summary_result = self._calculate_summary_result(
                tweet_ids, all_results,
                start_time,
                failed_tweets=all_failures,
            )

            # 使用结构化日志记录批量完成事件
            structured_logger.log_summary_batch_completed(
                total_tweets=summary_result.total_tweets,
                cache_hits=summary_result.cache_hits,
                cache_misses=summary_result.cache_misses,
                total_tokens=summary_result.total_tokens,
                total_cost_usd=summary_result.total_cost_usd,
                processing_time_ms=summary_result.processing_time_ms,
                providers_used=summary_result.providers_used,
            )

            # 同时保留传统日志
            failed_msg = f", 失败 {len(all_failures)}" if all_failures else ""
            logger.info(
                f"摘要完成: 处理 {summary_result.total_tweets} 条推文, "
                f"成功 {summary_result.total_tweets_succeeded}{failed_msg}, "
                f"缓存命中 {summary_result.cache_hits}, "
                f"耗时 {summary_result.processing_time_ms}ms"
            )

            return Success(summary_result)

        except Exception as e:
            logger.error(f"摘要处理失败: {e}")
            return Failure(e)

    async def regenerate_summary(
        self, tweet_id: str
    ) -> Result[SummaryRecord, Exception]:
        """强制重新生成单条推文的摘要。

        Args:
            tweet_id: 推文 ID

        Returns:
            Result[SummaryRecord, Exception]: 摘要记录
        """
        try:
            result = await self._process_single_tweet(
                tweet_id, force_refresh=True
            )

            if not result:
                return Failure(ValueError("摘要生成失败"))

            return Success(result)

        except Exception as e:
            logger.error(f"重新生成摘要失败 (tweet_id={tweet_id}): {e}")
            return Failure(e)

    async def get_cost_stats(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Result[CostStats, Exception]:
        """获取成本统计。

        Args:
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            Result[CostStats, Exception]: 成本统计结果
        """
        try:
            async with self._session_factory() as session:
                repository = get_summary_repo(session)
                stats = await repository.get_cost_stats(start_date, end_date)
                return Success(stats)

        except Exception as e:
            logger.error(f"获取成本统计失败: {e}")
            return Failure(e)

    async def _load_tweets(
        self,
        tweet_ids: list[str],
        session: AsyncSession | None = None,
    ) -> dict[str, dict[str, str | None]]:
        """从数据层加载推文文本和元数据(经 provider 门面,消除直查 ORM)。

        委派 get_summarization_read_repo().get_tweet_origins(tweet_ids),返回每条 6 字段
        dict(text/referenced_tweet_text/reference_type/referenced_tweet_id/author_username/
        referenced_tweet_author_username),reference_type 为字符串,与原内联查询同形。

        - file 模式:走文件层门面(忽略 session)。
        - sqlalchemy 模式:保留 session=None 回退语义(不提供时创建临时 session)。

        Args:
            tweet_ids: 推文 ID 列表
            session: 可选的已有 session（不提供时创建临时 session；file 模式忽略）

        Returns:
            推文 ID 到 {"text": ..., "reference_type": ..., ...} 的映射字典
        """
        from src.data_layer.provider import get_summarization_read_repo, is_file_mode

        if is_file_mode():
            return await get_summarization_read_repo().get_tweet_origins(tweet_ids)
        if session is not None:
            return await get_summarization_read_repo(session).get_tweet_origins(tweet_ids)
        async with self._session_factory() as new_session:
            return await get_summarization_read_repo(new_session).get_tweet_origins(tweet_ids)

    async def _process_independent_tweets_concurrent(
        self,
        tweet_ids: list[str],
        force_refresh: bool,
    ) -> tuple[list[SummaryRecord], list[TweetFailure]]:
        """并发处理独立推文（无去重组的推文），收集失败信息并重试。

        Args:
            tweet_ids: 推文 ID 列表
            force_refresh: 是否强制刷新

        Returns:
            (成功的摘要记录列表, 失败的推文列表)
        """
        semaphore = asyncio.Semaphore(self._max_concurrent)
        results: list[SummaryRecord] = []
        non_retryable_failed_ids: set[str] = set()
        previous_non_retryable_failed_ids = self._non_retryable_failed_tweet_ids
        self._non_retryable_failed_tweet_ids = non_retryable_failed_ids

        async def process_with_limit(
            tweet_id: str,
        ) -> tuple[str, SummaryRecord | None]:
            async with semaphore:
                record = await self._process_single_tweet(tweet_id, force_refresh)
                return tweet_id, record

        try:
            tasks = [process_with_limit(tid) for tid in tweet_ids]
            processed = await asyncio.gather(*tasks)

            failed_ids: list[str] = []
            for tid, result in processed:
                if result:
                    results.append(result)
                else:
                    failed_ids.append(tid)

            # 对 LLM 临时失败保留 1 次重试；解析彻底失败不自动重试，回到未摘要。
            retry_ids = [
                tid for tid in failed_ids if tid not in non_retryable_failed_ids
            ]
            failed_ids = [
                tid for tid in failed_ids if tid in non_retryable_failed_ids
            ]

            if retry_ids:
                logger.info(
                    f"重试 {len(retry_ids)} 条失败的独立推文，等待 5 秒...",
                    extra={
                        "event": "tweet_retry",
                        "retry_attempt": 1,
                        "wait_seconds": 5,
                        "total_tweets": len(retry_ids),
                    },
                )
                await asyncio.sleep(5)
                retry_tasks = [process_with_limit(tid) for tid in retry_ids]
                retry_processed = await asyncio.gather(*retry_tasks)
                for tid, result in retry_processed:
                    if result:
                        results.append(result)
                    else:
                        failed_ids.append(tid)

            # 记录最终仍失败的推文
            failures: list[TweetFailure] = []
            for tid in failed_ids:
                retry_note = (
                    "不自动重试"
                    if tid in non_retryable_failed_ids
                    else "含重试"
                )
                failures.append(TweetFailure(
                    tweet_id=tid,
                    error_type="llm_failure",
                    error_message=f"推文 {tid} 处理失败（{retry_note}）",
                    group_id=None,
                ))

            return results, failures
        finally:
            self._non_retryable_failed_tweet_ids = previous_non_retryable_failed_ids

    @staticmethod
    def _extract_original_author(text: str, tweet_type: TweetType) -> str | None:
        """从推文文本中提取被转推/引用的原作者用户名。

        对于转推，从 "RT @username: ..." 格式中提取。

        Args:
            text: 推文文本
            tweet_type: 推文类型

        Returns:
            原作者用户名或 None
        """
        if tweet_type == TweetType.retweeted:
            match = re.match(r"RT @(\w+):", text)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _determine_tweet_type(reference_type: str | None) -> TweetType:
        """根据 reference_type 判断推文类型。

        Args:
            reference_type: 数据库中的 reference_type 值

        Returns:
            TweetType 枚举值
        """
        if reference_type == "retweeted":
            return TweetType.retweeted
        elif reference_type == "quoted":
            return TweetType.quoted
        elif reference_type == "replied_to":
            return TweetType.replied_to
        return TweetType.original

    async def _process_single_tweet(
        self,
        tweet_id: str,
        force_refresh: bool,
    ) -> SummaryRecord | None:
        """处理单条独立推文（无去重组）。

        每次调用创建独立的 session，避免并发协程共享 session 导致冲突。

        Args:
            tweet_id: 推文 ID
            force_refresh: 是否强制刷新

        Returns:
            摘要记录或 None（处理失败时）
        """
        try:
            # 缓存键基于 tweet_id（不依赖去重组）
            content_hash = self._compute_hash(tweet_id, "standalone")

            # 检查内存缓存（不需要 DB session）
            if not force_refresh:
                cached = await self._get_from_cache(content_hash)
                if cached:
                    logger.debug(f"缓存命中（独立推文）: {content_hash[:8]}...")
                    structured_logger.log_cache_hit(
                        tweet_id=tweet_id,
                        content_hash=content_hash,
                    )
                    async with self._session_factory() as session:
                        repository = get_summary_repo(session)
                        summary = await repository.find_by_content_hash(
                            content_hash
                        )
                        if summary:
                            summary.cached = True
                            return summary

            logger.debug(f"缓存未命中，生成摘要（独立推文）: {content_hash[:8]}...")
            structured_logger.log_cache_miss(
                tweet_id=tweet_id,
                content_hash=content_hash,
            )

            # 使用独立 session 加载推文数据
            async with self._session_factory() as session:
                tweets_map = await self._load_tweets([tweet_id], session)

            tweet_data = tweets_map.get(tweet_id, {})
            tweet_text = tweet_data.get("text") or ""
            reference_type = tweet_data.get("reference_type")
            referenced_tweet_id = tweet_data.get("referenced_tweet_id")
            referenced_tweet_text = tweet_data.get("referenced_tweet_text")
            author_username = tweet_data.get("author_username")

            # 判断推文类型
            tweet_type = self._determine_tweet_type(reference_type)

            # 转推复用原推摘要：如果原推已有摘要，直接复用，避免重复调用 LLM
            if (
                tweet_type == TweetType.retweeted
                and referenced_tweet_id
                and not force_refresh
            ):
                async with self._session_factory() as session:
                    repository = get_summary_repo(session)
                    original_summary = await repository.get_summary_by_tweet(
                        referenced_tweet_id
                    )
                    if original_summary:
                        logger.info(
                            f"转推复用原推摘要: tweet={tweet_id[:12]}..., "
                            f"original={referenced_tweet_id[:12]}..."
                        )
                        # 创建此转推自己的摘要记录（复用原推文本）
                        record = SummaryRecord(
                            summary_id=str(uuid.uuid4()),
                            tweet_id=tweet_id,
                            summary_text=original_summary.summary_text,
                            translation_text=original_summary.translation_text,
                            model_provider=original_summary.model_provider,
                            model_name=original_summary.model_name,
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0,
                            cost_usd=0.0,
                            cached=True,
                            is_generated_summary=original_summary.is_generated_summary,
                            content_hash=content_hash,
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                        # 保存到数据库
                        await repository.save_summary_record(record)
                        await session.commit()
                        return record

            # 提取原作者：优先使用数据库存储的原作者，fallback 到正则提取
            original_author = (
                tweet_data.get("referenced_tweet_author_username")
                or self._extract_original_author(tweet_text, tweet_type)
            )

            # 用完整的被引用推文内容增强摘要输入
            if referenced_tweet_text:
                if tweet_type == TweetType.retweeted:
                    tweet_text = referenced_tweet_text
                elif tweet_type == TweetType.quoted:
                    tweet_text = (
                        f"{tweet_text}\n\n[引用原文]: {referenced_tweet_text}"
                    )
                elif tweet_type == TweetType.replied_to:
                    # 回复推文：拼接被回复原文 + 回复内容，提供上下文
                    tweet_text = (
                        f"[被回复原文]: {referenced_tweet_text}\n\n[回复]: {tweet_text}"
                    )

            # 智能摘要策略：根据语言选择阈值，检查推文长度
            tweet_length = len(tweet_text)
            if is_chinese_dominant(tweet_text):
                min_threshold = self._prompt_config.min_tweet_length_for_summary_chinese
            else:
                min_threshold = self._prompt_config.min_tweet_length_for_summary
            is_short = tweet_length < min_threshold

            if is_short:
                logger.info(
                    f"短推文 ({tweet_length}字 < {min_threshold})，"
                    f"仅翻译不摘要: {tweet_id[:8]}..."
                )
                structured_logger.log_summary_skipped(
                    tweet_id=tweet_id,
                    reason="tweet_too_short",
                    tweet_length=tweet_length,
                    threshold=min_threshold,
                )

            # 调用 LLM 生成摘要+翻译 —— 不需要 DB session
            result = await self._call_llm_with_fallback(
                tweet_id,
                content_hash,
                tweet_text,
                tweet_type=tweet_type,
                is_short=is_short,
                author_username=author_username,
                original_author=original_author,
            )

            if isinstance(result, Failure):
                error = result.failure()
                logger.error(f"LLM 调用失败（独立推文）: {error}")
                structured_logger.log_summary_error(
                    tweet_id=tweet_id,
                    error_type="llm_call_failed",
                    error_message=str(error),
                )
                return None

            llm_response = result.unwrap()

            # 解析响应
            try:
                summary_text, translation_text = self._parse_llm_response(llm_response.content)
            except LLMResponseParseError as error:
                logger.error(f"LLM 响应解析失败（独立推文）: {error}")
                structured_logger.log_summary_error(
                    tweet_id=tweet_id,
                    error_type="llm_response_parse_failed",
                    error_message=str(error),
                )
                if self._non_retryable_failed_tweet_ids is not None:
                    self._non_retryable_failed_tweet_ids.add(tweet_id)
                return None

            # 短推文：summary_text 使用特殊标记
            if is_short:
                summary_text = "[SHORT]"

            # 创建摘要记录
            record = SummaryRecord(
                summary_id=str(uuid.uuid4()),
                tweet_id=tweet_id,
                summary_text=summary_text,
                translation_text=translation_text,
                model_provider=llm_response.provider,  # type: ignore
                model_name=llm_response.model,
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
                total_tokens=llm_response.total_tokens,
                cost_usd=llm_response.cost_usd,
                cached=False,
                is_generated_summary=not is_short,
                content_hash=content_hash,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            # 使用独立 session 保存到数据库并提交
            async with self._session_factory() as session:
                repository = get_summary_repo(session)
                await repository.save_summary_record(record)
                await session.commit()

            # 保存到内存缓存
            await self._set_cache(content_hash, llm_response)

            return record

        except Exception as e:
            logger.error(
                f"处理独立推文失败 (tweet_id={tweet_id}, "
                f"error_type={type(e).__name__}): {e}",
                exc_info=True,
            )
            return None

    async def _call_llm_with_fallback(
        self,
        tweet_id: str,
        content_hash: str,
        tweet_text: str,
        tweet_type: TweetType = TweetType.original,
        is_short: bool = False,
        author_username: str | None = None,
        original_author: str | None = None,
        subjects: list[dict[str, str]] | None = None,
    ) -> Result[LLMResponse, Exception]:
        """调用 LLM 并实现降级策略。

        按顺序尝试提供商：OpenRouter → MiniMax → OpenSource
        临时错误重试 1 次，永久错误立即降级。

        Args:
            tweet_id: 推文 ID
            content_hash: 内容哈希
            tweet_text: 推文文本内容
            tweet_type: 推文类型
            is_short: 是否为短推文（仅翻译不摘要）
            author_username: 发布推文的用户名
            original_author: 被转推/引用的原作者用户名
            subjects: active 议题清单

        Returns:
            Result[LLMResponse, Exception]: LLM 响应或错误
        """
        last_error: Exception | None = None

        # 获取全局并发限制，防止多个后台任务同时发起过多 LLM 请求
        global_semaphore = _get_global_llm_semaphore()

        async with global_semaphore:
            for idx, provider in enumerate(self._providers):
                try:
                    # 生成统一的摘要+翻译 Prompt
                    prompt = self._prompt_config.format_unified_prompt(
                        tweet_text, tweet_type, is_short,
                        author_username=author_username,
                        original_author=original_author,
                        subjects=subjects,
                    )

                    # 尝试调用
                    result = await self._call_llm_with_retry(provider, prompt)

                    if isinstance(result, Success):
                        logger.info(
                            f"LLM 调用成功: {provider.get_provider_name()}, "
                            f"hash={content_hash[:8]}..."
                        )
                        # 使用结构化日志记录成功
                        llm_response = result.unwrap()
                        structured_logger.log_provider_call_success(
                            provider=provider.get_provider_name(),
                            model=provider.get_model_name(),
                            tweet_id=tweet_id,
                            tokens=llm_response.total_tokens,
                            cost_usd=llm_response.cost_usd,
                        )
                        return result

                    # 记录错误
                    error = result.failure()
                    last_error = error

                    # 检查错误类型
                    error_type = self._classify_error_from_exception(error)

                    # 获取下一个提供商（用于日志）
                    next_provider = (
                        self._providers[idx + 1].get_provider_name()
                        if idx + 1 < len(self._providers)
                        else None
                    )

                    # 使用结构化日志记录降级
                    structured_logger.log_provider_degradation(
                        from_provider=provider.get_provider_name(),
                        to_provider=next_provider,
                        error_type=error_type.value if error_type else "unknown",
                        error_message=str(error),
                    )

                    if error_type == LLMErrorType.permanent:
                        # 永久错误：立即降级
                        logger.warning(
                            f"提供商 {provider.get_provider_name()} 返回永久错误，"
                            f"尝试下一个提供商: {error}"
                        )
                        continue

                    elif error_type == LLMErrorType.temporary:
                        # 临时错误：记录但继续降级
                        logger.warning(
                            f"提供商 {provider.get_provider_name()} 返回临时错误，"
                            f"尝试下一个提供商: {error}"
                        )
                        continue

                    else:
                        # 未知错误类型：降级
                        logger.warning(
                            f"提供商 {provider.get_provider_name()} 返回未知错误，"
                            f"尝试下一个提供商: {error}"
                        )
                        continue

                except Exception as e:
                    last_error = e
                    # 使用结构化日志记录异常
                    structured_logger.log_provider_degradation(
                        from_provider=provider.get_provider_name(),
                        to_provider=(
                            self._providers[idx + 1].get_provider_name()
                            if idx + 1 < len(self._providers)
                            else None
                        ),
                        error_type="exception",
                        error_message=str(e),
                    )
                    logger.warning(
                        f"提供商 {provider.get_provider_name()} 调用异常: {e}"
                    )
                    continue

            # 所有提供商都失败
            error_message = (
                f"所有 LLM 提供商调用失败 (hash={content_hash[:8]}...), "
                f"最后错误: {last_error}"
            )
            logger.error(error_message)
            return Failure(Exception(error_message))

    async def _call_llm_with_retry(
        self,
        provider: LLMProvider,
        prompt: str,
        max_tokens: int | None = None,
    ) -> Result[LLMResponse, Exception]:
        """调用 LLM 并在临时错误时重试一次。

        当检测到输出被截断（finish_reason="length"）时，
        使用更大的 max_tokens 重试一次。

        Args:
            provider: LLM 提供商
            prompt: 输入提示词
            max_tokens: 最大输出 token 数，默认使用 DEFAULT_MAX_TOKENS

        Returns:
            Result[LLMResponse, Exception]: LLM 响应或错误
        """
        actual_max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS
        result = await provider.complete(prompt, max_tokens=actual_max_tokens)

        if isinstance(result, Failure):
            error = result.failure()
            error_type = self._classify_error_from_exception(error)

            if error_type == LLMErrorType.temporary:
                # 临时错误：退避 2 秒后重试一次
                logger.warning(
                    f"LLM 临时错误，等待 2 秒后重试: {error}",
                    extra={
                        "event": "llm_retry",
                        "provider": provider.get_provider_name(),
                        "error_type": type(error).__name__,
                        "retry_attempt": 1,
                        "wait_seconds": 2,
                    },
                )
                await asyncio.sleep(2)
                result = await provider.complete(
                    prompt, max_tokens=actual_max_tokens
                )

            return result

        # 检测截断：finish_reason == "length"
        llm_response = result.unwrap()
        if (
            llm_response.finish_reason == "length"
            and actual_max_tokens < self.TRUNCATION_RETRY_MAX_TOKENS
        ):
            logger.warning(
                f"LLM 输出被截断 (finish_reason=length, "
                f"completion_tokens={llm_response.completion_tokens}, "
                f"max_tokens={actual_max_tokens})，"
                f"使用 max_tokens={self.TRUNCATION_RETRY_MAX_TOKENS} 重试"
            )
            # 用更大的 max_tokens 重试一次
            retry_result = await provider.complete(
                prompt, max_tokens=self.TRUNCATION_RETRY_MAX_TOKENS
            )
            if isinstance(retry_result, Success):
                retry_response = retry_result.unwrap()
                if retry_response.finish_reason == "length":
                    logger.warning(
                        f"重试后仍被截断 "
                        f"(completion_tokens={retry_response.completion_tokens})"
                    )
                return retry_result
            # 重试失败（API 错误等），返回原始截断结果而非 Failure
            logger.warning("截断重试失败，返回原始截断结果")
            return result

        return result

    def _classify_error_from_exception(
        self, error: Exception
    ) -> LLMErrorType | None:
        """从异常中分类错误类型。

        Args:
            error: 异常对象

        Returns:
            错误类型或 None
        """
        # 检查是否有 error_type 属性（自定义错误类）
        if hasattr(error, "error_type"):
            error_type = getattr(error, "error_type")
            if error_type is not None:
                return error_type

        # 检查是否有 status_code 属性
        if hasattr(error, "status_code"):
            status_code = getattr(error, "status_code")
            if status_code is not None:
                return classify_error(int(status_code))

        # 默认为 None（未知类型）
        return None

    def _parse_llm_response(
        self,
        content: str,
    ) -> tuple[str, str | None]:
        """解析 LLM 响应内容。

        期望 JSON 格式: {"summary": "...", "translation": "..."}
        支持清理 markdown 代码块标记和修复常见 JSON 格式问题。

        Args:
            content: LLM 返回的内容

        Returns:
            返回 (摘要文本, 翻译文本)，保持旧单测与调试调用兼容。

        Raises:
            LLMResponseParseError: 响应彻底无法解析出摘要字段
        """
        # 清理 markdown 代码块标记
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # 尝试 JSON 解析（直接解析 → 修复引号后解析 → 正则提取）
        data = self._try_parse_json(cleaned)

        if data is None:
            # 尝试修复 LLM 常见问题：JSON 字符串值内的未转义双引号
            fixed = self._fix_json_unescaped_quotes(cleaned)
            if fixed != cleaned:
                data = self._try_parse_json(fixed)

        if data is None:
            # 用正则按字段名提取值
            data = self._extract_fields_by_regex(cleaned)

        if data is not None and isinstance(data, dict):
            summary = data.get("summary")
            translation = data.get("translation")
            if summary is None or summary == "null":
                summary = "[SHORT]"
            return summary, translation if translation else None

        # JSON 解析彻底失败
        preview = content[:200].replace("\n", " ")
        raise LLMResponseParseError(
            f"JSON 解析失败，内容无法提取有效摘要: {preview}..."
        )

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """尝试解析 JSON 文本。"""
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    @staticmethod
    def _fix_json_unescaped_quotes(text: str) -> str:
        """修复 LLM 生成的 JSON 中未转义的双引号。

        LLM 经常在 JSON 字符串值内输出未转义的双引号（如中文引号对 "..."），
        这会导致 json.loads 失败。通过按字段边界分割来安全提取值。
        """
        # 匹配 JSON 字段模式: "key": "value"
        # 策略：找到所有 "key": " 开头的位置，然后找到对应的结束引号
        # 结束引号的标志是：" 后跟 , 或 } 或换行
        result = re.sub(
            r'"(summary|translation)"\s*:\s*"((?:[^"\\]|\\.|"(?![,}\s]))*)"',
            lambda m: f'"{m.group(1)}": "{m.group(2).replace(chr(34), chr(8220))}"',
            text,
        )
        # 将替换的中文引号恢复为转义引号
        result = result.replace(chr(8220), '\\"')
        return result

    @staticmethod
    def _extract_fields_by_regex(text: str) -> dict | None:
        """用正则从文本中按字段名提取 summary 和 translation。"""
        result = {}

        # 匹配 "summary": "..." 或 "summary": null
        for field in ("summary", "translation"):
            # 匹配 null 值
            null_match = re.search(rf'"{field}"\s*:\s*null', text)
            if null_match:
                result[field] = None
                continue

            # 匹配字符串值：找 "field": " 后面的内容直到匹配的结束标记
            # 结束标记："}\n 或 ",\n 或 " 在行尾
            pattern = rf'"{field}"\s*:\s*"(.*?)"(?:\s*[,}}\n])'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                result[field] = match.group(1).replace('\\"', '"')

        return result if result else None

    def _compute_hash(self, content: str, task: str = "summary") -> str:
        """计算内容哈希用于缓存键。

        Args:
            content: 内容字符串
            task: 任务类型

        Returns:
            SHA256 哈希值（十六进制）
        """
        hash_input = f"{task}:{content}"
        return hashlib.sha256(hash_input.encode()).hexdigest()

    async def _get_from_cache(self, content_hash: str) -> LLMResponse | None:
        """从内存缓存获取响应。

        Args:
            content_hash: 内容哈希

        Returns:
            LLM 响应或 None
        """
        async with self._cache_lock:
            entry = self._cache.get(content_hash)
            if entry:
                response, cached_time = entry
                age = (datetime.now(timezone.utc) - cached_time).total_seconds()

                if age < self._cache_ttl_seconds:
                    return response
                else:
                    # 缓存过期，删除
                    del self._cache[content_hash]

        return None

    async def _set_cache(self, content_hash: str, response: LLMResponse) -> None:
        """设置内存缓存。

        Args:
            content_hash: 内容哈希
            response: LLM 响应
        """
        async with self._cache_lock:
            self._cache[content_hash] = (response, datetime.now(timezone.utc))

    def _calculate_summary_result(
        self,
        tweet_ids: list[str],
        summaries: list[SummaryRecord],
        start_time: float,
        failed_tweets: list[TweetFailure] | None = None,
    ) -> SummaryResult:
        """计算摘要处理结果统计。

        Args:
            tweet_ids: 原始推文 ID 列表
            summaries: 生成的摘要列表
            start_time: 开始时间
            failed_tweets: 失败的推文列表

        Returns:
            摘要结果统计
        """
        if failed_tweets is None:
            failed_tweets = []

        # 统计缓存命中
        cache_hits = sum(1 for s in summaries if s.cached)
        cache_misses = len(summaries) - cache_hits

        # 统计 token 和成本
        total_tokens = sum(s.total_tokens for s in summaries)
        total_cost_usd = sum(s.cost_usd for s in summaries)

        # 统计提供商使用
        providers_used: dict[str, int] = {}
        for s in summaries:
            if not s.cached:
                providers_used[s.model_provider] = (
                    providers_used.get(s.model_provider, 0) + 1
                )

        # 序列化失败推文信息
        failed_dicts = [
            {
                "tweet_id": f.tweet_id,
                "error_type": f.error_type,
                "error_message": f.error_message,
            }
            for f in failed_tweets
        ]

        return SummaryResult(
            total_tweets=len(tweet_ids),
            total_tweets_succeeded=len(summaries),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            providers_used=providers_used,
            processing_time_ms=int((time.time() - start_time) * 1000),
            failed_tweets=failed_dicts,
        )

    async def clear_cache(self) -> None:
        """清空内存缓存。"""
        async with self._cache_lock:
            self._cache.clear()
        logger.info("内存缓存已清空")

    async def get_cache_size(self) -> int:
        """获取缓存大小。

        Returns:
            缓存条目数
        """
        async with self._cache_lock:
            return len(self._cache)


def create_summarization_service(
    session_factory: async_sessionmaker[AsyncSession],
    config: "LLMProviderConfig",
    prompt_config: PromptConfig | None = None,
    max_concurrent: int = SummarizationService.DEFAULT_MAX_CONCURRENT,
) -> SummarizationService:
    """创建摘要服务实例。

    Args:
        session_factory: 异步会话工厂
        config: LLM 提供商配置
        prompt_config: Prompt 配置
        max_concurrent: 最大并发数

    Returns:
        摘要服务实例

    Raises:
        ValueError: 没有配置任何提供商时抛出
    """
    providers: list[LLMProvider] = _build_providers_from_config(config)

    if not providers:
        raise ValueError("至少需要配置一个 LLM 提供商")

    return SummarizationService(
        session_factory=session_factory,
        providers=providers,
        prompt_config=prompt_config,
        max_concurrent=max_concurrent,
    )


def _build_providers_from_config(config: "LLMProviderConfig") -> list[LLMProvider]:
    """根据配置构建 LLM 提供商列表。

    优先使用新的统一格式（unified_providers），回退到旧格式。

    Args:
        config: LLM 提供商聚合配置

    Returns:
        按优先级排序的提供商列表
    """
    from src.summarization.llm.openai_compatible import OpenAICompatibleProvider

    providers: list[LLMProvider] = []

    # 优先使用新格式
    if config.uses_unified_format():
        for inst in config.unified_providers:
            try:
                providers.append(
                    OpenAICompatibleProvider.from_preset(
                        slug=inst.slug,
                        api_key=inst.api_key,
                        base_url=inst.base_url or None,
                        model=inst.model or None,
                        timeout_seconds=inst.timeout_seconds,
                        max_retries=inst.max_retries,
                    )
                )
            except ValueError:
                # 未知 slug 时使用 custom 模式
                providers.append(
                    OpenAICompatibleProvider(
                        provider_name=inst.slug,
                        api_key=inst.api_key,
                        base_url=inst.base_url,
                        model=inst.model,
                        timeout_seconds=inst.timeout_seconds,
                        max_retries=inst.max_retries,
                    )
                )
        return providers

    # 回退到旧格式
    if config.openrouter:
        providers.append(
            OpenAICompatibleProvider(
                provider_name="openrouter",
                api_key=config.openrouter.api_key,
                base_url=config.openrouter.base_url,
                model=config.openrouter.model,
                timeout_seconds=config.openrouter.timeout_seconds,
                max_retries=config.openrouter.max_retries,
                cost_info=None,  # 使用默认值
            )
        )

    if config.minimax:
        from src.summarization.llm.presets import MINIMAX

        providers.append(
            OpenAICompatibleProvider(
                provider_name="minimax",
                api_key=config.minimax.api_key,
                base_url=config.minimax.base_url,
                model=config.minimax.model,
                timeout_seconds=config.minimax.timeout_seconds,
                max_retries=config.minimax.max_retries,
                cost_info=MINIMAX.cost_info,
            )
        )

    if config.open_source:
        providers.append(
            OpenAICompatibleProvider(
                provider_name="open_source",
                api_key=config.open_source.api_key,
                base_url=config.open_source.base_url,
                model=config.open_source.model,
                timeout_seconds=config.open_source.timeout_seconds,
                max_retries=config.open_source.max_retries,
            )
        )

    return providers
