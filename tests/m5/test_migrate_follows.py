from datetime import datetime


class _FakeFollowOrm:
    def __init__(self, i):
        self.id = i
        self.username = f"u{i}"
        self.platform_user_id = f"p{i}"
        self.reason = "r"
        self.added_by = "me"
        self.added_at = datetime(2030, 1, i)
        self.is_active = True
        self.manual_limit = None
        self.brief_intro = None
        self.backfill_status = "pending"
        self.backfill_completed_at = None


def test_follows_to_domain_fields():
    from src.data_layer.migration.follows import _to_domain
    d = _to_domain(_FakeFollowOrm(1))
    assert d.id == 1 and d.username == "u1" and d.added_at == datetime(2030, 1, 1)
    assert d.backfill_status == "pending"
    assert d.platform_user_id == "p1"
