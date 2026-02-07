"""去重编排服务。

协调整个去重流程，包括检测、存储和统计。
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.deduplication.domain.detectors import ExactDuplicateDetector, SimilarityDetector
from src.deduplication.domain.models import (
    DeduplicationConfig,
    DeduplicationGroup,
    DeduplicationResult,
    DeduplicationType,
    DuplicateGroup,
    SimilarGroup,
)
from src.deduplication.infrastructure.repository import DeduplicationRepository

if TYPE_CHECKING:
    from src.scraper.domain.models import Tweet

logger = logging.getLogger(__name__)


class DeduplicationService:
    """去重编排服务。

    协调精确重复和相似度检测，管理去重结果持久化。
    可选集成摘要服务，在去重完成后自动触发摘要任务。
    """

    def __init__(
        self,
        repository: DeduplicationRepository,
        exact_detector: ExactDuplicateDetector | None = None,
        similarity_detector: SimilarityDetector | None = None,
        summarization_service=None,
        task_registry=None,
    ) -> None:
        """初始化去重服务。

        Args:
            repository: 去重结果仓库
            exact_detector: 精确重复检测器
            similarity_detector: 相似度检测器
            summarization_service: 可选的摘要服务（用于集成触发）
            task_registry: 可选的任务注册表（用于创建摘要任务）
        """
        self._repository = repository
        self._exact_detector = exact_detector or ExactDuplicateDetector()
        self._similarity_detector = similarity_detector or SimilarityDetector()
        self._summarization_service = summarization_service
        self._task_registry = task_registry

    async def deduplicate_tweets(
        self,
        tweet_ids: list[str],
        tweets: list["Tweet"] | None = None,
        config: DeduplicationConfig | None = None,
    ) -> DeduplicationResult:
        """对指定推文执行去重。

        Args:
            tweet_ids: 推文 ID 列表
            tweets: 推文列表（为 None 时从数据库加载）
            config: 去重策略配置（为 None 时使用默认配置）

        Returns:
            DeduplicationResult: 去重结果统计
        """
        start_time = time.time()
        config = config or DeduplicationConfig()

        try:
            # 加载推文数据
            if tweets is None:
                tweets = await self._load_tweets(tweet_ids)

            if not tweets:
                return DeduplicationResult(
                    total_tweets=0,
                    exact_duplicate_count=0,
                    similar_content_count=0,
                    affected_tweets=0,
                    preserved_tweets=0,
                    elapsed_seconds=0.0,
                )

            # 过滤已去重的推文
            tweets_to_process = await self._filter_unduplicated(tweets)

            if not tweets_to_process:
                logger.info("所有推文已去重，跳过处理")
                return DeduplicationResult(
                    total_tweets=len(tweets),
                    exact_duplicate_count=0,
                    similar_content_count=0,
                    affected_tweets=0,
                    preserved_tweets=len(tweets),
                    elapsed_seconds=time.time() - start_time,
                )

            # 分批处理
            all_groups = await self._process_in_batches(
                tweets_to_process, config
            )

            # 保存去重结果
            await self._save_results(all_groups)

            # 统计结果
            result = self._calculate_result(
                tweets, all_groups, start_time
            )

            logger.info(
                f"去重完成: 处理 {len(tweets)} 条推文, "
                f"发现 {result.exact_duplicate_count} 个精确重复组, "
                f"{result.similar_content_count} 个相似内容组, "
                f"耗时 {result.elapsed_seconds:.2f} 秒"
            )

            # 触发摘要任务（如果配置了摘要服务）
            await self._trigger_summarization(all_groups)

            return result

        except Exception as e:
            logger.error(f"去重失败: {e}")
            # 返回失败结果
            return DeduplicationResult(
                total_tweets=len(tweet_ids),
                exact_duplicate_count=0,
                similar_content_count=0,
                affected_tweets=0,
                preserved_tweets=len(tweets) if tweets else 0,
                elapsed_seconds=time.time() - start_time,
            )

    async def _trigger_summarization(
        self, groups: list[DeduplicationGroup]
    ) -> None:
        """触发摘要任务。

        为每个去重组创建摘要任务。使用后台任务模式，不阻塞去重流程。

        Args:
            groups: 去重组列表
        """
        # 如果没有配置摘要服务，跳过
        if self._summarization_service is None:
            return

        # 如果没有去重组，跳过
        if not groups:
            return

        # 提取所有代表推文 ID（去重组的代表推文需要摘要）
        representative_ids = [g.representative_tweet_id for g in groups]

        logger.info(
            f"准备触发摘要任务: {len(representative_ids)} 条推文"
        )

        # 使用后台任务触发摘要
        asyncio.create_task(
            self._run_summarization_background(representative_ids)
        )

    async def _run_summarization_background(
        self, tweet_ids: list[str]
    ) -> None:
        """在后台运行摘要任务。

        Args:
            tweet_ids: 推文 ID 列表
        """
        from src.scraper import TaskStatus

        task_id = None

        try:
            # 如果有任务注册表，创建任务记录
            if self._task_registry is not None:
                task_id = self._task_registry.create_task(
                    task_name=f"摘要 {len(tweet_ids)} 条去重推文",
                    metadata={
                        "tweet_count": len(tweet_ids),
                        "tweet_ids": tweet_ids[:10],  # 只记录前 10 个
                        "triggered_by": "deduplication",
                    },
                )

            logger.info(
                f"开始后台摘要任务: {len(tweet_ids)} 条推文"
            )

            # 调用摘要服务
            result = await self._summarization_service.summarize_tweets(
                tweet_ids=tweet_ids,
                force_refresh=False,  # 优先使用缓存
            )

            # 检查结果
            from returns.result import Failure

            if isinstance(result, Failure):
                error = result.failure()
                logger.error(f"后台摘要任务失败: {error}")
                if task_id and self._task_registry is not None:
                    self._task_registry.update_task_status(
                        task_id, TaskStatus.FAILED, error=str(error)
                    )
                return

            summary_result = result.unwrap()

            logger.info(
                f"后台摘要任务完成: "
                f"{summary_result.total_groups} 个组, "
                f"缓存命中 {summary_result.cache_hits}, "
                f"成本 ${summary_result.total_cost_usd:.4f}"
            )

            if task_id and self._task_registry is not None:
                self._task_registry.update_task_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    result={
                        "total_tweets": summary_result.total_tweets,
                        "total_groups": summary_result.total_groups,
                        "cache_hits": summary_result.cache_hits,
                        "cache_misses": summary_result.cache_misses,
                        "total_tokens": summary_result.total_tokens,
                        "total_cost_usd": summary_result.total_cost_usd,
                        "providers_used": summary_result.providers_used,
                        "processing_time_ms": (
                            summary_result.processing_time_ms
                        ),
                    },
                )

        except Exception as e:
            logger.error(f"后台摘要任务异常: {e}")
            if task_id and self._task_registry is not None:
                self._task_registry.update_task_status(
                    task_id, TaskStatus.FAILED, error=str(e)
                )

    async def _load_tweets(self, tweet_ids: list[str]) -> list["Tweet"]:
        """从数据库加载推文。

        Args:
            tweet_ids: 推文 ID 列表

        Returns:
            推文列表
        """
        from sqlalchemy import select
        from src.scraper.infrastructure.models import TweetOrm

        stmt = select(TweetOrm).where(TweetOrm.tweet_id.in_(tweet_ids))
        result = await self._repository._session.execute(stmt)
        orm_tweets = result.scalars().all()

        return [t.to_domain() for t in orm_tweets]

    async def _filter_unduplicated(
        self, tweets: list["Tweet"]
    ) -> list["Tweet"]:
        """过滤未去重的推文。

        Args:
            tweets: 推文列表

        Returns:
            未去重的推文列表
        """
        unduplicated = []
        for tweet in tweets:
            group = await self._repository.find_by_tweet(tweet.tweet_id)
            if group is None:
                unduplicated.append(tweet)

        return unduplicated

    async def _process_in_batches(
        self,
        tweets: list["Tweet"],
        config: DeduplicationConfig,
    ) -> list[DeduplicationGroup]:
        """分批处理推文。

        Args:
            tweets: 推文列表
            config: 去重配置

        Returns:
            去重组列表
        """
        batch_size = config.batch_size
        all_groups = []

        for i in range(0, len(tweets), batch_size):
            batch = tweets[i : i + batch_size]
            groups = await self._process_batch(batch, config)
            all_groups.extend(groups)

        return all_groups

    async def _process_batch(
        self,
        tweets: list["Tweet"],
        config: DeduplicationConfig,
    ) -> list[DeduplicationGroup]:
        """处理单个批次。

        Args:
            tweets: 推文列表
            config: 去重配置

        Returns:
            去重组列表
        """
        groups = []

        # 1. 精确重复检测
        if config.enable_exact_duplicate:
            duplicate_groups = self._exact_detector.detect_duplicates(tweets)
            for dg in duplicate_groups:
                groups.append(self._duplicate_group_to_deduplication_group(dg))

        # 2. 获取未匹配的推文
        matched_ids = set()
        for g in groups:
            matched_ids.update(g.tweet_ids)

        unmatched_tweets = [t for t in tweets if t.tweet_id not in matched_ids]

        # 3. 相似度检测
        if config.enable_similar_content and unmatched_tweets:
            try:
                similar_groups = self._similarity_detector.detect_similar(
                    unmatched_tweets,
                    threshold=config.similarity_threshold,
                )
                for sg in similar_groups:
                    groups.append(self._similar_group_to_deduplication_group(sg))
            except Exception as e:
                logger.warning(f"相似度检测失败，使用仅精确重复结果: {e}")

        return groups

    def _duplicate_group_to_deduplication_group(
        self, dg: DuplicateGroup
    ) -> DeduplicationGroup:
        """转换精确重复组为去重组。

        Args:
            dg: 精确重复组

        Returns:
            去重组
        """
        return DeduplicationGroup(
            group_id=DeduplicationRepository.generate_group_id(),
            representative_tweet_id=dg.representative_id,
            deduplication_type=DeduplicationType.exact_duplicate,
            similarity_score=None,
            tweet_ids=dg.tweet_ids,
            created_at=datetime.now(timezone.utc),
        )

    def _similar_group_to_deduplication_group(
        self, sg: SimilarGroup
    ) -> DeduplicationGroup:
        """转换相似内容组为去重组。

        Args:
            sg: 相似内容组

        Returns:
            去重组
        """
        return DeduplicationGroup(
            group_id=DeduplicationRepository.generate_group_id(),
            representative_tweet_id=sg.representative_id,
            deduplication_type=DeduplicationType.similar_content,
            similarity_score=sg.similarity_score,
            tweet_ids=sg.tweet_ids,
            created_at=datetime.now(timezone.utc),
        )

    async def _save_results(self, groups: list[DeduplicationGroup]) -> None:
        """保存去重结果。

        Args:
            groups: 去重组列表
        """
        if groups:
            await self._repository.save_groups(groups)

    def _calculate_result(
        self,
        tweets: list["Tweet"],
        groups: list[DeduplicationGroup],
        start_time: float,
    ) -> DeduplicationResult:
        """计算去重结果统计。

        Args:
            tweets: 原始推文列表
            groups: 去重组列表
            start_time: 开始时间

        Returns:
            去重结果
        """
        exact_count = sum(
            1 for g in groups if g.deduplication_type == DeduplicationType.exact_duplicate
        )
        similar_count = sum(
            1 for g in groups if g.deduplication_type == DeduplicationType.similar_content
        )

        affected_ids = set()
        for g in groups:
            affected_ids.update(g.tweet_ids)

        # 计算保留的推文数（总推文数 - 被去重的推文数 + 代表推文数）
        affected_count = len(affected_ids)
        representative_count = len(groups)
        preserved_count = len(tweets) - affected_count + representative_count

        return DeduplicationResult(
            total_tweets=len(tweets),
            exact_duplicate_count=exact_count,
            similar_content_count=similar_count,
            affected_tweets=affected_count,
            preserved_tweets=preserved_count,
            elapsed_seconds=time.time() - start_time,
        )
