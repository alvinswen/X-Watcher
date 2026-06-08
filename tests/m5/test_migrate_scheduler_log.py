from datetime import datetime, timezone


class _FakeLogOrm:
    id = 42
    job_id = "scrape"
    event_type = "executed"
    executed_at = datetime(2030, 1, 1, 8, 0, tzinfo=timezone.utc)
    duration_seconds = 1.5
    error_type = None
    error_message = None
    next_run_time = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)


def test_scheduler_log_to_domain_naive_and_enum():
    from src.data_layer.migration.scheduler_log import _to_domain
    d = _to_domain(_FakeLogOrm())
    assert d.job_id == "scrape"
    assert d.event_type.value == "executed"            # str→enum coerce
    assert d.executed_at == datetime(2030, 1, 1, 8, 0)  # aware→naive
    assert d.next_run_time == datetime(2030, 1, 1, 9, 0)


def test_content_key_excludes_id():
    from src.data_layer.migration.scheduler_log import _content_key, _to_domain
    a = _to_domain(_FakeLogOrm())
    b = _to_domain(_FakeLogOrm())
    b.id = 999  # id 不同
    assert _content_key(a) == _content_key(b)          # content_key 忽略 id
