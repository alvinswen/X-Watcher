from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.storage import paths
from src.subjects.models import SubjectReview, SubjectReviewSection, SubjectReviewTrend
from src.subjects.store import FileSubjectStore

T0 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
IDS = ["9200000000000000001", "9200000000000000404"]


async def _store_with_subject(root: Path) -> tuple[FileSubjectStore, str]:
    store = FileSubjectStore(root)
    subject = await store.create_subject(
        name="历史综述测试议题",
        nl_description="CHG-050 fixture",
        keywords=["fixture"],
    )
    return store, subject.subject_id


def _review(
    subject_id: str,
    version: int,
    *,
    generated_by: str = "skill",
    sections: list[SubjectReviewSection] | None = None,
    trend: SubjectReviewTrend | None = None,
) -> SubjectReview:
    generated_at = T0 + timedelta(hours=version)
    return SubjectReview(
        subject_id=subject_id,
        version=version,
        sections=sections
        or [
            SubjectReviewSection(
                title=f"论点 v{version}",
                body=f"正文 v{version}",
                cited_tweet_ids=[],
            )
        ],
        trend=trend or SubjectReviewTrend(),
        cited_tweet_ids=[],
        prev_version=version - 1 if version > 1 else None,
        generated_at=generated_at,
        generated_by=generated_by,
        updated_at=generated_at,
        covered_until=generated_at,
    )


@pytest.mark.asyncio
async def test_review_history_list_returns_versions_desc_with_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store, subject_id = await _store_with_subject(tmp_path)
    reviews = [
        _review(subject_id, 1, generated_by="skill"),
        _review(subject_id, 2, generated_by="fallback"),
        _review(subject_id, 3, generated_by="llm"),
    ]
    for review in reviews:
        await store.save_review(review)

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["subject_id"] == subject_id
    assert payload["current_version"] == 3
    assert [item["version"] for item in payload["items"]] == [3, 2, 1]
    by_version = {review.version: review for review in reviews}
    for item in payload["items"]:
        stored = by_version[item["version"]]
        assert set(item) == {"version", "generated_at", "generated_by"}
        assert (
            datetime.fromisoformat(item["generated_at"].replace("Z", "+00:00"))
            == stored.generated_at
        )
        assert item["generated_by"] == stored.generated_by


@pytest.mark.asyncio
async def test_review_history_list_missing_subject_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    response = await async_client.get("/api/admin/subjects/sub_missing/review/history")

    assert response.status_code == 404
    assert response.json()["detail"] == "议题不存在"


@pytest.mark.asyncio
async def test_review_history_list_empty_when_never_generated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    _, subject_id = await _store_with_subject(tmp_path)

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review/history")

    assert response.status_code == 200
    assert response.json() == {
        "subject_id": subject_id,
        "current_version": 0,
        "items": [],
    }


@pytest.mark.asyncio
async def test_review_history_list_skips_corrupt_and_foreign_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store, subject_id = await _store_with_subject(tmp_path)
    for version in range(1, 5):
        await store.save_review(_review(subject_id, version))
    history_dir = paths.subject_review_history_doc(tmp_path, subject_id, 1).parent
    paths.subject_review_history_doc(tmp_path, subject_id, 2).write_text(
        "{broken", encoding="utf-8"
    )
    (history_dir / "foo.json").write_text("{broken too", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="src.subjects.store"):
        response = await async_client.get(f"/api/admin/subjects/{subject_id}/review/history")

    assert response.status_code == 200
    assert [item["version"] for item in response.json()["items"]] == [4, 3, 1]
    assert "2.json" in caplog.text
    assert "foo.json" not in caplog.text


@pytest.mark.asyncio
async def test_review_history_list_orders_numerically_double_digits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store, subject_id = await _store_with_subject(tmp_path)
    for version in (9, 10, 11):
        await store.save_review(_review(subject_id, version))

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review/history")

    assert response.status_code == 200
    assert [item["version"] for item in response.json()["items"]] == [11, 10, 9]


@pytest.mark.asyncio
async def test_review_version_returns_frozen_snapshot_with_cards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store, subject_id = await _store_with_subject(tmp_path)
    frozen_sections = [
        SubjectReviewSection(
            title="冻结论点",
            body="冻结正文",
            cited_tweet_ids=IDS,
        )
    ]
    frozen_trend = SubjectReviewTrend(emerging=["新增"], fading=["淡出"])
    frozen = _review(
        subject_id,
        1,
        generated_by="fallback",
        sections=frozen_sections,
        trend=frozen_trend,
    )
    await store.save_review(frozen)
    await store.save_review(_review(subject_id, 2, generated_by="llm"))
    await FileTweetStore(tmp_path).save_tweets(
        [
            Tweet(
                tweet_id=IDS[0],
                text="读取时的推文现在态",
                created_at=T0 + timedelta(days=1),
                author_username="current_author",
            )
        ]
    )

    response = await async_client.get(
        f"/api/admin/subjects/{subject_id}/review/history/{frozen.version}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == frozen.version
    assert payload["sections"] == [section.model_dump(mode="json") for section in frozen.sections]
    assert payload["trend"] == frozen.trend.model_dump(mode="json")
    assert payload["prev_version"] == frozen.prev_version
    assert (
        datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00"))
        == frozen.generated_at
    )
    assert payload["generated_by"] == frozen.generated_by
    assert payload["cited_tweets"][0]["text"] == "读取时的推文现在态"
    assert [card["tweet_id"] for card in payload["cited_tweets"]] == [IDS[0]]
    assert payload["missing_tweet_ids"] == [IDS[1]]


@pytest.mark.asyncio
async def test_review_version_missing_version_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store, subject_id = await _store_with_subject(tmp_path)
    await store.save_review(_review(subject_id, 1))

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review/history/5")

    assert response.status_code == 404
    assert response.json()["detail"] == "综述版本不存在"


@pytest.mark.asyncio
async def test_review_version_missing_subject_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    response = await async_client.get("/api/admin/subjects/sub_missing/review/history/1")

    assert response.status_code == 404
    assert response.json()["detail"] == "议题不存在"


@pytest.mark.asyncio
async def test_review_version_corrupt_file_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    async_client: AsyncClient,
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store, subject_id = await _store_with_subject(tmp_path)
    await store.save_review(_review(subject_id, 1))
    paths.subject_review_history_doc(tmp_path, subject_id, 1).write_text(
        "{broken", encoding="utf-8"
    )

    response = await async_client.get(f"/api/admin/subjects/{subject_id}/review/history/1")

    assert response.status_code == 404
    assert response.json()["detail"] == "综述版本不存在"


@pytest.mark.asyncio
async def test_get_review_version_store_rejects_version_below_one(tmp_path: Path) -> None:
    store, subject_id = await _store_with_subject(tmp_path)

    assert await store.get_review_version(subject_id, 0) is None
    assert await store.get_review_version(subject_id, -1) is None
