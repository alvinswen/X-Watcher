"""抓取服务编排。

协调 TwitterClient、TweetParser、TweetValidator、TweetRepository
完成完整的推文抓取流程。
"""

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
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

# 模块级并发抓取防护：记录当前正在抓取的用户名
_scraping_usernames: set[str] = set()
_scraping_lock = threading.Lock()


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

            # 同步用户档案（不影响抓取结果）
            await self._sync_user_profiles(usernames)

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
        _retry_count: int = 0,
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

        # 并发抓取防护：同一用户不允许同时抓取
        normalized = username.lower()
        with _scraping_lock:
            if normalized in _scraping_usernames:
                logger.info(f"跳过用户 {username}: 另一个抓取任务正在处理该用户")
                result["error_message"] = "另一个抓取任务正在处理该用户"
                return result
            _scraping_usernames.add(normalized)

        try:
            return await self._scrape_single_user_inner(
                username, result=result, limit=limit,
                since_id=since_id, manual_limit=manual_limit,
                _retry_count=_retry_count,
            )
        finally:
            with _scraping_lock:
                _scraping_usernames.discard(normalized)

    async def _scrape_single_user_inner(
        self,
        username: str,
        *,
        result: dict[str, Any],
        limit: int = 100,
        since_id: str | None = None,
        manual_limit: int | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        """抓取单个用户的推文（内部实现，由 scrape_single_user 调用）。"""
        try:
            # 0. 计算 limit：手动优先，否则动态计算
            fetch_stats = await self._get_fetch_stats(username)
            if manual_limit is not None and manual_limit > 0:
                actual_limit = manual_limit
                logger.info(
                    "开始抓取用户: %s (手动 limit=%d)",
                    username, actual_limit,
                )
            else:
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

                # 检测改名：404 + 有 platform_user_id + 未重试过
                if (
                    getattr(error, "status_code", None) == 404
                    and _retry_count == 0
                ):
                    new_username = await self._detect_and_fix_rename(username)
                    if new_username:
                        logger.info(
                            "检测到改名: %s -> %s，使用新用户名重试",
                            username, new_username,
                        )
                        return await self.scrape_single_user(
                            new_username,
                            limit=limit,
                            since_id=since_id,
                            manual_limit=manual_limit,
                            _retry_count=1,
                        )

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

                    # 仅在 author_id 缺失时用 username 填充（保留 API 返回的真实 ID）
                    for tweet in raw_data["data"]:
                        if tweet.get("author_id") is None:
                            tweet["author_id"] = username

                    # 收集所有 author_id 值，确保 includes.users 中有对应映射
                    existing_users = {}
                    for u in raw_data.get("includes", {}).get("users", []):
                        existing_users[u.get("id")] = u

                    author_ids_in_tweets = {
                        t["author_id"] for t in raw_data["data"] if t.get("author_id")
                    }

                    new_users = []
                    for aid in author_ids_in_tweets:
                        if aid not in existing_users:
                            new_users.append({
                                "id": aid,
                                "username": username,
                                "name": username,
                            })

                    if new_users:
                        includes = raw_data.setdefault("includes", {})
                        includes.setdefault("users", []).extend(new_users)

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

                    # 5. 自动补全 platform_user_id
                    if cleaned_tweets and cleaned_tweets[0].author_user_id:
                        await self._backfill_platform_user_id(
                            username, cleaned_tweets[0].author_user_id
                        )

                    # 5a. 检测并获取 X Articles
                    await self._fetch_and_save_articles(cleaned_tweets)

            # 5b. 满页检测：第一页全是新推文且接近 limit → 自动翻页
            settings = get_settings()
            max_extra_pages = settings.scraper_max_extra_pages
            next_cursor = raw_data.get("next_cursor")

            if (
                max_extra_pages > 0
                and next_cursor
                and result["new"] > 0
                and result["fetched"] > 0
                and result["new"] >= result["fetched"] * 0.8
            ):
                logger.info(
                    "用户 %s 满页检测触发: new=%d, fetched=%d, 开始翻页（最多 %d 页）",
                    username, result["new"], result["fetched"], max_extra_pages,
                )
                extra = await self._scrape_additional_pages(
                    username=username,
                    next_cursor=next_cursor,
                    max_extra_pages=max_extra_pages,
                )
                result["new"] += extra["new"]
                result["skipped"] += extra["skipped"]
                result["fetched"] += extra["fetched"]

            result["success"] = True

            # 6. 更新抓取统计（用于下次动态 limit 计算）
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

    async def backfill_user(
        self,
        username: str,
        *,
        max_pages: int = 20,
        min_pages: int = 0,
    ) -> dict[str, Any]:
        """全量回溯单个用户的历史推文。

        利用分页迭代器逐页抓取，每页保存后检查 skip 率，
        大量已存在推文时提前停止。完成后更新 backfill_status。

        Args:
            username: 用户名
            max_pages: 最大抓取页数
            min_pages: 最少抓取页数（在此之前不检查跳过率，用于穿透已有推文填补空缺）

        Returns:
            dict: 回溯结果 {username, success, fetched, new, skipped, pages}
        """
        result = {
            "username": username,
            "success": False,
            "fetched": 0,
            "new": 0,
            "skipped": 0,
            "pages": 0,
        }

        try:
            # 标记回溯开始
            await self._update_backfill_status(username, "running")

            logger.info("开始全量回溯: username=%s, max_pages=%d", username, max_pages)

            async for page_data in self._client.fetch_user_tweets_paginated(
                username, max_pages=max_pages,
            ):
                result["pages"] += 1

                # 解析
                tweets = self._parser.parse_tweet_response(page_data)
                result["fetched"] += len(tweets)

                if not tweets:
                    logger.info(
                        "回溯 %s 第 %d 页返回空结果，停止",
                        username, result["pages"],
                    )
                    break

                # 验证
                validation_results = self._validator.validate_and_clean_batch(tweets)
                cleaned_tweets = []
                for vr in validation_results:
                    match vr:
                        case Success(tweet):
                            cleaned_tweets.append(tweet)
                        case Failure(_):
                            pass

                if cleaned_tweets:
                    save_result = await self._save_tweets(cleaned_tweets)
                    result["new"] += save_result.success_count
                    result["skipped"] += save_result.skipped_count

                    # 获取本页推文关联的 Articles
                    await self._fetch_and_save_articles(cleaned_tweets)

                    # 停止条件：本页大部分推文已存在（min_pages 之前跳过检查）
                    total_processed = save_result.success_count + save_result.skipped_count
                    if result["pages"] > min_pages and total_processed > 0 and save_result.skipped_count / total_processed > 0.8:
                        logger.info(
                            "回溯 %s 第 %d 页跳过率 %.0f%%，停止回溯",
                            username, result["pages"],
                            save_result.skipped_count / total_processed * 100,
                        )
                        break

                logger.info(
                    "回溯 %s 第 %d/%d 页: 获取 %d, 新增 %d",
                    username, result["pages"], max_pages,
                    len(tweets), save_result.success_count if cleaned_tweets else 0,
                )

            # 标记回溯完成
            await self._update_backfill_status(
                username, "completed",
                completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            result["success"] = True

            logger.info(
                "全量回溯完成: username=%s, pages=%d, fetched=%d, new=%d, skipped=%d",
                username, result["pages"], result["fetched"],
                result["new"], result["skipped"],
            )

        except Exception as e:
            logger.exception("全量回溯失败: username=%s, error=%s", username, e)
            # 失败时重置为 pending，下次定时任务可重试
            await self._update_backfill_status(username, "pending")

        return result

    async def _update_backfill_status(
        self,
        username: str,
        status: str,
        completed_at: datetime | None = None,
    ) -> None:
        """更新用户的回溯状态。"""
        try:
            from src.database.async_session import get_async_session_maker
            from src.preference.infrastructure.scraper_config_repository import (
                ScraperConfigRepository,
            )

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = ScraperConfigRepository(session)
                await repo.update_backfill_status(
                    username, status, completed_at=completed_at,
                )
                await session.commit()
        except Exception as e:
            logger.warning("更新回溯状态失败: username=%s, status=%s, error=%s", username, status, e)

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

    async def _scrape_additional_pages(
        self,
        username: str,
        next_cursor: str,
        max_extra_pages: int = 3,
    ) -> dict[str, int]:
        """抓取后续页面的推文（满页翻页机制）。

        当第一页几乎全是新推文时，继续翻页获取更多推文，
        直到遇到大量已存在推文（skip 率 >80%）或达到页数上限。

        Args:
            username: 用户名
            next_cursor: 下一页的分页游标
            max_extra_pages: 最多翻几页

        Returns:
            dict: 额外页面的抓取统计 {fetched, new, skipped}
        """
        totals = {"fetched": 0, "new": 0, "skipped": 0}
        cursor = next_cursor

        for page_num in range(1, max_extra_pages + 1):
            logger.info(
                "用户 %s 翻页 %d/%d (cursor=%s...)",
                username, page_num, max_extra_pages, cursor[:20] if cursor else "",
            )

            api_result = await self._client.fetch_user_tweets(
                username, cursor=cursor,
            )

            if isinstance(api_result, Failure):
                logger.warning(
                    "用户 %s 翻页 %d 失败: %s",
                    username, page_num, api_result.failure().message,
                )
                break

            page_data = api_result.unwrap()

            # 解析
            tweets = self._parser.parse_tweet_response(page_data)
            totals["fetched"] += len(tweets)

            if not tweets:
                logger.info("用户 %s 翻页 %d 返回空结果，停止翻页", username, page_num)
                break

            # 验证
            validation_results = self._validator.validate_and_clean_batch(tweets)
            cleaned_tweets = []
            for vr in validation_results:
                match vr:
                    case Success(tweet):
                        cleaned_tweets.append(tweet)
                    case Failure(error):
                        logger.warning(f"翻页验证失败: {error.message}")

            if cleaned_tweets:
                save_result = await self._save_tweets(cleaned_tweets)
                totals["new"] += save_result.success_count
                totals["skipped"] += save_result.skipped_count

                # 停止条件：本页大部分推文已存在
                total_processed = save_result.success_count + save_result.skipped_count
                if total_processed > 0 and save_result.skipped_count / total_processed > 0.8:
                    logger.info(
                        "用户 %s 翻页 %d 跳过率 %.0f%%，停止翻页",
                        username, page_num,
                        save_result.skipped_count / total_processed * 100,
                    )
                    break

            # 检查下一页游标
            cursor = page_data.get("next_cursor")
            if not cursor:
                logger.info("用户 %s 翻页 %d 无更多页面", username, page_num)
                break

            # 页间延迟
            await asyncio.sleep(1.0)

        logger.info(
            "用户 %s 翻页完成: 额外获取 %d 条, 新增 %d 条, 跳过 %d 条",
            username, totals["fetched"], totals["new"], totals["skipped"],
        )
        return totals

    async def _fetch_and_save_articles(self, tweets: list[Tweet]) -> None:
        """检测并保存推文关联的 X Article。

        使用推文自带的 article 预览字段（has_article）进行零成本检测，
        然后调用 /article API 获取全文。API 失败时 fallback 到预览信息。
        """
        article_tweets = [t for t in tweets if t.has_article]

        if not article_tweets:
            return

        logger.info("检测到 %d 条推文含 Article（via article 字段），开始获取", len(article_tweets))

        try:
            from src.database.async_session import get_async_session_maker
            from src.scraper.domain.models import Article
            from src.scraper.infrastructure.article_repository import ArticleRepository

            session_maker = get_async_session_maker()

            for tweet in article_tweets:
                try:
                    # 检查是否已存在
                    async with session_maker() as session:
                        repo = ArticleRepository(session)
                        if await repo.article_exists(tweet.tweet_id):
                            continue

                    # 调用 /article API 获取全文
                    api_result = await self._client.fetch_article(tweet.tweet_id)

                    if isinstance(api_result, Success):
                        data = api_result.unwrap()

                        # API 返回 200 但 article=null / status=failed → 非 Article，跳过
                        if data.get("status") == "failed" or data.get("article") is None:
                            logger.info("Article API 返回空: tweet_id=%s, 跳过", tweet.tweet_id)
                            continue

                        article_data = data.get("article", data.get("data", data))

                        # 拼接 contents 为纯文本
                        contents = article_data.get("contents", [])
                        content_text = "\n\n".join(
                            c.get("text", "") for c in contents
                            if isinstance(c, dict) and c.get("text")
                        ) if contents else None

                        article = Article(
                            tweet_id=tweet.tweet_id,
                            title=article_data.get("title") or (tweet.article_preview.title if tweet.article_preview else None),
                            preview_text=article_data.get("preview_text") or (tweet.article_preview.preview_text if tweet.article_preview else None),
                            cover_image_url=article_data.get("cover_media_img_url") or (tweet.article_preview.cover_media_img_url if tweet.article_preview else None),
                            content=content_text,
                            content_html=article_data.get("contentHtml") or article_data.get("content_html"),
                            author_username=tweet.author_username,
                            fetched_at=datetime.now(timezone.utc),
                        )
                    else:
                        # API 失败时 fallback 到预览信息
                        logger.warning(
                            "获取 Article 全文失败，使用预览信息: tweet_id=%s, error=%s",
                            tweet.tweet_id, api_result.failure().message,
                        )
                        article = Article(
                            tweet_id=tweet.tweet_id,
                            title=tweet.article_preview.title if tweet.article_preview else None,
                            preview_text=tweet.article_preview.preview_text if tweet.article_preview else None,
                            cover_image_url=tweet.article_preview.cover_media_img_url if tweet.article_preview else None,
                            content=None,
                            content_html=None,
                            author_username=tweet.author_username,
                            fetched_at=datetime.now(timezone.utc),
                        )

                    async with session_maker() as session:
                        repo = ArticleRepository(session)
                        saved = await repo.save_article(article)
                        await session.commit()

                    if saved:
                        logger.info(
                            "Article 已保存: tweet_id=%s, title=%s",
                            tweet.tweet_id, article.title,
                        )

                    # API 调用间延迟
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.warning(
                        "处理 Article 失败: tweet_id=%s, error=%s",
                        tweet.tweet_id, e,
                    )

        except Exception as e:
            logger.warning("Article 批量获取失败（不影响抓取结果）: %s", e)

    async def backfill_articles_for_user(
        self,
        username: str,
        *,
        max_tweets: int = 200,
    ) -> dict[str, Any]:
        """回溯指定用户已有推文的 Article 信息。

        扫描该用户在 DB 中的推文，对尚无 article 记录的推文
        逐个调用 /article API 尝试获取。404 = 非 Article，200 = 保存。

        注意：每次 API 调用消耗 100 credits。

        Args:
            username: 用户名
            max_tweets: 最多检查的推文数量

        Returns:
            dict: {checked, found, skipped, errors}
        """
        result: dict[str, Any] = {"checked": 0, "found": 0, "skipped": 0, "errors": 0}

        try:
            from src.database.async_session import get_async_session_maker
            from src.scraper.domain.models import Article
            from src.scraper.infrastructure.article_repository import ArticleRepository

            session_maker = get_async_session_maker()

            # 1. 查询该用户尚无 article 记录的推文 ID
            async with session_maker() as session:
                from sqlalchemy import select
                from src.scraper.infrastructure.models import TweetOrm
                from src.scraper.infrastructure.article_models import ArticleOrm

                stmt = (
                    select(TweetOrm.tweet_id)
                    .outerjoin(ArticleOrm, TweetOrm.tweet_id == ArticleOrm.tweet_id)
                    .where(
                        TweetOrm.author_username == username,
                        ArticleOrm.tweet_id.is_(None),
                    )
                    .order_by(TweetOrm.created_at.desc())
                    .limit(max_tweets)
                )
                rows = await session.execute(stmt)
                tweet_ids = [row[0] for row in rows]

            if not tweet_ids:
                logger.info("用户 %s 无需回溯的推文", username)
                return result

            logger.info("开始回溯用户 %s 的 Articles: %d 条推文待检查", username, len(tweet_ids))

            # 2. 逐个调用 /article API
            for tweet_id in tweet_ids:
                result["checked"] += 1

                try:
                    api_result = await self._client.fetch_article(tweet_id)

                    if isinstance(api_result, Failure):
                        err = api_result.failure()
                        if getattr(err, "status_code", None) == 404:
                            result["skipped"] += 1
                        else:
                            result["errors"] += 1
                            logger.warning(
                                "Article API 错误: tweet_id=%s, error=%s",
                                tweet_id, err.message,
                            )
                        continue

                    data = api_result.unwrap()

                    # API 返回 200 但 article=null / status=failed → 非 Article，跳过
                    if data.get("status") == "failed" or data.get("article") is None:
                        result["skipped"] += 1
                        continue

                    article_data = data.get("article", data.get("data", data))

                    # 拼接 contents 为纯文本
                    contents = article_data.get("contents", [])
                    content_text = "\n\n".join(
                        c.get("text", "") for c in contents
                        if isinstance(c, dict) and c.get("text")
                    ) if contents else None

                    article = Article(
                        tweet_id=tweet_id,
                        title=article_data.get("title"),
                        preview_text=article_data.get("preview_text"),
                        cover_image_url=article_data.get("cover_media_img_url"),
                        content=content_text,
                        content_html=article_data.get("contentHtml") or article_data.get("content_html"),
                        author_username=username,
                        fetched_at=datetime.now(timezone.utc),
                    )

                    async with session_maker() as session:
                        repo = ArticleRepository(session)
                        saved = await repo.save_article(article)
                        await session.commit()

                    if saved:
                        result["found"] += 1
                        logger.info(
                            "Article 回溯成功: tweet_id=%s, title=%s",
                            tweet_id, article.title,
                        )

                    await asyncio.sleep(0.5)

                except Exception as e:
                    result["errors"] += 1
                    logger.warning("Article 回溯异常: tweet_id=%s, error=%s", tweet_id, e)

            logger.info(
                "用户 %s Article 回溯完成: checked=%d, found=%d, skipped=%d, errors=%d",
                username, result["checked"], result["found"],
                result["skipped"], result["errors"],
            )

        except Exception as e:
            logger.exception("Article 回溯失败: username=%s, error=%s", username, e)

        return result

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

            # 队列未运行时（MCP stdio 模式），直接内联处理摘要
            if not queue.is_running:
                logger.info(
                    f"触发摘要: {len(tweet_ids)} 条推文, 方式=inline（队列未运行）",
                    extra={
                        "event": "trigger_summarization",
                        "total_tweets": len(tweet_ids),
                        "enqueue_method": "inline",
                        "source": "scraping",
                    },
                )
                await self._inline_summarize(tweet_ids)
                return

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

    async def _inline_summarize(self, tweet_ids: list[str]) -> None:
        """内联摘要回退：队列未运行时直接调用 SummarizationService。"""
        from src.database.async_session import get_async_session_maker
        from src.summarization.domain.models import PromptConfig
        from src.summarization.llm.config import LLMProviderConfig
        from src.summarization.services.summarization_service import (
            create_summarization_service,
        )

        session_factory = get_async_session_maker()
        config = LLMProviderConfig.from_env()
        service = create_summarization_service(
            session_factory=session_factory,
            config=config,
            prompt_config=PromptConfig(),
        )

        result = await service.summarize_tweets(tweet_ids=tweet_ids)

        from returns.result import Failure

        if isinstance(result, Failure):
            logger.warning(f"内联摘要失败: {result.failure()}")
        else:
            summary = result.unwrap()
            logger.info(
                f"内联摘要完成: 成功 {summary.total_tweets_succeeded}/{summary.total_tweets}, "
                f"缓存命中 {summary.cache_hits}, 耗时 {summary.processing_time_ms}ms"
            )

    async def _backfill_platform_user_id(
        self, username: str, user_id: str
    ) -> None:
        """将 API 返回的 user_id 回填到 scraper_follows 表。

        仅在 platform_user_id 为空时执行写入，已有值时跳过。
        失败时仅记录警告日志，不影响抓取结果。
        """
        try:
            from src.database.async_session import get_async_session_maker
            from src.preference.infrastructure.scraper_config_repository import (
                ScraperConfigRepository,
            )

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = ScraperConfigRepository(session)
                await repo.update_platform_user_id(username, user_id)
                await session.commit()
                logger.info(
                    "已回填 platform_user_id: %s -> %s", username, user_id
                )
        except Exception as e:
            logger.warning("回填 platform_user_id 失败（不影响抓取结果）: %s", e)

    async def _detect_and_fix_rename(self, old_username: str) -> str | None:
        """检测用户改名并自动修复数据库记录。

        当抓取某个 username 返回 404 时调用此方法。
        如果数据库中有该用户的 platform_user_id，则通过
        batch_info_by_ids API 查询最新 username。

        Returns:
            str | None: 新的 username，或 None（无法检测/修复）
        """
        try:
            from src.database.async_session import get_async_session_maker
            from src.preference.infrastructure.scraper_config_repository import (
                ScraperConfigRepository,
            )

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                repo = ScraperConfigRepository(session)
                follow = await repo.get_follow_by_username(old_username)

                if not follow or not follow.platform_user_id:
                    logger.warning(
                        "用户 %s 不存在或无 platform_user_id，无法检测改名",
                        old_username,
                    )
                    return None

                # 调用 batch_info_by_ids 查询最新用户信息
                user_info_result = await self._client.fetch_user_info_by_ids(
                    [follow.platform_user_id]
                )

                if isinstance(user_info_result, Failure):
                    logger.error(
                        "查询用户信息失败: %s",
                        user_info_result.failure().message,
                    )
                    return None

                users = user_info_result.unwrap()
                if not users:
                    logger.warning(
                        "platform_user_id %s 查询无结果（账号可能已被删除）",
                        follow.platform_user_id,
                    )
                    return None

                new_username = users[0].get("userName") or users[0].get("username")
                if not new_username:
                    return None

                new_username = new_username.lower()

                if new_username == old_username.lower():
                    logger.info(
                        "用户名未变化，404 非改名导致: %s", old_username
                    )
                    return None

                # 更新数据库中的 username
                await repo.update_username(old_username, new_username)
                await session.commit()

                logger.info(
                    "用户改名已修复: %s -> %s (user_id=%s)",
                    old_username, new_username, follow.platform_user_id,
                )
                return new_username

        except Exception as e:
            logger.error("改名检测失败: %s", e)
            return None

    async def _sync_user_profiles(self, usernames: list[str]) -> None:
        """同步用户档案信息。

        从数据库查询指定用户名对应的 platform_user_id，
        然后批量调用 TwitterAPI.io 获取完整档案信息并持久化。

        Args:
            usernames: 刚完成抓取的用户名列表
        """
        try:
            from src.database.async_session import get_async_session_maker
            from src.preference.infrastructure.scraper_config_repository import (
                ScraperConfigRepository,
            )
            from src.preference.infrastructure.x_user_profile_repository import (
                XUserProfileRepository,
            )
            from src.preference.domain.models import XUserProfile

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                config_repo = ScraperConfigRepository(session)

                # 查询这些用户名对应的 platform_user_id
                user_ids: list[str] = []
                for username in usernames:
                    follow = await config_repo.get_follow_by_username(username)
                    if follow and follow.platform_user_id:
                        user_ids.append(follow.platform_user_id)

                if not user_ids:
                    logger.debug("档案同步: 无可用 platform_user_id，跳过")
                    return

                # 批量获取用户信息
                result = await self._client.fetch_user_info_by_ids(user_ids)

                if isinstance(result, Failure):
                    logger.warning(
                        "档案同步: API 调用失败: %s",
                        result.failure().message,
                    )
                    return

                users_data = result.unwrap()
                if not users_data:
                    logger.debug("档案同步: API 返回空结果")
                    return

                # 转换为领域模型
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                profiles = []
                raw_data_map: dict[str, dict] = {}
                for u in users_data:
                    profile = XUserProfile.from_api_response(u, fetched_at=now)
                    if profile.platform_user_id:
                        profiles.append(profile)
                        raw_data_map[profile.platform_user_id] = u

                # 持久化
                profile_repo = XUserProfileRepository(session)
                count = await profile_repo.upsert_profiles(
                    profiles, raw_data_map=raw_data_map
                )
                await session.commit()
                logger.info("档案同步完成: %d 个用户档案已更新", count)

        except Exception as e:
            logger.warning("档案同步失败（不影响抓取结果）: %s", e)

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
