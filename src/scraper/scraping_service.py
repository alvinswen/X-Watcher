"""抓取服务编排。

协调 TwitterClient、TweetParser、TweetValidator、TweetRepository
完成完整的推文抓取流程。
"""

import asyncio
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, cast

from returns.result import Failure, Success

from src.config import get_settings
from src.scraper.client import TwitterClient, TwitterClientError
from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.parser import TweetParser
from src.scraper.services.article_fetch_service import ArticleFetchService
from src.scraper.services.limit_calculator import LimitCalculator
from src.scraper.services.profile_sync_service import ProfileSyncService
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
        self._article_service = ArticleFetchService(client=self._client)
        self._profile_service = ProfileSyncService(client=self._client)
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
        task_id: str | None = None,
        manual_limits: dict[str, int] | None = None,
    ) -> str:
        """抓取多个用户的推文。

        Args:
            usernames: 用户名列表
            limit: 每个用户抓取的推文数量限制
            task_id: 可选的任务 ID（为 None 时自动创建）
            manual_limits: 手动 limit 映射 {username: limit}（可选）。为 None 时
                服务层自动从 follows 仓储解析活跃账号的 manual_limit 配置（含
                空字典在内的非 None 值视为调用方已显式提供，不再二次查询，
                CHG-031）

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
                },
            )

        # 更新任务状态为运行中
        self._registry.update_task_status(task_id, TaskStatus.RUNNING)

        # manual_limits 未显式传入(None)时,服务层单点自动解析活跃账号的手动限额
        # 配置,使 REST(_run_scraping_task_async)与 MCP(trigger_scrape)两条触发
        # 路径自动生效、无需各自维护一份(CHG-031 目标 1)。非 None(含调用方显式
        # 传入的空字典)视为调用方已给出确定值,不再二次查询。
        if manual_limits is None:
            from src.scraper.scheduled_job import resolve_manual_limits

            manual_limits = await resolve_manual_limits(usernames)

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
                    manual_limit=manual_limits.get(username) if manual_limits else None,
                )
                for username in usernames
            ]

            # 并发执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 同步用户档案（不影响抓取结果）
            await self._profile_service.sync_user_profiles(usernames)

            # 汇总结果
            summary = self._summarize_results(
                usernames,
                cast(list[dict[str, Any] | Exception], results),
            )

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
        manual_limit: int | None = None,
    ) -> dict[str, Any]:
        """使用信号量控制并发抓取。"""
        async with semaphore:
            return await self.scrape_single_user(
                username, limit=limit, manual_limit=manual_limit,
            )

    async def scrape_single_user(
        self,
        username: str,
        *,
        limit: int = 100,
        manual_limit: int | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        """抓取单个用户的推文。

        使用动态 limit 策略：根据历史抓取统计自动调整每次 API 请求的 limit，
        减少重复推文的 API 调用成本。当设置了 manual_limit 时，使用手动值。

        Args:
            username: 用户名
            limit: 抓取的推文数量限制（作为上限参考，实际 limit 由动态计算决定）
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
        result: dict[str, Any] = {
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
                manual_limit=manual_limit,
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
            )

            if isinstance(api_result, Failure):
                error = api_result.failure()

                # 检测改名：404 + 有 platform_user_id + 未重试过
                if (
                    getattr(error, "status_code", None) == 404
                    and _retry_count == 0
                ):
                    new_username = await self._profile_service.detect_and_fix_rename(
                        username
                    )
                    if new_username:
                        logger.info(
                            "检测到改名: %s -> %s，使用新用户名重试",
                            username, new_username,
                        )
                        return await self.scrape_single_user(
                            new_username,
                            limit=limit,
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
                    await self._article_service.fetch_and_save_articles(cleaned_tweets)

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
        result: dict[str, Any] = {
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
                    await self._article_service.fetch_and_save_articles(cleaned_tweets)

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
                completed_at=datetime.now(UTC).replace(tzinfo=None),
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
            from src.data_layer.provider import get_follows_repo

            repo = get_follows_repo()
            await repo.update_backfill_status(
                username, status, completed_at=completed_at,
            )
        except Exception as e:
            logger.warning("更新回溯状态失败: username=%s, status=%s, error=%s", username, status, e)

    async def _get_fetch_stats(self, username: str) -> Any:
        """查询用户的历史抓取统计。

        Args:
            username: 用户名

        Returns:
            FetchStats | None: 统计数据，不存在时返回 None
        """
        try:
            from src.data_layer.provider import get_fetch_stats_repo

            repo = get_fetch_stats_repo()
            return await repo.get_stats(username)
        except Exception as e:
            logger.warning("查询抓取统计失败（使用默认 limit）: %s", e)
            return None

    async def _update_fetch_stats(
        self,
        username: str,
        old_stats: Any,
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
            from src.data_layer.provider import get_fetch_stats_repo

            updated = self._limit_calculator.update_stats_after_fetch(
                stats=old_stats,
                username=username,
                fetched_count=fetched_count,
                new_count=new_count,
            )

            repo = get_fetch_stats_repo()
            await repo.upsert_stats(updated)

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
        cursor: str | None = next_cursor

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
            from src.data_layer.provider import get_tweet_repo

            repo = get_tweet_repo()
            result = await repo.save_tweets(tweets, early_stop_threshold=early_stop)
            return cast(SaveResult, result)
        else:
            # 如果已经有 repository，由调用者管理事务
            return cast(
                SaveResult,
                await self._repository.save_tweets(
                    tweets, early_stop_threshold=early_stop
                ),
            )

    async def _backfill_platform_user_id(
        self, username: str, user_id: str
    ) -> None:
        """将 API 返回的 user_id 回填到 scraper_follows 表。

        仅在 platform_user_id 为空时执行写入，已有值时跳过。
        失败时仅记录警告日志，不影响抓取结果。
        """
        try:
            from src.data_layer.provider import get_follows_repo

            repo = get_follows_repo()
            await repo.update_platform_user_id(username, user_id)
            logger.info(
                "已回填 platform_user_id: %s -> %s", username, user_id
            )
        except Exception as e:
            logger.warning("回填 platform_user_id 失败（不影响抓取结果）: %s", e)

    def _summarize_results(
        self,
        usernames: list[str],
        results: list[dict[str, Any] | Exception],
    ) -> dict[str, Any]:
        """汇总抓取结果。

        Args:
            usernames: 用户名列表
            results: 抓取结果列表

        Returns:
            dict: 汇总统计
        """
        summary: dict[str, Any] = {
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
