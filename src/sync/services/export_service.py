"""Export 服务。

编排 repository → serializer → ExportPackage 组装。
"""

from datetime import datetime, timezone
from typing import Any

from src.sync.domain.models import (
    ExportFilters,
    ExportMetadata,
    ExportPackage,
    SyncCategory,
)
from src.data_layer.provider import get_export_repo


class ExportService:
    """编排数据导出流程。"""

    def __init__(self, session: Any = None) -> None:
        self._repo = get_export_repo(session)

    def export(
        self,
        categories: list[SyncCategory] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        authors: list[str] | None = None,
        instance_id: str = "unknown",
    ) -> ExportPackage:
        """执行导出。

        Args:
            categories: 要导出的分类，None 表示全部
            since: content 过滤 - 起始时间
            until: content 过滤 - 结束时间
            authors: content 过滤 - 作者列表
            instance_id: 来源实例标识

        Returns:
            ExportPackage 包含元数据和数据
        """
        if categories is None:
            categories = list(SyncCategory)

        data: dict[str, Any] = {}
        counts: dict[str, int] = {}

        if SyncCategory.config in categories:
            config_data, config_counts = self._export_config()
            data["config"] = config_data
            counts.update(config_counts)

        if SyncCategory.content in categories:
            content_data, content_counts = self._export_content(
                since=since, until=until, authors=authors
            )
            data["content"] = content_data
            counts.update(content_counts)

        metadata = ExportMetadata(
            exported_at=datetime.now(timezone.utc),
            source_instance_id=instance_id,
            categories=[c.value for c in categories],
            filters=ExportFilters(since=since, until=until, authors=authors),
            counts=counts,
        )

        return ExportPackage(metadata=metadata, data=data)

    def _export_config(self) -> tuple[dict[str, Any], dict[str, int]]:
        follows = self._repo.get_follows()

        config_data: dict[str, Any] = {
            "scraper_follows": follows,
        }
        counts = {"scraper_follows": len(follows)}

        return config_data, counts

    def _export_content(
        self,
        since: datetime | None,
        until: datetime | None,
        authors: list[str] | None,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        tweets = self._repo.get_tweets(since=since, until=until, authors=authors)
        tweet_ids = [t["tweet_id"] for t in tweets] if tweets else None

        summaries = self._repo.get_summaries(tweet_ids=tweet_ids)
        articles = self._repo.get_articles(tweet_ids=tweet_ids)

        content_data = {
            "tweets": tweets,
            "summaries": summaries,
            "articles": articles,
        }
        counts = {
            "tweets": len(tweets),
            "summaries": len(summaries),
            "articles": len(articles),
        }
        return content_data, counts
