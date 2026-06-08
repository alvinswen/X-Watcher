from datetime import datetime, timezone


class _FakeFetchStatsOrm:
    username = "bob"
    last_fetch_at = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    last_fetched_count = 50
    last_new_count = 10
    total_fetches = 7
    avg_new_rate = 0.2
    consecutive_empty_fetches = 0
    created_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    updated_at = datetime(2030, 1, 2, tzinfo=timezone.utc)


def test_fetch_stats_to_domain_naive():
    from src.data_layer.migration.fetch_stats import _to_domain
    d = _to_domain(_FakeFetchStatsOrm())
    assert d.username == "bob"
    assert d.last_fetch_at == datetime(2030, 1, 1, 12, 0)   # aware→naive
    assert d.total_fetches == 7 and d.avg_new_rate == 0.2
