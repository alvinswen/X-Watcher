"""M-5 provider:export/import 门面工厂按 env flag 切换 + sync-bridge 适配器。"""


def test_get_export_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_export_repo, _FileExportSyncAdapter

    repo = get_export_repo(session=None)
    assert isinstance(repo, _FileExportSyncAdapter)


def test_get_export_repo_default_is_sqlalchemy_dict_adapter(monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    from src.data_layer.provider import get_export_repo, _SqlalchemyExportDictAdapter

    repo = get_export_repo(session=None)  # 套 ExportRepository(None),不触 DB
    assert isinstance(repo, _SqlalchemyExportDictAdapter)


def test_file_export_adapter_returns_dicts(monkeypatch, tmp_path):
    """file 适配器 get_* 返 dict(空 data_root→空 list)。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_export_repo

    repo = get_export_repo(session=None)
    assert repo.get_follows() == []
    assert repo.get_tweets(since=None, until=None, authors=None) == []
    assert repo.get_summaries(tweet_ids=None) == []
    assert repo.get_articles(tweet_ids=None) == []


def test_get_import_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_import_repo, _FileImportSyncAdapter

    repo = get_import_repo(session=None, dry_run=False)
    assert isinstance(repo, _FileImportSyncAdapter)


def test_get_import_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    from src.data_layer.provider import get_import_repo
    from src.sync.infrastructure.import_repository import ImportRepository

    repo = get_import_repo(session=None, dry_run=False)  # ImportRepository(None),不触 DB
    assert isinstance(repo, ImportRepository)


def test_file_import_adapter_real_write_persists(monkeypatch, tmp_path):
    """非 dry_run:import_follows 真写 data_root,follows.json 落地。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_import_repo
    from src.sync.domain.models import ConflictStrategy

    repo = get_import_repo(session=None, dry_run=False)
    item = {"username": "alice", "is_active": True, "added_by": "t", "reason": "r"}
    stats = repo.import_follows([item], ConflictStrategy.skip)
    assert stats.inserted == 1
    repo.close()
    assert (tmp_path / "follows" / "follows.json").exists()


def test_file_import_adapter_dry_run_does_not_persist(monkeypatch, tmp_path):
    """dry_run:import_follows 在 temp 副本上跑,真 data_root 未落地。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_import_repo
    from src.sync.domain.models import ConflictStrategy

    repo = get_import_repo(session=None, dry_run=True)
    item = {"username": "bob", "is_active": True, "added_by": "t", "reason": "r"}
    stats = repo.import_follows([item], ConflictStrategy.skip)
    assert stats.inserted == 1  # 真实 stats
    repo.close()
    assert not (tmp_path / "follows" / "follows.json").exists()  # 真 data_root 未落地
