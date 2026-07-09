"""M-5 provider:scraper 簇在线工厂按 env flag 切换。"""


def test_get_tweet_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_tweet_repo
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    assert isinstance(get_tweet_repo(session=None), FileTweetStore)


def test_get_article_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_article_repo
    from src.scraper.infrastructure.file_article_repository import FileArticleStore

    assert isinstance(get_article_repo(session=None), FileArticleStore)


def test_get_fetch_stats_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_fetch_stats_repo
    from src.scraper.infrastructure.file_fetch_stats_repository import FileFetchStatsStore

    assert isinstance(get_fetch_stats_repo(session=None), FileFetchStatsStore)
