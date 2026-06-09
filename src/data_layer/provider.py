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


def _data_root() -> Path:
    return Path(os.environ.get("XWATCHER_DATA_ROOT", "data"))


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


def get_article_repo(session=None):
    """返回 ArticleStore 形态 repo。file:FileArticleStore;sqlalchemy:ArticleRepository(session)。"""
    if _data_layer() == "file":
        from src.scraper.infrastructure.file_article_repository import FileArticleStore

        return FileArticleStore(_data_root())
    from src.scraper.infrastructure.article_repository import ArticleRepository

    return ArticleRepository(session)


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
