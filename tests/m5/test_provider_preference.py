"""M-5 provider:follows/profile 工厂按 env flag 切换。"""


def test_get_follows_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_follows_repo
    from src.preference.infrastructure.file_follow_repository import FileFollowStore

    repo = get_follows_repo(session=None)
    assert isinstance(repo, FileFollowStore)


def test_get_follows_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_follows_repo
    from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository

    repo = get_follows_repo(session=None)   # 构造 ScraperConfigRepository(None),不触 DB
    assert isinstance(repo, ScraperConfigRepository)


def test_get_profile_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_profile_repo
    from src.preference.infrastructure.file_profile_repository import FileProfileStore

    repo = get_profile_repo(session=None)
    assert isinstance(repo, FileProfileStore)


def test_get_profile_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer.provider import get_profile_repo
    from src.preference.infrastructure.x_user_profile_repository import XUserProfileRepository

    repo = get_profile_repo(session=None)
    assert isinstance(repo, XUserProfileRepository)
