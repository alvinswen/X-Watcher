"""摘要翻译编排服务。

协调缓存、LLM 调用、数据持久化，实现完整的摘要翻译流程。
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from returns.result import Failure, Result, Success

from src.deduplication.domain.models import DeduplicationGroup
from src.summarization.domain.models import (
    CostStats,
    LLMErrorType,
    LLMResponse,
    PromptConfig,
    SummaryRecord,
    SummaryResult,
)
from src.summarization.infrastructure.repository import SummarizationRepository
from src.summarization.logging_utils import get_summary_logger
from src.summarization.llm.base import LLMProvider, classify_error

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.summarization.llm.config import LLMProviderConfig

logger = logging.getLogger(__name__)
structured_logger = get_summary_logger()


# 内存缓存类型
_CacheEntry = tuple[LLMResponse, datetime]  # (响应, 缓存时间)


class SummarizationService:
    """摘要翻译编排服务。

    协调整个摘要翻译流程，包括：
    - 按去重组处理推文
    - 内存缓存管理
    - LLM 调用与降级
    - 结果持久化
    - 并发控制
    """

    # 默认配置
    DEFAULT_MAX_CONCURRENT = 5
    DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 天

    def __init__(
        self,
        repository: SummarizationRepository,
        providers: Sequence[LLMProvider],
        prompt_config: PromptConfig | None = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        """初始化摘要服务。

        Args:
            repository: 摘要仓储
            providers: LLM 提供商列表（按优先级排序）
            prompt_config: Prompt 配置
            max_concurrent: 最大并发数
            cache_ttl_seconds: 缓存有效期（秒）
        """
        self._repository = repository
        self._providers = list(providers)
        self._prompt_config = prompt_config or PromptConfig()
        self._max_concurrent = max_concurrent
        self._cache_ttl_seconds = cache_ttl_seconds

        # 内存缓存
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = asyncio.Lock()

    async def summarize_tweets(
        self,
        tweet_ids: list[str],
        deduplication_groups: list[DeduplicationGroup] | None = None,
        force_refresh: bool = False,
    ) -> Result[SummaryResult, Exception]:
        """对指定推文执行摘要和翻译。

        Args:
            tweet_ids: 推文 ID 列表
            deduplication_groups: 去重组列表（为 None 时从数据库加载）
            force_refresh: 是否强制刷新缓存

        Returns:
            Result[SummaryResult, Exception]: 处理统计结果
        """
        start_time = time.time()

        try:
            # 1. 加载去重组
            if deduplication_groups is None:
                deduplication_groups = await self._load_deduplication_groups(tweet_ids)

            if not deduplication_groups:
                logger.info("没有去重组需要处理")
                return Success(
                    SummaryResult(
                        total_tweets=len(tweet_ids),
                        total_groups=0,
                        cache_hits=0,
                        cache_misses=0,
                        total_tokens=0,
                        total_cost_usd=0.0,
                        providers_used={},
                        processing_time_ms=int((time.time() - start_time) * 1000),
                    )
                )

            # 2. 并发处理每个去重组
            results = await self._process_groups_concurrent(
                deduplication_groups, force_refresh
            )

            # 检查是否有任何成功的摘要生成
            # 如果有去重组但没有成功结果，说明所有提供商都失败了
            if deduplication_groups and not results:
                return Failure(
                    Exception("所有 LLM 提供商调用失败，无法生成摘要")
                )

            # 3. 汇总统计
            summary_result = self._calculate_summary_result(
                tweet_ids, deduplication_groups, results, start_time
            )

            # 使用结构化日志记录批量完成事件
            structured_logger.log_summary_batch_completed(
                total_tweets=summary_result.total_tweets,
                total_groups=summary_result.total_groups,
                cache_hits=summary_result.cache_hits,
                cache_misses=summary_result.cache_misses,
                total_tokens=summary_result.total_tokens,
                total_cost_usd=summary_result.total_cost_usd,
                processing_time_ms=summary_result.processing_time_ms,
                providers_used=summary_result.providers_used,
            )

            # 同时保留传统日志
            logger.info(
                f"摘要完成: 处理 {summary_result.total_tweets} 条推文, "
                f"{summary_result.total_groups} 个去重组, "
                f"缓存命中 {summary_result.cache_hits}/{summary_result.total_groups}, "
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
            # 1. 加载去重组
            group = await self._load_deduplication_groups([tweet_id])
            if not group:
                return Failure(ValueError(f"推文 {tweet_id} 未找到去重组"))

            # 2. 强制刷新处理
            results = await self._process_groups_concurrent(group, force_refresh=True)

            if not results:
                return Failure(ValueError("摘要生成失败"))

            # 返回第一个结果（单条推文只有一个去重组）
            return Success(results[0])

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
            stats = await self._repository.get_cost_stats(start_date, end_date)
            return Success(stats)

        except Exception as e:
            logger.error(f"获取成本统计失败: {e}")
            return Failure(e)

    async def _load_deduplication_groups(
        self, tweet_ids: list[str]
    ) -> list[DeduplicationGroup]:
        """加载推文的去重组。

        Args:
            tweet_ids: 推文 ID 列表

        Returns:
            去重组列表（去重）
        """
        from src.deduplication.infrastructure.repository import (
            DeduplicationRepository,
        )

        dedup_repo = DeduplicationRepository(self._repository._session)
        groups = []

        for tweet_id in tweet_ids:
            group = await dedup_repo.find_by_tweet(tweet_id)
            if group and not any(g.group_id == group.group_id for g in groups):
                groups.append(group)

        return groups

    async def _load_tweets(
        self, tweet_ids: list[str]
    ) -> dict[str, str]:
        """从数据库加载推文文本。

        Args:
            tweet_ids: 推文 ID 列表

        Returns:
            推文 ID 到文本的映射字典
        """
        from sqlalchemy import select
        from src.scraper.infrastructure.models import TweetOrm

        stmt = select(TweetOrm).where(TweetOrm.tweet_id.in_(tweet_ids))
        result = await self._repository._session.execute(stmt)
        orm_tweets = result.scalars().all()

        return {tweet.tweet_id: tweet.text for tweet in orm_tweets}

    async def _process_groups_concurrent(
        self,
        groups: list[DeduplicationGroup],
        force_refresh: bool,
    ) -> list[SummaryRecord]:
        """并发处理去重组。

        Args:
            groups: 去重组列表
            force_refresh: 是否强制刷新

        Returns:
            摘要记录列表
        """
        semaphore = asyncio.Semaphore(self._max_concurrent)
        results = []

        async def process_with_limit(
            group: DeduplicationGroup,
        ) -> SummaryRecord | None:
            async with semaphore:
                return await self._process_deduplication_group(group, force_refresh)

        tasks = [process_with_limit(g) for g in groups]
        processed = await asyncio.gather(*tasks)

        for result in processed:
            if result:
                results.append(result)

        return results

    async def _process_deduplication_group(
        self,
        group: DeduplicationGroup,
        force_refresh: bool,
    ) -> SummaryRecord | None:
        """处理单个去重组。

        Args:
            group: 去重组
            force_refresh: 是否强制刷新

        Returns:
            摘要记录或 None（处理失败时）
        """
        try:
            # 使用代表推文的内容作为摘要输入
            representative_id = group.representative_tweet_id

            # 计算内容哈希
            content_hash = self._compute_hash(
                representative_id, group.deduplication_type.value
            )

            # 检查缓存
            if not force_refresh:
                cached = await self._get_from_cache(content_hash)
                if cached:
                    logger.debug(f"缓存命中: {content_hash[:8]}...")
                    # 使用结构化日志记录缓存命中
                    structured_logger.log_cache_hit(
                        tweet_id=representative_id,
                        content_hash=content_hash,
                    )
                    # 从缓存中获取摘要记录
                    summary = await self._repository.find_by_content_hash(content_hash)
                    if summary:
                        # 更新缓存统计
                        await self._save_summary_for_tweets(
                            group.tweet_ids, summary
                        )
                        return summary

            logger.debug(f"缓存未命中，生成摘要: {content_hash[:8]}...")
            # 使用结构化日志记录缓存未命中
            structured_logger.log_cache_miss(
                tweet_id=representative_id,
                content_hash=content_hash,
            )

            # 加载该去重组的所有推文文本
            tweets_map = await self._load_tweets(group.tweet_ids)
            representative_text = tweets_map.get(representative_id, "")

            # 智能摘要长度策略：检查推文长度
            tweet_length = len(representative_text)
            min_threshold = self._prompt_config.min_tweet_length_for_summary

            if tweet_length < min_threshold:
                # 推文太短，直接返回原文
                logger.info(
                    f"推文长度 ({tweet_length}) 小于阈值 ({min_threshold})，"
                    f"直接返回原文: {representative_id[:8]}..."
                )
                # 使用结构化日志记录
                structured_logger.log_summary_skipped(
                    tweet_id=representative_id,
                    reason="tweet_too_short",
                    tweet_length=tweet_length,
                    threshold=min_threshold,
                )

                # 创建摘要记录（原文直接返回，标记为非生成摘要）
                record = SummaryRecord(
                    summary_id=str(uuid.uuid4()),
                    tweet_id=representative_id,
                    summary_text=representative_text,  # 直接使用原文
                    translation_text=None,  # 短推文不翻译
                    model_provider="open_source",  # 标记为系统处理
                    model_name="original_text",
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    cost_usd=0.0,
                    cached=False,
                    is_generated_summary=False,  # 标记为非生成的摘要
                    content_hash=content_hash,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )

                # 保存到数据库
                await self._repository.save_summary_record(record)

                # 为组内所有推文保存摘要引用
                await self._save_summary_for_tweets(group.tweet_ids, record)

                return record

            # 计算动态摘要长度范围
            min_summary_length = int(
                tweet_length * self._prompt_config.summary_min_length_ratio
            )
            max_summary_length = int(
                tweet_length * self._prompt_config.summary_max_length_ratio
            )

            # 调用 LLM 生成摘要和翻译
            result = await self._call_llm_with_fallback(
                representative_id,
                content_hash,
                representative_text,
                min_summary_length,
                max_summary_length,
            )

            if isinstance(result, Failure):
                # Result 类型使用 failure() 方法获取错误值
                error = result.failure()
                logger.error(f"LLM 调用失败: {error}")
                # 使用结构化日志记录错误
                structured_logger.log_summary_error(
                    tweet_id=representative_id,
                    error_type="llm_call_failed",
                    error_message=str(error),
                )
                return None

            llm_response = result.unwrap()

            # 解析响应（假设 LLM 返回格式为 JSON 或分段文本）
            summary_text, translation_text = self._parse_llm_response(
                llm_response.content
            )

            # 创建摘要记录
            record = SummaryRecord(
                summary_id=str(uuid.uuid4()),
                tweet_id=representative_id,
                summary_text=summary_text,
                translation_text=translation_text,
                model_provider=llm_response.provider,  # type: ignore
                model_name=llm_response.model,
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
                total_tokens=llm_response.total_tokens,
                cost_usd=llm_response.cost_usd,
                cached=False,
                is_generated_summary=True,  # 标记为生成的摘要
                content_hash=content_hash,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            # 保存到数据库
            await self._repository.save_summary_record(record)

            # 保存到内存缓存
            await self._set_cache(content_hash, llm_response)

            # 为组内所有推文保存摘要引用
            await self._save_summary_for_tweets(group.tweet_ids, record)

            return record

        except Exception as e:
            logger.error(f"处理去重组失败 (group_id={group.group_id}): {e}")
            return None

    async def _call_llm_with_fallback(
        self,
        tweet_id: str,
        content_hash: str,
        tweet_text: str,
        min_length: int | None = None,
        max_length: int | None = None,
    ) -> Result[LLMResponse, Exception]:
        """调用 LLM 并实现降级策略。

        按顺序尝试提供商：OpenRouter → MiniMax → OpenSource
        临时错误重试 1 次，永久错误立即降级。

        Args:
            tweet_id: 推文 ID
            content_hash: 内容哈希
            tweet_text: 推文文本内容
            min_length: 摘要最小字数（可选）
            max_length: 摘要最大字数（可选）

        Returns:
            Result[LLMResponse, Exception]: LLM 响应或错误
        """
        last_error: Exception | None = None

        for idx, provider in enumerate(self._providers):
            try:
                # 生成摘要 Prompt - 使用真实的推文文本和动态长度
                prompt = self._prompt_config.format_summary(
                    tweet_text, min_length, max_length
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
    ) -> Result[LLMResponse, Exception]:
        """调用 LLM 并在临时错误时重试一次。

        Args:
            provider: LLM 提供商
            prompt: 输入提示词

        Returns:
            Result[LLMResponse, Exception]: LLM 响应或错误
        """
        result = await provider.complete(prompt)

        if isinstance(result, Failure):
            error = result.failure()
            error_type = self._classify_error_from_exception(error)

            if error_type == LLMErrorType.temporary:
                # 临时错误：重试一次
                logger.debug(f"临时错误，重试一次: {error}")
                result = await provider.complete(prompt)

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

    def _parse_llm_response(self, content: str) -> tuple[str, str | None]:
        """解析 LLM 响应内容。

        假设响应格式为：
        1. JSON: {"summary": "...", "translation": "..."}
        2. 分段文本：第一行是摘要，第二行是翻译

        Args:
            content: LLM 返回的内容

        Returns:
            (摘要文本, 翻译文本) 元组
        """
        # 尝试 JSON 解析
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                summary = data.get("summary", content)
                translation = data.get("translation")
                return summary, translation
        except (json.JSONDecodeError, ValueError):
            pass

        # 分段文本解析
        lines = content.strip().split("\n")
        if len(lines) >= 2:
            return lines[0].strip(), lines[1].strip()

        # 单行内容：仅摘要
        return content.strip(), None

    async def _save_summary_for_tweets(
        self,
        tweet_ids: list[str],
        summary: SummaryRecord,
    ) -> None:
        """为组内所有推文保存摘要引用。

        Args:
            tweet_ids: 推文 ID 列表
            summary: 摘要记录
        """
        # 为每个推文创建摘要记录（共享同一 content_hash）
        for tweet_id in tweet_ids:
            if tweet_id != summary.tweet_id:
                # 为同一去重组内的其他推文创建记录
                record = SummaryRecord(
                    summary_id=str(uuid.uuid4()),
                    tweet_id=tweet_id,
                    summary_text=summary.summary_text,
                    translation_text=summary.translation_text,
                    model_provider=summary.model_provider,
                    model_name=summary.model_name,
                    prompt_tokens=0,  # 非代表推文不计 token
                    completion_tokens=0,
                    total_tokens=0,
                    cost_usd=0.0,  # 非代表推文不计成本
                    cached=True,  # 标记为缓存
                    content_hash=summary.content_hash,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                await self._repository.save_summary_record(record)

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
        groups: list[DeduplicationGroup],
        summaries: list[SummaryRecord],
        start_time: float,
    ) -> SummaryResult:
        """计算摘要处理结果统计。

        Args:
            tweet_ids: 原始推文 ID 列表
            groups: 去重组列表
            summaries: 生成的摘要列表
            start_time: 开始时间

        Returns:
            摘要结果统计
        """
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

        return SummaryResult(
            total_tweets=len(tweet_ids),
            total_groups=len(groups),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            providers_used=providers_used,
            processing_time_ms=int((time.time() - start_time) * 1000),
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
    repository: SummarizationRepository,
    config: "LLMProviderConfig",
    prompt_config: PromptConfig | None = None,
    max_concurrent: int = SummarizationService.DEFAULT_MAX_CONCURRENT,
) -> SummarizationService:
    """创建摘要服务实例。

    Args:
        repository: 摘要仓储
        config: LLM 提供商配置
        prompt_config: Prompt 配置
        max_concurrent: 最大并发数

    Returns:
        摘要服务实例

    Raises:
        ValueError: 没有配置任何提供商时抛出
    """
    providers: list[LLMProvider] = []

    # 按优先级顺序创建提供商
    if config.openrouter:
        from src.summarization.llm.openrouter import OpenRouterProvider

        providers.append(
            OpenRouterProvider(
                api_key=config.openrouter.api_key,
                base_url=config.openrouter.base_url,
                model=config.openrouter.model,
                timeout_seconds=config.openrouter.timeout_seconds,
                max_retries=config.openrouter.max_retries,
            )
        )

    if config.minimax:
        from src.summarization.llm.minimax import MiniMaxProvider

        providers.append(
            MiniMaxProvider(
                api_key=config.minimax.api_key,
                base_url=config.minimax.base_url,
                model=config.minimax.model,
                group_id=config.minimax.group_id,
                timeout_seconds=config.minimax.timeout_seconds,
                max_retries=config.minimax.max_retries,
            )
        )

    if config.open_source:
        # TODO: 实现开源模型提供商
        logger.warning("开源模型提供商尚未实现")
        pass

    if not providers:
        raise ValueError("至少需要配置一个 LLM 提供商")

    return SummarizationService(
        repository=repository,
        providers=providers,
        prompt_config=prompt_config,
        max_concurrent=max_concurrent,
    )
