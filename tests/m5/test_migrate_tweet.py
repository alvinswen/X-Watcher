import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _make_orm(tweet_id, author, created_at):
    from src.scraper.infrastructure.models import TweetOrm
    o = TweetOrm()
    o.tweet_id = tweet_id
    o.text = f"text-{tweet_id}"
    o.created_at = created_at
    o.author_username = author
    o.author_display_name = author.title()
    o.author_user_id = f"uid-{author}"
    o.referenced_tweet_id = None
    o.reference_type = None
    o.media = None
    o.referenced_tweet_text = None
    o.referenced_tweet_media = None
    o.referenced_tweet_author_username = None
    return o


def test_tweet_to_domain_naive():
    from src.data_layer.migration.tweet import _to_domain
    o = _make_orm("1", "alice", datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc))
    d = _to_domain(o)
    assert d.tweet_id == "1" and d.author_username == "alice"
    assert d.created_at == datetime(2024, 1, 15, 10, 0)   # aware→naive
    assert d.media is None


def test_tweet_seed_and_validate_shards_and_views():
    from src.data_layer.migration.tweet import _seed_and_validate, _to_domain
    orms = [
        _make_orm("1", "alice", datetime(2024, 1, 15, tzinfo=timezone.utc)),
        _make_orm("2", "alice", datetime(2024, 2, 3, tzinfo=timezone.utc)),   # 跨月
        _make_orm("3", "bob", datetime(2024, 1, 20, tzinfo=timezone.utc)),    # 异作者
    ]
    domains = [_to_domain(o) for o in orms]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rep = asyncio.run(_seed_and_validate(domains, len(orms), root))
        assert rep.ok, rep.mismatches
        assert rep.pg_count == rep.written == rep.validated == 3
        # 分片路径:alice 两个月分片 + bob 一个
        assert (root / "tweets" / "alice" / "2024-01.jsonl").exists()
        assert (root / "tweets" / "alice" / "2024-02.jsonl").exists()
        assert (root / "tweets" / "bob" / "2024-01.jsonl").exists()
        # by-day 视图生成
        assert (root / "_views" / "by-day").exists()
        assert rep.dropped_columns == ["db_created_at", "db_updated_at"]
