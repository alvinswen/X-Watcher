"""M-5 provider:summary/user 工厂返回文件层实现。"""


def test_get_summary_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_summary_repo
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

    repo = get_summary_repo()
    assert isinstance(repo, FileSummaryStore)


def test_get_user_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_user_repo
    from src.user.infrastructure.file_user_repository import FileUserStore

    repo = get_user_repo()
    assert isinstance(repo, FileUserStore)
