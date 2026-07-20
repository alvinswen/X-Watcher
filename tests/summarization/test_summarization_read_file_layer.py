"""M-5 summarization read facade file-mode integration tests."""

from datetime import UTC, datetime

import pytest

from src.scraper.domain.models import ReferenceType, Tweet
from src.summarization.domain.models import SummaryRecord


def _tweet(tid, author="alice", created=datetime(2050, 1, 1), text=None, **kw):
    base = {
        "tweet_id": tid,
        "text": text if text is not None else "t" + tid,
        "created_at": created,
        "author_username": author,
    }
    base.update(kw)
    return Tweet(**base)


def _summary(sid, tid):
    return SummaryRecord(
        summary_id=sid,
        tweet_id=tid,
        summary_text="s",
        translation_text=None,
        model_provider="p",
        model_name="m",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0.0,
        cached=False,
        is_generated_summary=True,
        content_hash="h" + sid,
        created_at=datetime(2050, 1, 1),
        updated_at=datetime(2050, 1, 1),
    )


@pytest.mark.asyncio
async def test_unsummarized_file_controlled(monkeypatch, tmp_path):
    """File facade returns unsummarized tweets with filters, DESC order, and limit clamp."""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "filestore"))
    from src.data_layer.provider import get_summarization_read_repo

    tweets = [
        _tweet("1", "alice", created=datetime(2050, 1, 1, tzinfo=UTC), text="a1"),
        _tweet("2", "alice", created=datetime(2050, 5, 1, tzinfo=UTC), text="a2"),
        _tweet(
            "3",
            "alice",
            created=datetime(2050, 3, 1, tzinfo=UTC),
            text="a3",
            reference_type=ReferenceType.quoted,
            referenced_tweet_text="orig",
            referenced_tweet_author_username="orig_a",
            author_display_name="Alice",
        ),
        _tweet("4", "bob", created=datetime(2050, 2, 1, tzinfo=UTC), text="b4"),
    ]
    summaries = [_summary("s2", "2")]

    store = get_summarization_read_repo()
    await store.seed_tweets(tweets)
    await store.seed_summaries(summaries)

    out = await store.get_unsummarized_tweets()
    assert [t["tweet_id"] for t in out] == ["3", "4", "1"]

    by_author = await store.get_unsummarized_tweets(author="alice")
    assert [t["tweet_id"] for t in by_author] == ["3", "1"]

    since = await store.get_unsummarized_tweets(
        since=datetime(2050, 3, 1, tzinfo=UTC)
    )
    assert {t["tweet_id"] for t in since} == {"3"}

    until = await store.get_unsummarized_tweets(
        until=datetime(2050, 3, 1, tzinfo=UTC)
    )
    assert {t["tweet_id"] for t in until} == {"1", "4"}

    limited = await store.get_unsummarized_tweets(limit=1)
    assert [t["tweet_id"] for t in limited] == ["3"]
    assert out[0]["created_at"] == "2050-03-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_origins_six_fields_file_controlled(monkeypatch, tmp_path):
    """File facade returns the six CR-023 origin fields, with missing ids omitted."""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "filestore"))
    from src.data_layer.provider import get_summarization_read_repo

    tweets = [
        _tweet(
            "1",
            "bob",
            text="t1",
            reference_type=ReferenceType.retweeted,
            referenced_tweet_text="orig",
            referenced_tweet_id="999",
            referenced_tweet_author_username="orig_a",
        ),
        _tweet("2", "alice", text="t2"),
    ]

    store = get_summarization_read_repo()
    await store.seed_tweets(tweets)
    origins = await store.get_tweet_origins(["1", "2", "404"])

    assert set(origins) == {"1", "2"}
    assert origins["1"] == {
        "text": "t1",
        "referenced_tweet_text": "orig",
        "reference_type": "retweeted",
        "referenced_tweet_id": "999",
        "author_username": "bob",
        "referenced_tweet_author_username": "orig_a",
    }
    assert origins["2"] == {
        "text": "t2",
        "referenced_tweet_text": None,
        "reference_type": None,
        "referenced_tweet_id": None,
        "author_username": "alice",
        "referenced_tweet_author_username": None,
    }


@pytest.mark.asyncio
async def test_list_unsummarized_ids_file_path(monkeypatch, tmp_path):
    """File path list_unsummarized_ids excludes summarized tweets and respects half-open windows."""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "filestore"))
    from src.data_layer.provider import get_summarization_read_repo

    tweets = [
        _tweet("1", "alice", created=datetime(2050, 1, 1, tzinfo=UTC)),
        _tweet("2", "alice", created=datetime(2050, 5, 1, tzinfo=UTC)),
        _tweet("3", "bob", created=datetime(2050, 3, 1, tzinfo=UTC)),
        _tweet("4", "bob", created=datetime(2050, 2, 1, tzinfo=UTC)),
    ]
    store = get_summarization_read_repo()
    await store.seed_tweets(tweets)
    await store.seed_summaries([_summary("s2", "2")])

    ids = await store.list_unsummarized_ids()
    assert ids == ["1", "3", "4"]

    ids_since = await store.list_unsummarized_ids(
        since=datetime(2050, 3, 1, tzinfo=UTC)
    )
    assert set(ids_since) == {"3"}

    ids_until = await store.list_unsummarized_ids(
        until=datetime(2050, 3, 1, tzinfo=UTC)
    )
    assert set(ids_until) == {"1", "4"}

    assert len(ids) == await store.count_unsummarized()


@pytest.mark.asyncio
async def test_list_tweet_ids_in_window_file_path(monkeypatch, tmp_path):
    """File path list_tweet_ids_in_window is half-open and includes summarized tweets."""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "filestore"))
    from src.data_layer.provider import get_summarization_read_repo

    tweets = [
        _tweet("1", "alice", created=datetime(2050, 1, 1, tzinfo=UTC)),
        _tweet("2", "alice", created=datetime(2050, 3, 1, tzinfo=UTC)),
        _tweet("3", "bob", created=datetime(2050, 5, 1, tzinfo=UTC)),
    ]
    store = get_summarization_read_repo()
    await store.seed_tweets(tweets)
    await store.seed_summaries([_summary("s2", "2")])

    ids = await store.list_tweet_ids_in_window(
        datetime(2050, 3, 1, tzinfo=UTC),
        datetime(2050, 5, 1, tzinfo=UTC),
    )
    assert set(ids) == {"2"}

    ids_all = await store.list_tweet_ids_in_window(
        datetime(2049, 1, 1, tzinfo=UTC),
        datetime(2051, 1, 1, tzinfo=UTC),
    )
    assert set(ids_all) == {"1", "2", "3"}
    assert len(ids_all) == await store.count_tweets_in_window(
        datetime(2049, 1, 1, tzinfo=UTC),
        datetime(2051, 1, 1, tzinfo=UTC),
    )
