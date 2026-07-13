"""Import 服务。

按 FK 顺序处理 categories，应用冲突策略，dry-run 支持，per-category 事务。
"""

from __future__ import annotations

from typing import Any

from src.sync.domain.models import (
    ConflictStrategy,
    ExportPackage,
    ImportResult,
    SyncCategory,
)
from src.data_layer.provider import get_import_repo


class ImportService:
    """编排数据导入流程。"""

    def import_data(
        self,
        package: ExportPackage,
        categories: list[SyncCategory] | None = None,
        strategy: ConflictStrategy = ConflictStrategy.skip,
        dry_run: bool = False,
    ) -> ImportResult:
        """执行导入。

        按 FK 顺序处理：config → tweets → summaries → articles。
        每个 category 使用独立事务，单个 category 失败不影响已提交的 category。
        """
        if categories is None:
            # 只导入文件中包含的分类
            available = package.metadata.categories
            categories = [SyncCategory(c) for c in available if c in SyncCategory.__members__]

        result = ImportResult(dry_run=dry_run)

        # 按 FK 顺序处理
        if SyncCategory.config in categories and "config" in package.data:
            self._import_category("config", package.data["config"], strategy, dry_run, result)

        if SyncCategory.content in categories and "content" in package.data:
            self._import_category("content", package.data["content"], strategy, dry_run, result)

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
        repo = get_import_repo(dry_run=dry_run)
        try:
            if category == "config":
                self._import_config(repo, data, strategy, result)
            elif category == "content":
                self._import_content(repo, data, strategy, result)
        except Exception as e:
            result.success = False
            result.errors.append(f"[{category}] {e}")
        finally:
            if hasattr(repo, "close"):
                repo.close()

    def _import_config(
        self,
        repo: Any,
        data: dict[str, Any],
        strategy: ConflictStrategy,
        result: ImportResult,
    ) -> None:
        follows = data.get("scraper_follows", [])
        if follows:
            result.stats["scraper_follows"] = repo.import_follows(follows, strategy)

    def _import_content(
        self,
        repo: Any,
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
