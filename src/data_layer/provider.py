"""M-5 数据层 provider:按 XWATCHER_DATA_LAYER 在旧 SQLAlchemy repo 与 se 文件层 store 间切换。

- 默认 sqlalchemy:旧应用零行为变化;设 XWATCHER_DATA_LAYER=file 切到文件层。
- 文件层 store 经 scripts/link_se_stores.sh 符号链接进 src.* 命名空间。
- import 延迟到函数内,使 env 变更逐调用生效(测试可 monkeypatch)。
"""
from __future__ import annotations

import os
from pathlib import Path


def _data_layer() -> str:
    return os.environ.get("XWATCHER_DATA_LAYER", "sqlalchemy").strip().lower()


def _data_root() -> Path:
    return Path(os.environ.get("XWATCHER_DATA_ROOT", "data"))


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
