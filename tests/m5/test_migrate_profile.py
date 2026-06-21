from datetime import datetime, timezone


class _FakeProfileOrm:
    platform_user_id = "123"
    username = "alice"
    display_name = "Alice"
    is_blue_verified = True
    verified_type = "blue"
    profile_picture = "http://x/p.jpg"
    cover_picture = None
    description = "hi"
    location = "SF"
    followers_count = 10
    following_count = 5
    statuses_count = 100
    favourites_count = 20
    media_count = 3
    account_created_at = "2020-01-01"
    is_automated = False
    possibly_sensitive = False
    pinned_tweet_ids = ["9"]
    unavailable = False
    unavailable_reason = None
    fetched_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    # ORM-only(dropped):
    raw_json = '{"x":1}'
    created_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    updated_at = datetime(2030, 1, 2, tzinfo=timezone.utc)


def test_profile_to_domain_fields_and_naive():
    from src.data_layer.migration.profile import _to_domain
    d = _to_domain(_FakeProfileOrm())
    assert d.platform_user_id == "123" and d.username == "alice"
    assert d.fetched_at == datetime(2030, 1, 1)       # aware→naive
    assert d.pinned_tweet_ids == ["9"]
    assert not hasattr(d, "raw_json")                  # dropped, 域无此字段
