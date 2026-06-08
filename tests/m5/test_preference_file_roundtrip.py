"""M-5 preference 文件层 round-trip:经 provider 写→读一致 + 盘面落地。

同时验证:se file store 在旧应用解释器内用旧应用域模型构造成功(域字段兼容)。
"""


async def test_follows_create_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_follows_repo

    repo = get_follows_repo(session=None)
    created = await repo.create_scraper_follow(username="alice", reason="m5", added_by="tester")
    assert created.username == "alice" and created.is_active is True

    got = await repo.get_follow_by_username("alice")
    assert got is not None and got.username == "alice"

    active = await repo.get_active_follows()
    assert any(f.username == "alice" for f in active)
    assert (tmp_path / "follows" / "follows.json").exists()


async def test_profile_upsert_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_profile_repo
    from src.preference.domain.models import XUserProfile

    repo = get_profile_repo(session=None)
    prof = XUserProfile(platform_user_id="U123", username="bob")
    count = await repo.upsert_profiles([prof])
    assert count == 1

    got = await repo.get_profile_by_user_id("U123")
    assert got is not None and got.username == "bob"
    assert (tmp_path / "profiles" / "profiles.json").exists()
