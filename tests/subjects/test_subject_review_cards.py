from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

from src.scraper.domain.models import Media, Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.subjects.models import SubjectMatch, SubjectReviewSection
from src.subjects.services.review_service import SubjectReviewService
from src.subjects.store import FileSubjectStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

T0 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
IDS = ["9100000000000000001", "9100000000000000002", "9100000000000000404"]
CARD_KEYS = {
    "tweet_id",
    "text",
    "created_at",
    "author_username",
    "author_display_name",
    "summary_text",
    "translation_text",
    "media",
    "reference_type",
    "referenced_tweet_id",
    "referenced_tweet_text",
    "referenced_tweet_author_username",
    "referenced_tweet_media",
}
LEGACY_KEYS = {
    "tweet_id",
    "text",
    "summary",
    "translation",
    "author",
    "author_username",
    "created_at",
    "reference_type",
    "referenced_tweet_id",
}


async def _seed(
    root: Path,
    *,
    sections: list[SubjectReviewSection] | None = None,
    write_review: bool = True,
) -> tuple[FileSubjectStore, str]:
    store = FileSubjectStore(root)
    subject = await store.create_subject(
        name="引用卡测试议题", nl_description="CHG-049 fixture", keywords=["fixture"]
    )
    tweets = [
        Tweet(
            tweet_id=IDS[0],
            text="anchor tweet one",
            created_at=T0,
            author_username="anchor_author",
            author_display_name="Anchor Author",
            media=[Media(media_key="mk1", type="photo", url="https://x.test/1.jpg")],
        ),
        Tweet(
            tweet_id=IDS[1],
            text="anchor tweet two (quoted)",
            created_at=T0,
            author_username="quoter",
            referenced_tweet_id="9100000000000000009",
            referenced_tweet_text="original text",
            referenced_tweet_author_username="orig_author",
        ),
    ]
    await FileTweetStore(root).save_tweets(tweets)
    await FileSummaryStore(root).seed(
        [
            SummaryRecord(
                summary_id="00000000-0000-0000-0000-000000000001",
                tweet_id=IDS[0],
                summary_text="s1",
                translation_text="t1",
                model_provider="test",
                model_name="test",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                cost_usd=0.0,
                created_at=T0,
                updated_at=T0,
                content_hash="anchorhash",
            )
        ]
    )
    await store.upsert_matches(
        [SubjectMatch(subject_id=subject.subject_id, tweet_id=tweet_id, matched_at=T0) for tweet_id in IDS]
    )
    if write_review:
        await SubjectReviewService(store).write_review(
            subject_id=subject.subject_id,
            prev_version=0,
            sections=sections
            or [SubjectReviewSection(title="论点一", body="正文一", cited_tweet_ids=IDS)],
            covered_until=T0,
        )
    return store, subject.subject_id


@pytest.mark.asyncio
async def test_get_tweet_cards_by_ids_card_has_exactly_13_keys(tmp_path: Path) -> None:
    store, _ = await _seed(tmp_path)

    cards, _ = await store.get_tweet_cards_by_ids([IDS[0]])

    assert set(cards[0]) == CARD_KEYS


@pytest.mark.asyncio
async def test_get_tweet_cards_by_ids_renames_summary_and_translation(tmp_path: Path) -> None:
    store, _ = await _seed(tmp_path)

    cards, _ = await store.get_tweet_cards_by_ids(IDS[:2])

    assert (cards[0]["summary_text"], cards[0]["translation_text"]) == ("s1", "t1")
    assert (cards[1]["summary_text"], cards[1]["translation_text"]) == (None, None)
    assert not {"summary", "translation", "author"}.intersection(cards[0])


@pytest.mark.asyncio
async def test_get_tweet_cards_by_ids_referenced_fields_passthrough(tmp_path: Path) -> None:
    store, _ = await _seed(tmp_path)

    cards, _ = await store.get_tweet_cards_by_ids([IDS[1]])

    assert cards[0]["referenced_tweet_id"] == "9100000000000000009"
    assert cards[0]["referenced_tweet_text"] == "original text"
    assert cards[0]["referenced_tweet_author_username"] == "orig_author"


@pytest.mark.asyncio
async def test_get_tweet_cards_by_ids_media_serialized_as_dicts(tmp_path: Path) -> None:
    store, _ = await _seed(tmp_path)

    cards, _ = await store.get_tweet_cards_by_ids([IDS[0]])

    media = cards[0]["media"]
    assert isinstance(media, list)
    assert isinstance(media[0], dict)
    assert {"media_key", "type", "url"}.issubset(media[0])


@pytest.mark.asyncio
async def test_get_tweet_cards_by_ids_missing_and_dedup_order(tmp_path: Path) -> None:
    store, _ = await _seed(tmp_path)

    cards, missing = await store.get_tweet_cards_by_ids(
        [IDS[1], "", IDS[0], IDS[1], IDS[2], IDS[2]]
    )

    assert [card["tweet_id"] for card in cards] == [IDS[1], IDS[0]]
    assert missing == [IDS[2]]


@pytest.mark.asyncio
async def test_get_tweets_by_ids_wire_face_frozen_9_keys(tmp_path: Path) -> None:
    store, _ = await _seed(tmp_path)

    items, _ = await store.get_tweets_by_ids([IDS[0]])

    assert set(items[0]) == LEGACY_KEYS


@pytest.mark.asyncio
async def test_review_payload_service_face_has_no_card_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, async_client: AsyncClient
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store, subject_id = await _seed(tmp_path)

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review")
    payload = await SubjectReviewService(store).get_review_payload(subject_id)

    assert response.status_code == 200
    assert payload is not None
    assert "cited_tweets" not in payload
    assert "missing_tweet_ids" not in payload


@pytest.mark.asyncio
async def test_rest_review_returns_cards_and_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, async_client: AsyncClient
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    _, subject_id = await _seed(tmp_path)

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review")

    assert response.status_code == 200
    payload = response.json()
    assert [card["tweet_id"] for card in payload["cited_tweets"]] == IDS[:2]
    assert payload["missing_tweet_ids"] == [IDS[2]]
    assert payload["cited_tweets"][0]["summary_text"] == "s1"


@pytest.mark.asyncio
async def test_rest_review_v0_empty_shell_has_empty_card_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, async_client: AsyncClient
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    _, subject_id = await _seed(tmp_path, write_review=False)

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 0
    assert payload["cited_tweets"] == []
    assert payload["missing_tweet_ids"] == []


@pytest.mark.asyncio
async def test_rest_review_dedups_ids_across_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, async_client: AsyncClient
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    sections = [
        SubjectReviewSection(title="论点一", body="正文一", cited_tweet_ids=[IDS[0]]),
        SubjectReviewSection(title="论点二", body="正文二", cited_tweet_ids=[IDS[0]]),
    ]
    _, subject_id = await _seed(tmp_path, sections=sections)

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review")

    assert response.status_code == 200
    assert [card["tweet_id"] for card in response.json()["cited_tweets"]] == [IDS[0]]
