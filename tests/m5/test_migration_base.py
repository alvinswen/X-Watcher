from datetime import datetime, timezone


def test_naive_strips_aware():
    from src.data_layer.migration.base import naive
    aware = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    out = naive(aware)
    assert out.tzinfo is None
    assert out == datetime(2030, 1, 1, 12, 0)


def test_naive_passthrough_naive():
    from src.data_layer.migration.base import naive
    n = datetime(2030, 1, 1, 12, 0)
    assert naive(n) is n


def test_naive_none():
    from src.data_layer.migration.base import naive
    assert naive(None) is None


def test_report_mismatch_marks_fail():
    from src.data_layer.migration.base import MigrationReport
    r = MigrationReport(entity="x", pg_count=2, written=2)
    r.validated = 2
    r.mismatches.append("id=1 field foo: pg=a file=b")
    assert r.ok is False
    r2 = MigrationReport(entity="y", pg_count=1, written=1)
    r2.validated = 1
    assert r2.ok is True
