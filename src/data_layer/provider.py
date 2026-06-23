"""M-5 数据层 provider:按 XWATCHER_DATA_LAYER 在旧 SQLAlchemy repo 与 se 文件层 store 间切换。

- 默认 sqlalchemy:旧应用零行为变化;设 XWATCHER_DATA_LAYER=file 切到文件层。
- 文件层 store 经 scripts/link_se_stores.sh 符号链接进 src.* 命名空间。
- import 延迟到函数内,使 env 变更逐调用生效(测试可 monkeypatch)。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path


def _data_layer() -> str:
    return os.environ.get("XWATCHER_DATA_LAYER", "sqlalchemy").strip().lower()


def is_file_mode() -> bool:
    """当前是否文件数据层模式(XWATCHER_DATA_LAYER=file)。pg 下线守卫用。"""
    return _data_layer() == "file"


def _data_root() -> Path:
    return Path(os.environ.get("XWATCHER_DATA_ROOT", "data"))


def data_root() -> Path:
    """文件数据层根目录(XWATCHER_DATA_ROOT,默认 data)。pg 下线守卫的单一真值源。"""
    return _data_root()


logger = logging.getLogger(__name__)

# 模块级:串化跨线程同步写,规避 asyncio.Lock 跨 loop/跨线程复用(file 模式同步桥接专用)
_SCHEDULER_LOG_SYNC_LOCK = threading.Lock()


def get_schedule_repo(session=None):
    """返回 ScheduleStore 形态 repo(get_schedule_config / upsert_schedule_config)。

    file 模式:FileScheduleStore(data_root),忽略 session。
    sqlalchemy 模式:ScraperScheduleRepository(session)。
    """
    if _data_layer() == "file":
        from src.preference.infrastructure.file_schedule_repository import FileScheduleStore

        return FileScheduleStore(_data_root())
    from src.preference.infrastructure.schedule_repository import ScraperScheduleRepository

    return ScraperScheduleRepository(session)


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


def get_scheduler_log_repo(session=None):
    """返回 SchedulerLogStore 形态 repo(async 读/cleanup)。file:FileSchedulerLogStore;sqlalchemy:SchedulerExecutionLogRepository(session)。"""
    if _data_layer() == "file":
        from src.scraper.infrastructure.file_scheduler_log_repository import FileSchedulerLogStore

        return FileSchedulerLogStore(_data_root())
    from src.scraper.infrastructure.scheduler_log_repository import SchedulerExecutionLogRepository

    return SchedulerExecutionLogRepository(session)


class _FileSchedulerLogSyncWriter:
    """file 模式同步桥接:把 async 文件层 write_log 桥到同步调用点。

    BackgroundScheduler 回调线程无 running loop → asyncio.run 安全。
    threading.Lock 串化跨线程并发(多 job 同刻完成);整体 try/except 吞异常仅 log,
    镜像旧 SchedulerExecutionLogSyncWriter「写失败不影响调度器运行」契约。
    """

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root

    def write_log(self, log) -> None:
        try:
            import asyncio

            from src.scraper.infrastructure.file_scheduler_log_repository import FileSchedulerLogStore

            with _SCHEDULER_LOG_SYNC_LOCK:
                asyncio.run(FileSchedulerLogStore(self._data_root).write_log(log))
        except Exception as e:  # noqa: BLE001
            logger.error("file 模式同步写入调度器执行日志失败: %s", e, exc_info=True)


def get_scheduler_log_sync_writer():
    """返回带 write_log(log) 的同步写入器(鸭子兼容旧静态调用 `.write_log(log_entry)`)。

    file 模式:_FileSchedulerLogSyncWriter 实例(asyncio.run 桥接 async 文件层)。
    sqlalchemy 模式:旧 SchedulerExecutionLogSyncWriter 类本身(静态 write_log,零行为变化)。
    """
    if _data_layer() == "file":
        return _FileSchedulerLogSyncWriter(_data_root())
    from src.scraper.infrastructure.scheduler_log_repository import SchedulerExecutionLogSyncWriter

    return SchedulerExecutionLogSyncWriter


def get_summary_repo(session=None):
    """返回 SummaryStore 形态 repo。file:FileSummaryStore(忽略 session);sqlalchemy:SummarizationRepository(session)。"""
    if _data_layer() == "file":
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

        return FileSummaryStore(_data_root())
    from src.summarization.infrastructure.repository import SummarizationRepository

    return SummarizationRepository(session)


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


def get_topic_store(session=None):
    """返回 TopicStore 形态 repo(11 契约方法)。

    file 模式:FileTopicStore(data_root),忽略 session。
    sqlalchemy 模式:SqlalchemyTopicStore(session)(包旧 TopicRepository,延迟 commit)。
    """
    if _data_layer() == "file":
        from src.topic.infrastructure.file_topic_repository import FileTopicStore

        return FileTopicStore(_data_root())
    from src.data_layer._topic_sqlalchemy import SqlalchemyTopicStore

    return SqlalchemyTopicStore(session)


def get_topic_summary_task_store(session=None):
    """返回 TopicTaskStore 形态 repo(8 契约方法)。

    file 模式:FileTopicSummaryTaskStore(data_root),忽略 session。
    sqlalchemy 模式:SqlalchemyTopicSummaryTaskStore(session)。
    """
    if _data_layer() == "file":
        from src.topic.infrastructure.file_topic_summary_task_repository import (
            FileTopicSummaryTaskStore,
        )

        return FileTopicSummaryTaskStore(_data_root())
    from src.data_layer._topic_sqlalchemy import SqlalchemyTopicSummaryTaskStore

    return SqlalchemyTopicSummaryTaskStore(session)


def get_topic_query_repo(session=None):
    """返回 topic 跨域读门面(query_tweets:取指定账号在时间窗内的推文 outerjoin 翻译)。

    file 模式:FileTopicQueryStore(_data_root())(组合 FileTweetStore+FileSummaryStore;
      作者大小写不敏感 + 闭区间时间窗 + outerjoin translation + ASC;created_at 归一 naive-UTC),忽略 session。
    sqlalchemy 模式:SqlalchemyTopicQueryStore(session)(逐字复刻原内联 outerjoin SQL,SQL 零变化)。
    """
    if _data_layer() == "file":
        from src.topic.infrastructure.topic_query_read_repository import FileTopicQueryStore

        return FileTopicQueryStore(_data_root())
    from src.topic.infrastructure.topic_query_read_repository import SqlalchemyTopicQueryStore

    return SqlalchemyTopicQueryStore(session)


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

    def get_schedule_config(self):
        import asyncio
        return asyncio.run(self._store.export_schedule_config())

    def get_tweets(self, since=None, until=None, authors=None):
        import asyncio
        return asyncio.run(self._store.export_tweets(since=since, until=until, authors=authors))

    def get_summaries(self, tweet_ids=None):
        import asyncio
        return asyncio.run(self._store.export_summaries(tweet_ids=tweet_ids))

    def get_articles(self, tweet_ids=None):
        import asyncio
        return asyncio.run(self._store.export_articles(tweet_ids=tweet_ids))

    def get_topics(self):
        import asyncio
        return asyncio.run(self._store.export_topics())


class _SqlalchemyExportDictAdapter:
    """sqlalchemy 模式 export 门面:套旧 ExportRepository + serializers.*_to_dict,统一返 dict。

    把原 export_service 的序列化职责搬进适配器,使两侧 export_service 消费同格式 dict。
    """

    def __init__(self, repo) -> None:
        self._repo = repo

    def get_follows(self):
        from src.sync.infrastructure.serializers import follow_to_dict
        return [follow_to_dict(f) for f in self._repo.get_follows()]

    def get_schedule_config(self):
        from src.sync.infrastructure.serializers import schedule_config_to_dict
        c = self._repo.get_schedule_config()
        return schedule_config_to_dict(c) if c is not None else None

    def get_tweets(self, since=None, until=None, authors=None):
        from src.sync.infrastructure.serializers import tweet_to_dict
        return [tweet_to_dict(t) for t in self._repo.get_tweets(since=since, until=until, authors=authors)]

    def get_summaries(self, tweet_ids=None):
        from src.sync.infrastructure.serializers import summary_to_dict
        return [summary_to_dict(s) for s in self._repo.get_summaries(tweet_ids=tweet_ids)]

    def get_articles(self, tweet_ids=None):
        from src.sync.infrastructure.serializers import article_to_dict
        return [article_to_dict(a) for a in self._repo.get_articles(tweet_ids=tweet_ids)]

    def get_topics(self):
        from src.sync.infrastructure.serializers import topic_to_dict
        return [topic_to_dict(t) for t in self._repo.get_topics()]


def get_export_repo(session=None):
    """返回 export 门面(统一 6 方法返 dict)。file:_FileExportSyncAdapter;sqlalchemy:_SqlalchemyExportDictAdapter。"""
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

    def import_schedule_config(self, item, strategy):
        return self._run(self._store.import_schedule_config(item, strategy))

    def import_tweets(self, items, strategy):
        return self._run(self._store.import_tweets(items, strategy))

    def import_summaries(self, items, strategy):
        return self._run(self._store.import_summaries(items, strategy))

    def import_articles(self, items, strategy):
        return self._run(self._store.import_articles(items, strategy))

    def import_topics(self, items, strategy):
        return self._run(self._store.import_topics(items, strategy))

    def close(self) -> None:
        """清理 dry_run temp 副本(非 dry_run 无副本,no-op)。"""
        if self._tmp is not None:
            import shutil

            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None


def get_import_repo(session=None, dry_run=False):
    """返回 import 门面(6 方法同名同形 import_*→ImportStats)。

    file 模式:_FileImportSyncAdapter(asyncio.run 桥;dry_run=True copytree 隔离写,真数据未动)。
    sqlalchemy 模式:旧 ImportRepository(session)(dry_run 由 import_service session.rollback 处理)。
    """
    if _data_layer() == "file":
        return _FileImportSyncAdapter(_data_root(), dry_run=dry_run)
    from src.sync.infrastructure.import_repository import ImportRepository

    return ImportRepository(session)


def get_analytics_repo(session=None):
    """返回 analytics 读门面(get_posting_frequency)。

    file 模式:FileAnalyticsStore(_data_root())(忽略 session,Python 槽聚合)。
    sqlalchemy 模式:AnalyticsService(session)(现有 SQL 不动,零行为变化)。
    """
    if _data_layer() == "file":
        from src.analytics.infrastructure.file_analytics_repository import FileAnalyticsStore

        return FileAnalyticsStore(_data_root())
    from src.analytics.services.analytics_service import AnalyticsService

    return AnalyticsService(session)


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
    """返回 status 统计读门面(get_tweet_stats / get_follow_stats / get_summary_stats / get_topic_stats)。

    file 模式:FileStatusReadStore(_data_root())(组合 file store 在 Python 槽 count/max/反连接,忽略 session)。
    sqlalchemy 模式:SqlalchemyStatusReadStore(session)(薄 wrapper 转调旧 _get_*_stats,SQL 字节零变化)。
    """
    if _data_layer() == "file":
        from src.api.status_read_repository import FileStatusReadStore

        return FileStatusReadStore(_data_root())
    from src.api.status_read_repository import SqlalchemyStatusReadStore

    return SqlalchemyStatusReadStore(session)
