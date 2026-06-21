from datetime import datetime, timezone


class _FakeUser:
    def __init__(self, i, is_admin=False):
        self.id = i
        self.name = f"user{i}"
        self.email = f"u{i}@x.com"
        self.password_hash = f"ph{i}"
        self.is_admin = is_admin
        self.created_at = datetime(2030, 1, i, tzinfo=timezone.utc)


class _FakeKey:
    def __init__(self, i, user_id, active=True):
        self.id = i
        self.user_id = user_id
        self.key_hash = f"kh{i}"
        self.key_prefix = f"pre{i}"
        self.name = "default"
        self.is_active = active
        self.created_at = datetime(2030, 2, i, tzinfo=timezone.utc)
        self.last_used_at = None


def test_iso_naive():
    from src.data_layer.migration.user import _iso
    assert _iso(datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)) == "2030-01-01T12:00:00"
    assert _iso(None) is None


def test_build_doc_structure_includes_hashes():
    from src.data_layer.migration.user import _build_doc
    users = [_FakeUser(1, is_admin=True), _FakeUser(2)]
    keys = [_FakeKey(1, 1), _FakeKey(2, 2, active=False)]
    doc = _build_doc(users, keys)
    # users
    assert doc["users"]["1"]["password_hash"] == "ph1"      # hash 存盘
    assert doc["users"]["1"]["is_admin"] is True
    assert doc["users"]["1"]["created_at"] == "2030-01-01T00:00:00"  # aware→naive str
    # api_keys
    assert doc["api_keys"]["1"]["key_hash"] == "kh1"        # hash 存盘
    assert doc["api_keys"]["1"]["last_used_at"] is None
    # _seq = max id
    assert doc["_seq"] == {"users": 2, "api_keys": 2}
