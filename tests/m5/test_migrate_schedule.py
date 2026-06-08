from datetime import datetime, timezone


class _FakeOrm:
    id = 1
    interval_seconds = 300
    next_run_time = datetime(2030, 1, 1, tzinfo=timezone.utc)
    is_enabled = True
    updated_at = datetime(2030, 1, 2, tzinfo=timezone.utc)
    updated_by = "mig"


def test_schedule_to_domain_naive():
    from src.data_layer.migration.schedule import _to_domain
    d = _to_domain(_FakeOrm())
    assert d.next_run_time == datetime(2030, 1, 1)      # aware→naive
    assert d.updated_at == datetime(2030, 1, 2)
    assert d.id == 1 and d.interval_seconds == 300
