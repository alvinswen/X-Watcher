"""M-5 provider:follows/profile 工厂返回文件层实现。"""


def test_get_follows_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_follows_repo
    from src.preference.infrastructure.file_follow_repository import FileFollowStore

    repo = get_follows_repo()
    assert isinstance(repo, FileFollowStore)


def test_get_profile_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_profile_repo
    from src.preference.infrastructure.file_profile_repository import FileProfileStore

    repo = get_profile_repo()
    assert isinstance(repo, FileProfileStore)
