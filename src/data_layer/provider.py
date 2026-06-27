"""M-5 数据层 provider:按 XWATCHER_DATA_LAYER 在旧 SQLAlchemy repo 与 se 文件层 store 间切换。

- 默认 file:旧 SQLAlchemy 能力可通过设 XWATCHER_DATA_LAYER=sqlalchemy 显式保留。
- 文件层 store 已实体化 vendoring 进 src.* 命名空间（早期曾用符号链接，见 754c0be）。
- import 延迟到函数内,使 env 变更逐调用生效(测试可 monkeypatch)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


def _data_layer() -> str:
    return os.environ.get("XWATCHER_DATA_LAYER", "file").strip().lower()


def is_file_mode() -> bool:
    """当前是否文件数据层模式(XWATCHER_DATA_LAYER=file)。pg 下线守卫用。"""
    return _data_layer() == "file"


def _data_root() -> Path:
    return Path(os.environ.get("XWATCHER_DATA_ROOT", "data_migrated"))


def data_root() -> Path:
    """文件数据层根目录(XWATCHER_DATA_ROOT,默认 data_migrated)。pg 下线守卫的单一真值源。"""
    return _data_root()


logger = logging.getLogger(__name__)


def get_follows_repo(session=None):
    """返回 FollowStore 形态 repo(12 契约方法)。

    file 模式:FileFollowStore(data_root),忽略 session。
    sqlalchemy 模式:ScraperConfigRepository(session)。
    """
    if _data_layer() == "file":
        from src.preference.infrastructure.file_follow_repository import FileFollowStore

        return FileFollowStore(_data_root())
    from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository

    return ScraperConfigRepository(session)


def get_profile_repo(session=None):
    """返回 ProfileStore 形态 repo(6 契约方法)。

    file 模式:FileProfileStore(data_root),忽略 session。
    sqlalchemy 模式:XUserProfileRepository(session)。
    """
    if _data_layer() == "file":
        from src.preference.infrastructure.file_profile_repository import FileProfileStore

        return FileProfileStore(_data_root())
    from src.preference.infrastructure.x_user_profile_repository import XUserProfileRepository

    return XUserProfileRepository(session)


def get_tweet_repo(session=None):
    """返回 TweetStore 形态 repo。file:FileTweetStore(忽略 session);sqlalchemy:TweetRepository(session)。"""
    if _data_layer() == "file":
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        return FileTweetStore(_data_root())
    from src.scraper.infrastructure.repository import TweetRepository

    return TweetRepository(session)


def get_tweet_read_repo(session=None):
    """返回 tweet 读门面(list_tweets / get_tweet_detail,供 /api/tweets 两端点)。

    file 模式:FileTweetReadStore(_data_root())(组合 FileTweetStore + FileSummaryStore;
      author 大小写不敏感 / created 窗 [after, before) / has_summary / DESC 分页;
      ⚠️ db_created_at 降级返 created_at),忽略 session。
    sqlalchemy 模式:SqlalchemyTweetReadStore(session)(逐字复刻两端点原 SQL,SQL 零变化)。
    """
    if _data_layer() == "file":
        from src.scraper.infrastructure.tweet_read_repository import FileTweetReadStore

        return FileTweetReadStore(_data_root())
    from src.scraper.infrastructure.tweet_read_repository import SqlalchemyTweetReadStore

    return SqlalchemyTweetReadStore(session)


def get_article_repo(session=None):
    """返回 ArticleStore 形态 repo。file:FileArticleStore;sqlalchemy:ArticleRepository(session)。"""
    if _data_layer() == "file":
        from src.scraper.infrastructure.file_article_repository import FileArticleStore

        return FileArticleStore(_data_root())
    from src.scraper.infrastructure.article_repository import ArticleRepository

    return ArticleRepository(session)


def get_article_read_repo(session=None):
    """返回 article 反连接读门面(get_unarticled_tweets:找无 article 记录的作者推文)。

    file 模式:FileArticleReadStore(_data_root())(组合 FileTweetStore+FileArticleStore 集合差,忽略 session)。
    sqlalchemy 模式:SqlalchemyArticleReadStore(session)(逐字复刻原内联反连接 SQL,SQL 零变化)。
    """
    if _data_layer() == "file":
        from src.scraper.infrastructure.article_read_repository import FileArticleReadStore

        return FileArticleReadStore(_data_root())
    from src.scraper.infrastructure.article_read_repository import SqlalchemyArticleReadStore

    return SqlalchemyArticleReadStore(session)


def get_fetch_stats_repo(session=None):
    """返回 FetchStatsStore 形态 repo。file:FileFetchStatsStore;sqlalchemy:FetchStatsRepository(session)。"""
    if _data_layer() == "file":
        from src.scraper.infrastructure.file_fetch_stats_repository import FileFetchStatsStore

        return FileFetchStatsStore(_data_root())
    from src.scraper.infrastructure.fetch_stats_repository import FetchStatsRepository

    return FetchStatsRepository(session)


def get_summary_repo(session=None):
    """返回 SummaryStore 形态 repo。file:FileSummaryStore(忽略 session);sqlalchemy:SummarizationRepository(session)。"""
    if _data_layer() == "file":
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

        return FileSummaryStore(_data_root())
    from src.summarization.infrastructure.repository import SummarizationRepository

    return SummarizationRepository(session)


def get_subject_repo(session=None):
    """返回 SubjectStore 形态 repo。file:FileSubjectStore;sqlalchemy:一期不实现。"""
    if _data_layer() == "file":
        from src.subjects.store import FileSubjectStore

        return FileSubjectStore(_data_root())
    raise NotImplementedError("SubjectStore sqlalchemy 模式尚未实现；本期仅支持 file 数据层")


def get_summarization_read_repo(session=None):
    """返回 summarization 读门面(get_unsummarized_tweets 反连接 + get_tweet_origins 原文回查)。

    file 模式:FileSummarizationReadStore(组合 FileTweetStore+FileSummaryStore),忽略 session。
    sqlalchemy 模式:SqlalchemySummarizationReadStore(session)(逐字复刻原 raw 查询,产同构 dict)。
    """
    if _data_layer() == "file":
        from src.summarization.infrastructure.file_summarization_read_repository import (
            FileSummarizationReadStore,
        )

        return FileSummarizationReadStore(_data_root())
    from src.data_layer._summarization_read_sqlalchemy import SqlalchemySummarizationReadStore

    return SqlalchemySummarizationReadStore(session)


def get_user_repo(session=None):
    """返回 UserStore 形态 repo(14 契约方法,含 get_password_hash_by_*)。

    file 模式:FileUserStore(data_root),忽略 session。
    sqlalchemy 模式:UserRepository(session)。
    """
    if _data_layer() == "file":
        from src.user.infrastructure.file_user_repository import FileUserStore

        return FileUserStore(_data_root())
    from src.user.infrastructure.repository import UserRepository

    return UserRepository(session)


class _FileExportSyncAdapter:
    """file 模式 export 同步门面:asyncio.run 桥 async FileExportStore.export_*,统一返 dict。

    调用上下文无 running loop(路由 to_thread 工作线程 / CLI 同步)→ asyncio.run 安全。
    暴露 export_service 调用的 6 方法名。
    """

    def __init__(self, store) -> None:
        self._store = store

    def get_follows(self):
        import asyncio

        return asyncio.run(self._store.export_follows())

    def get_tweets(self, since=None, until=None, authors=None):
        import asyncio

        return asyncio.run(self._store.export_tweets(since=since, until=until, authors=authors))

    def get_summaries(self, tweet_ids=None):
        import asyncio

        return asyncio.run(self._store.export_summaries(tweet_ids=tweet_ids))

    def get_articles(self, tweet_ids=None):
        import asyncio

        return asyncio.run(self._store.export_articles(tweet_ids=tweet_ids))


class _SqlalchemyExportDictAdapter:
    """sqlalchemy 模式 export 门面:套旧 ExportRepository + serializers.*_to_dict,统一返 dict。

    把原 export_service 的序列化职责搬进适配器,使两侧 export_service 消费同格式 dict。
    """

    def __init__(self, repo) -> None:
        self._repo = repo

    def get_follows(self):
        from src.sync.infrastructure.serializers import follow_to_dict

        return [follow_to_dict(f) for f in self._repo.get_follows()]

    def get_tweets(self, since=None, until=None, authors=None):
        from src.sync.infrastructure.serializers import tweet_to_dict

        return [
            tweet_to_dict(t)
            for t in self._repo.get_tweets(since=since, until=until, authors=authors)
        ]

    def get_summaries(self, tweet_ids=None):
        from src.sync.infrastructure.serializers import summary_to_dict

        return [summary_to_dict(s) for s in self._repo.get_summaries(tweet_ids=tweet_ids)]

    def get_articles(self, tweet_ids=None):
        from src.sync.infrastructure.serializers import article_to_dict

        return [article_to_dict(a) for a in self._repo.get_articles(tweet_ids=tweet_ids)]


def get_export_repo(session=None):
    """返回 export 门面。file:_FileExportSyncAdapter;sqlalchemy:_SqlalchemyExportDictAdapter。"""
    if _data_layer() == "file":
        from src.sync.infrastructure.file_export_repository import FileExportStore

        return _FileExportSyncAdapter(FileExportStore(_data_root()))
    from src.sync.infrastructure.export_repository import ExportRepository

    return _SqlalchemyExportDictAdapter(ExportRepository(session))


class _FileImportSyncAdapter:
    """file 模式 import 同步门面:asyncio.run 桥 async FileImportStore.import_*。

    dry_run=True 时 copytree data_root→temp、FileImportStore 指向 temp 跑、close() 清理 temp
    → 真数据未动(per-category 独立副本匹配 sqlalchemy per-category rollback 隔离)。
    调用上下文无 running loop(路由 to_thread / CLI 同步)→ asyncio.run 安全。
    """

    def __init__(self, data_root, dry_run=False) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        from src.sync.infrastructure.file_import_repository import FileImportStore

        self._dry_run = dry_run
        self._tmp = None
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
        self._store = FileImportStore(root)

    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def import_follows(self, items, strategy):
        return self._run(self._store.import_follows(items, strategy))

    def import_tweets(self, items, strategy):
        return self._run(self._store.import_tweets(items, strategy))

    def import_summaries(self, items, strategy):
        return self._run(self._store.import_summaries(items, strategy))

    def import_articles(self, items, strategy):
        return self._run(self._store.import_articles(items, strategy))

    def close(self) -> None:
        """清理 dry_run temp 副本(非 dry_run 无副本,no-op)。"""
        if self._tmp is not None:
            import shutil

            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None


def get_import_repo(session=None, dry_run=False):
    """返回 import 门面(import_*→ImportStats)。

    file 模式:_FileImportSyncAdapter(asyncio.run 桥;dry_run=True copytree 隔离写,真数据未动)。
    sqlalchemy 模式:旧 ImportRepository(session)(dry_run 由 import_service session.rollback 处理)。
    """
    if _data_layer() == "file":
        return _FileImportSyncAdapter(_data_root(), dry_run=dry_run)
    from src.sync.infrastructure.import_repository import ImportRepository

    return ImportRepository(session)


def get_browse_repo(session=None):
    """返回 browse 读门面(get_tweets / get_author_timeline 列表面 + get_daily_stats / get_authors 聚合两法)。

    file 模式:FileBrowseReadStore(_data_root())(组合 file store;列表面 summary JOIN,聚合两法纯 tweet 计数/分组)。
    sqlalchemy 模式:BrowseService(session)(现有服务不动)。
    """
    if _data_layer() == "file":
        from src.browse.infrastructure.file_browse_read_repository import FileBrowseReadStore

        return FileBrowseReadStore(_data_root())
    from src.browse.services.browse_service import BrowseService

    return BrowseService(session)


def get_feed_repo(session=None):
    """返回 feed 读门面(get_feed 时间窗增量 + author/keyword + summary JOIN)。

    file 模式:FileFeedReadStore(_data_root())(组合 file store + summary JOIN;db_created_at→None)。
    sqlalchemy 模式:FeedService(session)(现有服务不动,零行为变化)。
    """
    if _data_layer() == "file":
        from src.feed.infrastructure.file_feed_read_repository import FileFeedReadStore

        return FileFeedReadStore(_data_root())
    from src.feed.services.feed_service import FeedService

    return FeedService(session)


def get_search_repo(session=None):
    """返回 search 读门面(search_tweets 多词 AND 全文 + 时间窗/author + summary JOIN)。

    file 模式:FileSearchReadStore(_data_root())(窗口快路径/全扫 + 多词 AND;db_created_at→None)。
    sqlalchemy 模式:SearchService(session)(现有服务不动,零行为变化)。
    """
    if _data_layer() == "file":
        from src.search.infrastructure.file_search_read_repository import FileSearchReadStore

        return FileSearchReadStore(_data_root())
    from src.search.services.search_service import SearchService

    return SearchService(session)


def get_scraper_stats_repo(session=None):
    """返回 scraper_config 账号聚合读门面(max_period_counts / tweet_time_range / period_analysis)。

    file 模式:FileScraperStatsReadStore(_data_root())(组合 FileTweetStore Python 槽聚合;
      ⚠️ max_period_counts 用 round-half-up 整数分桶复刻生产 PG cast 进位,非 floor)。
    sqlalchemy 模式:SqlalchemyScraperStatsReadStore(session)(转调与原端点等价内联 SQL,SQL 零变化)。
    """
    if _data_layer() == "file":
        from src.preference.infrastructure.scraper_stats_read_repository import (
            FileScraperStatsReadStore,
        )

        return FileScraperStatsReadStore(_data_root())
    from src.preference.infrastructure.scraper_stats_read_repository import (
        SqlalchemyScraperStatsReadStore,
    )

    return SqlalchemyScraperStatsReadStore(session)


def get_status_repo(session=None):
    """返回 status 统计读门面(get_tweet_stats / get_follow_stats / get_summary_stats)。

    file 模式:FileStatusReadStore(_data_root())(组合 file store 在 Python 槽 count/max/反连接,忽略 session)。
    sqlalchemy 模式:SqlalchemyStatusReadStore(session)(薄 wrapper 转调旧 _get_*_stats,SQL 字节零变化)。
    """
    if _data_layer() == "file":
        from src.api.status_read_repository import FileStatusReadStore

        return FileStatusReadStore(_data_root())
    from src.api.status_read_repository import SqlalchemyStatusReadStore

    return SqlalchemyStatusReadStore(session)
