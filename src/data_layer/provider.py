"""数据层 provider:文件层唯一数据层,各 get_*_repo 工厂固定返回 File* store。

- 文件层 store 已实体化 vendoring 进 src.* 命名空间（早期曾用符号链接，见 754c0be）。
- import 延迟到函数内,使 env 变更逐调用生效(测试可 monkeypatch)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any


def _data_root() -> Path:
    return Path(os.environ.get("XWATCHER_DATA_ROOT", "data_migrated"))


def data_root() -> Path:
    """文件数据层根目录(XWATCHER_DATA_ROOT,默认 data_migrated)。pg 下线守卫的单一真值源。"""
    return _data_root()


logger = logging.getLogger(__name__)


def get_follows_repo() -> Any:
    """返回 FollowStore 形态 repo(12 契约方法)。

    固定返回 FileFollowStore(data_root)。
    """
    from src.preference.infrastructure.file_follow_repository import FileFollowStore

    return FileFollowStore(_data_root())


def get_profile_repo() -> Any:
    """返回 ProfileStore 形态 repo(6 契约方法)。

    固定返回 FileProfileStore(data_root)。
    """
    from src.preference.infrastructure.file_profile_repository import FileProfileStore

    return FileProfileStore(_data_root())


def get_tweet_repo() -> Any:
    """返回 TweetStore 形态 repo。

    固定返回 FileTweetStore(_data_root())。
    """
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    return FileTweetStore(_data_root())


def get_tweet_read_repo() -> Any:
    """返回 tweet 读门面(list_tweets / get_tweet_detail,供 /api/tweets 两端点)。

    固定返回 FileTweetReadStore(_data_root())。
    """
    from src.scraper.infrastructure.tweet_read_repository import FileTweetReadStore

    return FileTweetReadStore(_data_root())


def get_article_repo() -> Any:
    """返回 ArticleStore 形态 repo。

    固定返回 FileArticleStore(_data_root())。
    """
    from src.scraper.infrastructure.file_article_repository import FileArticleStore

    return FileArticleStore(_data_root())


def get_article_read_repo() -> Any:
    """返回 article 反连接读门面(get_unarticled_tweets:找无 article 记录的作者推文)。

    固定返回 FileArticleReadStore(_data_root())(组合 FileTweetStore+FileArticleStore 集合差)。
    """
    from src.scraper.infrastructure.article_read_repository import FileArticleReadStore

    return FileArticleReadStore(_data_root())


def get_fetch_stats_repo() -> Any:
    """返回 FetchStatsStore 形态 repo,固定 FileFetchStatsStore(data_root)。"""
    from src.scraper.infrastructure.file_fetch_stats_repository import FileFetchStatsStore

    return FileFetchStatsStore(_data_root())


def get_summary_repo() -> Any:
    """返回 SummaryStore 形态 repo,固定 FileSummaryStore(data_root)。"""
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

    return FileSummaryStore(_data_root())


def get_subject_repo() -> Any:
    """返回 SubjectStore 形态 repo。

    固定返回 FileSubjectStore(_data_root())。
    """
    from src.subjects.store import FileSubjectStore

    return FileSubjectStore(_data_root())


def get_summarization_read_repo() -> Any:
    """返回 summarization 读门面(get_unsummarized_tweets 反连接 + get_tweet_origins 原文回查)。

    固定返回 FileSummarizationReadStore(组合 FileTweetStore+FileSummaryStore)。
    """
    from src.summarization.infrastructure.file_summarization_read_repository import (
        FileSummarizationReadStore,
    )

    return FileSummarizationReadStore(_data_root())


def get_user_repo() -> Any:
    """返回 UserStore 形态 repo(14 契约方法,含 get_password_hash_by_*)。

    固定返回 FileUserStore(data_root)。
    """
    from src.user.infrastructure.file_user_repository import FileUserStore

    return FileUserStore(_data_root())


class _FileExportSyncAdapter:
    """file 模式 export 同步门面:asyncio.run 桥 async FileExportStore.export_*,统一返 dict。

    调用上下文无 running loop(路由 to_thread 工作线程 / CLI 同步)→ asyncio.run 安全。
    暴露 export_service 调用的 6 方法名。
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def get_follows(self) -> Any:
        import asyncio

        return asyncio.run(self._store.export_follows())

    def get_tweets(self, since: Any = None, until: Any = None, authors: Any = None) -> Any:
        import asyncio

        return asyncio.run(self._store.export_tweets(since=since, until=until, authors=authors))

    def get_summaries(self, tweet_ids: Any = None) -> Any:
        import asyncio

        return asyncio.run(self._store.export_summaries(tweet_ids=tweet_ids))

    def get_articles(self, tweet_ids: Any = None) -> Any:
        import asyncio

        return asyncio.run(self._store.export_articles(tweet_ids=tweet_ids))


def get_export_repo() -> Any:
    """返回 export 文件同步门面 _FileExportSyncAdapter。"""
    from src.sync.infrastructure.file_export_repository import FileExportStore

    return _FileExportSyncAdapter(FileExportStore(_data_root()))


class _FileImportSyncAdapter:
    """file 模式 import 同步门面:asyncio.run 桥 async FileImportStore.import_*。

    dry_run=True 时 copytree data_root→temp、FileImportStore 指向 temp 跑、close() 清理 temp
    → 真数据未动(per-category 独立副本匹配 sqlalchemy per-category rollback 隔离)。
    调用上下文无 running loop(路由 to_thread / CLI 同步)→ asyncio.run 安全。
    """

    def __init__(self, data_root: str | Path, dry_run: bool = False) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        from src.sync.infrastructure.file_import_repository import FileImportStore

        self._dry_run = dry_run
        self._tmp = None
        root: str | Path
        if dry_run:
            self._tmp = tempfile.mkdtemp(prefix="xw-import-dryrun-")
            try:
                src = Path(data_root)
                if src.exists():
                    shutil.copytree(src, self._tmp, dirs_exist_ok=True)
            except Exception:
                # 构造期 copytree 失败(磁盘满/权限):先清理 temp 再上抛,避免泄漏
                shutil.rmtree(self._tmp, ignore_errors=True)
                self._tmp = None
                raise
            root = self._tmp
        else:
            root = data_root
        self._store = FileImportStore(Path(root))

    def _run(self, coro: Any) -> Any:
        import asyncio

        return asyncio.run(coro)

    def import_follows(self, items: Any, strategy: Any) -> Any:
        return self._run(self._store.import_follows(items, strategy))

    def import_tweets(self, items: Any, strategy: Any) -> Any:
        return self._run(self._store.import_tweets(items, strategy))

    def import_summaries(self, items: Any, strategy: Any) -> Any:
        return self._run(self._store.import_summaries(items, strategy))

    def import_articles(self, items: Any, strategy: Any) -> Any:
        return self._run(self._store.import_articles(items, strategy))

    def close(self) -> None:
        """清理 dry_run temp 副本(非 dry_run 无副本,no-op)。"""
        if self._tmp is not None:
            import shutil

            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None


def get_import_repo(dry_run: bool = False) -> Any:
    """返回 import 门面(import_*→ImportStats)。

    固定返回 _FileImportSyncAdapter(asyncio.run 桥;dry_run=True copytree 隔离写,真数据未动)。
    """
    return _FileImportSyncAdapter(_data_root(), dry_run=dry_run)


def get_browse_repo() -> Any:
    """返回 browse 读门面(get_tweets / get_author_timeline 列表面 + get_daily_stats / get_authors 聚合两法)。

    固定返回 FileBrowseReadStore(_data_root())。
    """
    from src.browse.infrastructure.file_browse_read_repository import FileBrowseReadStore

    return FileBrowseReadStore(_data_root())


def get_feed_repo() -> Any:
    """返回 feed 读门面(get_feed 时间窗增量 + author/keyword + summary JOIN)。

    固定返回 FileFeedReadStore(_data_root())。
    """
    from src.feed.infrastructure.file_feed_read_repository import FileFeedReadStore

    return FileFeedReadStore(_data_root())


def get_search_repo() -> Any:
    """返回 search 读门面(search_tweets 多词 AND 全文 + 时间窗/author + summary JOIN)。

    固定返回 FileSearchReadStore(_data_root())。
    """
    from src.search.infrastructure.file_search_read_repository import FileSearchReadStore

    return FileSearchReadStore(_data_root())


def get_scraper_stats_repo() -> Any:
    """返回 scraper_config 账号聚合读门面(tweet_time_range / period_analysis)。

    固定返回 FileScraperStatsReadStore(_data_root())。
    """
    from src.preference.infrastructure.scraper_stats_read_repository import (
        FileScraperStatsReadStore,
    )

    return FileScraperStatsReadStore(_data_root())


def get_status_repo() -> Any:
    """返回 status 统计读门面(get_tweet_stats / get_follow_stats / get_summary_stats)。

    固定返回 FileStatusReadStore(_data_root())。
    """
    from src.api.status_read_repository import FileStatusReadStore

    return FileStatusReadStore(_data_root())
