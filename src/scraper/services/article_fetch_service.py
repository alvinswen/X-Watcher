"""X Article fetching and persistence services."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from returns.result import Failure, Success

from src.scraper.client import TwitterClient
from src.scraper.domain.models import Tweet

logger = logging.getLogger(__name__)


class ArticleFetchService:
    """Fetch and persist X Articles for live and backfill workflows."""

    def __init__(self, client: TwitterClient | None = None) -> None:
        self._client = client or TwitterClient()

    async def fetch_and_save_articles(self, tweets: list[Tweet]) -> None:
        """检测并保存推文关联的 X Article。

        使用推文自带的 article 预览字段（has_article）进行零成本检测，
        然后调用 /article API 获取全文。API 失败时 fallback 到预览信息。
        """
        article_tweets = [t for t in tweets if t.has_article]

        if not article_tweets:
            return

        logger.info("检测到 %d 条推文含 Article（via article 字段），开始获取", len(article_tweets))

        try:
            from src.data_layer.provider import get_article_repo
            from src.scraper.domain.models import Article

            for tweet in article_tweets:
                try:
                    # 检查是否已存在
                    repo = get_article_repo()
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
                            fetched_at=datetime.now(UTC),
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
                            fetched_at=datetime.now(UTC),
                        )

                    repo = get_article_repo()
                    saved = await repo.save_article(article)

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
            from src.data_layer.provider import (
                get_article_read_repo,
                get_article_repo,
            )
            from src.scraper.domain.models import Article

            # 1. 查询该用户尚无 article 记录的推文 ID(file 模式走文件层反连接门面)
            tweet_ids = await get_article_read_repo().get_unarticled_tweets(
                username, max_tweets=max_tweets
            )

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
                        fetched_at=datetime.now(UTC),
                    )

                    repo = get_article_repo()
                    saved = await repo.save_article(article)

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

    async def close(self) -> None:
        """Close the underlying client for standalone use."""
        await self._client.close()
