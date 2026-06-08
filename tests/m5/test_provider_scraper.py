"""M-5 provider:scraper 簇 4 async 工厂 + 同步写入器 按 env flag 切换。"""


def test_get_tweet_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_tweet_repo
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    assert isinstance(get_tweet_repo(session=None), FileTweetStore)


def test_get_tweet_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_tweet_repo
    from src.scraper.infrastructure.repository import TweetRepository

    assert isinstance(get_tweet_repo(session=None), TweetRepository)


def test_get_article_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_article_repo
    from src.scraper.infrastructure.file_article_repository import FileArticleStore

    assert isinstance(get_article_repo(session=None), FileArticleStore)


def test_get_article_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_article_repo
    from src.scraper.infrastructure.article_repository import ArticleRepository

    assert isinstance(get_article_repo(session=None), ArticleRepository)


def test_get_fetch_stats_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_fetch_stats_repo
    from src.scraper.infrastructure.file_fetch_stats_repository import FileFetchStatsStore

    assert isinstance(get_fetch_stats_repo(session=None), FileFetchStatsStore)


def test_get_fetch_stats_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_fetch_stats_repo
    from src.scraper.infrastructure.fetch_stats_repository import FetchStatsRepository

    assert isinstance(get_fetch_stats_repo(session=None), FetchStatsRepository)


def test_get_scheduler_log_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_scheduler_log_repo
    from src.scraper.infrastructure.file_scheduler_log_repository import FileSchedulerLogStore

    assert isinstance(get_scheduler_log_repo(session=None), FileSchedulerLogStore)


def test_get_scheduler_log_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_scheduler_log_repo
    from src.scraper.infrastructure.scheduler_log_repository import SchedulerExecutionLogRepository

    assert isinstance(get_scheduler_log_repo(session=None), SchedulerExecutionLogRepository)
