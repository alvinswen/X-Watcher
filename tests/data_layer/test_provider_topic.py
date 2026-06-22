"""provider get_topic_store / get_topic_summary_task_store:按 env flag 切换。"""
from src.data_layer import provider


def test_sqlalchemy_mode_returns_adapter(monkeypatch):
    monkeypatch.delenv("XWATCHER_DATA_LAYER", raising=False)
    from src.data_layer._topic_sqlalchemy import SqlalchemyTopicStore, SqlalchemyTopicSummaryTaskStore
    assert isinstance(provider.get_topic_store(session=None), SqlalchemyTopicStore)
    assert isinstance(provider.get_topic_summary_task_store(session=None), SqlalchemyTopicSummaryTaskStore)


def test_file_mode_returns_file_store(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.topic.infrastructure.file_topic_repository import FileTopicStore
    from src.topic.infrastructure.file_topic_summary_task_repository import FileTopicSummaryTaskStore
    assert isinstance(provider.get_topic_store(), FileTopicStore)
    assert isinstance(provider.get_topic_summary_task_store(), FileTopicSummaryTaskStore)
