"""M-5 5 文件层 round-trip:export 读 + import 写 + dry_run temp-copy 不动真数据。"""

import json

from src.sync.domain.models import ConflictStrategy


def test_export_then_import_follow_roundtrip(monkeypatch, tmp_path):
    """export 出 follows dict → import 回另一 data_root → 计数一致 + 落盘。"""
    src_root = tmp_path / "src"
    dst_root = tmp_path / "dst"
    src_root.mkdir()
    dst_root.mkdir()

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(src_root))
    import asyncio

    from src.data_layer.provider import get_export_repo, get_follows_repo, get_import_repo

    asyncio.run(get_follows_repo().create_scraper_follow(username="alice", reason="m5", added_by="t"))

    exported = get_export_repo().get_follows()
    assert len(exported) == 1 and exported[0]["username"] == "alice"

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(dst_root))
    repo = get_import_repo(dry_run=False)
    stats = repo.import_follows(exported, ConflictStrategy.skip)
    repo.close()
    assert stats.inserted == 1
    assert (dst_root / "follows" / "follows.json").exists()


def test_dry_run_does_not_touch_real_data(monkeypatch, tmp_path):
    """dry_run import 后真 data_root 字节不变。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    import asyncio

    from src.data_layer.provider import get_follows_repo, get_import_repo

    asyncio.run(get_follows_repo().create_scraper_follow(username="existing", reason="r", added_by="t"))
    follows_file = tmp_path / "follows" / "follows.json"
    before = follows_file.read_bytes()

    repo = get_import_repo(dry_run=True)
    stats = repo.import_follows(
        [{"username": "ghost", "is_active": True, "added_by": "t", "reason": "r"}],
        ConflictStrategy.skip,
    )
    repo.close()
    assert stats.inserted == 1
    assert follows_file.read_bytes() == before
    after = json.loads(follows_file.read_text())
    assert all(f["username"] != "ghost" for f in after["follows"].values())
