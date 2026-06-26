"""M-5 provider:summary/user 工厂按 env flag 切换。"""


def test_get_summary_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_summary_repo
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

    repo = get_summary_repo(session=None)
    assert isinstance(repo, FileSummaryStore)


def test_get_summary_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    from src.data_layer.provider import get_summary_repo
    from src.summarization.infrastructure.repository import SummarizationRepository

    repo = get_summary_repo(session=None)   # 构造 SummarizationRepository(None),不触 DB
    assert isinstance(repo, SummarizationRepository)


def test_get_user_repo_file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_user_repo
    from src.user.infrastructure.file_user_repository import FileUserStore

    repo = get_user_repo(session=None)
    assert isinstance(repo, FileUserStore)


def test_get_user_repo_default_is_sqlalchemy(monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    from src.data_layer.provider import get_user_repo
    from src.user.infrastructure.repository import UserRepository

    repo = get_user_repo(session=None)
    assert isinstance(repo, UserRepository)
