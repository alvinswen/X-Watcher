"""M-5 provider:schedule 工厂按 env flag 切换。"""


def test_get_schedule_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_schedule_repo
    from src.preference.infrastructure.file_schedule_repository import FileScheduleStore

    repo = get_schedule_repo(session=None)
    assert isinstance(repo, FileScheduleStore)


def test_get_schedule_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_schedule_repo
    from src.preference.infrastructure.schedule_repository import ScraperScheduleRepository

    repo = get_schedule_repo(session=None)   # 构造 ScraperScheduleRepository(None),不触 DB
    assert isinstance(repo, ScraperScheduleRepository)
