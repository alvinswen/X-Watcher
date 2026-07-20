"""Import 服务。

按 FK 顺序处理 categories，应用冲突策略，dry-run 支持，per-category 事务。
"""

from __future__ import annotations

from typing import Any

from src.data_layer.provider import get_import_repo
from src.shared.error_messages import SYNC_IMPORT_USERNAME_BLOCKED_TMPL
from src.shared.username import is_valid_username_format
from src.sync.domain.models import (
    ConflictStrategy,
    ExportPackage,
    ImportResult,
    ImportStats,
    SyncCategory,
)


def _split_by_username_validity(
    items: list[dict[str, Any]], field: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """按严格版白名单切分。缺字段/None/非 str 一律判非法（拼路径同样危险）。"""
    valid: list[dict[str, Any]] = []
    blocked: list[str] = []
    for item in items:
        value = item.get(field)
        if isinstance(value, str) and is_valid_username_format(value):
            valid.append(item)
        else:
            blocked.append(repr(value))
    return valid, blocked


def _record_blocked(result: ImportResult, table: str, blocked: list[str]) -> None:
    stats = result.stats.setdefault(table, ImportStats())
    stats.skipped += len(blocked)
    result.errors.append(
        SYNC_IMPORT_USERNAME_BLOCKED_TMPL.format(
            table=table, count=len(blocked), examples=", ".join(blocked[:5])
        )
    )


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
            valid, blocked = _split_by_username_validity(follows, "username")
            if valid:
                result.stats["scraper_follows"] = repo.import_follows(valid, strategy)
            if blocked:
                _record_blocked(result, "scraper_follows", blocked)

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
            valid, blocked = _split_by_username_validity(tweets, "author_username")
            if valid:
                result.stats["tweets"] = repo.import_tweets(valid, strategy)
            if blocked:
                _record_blocked(result, "tweets", blocked)

        summaries = data.get("summaries", [])
        if summaries:
            result.stats["summaries"] = repo.import_summaries(summaries, strategy)

        articles = data.get("articles", [])
        if articles:
            result.stats["articles"] = repo.import_articles(articles, strategy)
