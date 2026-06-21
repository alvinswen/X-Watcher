from datetime import datetime


class _FakeTopicOrm:
    id = 1
    name = "AI"
    description = "desc"
    user_id = None
    created_at = datetime(2030, 1, 1)
    updated_at = datetime(2030, 1, 2)


class _FakeAccountOrm:
    id = 7
    topic_id = 1
    username = "elonmusk"
    added_at = datetime(2030, 1, 3)


class _FakeTaskOrm:
    id = 11
    topic_id = 1
    time_span_hours = 24
    deadline = datetime(2030, 2, 1)
    custom_prompt = None
    tz_offset = 0
    status = "completed"
    error_message = None
    created_at = datetime(2030, 1, 4)
    started_at = None
    completed_at = datetime(2030, 1, 5)


class _FakeSummaryOrm:
    id = 21
    task_id = 11
    content = "summary body"
    llm_provider = "openai"
    llm_model = "gpt-x"
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15
    cost_usd = 0.02
    tweet_count = 3
    account_count = 1
    created_at = datetime(2030, 1, 5)
    metadata_json = {"k": "v"}


def test_topic_mappers():
    from src.data_layer.migration.topic import (
        _account_to_domain, _summary_to_domain, _task_to_domain, _topic_to_domain,
    )
    t = _topic_to_domain(_FakeTopicOrm())
    assert t.id == 1 and t.name == "AI" and t.created_at == datetime(2030, 1, 1)
    a = _account_to_domain(_FakeAccountOrm())
    assert a.id == 7 and a.topic_id == 1 and a.username == "elonmusk"
    tk = _task_to_domain(_FakeTaskOrm(), "AI")
    assert tk.id == 11 and tk.topic_name == "AI"          # 派生 name 注入
    assert tk.status.value == "completed"                  # str→enum coerce
    assert tk.summary is None
    s = _summary_to_domain(_FakeSummaryOrm())
    assert s.id == 21 and s.task_id == 11 and s.metadata_json == {"k": "v"}


def test_task_to_rec_drops_derived():
    from src.data_layer.migration.topic import _task_to_domain
    from src.topic.infrastructure.file_topic_summary_task_repository import _task_to_rec
    tk = _task_to_domain(_FakeTaskOrm(), "AI")
    rec = _task_to_rec(tk)
    assert "topic_name" not in rec and "summary" not in rec   # 派生不落盘
    assert rec["tz_offset"] == 0
