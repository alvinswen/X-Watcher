"""Import 服务。

按 FK 顺序处理 categories，应用冲突策略，dry-run 支持，per-category 事务。
"""

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from src.sync.domain.models import (
    ConflictStrategy,
    ExportPackage,
    ImportResult,
    ImportStats,
    SyncCategory,
)
from src.sync.infrastructure.import_repository import ImportRepository


class ImportService:
    """编排数据导入流程。"""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def import_data(
        self,
        package: ExportPackage,
        categories: list[SyncCategory] | None = None,
        strategy: ConflictStrategy = ConflictStrategy.skip,
        dry_run: bool = False,
    ) -> ImportResult:
        """执行导入。

        按 FK 顺序处理：config → tweets → summaries → articles → topics。
        每个 category 使用独立事务，单个 category 失败不影响已提交的 category。
        """
        if categories is None:
            # 只导入文件中包含的分类
            available = package.metadata.categories
            categories = [SyncCategory(c) for c in available if c in SyncCategory.__members__]

        result = ImportResult(dry_run=dry_run)

        # 按 FK 顺序处理
        if SyncCategory.config in categories and "config" in package.data:
            self._import_category(
                "config", package.data["config"], strategy, dry_run, result
            )

        if SyncCategory.content in categories and "content" in package.data:
            self._import_category(
                "content", package.data["content"], strategy, dry_run, result
            )

        if SyncCategory.topics in categories and "topics" in package.data:
            self._import_category(
                "topics", package.data["topics"], strategy, dry_run, result
            )

        return result

    def _import_category(
        self,
        category: str,
        data: dict[str, Any],
        strategy: ConflictStrategy,
        dry_run: bool,
        result: ImportResult,
    ) -> None:
        """在独立事务中导入一个 category。"""
        session: Session = self._session_factory()
        try:
            repo = ImportRepository(session)

            if category == "config":
                self._import_config(repo, data, strategy, result)
            elif category == "content":
                self._import_content(repo, data, strategy, result)
            elif category == "topics":
                self._import_topics(repo, data, strategy, result)

            if dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as e:
            session.rollback()
            result.success = False
            result.errors.append(f"[{category}] {e}")
        finally:
            session.close()

    def _import_config(
        self,
        repo: ImportRepository,
        data: dict[str, Any],
        strategy: ConflictStrategy,
        result: ImportResult,
    ) -> None:
        follows = data.get("scraper_follows", [])
        if follows:
            result.stats["scraper_follows"] = repo.import_follows(follows, strategy)

        schedule = data.get("scraper_schedule_config")
        if schedule is not None:
            result.stats["scraper_schedule_config"] = repo.import_schedule_config(
                schedule, strategy
            )

    def _import_content(
        self,
        repo: ImportRepository,
        data: dict[str, Any],
        strategy: ConflictStrategy,
        result: ImportResult,
    ) -> None:
        # 按 FK 顺序：tweets → summaries → articles
        tweets = data.get("tweets", [])
        if tweets:
            result.stats["tweets"] = repo.import_tweets(tweets, strategy)

        summaries = data.get("summaries", [])
        if summaries:
            result.stats["summaries"] = repo.import_summaries(summaries, strategy)

        articles = data.get("articles", [])
        if articles:
            result.stats["articles"] = repo.import_articles(articles, strategy)

    def _import_topics(
        self,
        repo: ImportRepository,
        data: dict[str, Any],
        strategy: ConflictStrategy,
        result: ImportResult,
    ) -> None:
        topics = data.get("topics", [])
        if topics:
            result.stats["topics"] = repo.import_topics(topics, strategy)
