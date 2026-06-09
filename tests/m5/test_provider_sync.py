"""M-5 provider:export/import 门面工厂按 env flag 切换 + sync-bridge 适配器。"""


def test_get_export_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_export_repo, _FileExportSyncAdapter

    repo = get_export_repo(session=None)
    assert isinstance(repo, _FileExportSyncAdapter)


def test_get_export_repo_default_is_sqlalchemy_dict_adapter(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_export_repo, _SqlalchemyExportDictAdapter

    repo = get_export_repo(session=None)   # 套 ExportRepository(None),不触 DB
    assert isinstance(repo, _SqlalchemyExportDictAdapter)


def test_file_export_adapter_returns_dicts(monkeypatch, tmp_path):
    """file 适配器 get_* 返 dict(空 data_root→空 list / schedule None)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_export_repo

    repo = get_export_repo(session=None)
    assert repo.get_follows() == []
    assert repo.get_schedule_config() is None
    assert repo.get_tweets(since=None, until=None, authors=None) == []
    assert repo.get_summaries(tweet_ids=None) == []
    assert repo.get_articles(tweet_ids=None) == []
    assert repo.get_topics() == []
