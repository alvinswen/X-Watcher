"""抓取服务编排。

协调 TwitterClient、TweetParser、TweetValidator、TweetRepository
完成完整的推文抓取流程。
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from returns.result import Failure, Success

from src.config import get_settings
from src.scraper.client import TwitterClient, TwitterClientError
from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.parser import TweetParser
from src.scraper.services.limit_calculator import LimitCalculator
from src.scraper.task_registry import TaskRegistry, TaskStatus
from src.scraper.validator import TweetValidator

logger = logging.getLogger(__name__)


class ScrapingService:
    """抓取服务。

    编排完整的推文抓取流程，包括：
    - 调用 Twitter API 获取推文
    - 解析 API 响应
    - 验证和清理数据
    - 保存到数据库
    - 生成进度和汇总报告
    """

    def __init__(
        self,
        client: TwitterClient | None = None,
        parser: TweetParser | None = None,
        validator: TweetValidator | None = None,
        repository: Any | None = None,
        max_concurrent: int = 3,
        limit_calculator: LimitCalculator | None = None,
    ) -> None:
        """初始化抓取服务。

        Args:
            client: Twitter API 客户端（为 None 时创建新实例）
            parser: 推文解析器（为 None 时创建新实例）
            validator: 推文验证器（为 None 时创建新实例）
            repository: 推文仓库（为 None 时创建新实例）
            max_concurrent: 最大并发请求数
            limit_calculator: 动态 Limit 计算器（为 None 时从配置创建）
        """
        self._client = client or TwitterClient()
        self._parser = parser or TweetParser()
        self._validator = validator or TweetValidator()
        self._repository = repository
        self._max_concurrent = max_concurrent
        self._registry = TaskRegistry.get_instance()

        if limit_calculator is not None:
            self._limit_calculator = limit_calculator
        else:
            settings = get_settings()
            self._limit_calculator = LimitCalculator(
                default_limit=settings.scraper_limit,
                min_limit=settings.scraper_min_limit,
                max_limit=settings.scraper_max_limit,
                ema_alpha=settings.scraper_ema_alpha,
            )

    async def scrape_users(
        self,
        usernames: list[str],
        *,
        limit: int = 100,
        since_id: str | None = None,
        task_id: str | None = None,
        manual_limits: dict[str, int] | None = None,
    ) -> str:
        """抓取多个用户的推文。

        Args:
            usernames: 用户名列表
            limit: 每个用户抓取的推文数量限制
            since_id: 只获取此 ID 之后的推文
            task_id: 可选的任务 ID（为 None 时自动创建）
            manual_limits: 手动 limit 映射 {username: limit}（可选）

        Returns:
            str: 任务 ID
        """
        # 创建或使用指定的任务 ID
        if task_id is None:
            task_id = self._registry.create_task(
                f"抓取 {len(usernames)} 个用户",
                metadata={
                    "usernames": ",".join(usernames),
                    "limit": limit,
                    "since_id": since_id,
                },
            )

        # 更新任务状态为运行中
        self._registry.update_task_status(task_id, TaskStatus.RUNNING)

        start_time = time.time()

        try:
            # 使用 Semaphore 控制并发
            semaphore = asyncio.Semaphore(self._max_concurrent)

            # 创建抓取任务
            tasks = [
                self._scrape_with_semaphore(
                    semaphore,
                    username,
                    limit,
                    since_id,
                    manual_limit=manual_limits.get(username) if manual_limits else None,
                )
                for username in usernames
            ]

            # 并发执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 汇总结果
            summary = self._summarize_results(usernames, results)

            elapsed = time.time() - start_time

            # 生成最终报告
            final_report = {
                "total_users": len(usernames),
                "successful_users": summary["successful"],
                "failed_users": summary["failed"],
                "total_tweets": summary["total_tweets"],
                "new_tweets": summary["new_tweets"],
                "skipped_tweets": summary["skipped_tweets"],
                "total_errors": summary["errors"],
                "elapsed_seconds": round(elapsed, 2),
            }

            logger.info(
                f"抓取完成: {final_report['successful_users']}/{final_report['total_users']} 用户成功, "
                f"{final_report['new_tweets']} 条新推文, "
                f"耗时 {final_report['elapsed_seconds']} 秒"
            )

            # 更新任务状态为完成
            self._registry.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                result=final_report,
            )

            return task_id

        except Exception as e:
            logger.exception(f"抓取任务失败: {e}")
            self._registry.update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=str(e),
            )
            return task_id

    async def _scrape_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        username: str,
        limit: int,
        since_id: str | None,
        manual_limit: int | None = None,
    ) -> dict[str, Any]:
        """使用信号量控制并发抓取。"""
        async with semaphore:
            return await self.scrape_single_user(
                username, limit=limit, since_id=since_id, manual_limit=manual_limit,
            )

    async def scrape_single_user(
        self,
        username: str,
        *,
        limit: int = 100,
        since_id: str | None = None,
        manual_limit: int | None = None,
    ) -> dict[str, Any]:
        """抓取单个用户的推文。

        使用动态 limit 策略：根据历史抓取统计自动调整每次 API 请求的 limit，
        减少重复推文的 API 调用成本。当设置了 manual_limit 时，使用手动值。

        Args:
            username: 用户名
            limit: 抓取的推文数量限制（作为上限参考，实际 limit 由动态计算决定）
            since_id: 只获取此 ID 之后的推文
            manual_limit: 手动 limit（优先于自动计算）

        Returns:
            dict: 抓取结果
            {
                "username": str,
                "success": bool,
                "fetched": int,
                "new": int,
                "skipped": int,
                "errors": int,
                "error_message": str | None,
            }
        """
        result = {
            "username": username,
            "success": False,
            "fetched": 0,
            "new": 0,
            "skipped": 0,
            "errors": 0,
            "error_message": None,
        }

        try:
            # 0. 计算 limit：手动优先，否则动态计算
            if manual_limit is not None and manual_limit > 0:
                actual_limit = manual_limit
                logger.info(
                    "开始抓取用户: %s (手动 limit=%d)",
                    username, actual_limit,
                )
            else:
                fetch_stats = await self._get_fetch_stats(username)
                dynamic_limit = self._limit_calculator.calculate_next_limit(fetch_stats)
                actual_limit = min(dynamic_limit, limit)  # 不超过传入的上限
                logger.info(
                    "开始抓取用户: %s (动态 limit=%d, 传入上限=%d)",
                    username, actual_limit, limit,
                )

            # 1. 调用 Twitter API
            api_result = await self._client.fetch_user_tweets(
                username,
                limit=actual_limit,
                since_id=since_id,
            )

            if isinstance(api_result, Failure):
                error = api_result.failure()
                result["success"] = False
                result["errors"] = 1
                result["error_message"] = error.message
                logger.error(f"抓取用户 {username} 失败: {error.message}")
                return result

            raw_data = api_result.unwrap()

            # 2. 为 TwitterAPI.io 响应添加用户信息
            # TwitterAPI.io 的 /user/last_tweets 不返回用户信息，因为所有推文属于同一用户
            # 我们需要手动添加用户信息和 author_id
            if "data" in raw_data and isinstance(raw_data["data"], list):
                # 检查推文是否缺少 author_id
                needs_author_info = any(
                    tweet.get("author_id") is None
                    for tweet in raw_data["data"]
                )

                if needs_author_info:
                    logger.debug(f"为用户 {username} 的推文添加作者信息")

                    # 为每条推文添加 author_id
                    for tweet in raw_data["data"]:
                        tweet["author_id"] = username  # 使用 username 作为临时 ID

                    # 添加 includes.users，使 parser 能够找到用户信息
                    raw_data.setdefault("includes", {})["users"] = [
                        {
                            "id": username,  # 使用 username 作为 ID
                            "username": username,
                            "name": username,  # TwitterAPI.io 不返回 display name
                        }
                    ]

            # 3. 解析推文
            tweets = self._parser.parse_tweet_response(raw_data)
            result["fetched"] = len(tweets)

            if tweets:
                # 3. 验证和清理
                validation_results = self._validator.validate_and_clean_batch(tweets)

                # 过滤出验证成功的推文
                cleaned_tweets = []
                validation_errors = 0

                for vr in validation_results:
                    match vr:
                        case Success(tweet):
                            cleaned_tweets.append(tweet)
                        case Failure(error):
                            validation_errors += 1
                            logger.warning(f"验证失败: {error.message}")

                if validation_errors > 0:
                    logger.warning(f"用户 {username} 有 {validation_errors} 条推文验证失败")

                if cleaned_tweets:
                    # 4. 保存到数据库
                    save_result = await self._save_tweets(cleaned_tweets)
                    result["new"] = save_result.success_count
                    result["skipped"] = save_result.skipped_count
                    result["errors"] = save_result.error_count

            result["success"] = True

            # 5. 更新抓取统计（用于下次动态 limit 计算）
            await self._update_fetch_stats(
                username=username,
                old_stats=fetch_stats,
                fetched_count=result["fetched"],
                new_count=result["new"],
            )

            logger.info(
                "用户 %s 抓取完成: 获取 %d 条, 新增 %d 条, 跳过 %d 条 (limit=%d)",
                username, result["fetched"], result["new"], result["skipped"],
                actual_limit,
            )

        except TwitterClientError as e:
            result["success"] = False
            result["errors"] = 1
            result["error_message"] = f"API 错误: {e.message}"
            logger.error(f"用户 {username} API 错误: {e}")

        except Exception as e:
            result["success"] = False
            result["errors"] = 1
            result["error_message"] = f"未预期的错误: {e}"
            logger.exception(f"用户 {username} 未预期的错误")

        return result

    async def _get_fetch_stats(self, username: str):
        """查询用户的历史抓取统计。

        Args:
            username: 用户名

        Returns:
            FetchStats | None: 统计数据，不存在时返回 None
        """
        try:
            from src.database.async_session import get_async_session_maker
            from src.scraper.infrastructure.fetch_stats_repository import (
                FetchStatsRepository,
            )

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = FetchStatsRepository(session)
                return await repo.get_stats(username)
        except Exception as e:
            logger.warning("查询抓取统计失败（使用默认 limit）: %s", e)
            return None

    async def _update_fetch_stats(
        self,
        username: str,
        old_stats,
        fetched_count: int,
        new_count: int,
    ) -> None:
        """更新用户的抓取统计。

        Args:
            username: 用户名
            old_stats: 旧的统计数据
            fetched_count: 本次 API 返回的推文数
            new_count: 本次新增的推文数
        """
        try:
            from src.database.async_session import get_async_session_maker
            from src.scraper.infrastructure.fetch_stats_repository import (
                FetchStatsRepository,
            )

            updated = self._limit_calculator.update_stats_after_fetch(
                stats=old_stats,
                username=username,
                fetched_count=fetched_count,
                new_count=new_count,
            )

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = FetchStatsRepository(session)
                await repo.upsert_stats(updated)
                await session.commit()

            logger.debug(
                "用户 %s 统计已更新: avg_rate=%.2f, empty=%d",
                username, updated.avg_new_rate, updated.consecutive_empty_fetches,
            )
        except Exception as e:
            # 统计更新失败不影响抓取结果
            logger.warning("更新抓取统计失败（不影响抓取结果）: %s", e)

    async def _save_tweets(self, tweets: list[Tweet]) -> SaveResult:
        """保存推文到数据库。

        Args:
            tweets: 推文列表

        Returns:
            SaveResult: 保存结果
        """
        settings = get_settings()
        early_stop = settings.scraper_early_stop_threshold

        if self._repository is None:
            # 延迟导入避免循环依赖
            from src.database.async_session import get_async_session_maker
            from src.scraper.infrastructure.repository import TweetRepository

            session_maker = get_async_session_maker()

            async with session_maker() as session:
                repo = TweetRepository(session)
                result = await repo.save_tweets(tweets, early_stop_threshold=early_stop)
                # 提交事务
                await session.commit()

                # 保存成功后，触发摘要
                if result.success_count > 0:
                    await self._trigger_summarization(result.saved_tweet_ids)

                return result
        else:
            # 如果已经有 repository，由调用者管理事务
            save_result = await self._repository.save_tweets(
                tweets, early_stop_threshold=early_stop
            )

            # 保存成功后，触发摘要
            if save_result.success_count > 0:
                await self._trigger_summarization(save_result.saved_tweet_ids)

            return save_result

    async def _trigger_summarization(self, tweet_ids: list[str]) -> None:
        """触发摘要生成任务。

        将摘要请求入队到集中式摘要队列，由队列 worker 统一处理。
        支持跨线程入队（APScheduler 后台线程）。

        Args:
            tweet_ids: 推文 ID 列表
        """
        try:
            from src.config import get_settings

            settings = get_settings()

            # 检查是否启用自动摘要
            if not settings.auto_summarization_enabled:
                logger.debug("自动摘要已禁用，跳过摘要生成")
                return

            if not tweet_ids:
                return

            from src.summarization.services.summarization_queue import (
                SummarizationPriority,
                SummarizationQueue,
            )

            queue = SummarizationQueue.get_instance()

            # 检测当前是否在主事件循环中
            try:
                running_loop = asyncio.get_running_loop()
                if running_loop is queue._loop:
                    logger.info(
                        f"触发摘要: {len(tweet_ids)} 条推文, 方式=enqueue（主循环）",
                        extra={"event": "trigger_summarization", "total_tweets": len(tweet_ids), "enqueue_method": "enqueue", "source": "scraping"},
                    )
                    await queue.enqueue(
                        tweet_ids,
                        source="scraping",
                        priority=SummarizationPriority.NORMAL,
                    )
                else:
                    logger.info(
                        f"触发摘要: {len(tweet_ids)} 条推文, 方式=enqueue_threadsafe（跨循环）",
                        extra={"event": "trigger_summarization", "total_tweets": len(tweet_ids), "enqueue_method": "enqueue_threadsafe", "source": "scraping"},
                    )
                    task_id = queue.enqueue_threadsafe(
                        tweet_ids,
                        source="scraping",
                        priority=SummarizationPriority.NORMAL,
                    )
                    if task_id is None:
                        logger.error(
                            f"摘要入队失败（enqueue_threadsafe 返回 None）: "
                            f"{len(tweet_ids)} 条推文的摘要请求被丢弃"
                        )
            except RuntimeError:
                # 无事件循环（后台线程）
                logger.info(
                    f"触发摘要: {len(tweet_ids)} 条推文, 方式=enqueue_threadsafe（无事件循环）",
                    extra={"event": "trigger_summarization", "total_tweets": len(tweet_ids), "enqueue_method": "enqueue_threadsafe", "source": "scraping"},
                )
                task_id = queue.enqueue_threadsafe(
                    tweet_ids,
                    source="scraping",
                    priority=SummarizationPriority.NORMAL,
                )
                if task_id is None:
                    logger.error(
                        f"摘要入队失败（enqueue_threadsafe 返回 None，无事件循环）: "
                        f"{len(tweet_ids)} 条推文的摘要请求被丢弃"
                    )

        except Exception as e:
            # 摘要触发失败不影响抓取结果
            logger.warning(f"触发摘要任务失败（不影响抓取结果）: {e}")

    def _summarize_results(
        self,
        usernames: list[str],
        results: list[dict | Exception],
    ) -> dict[str, Any]:
        """汇总抓取结果。

        Args:
            usernames: 用户名列表
            results: 抓取结果列表

        Returns:
            dict: 汇总统计
        """
        summary = {
            "successful": 0,
            "failed": 0,
            "total_tweets": 0,
            "new_tweets": 0,
            "skipped_tweets": 0,
            "errors": 0,
            "user_results": [],
        }

        for username, result in zip(usernames, results):
            if isinstance(result, Exception):
                summary["failed"] += 1
                summary["errors"] += 1
                summary["user_results"].append({
                    "username": username,
                    "success": False,
                    "error": str(result),
                })
            else:
                summary["total_tweets"] += result.get("fetched", 0)
                summary["new_tweets"] += result.get("new", 0)
                summary["skipped_tweets"] += result.get("skipped", 0)
                summary["errors"] += result.get("errors", 0)

                if result.get("success"):
                    summary["successful"] += 1
                else:
                    summary["failed"] += 1

                summary["user_results"].append({
                    "username": username,
                    "success": result.get("success", False),
                    "fetched": result.get("fetched", 0),
                    "new": result.get("new", 0),
                    "skipped": result.get("skipped", 0),
                    "error": result.get("error_message"),
                })

        return summary

    async def close(self) -> None:
        """关闭客户端资源。"""
        await self._client.close()
