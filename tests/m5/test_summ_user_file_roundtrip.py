"""M-5 4a 文件层 round-trip:经 provider 写→读一致(summary / user 重表达)。"""

from datetime import datetime, timezone, UTC


async def test_user_create_then_password_hash_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_user_repo

    repo = get_user_repo()
    created = await repo.create_user("Alice", "alice@example.com", "hash_alice")
    assert created.email == "alice@example.com" and created.is_admin is False

    # 重表达公共契约:file 模式读回 hash 一致
    by_email = await repo.get_password_hash_by_email("alice@example.com")
    by_id = await repo.get_password_hash_by_id(created.id)
    assert by_email == "hash_alice" and by_id == "hash_alice"
    assert await repo.get_password_hash_by_email("nobody@example.com") is None

    # 域字段可读(auth_router 双调用路径所需)
    got = await repo.get_user_by_email("alice@example.com")
    assert got is not None and got.id == created.id and got.is_admin is False
    assert (tmp_path / "users" / "users.json").exists()


async def test_summary_save_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_summary_repo
    from src.summarization.domain.models import SummaryRecord

    repo = get_summary_repo()
    now = datetime.now(UTC).replace(tzinfo=None)
    rec = SummaryRecord(
        summary_id="s-roundtrip-1",
        tweet_id="t-1",
        summary_text="测试摘要",
        translation_text=None,
        model_provider="minimax",
        model_name="abab",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_usd=0.5,
        cached=False,
        is_generated_summary=True,
        content_hash="h-1",
        created_at=now,
        updated_at=now,
    )
    await repo.save_summary_record(rec)

    got = await repo.get_summary_by_tweet("t-1")
    assert got is not None and got.summary_id == rec.summary_id
    assert got.tweet_id == "t-1" and got.content_hash == "h-1"
    assert (tmp_path / "summaries" / "summaries.json").exists()
