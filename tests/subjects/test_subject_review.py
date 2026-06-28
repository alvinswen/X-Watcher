from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from returns.result import Failure, Success

from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.storage import paths
from src.subjects.models import (
    SubjectDigest,
    SubjectHighlight,
    SubjectReview,
    SubjectReviewSection,
    SubjectReviewTrend,
)
from src.subjects.services.review_service import SubjectReviewService
from src.subjects.store import FileSubjectStore
from src.summarization.domain.models import LLMResponse


class _StaticProvider:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.prompts: list[str] = []

    async def complete(self, prompt: str, max_tokens: int):
        self.prompts.append(prompt)
        if self.error is not None:
            return Failure(self.error)
        return Success(
            LLMResponse(
                content=self.content or "{}",
                model="fake-review-model",
                provider="fake",
                prompt_tokens=1,
                completion_tokens=2,
                total_tokens=3,
                cost_usd=0,
            )
        )


def _tweet(tweet_id: str, created_at: datetime, text: str = "tweet text") -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        text=text,
        created_at=created_at,
        author_username="author",
    )


async def _create_subject(repo: FileSubjectStore):
    return await repo.create_subject(
        name="Review 议题",
        nl_description="用于验证 SubjectReview 活综述",
    )


async def _save_digest(
    repo: FileSubjectStore,
    *,
    subject_id: str,
    hour: str,
    generated_at: datetime,
    text: str,
    cited_ids: list[str],
) -> SubjectDigest:
    digest = SubjectDigest(
        subject_id=subject_id,
        hour=hour,
        tweet_count=len(cited_ids),
        digest_text=text,
        highlights=[
            SubjectHighlight(point=text, cited_tweet_ids=cited_ids),
        ],
        cited_tweet_ids=cited_ids,
        generated_at=generated_at,
        generated_by="llm",
    )
    return await repo.save_digest(digest)


@pytest.mark.asyncio
async def test_review_incremental_generation_only_feeds_digests_after_previous_updated_at(
    tmp_path,
):
    repo = FileSubjectStore(tmp_path)
    subject = await _create_subject(repo)
    baseline = datetime(2026, 6, 28, 10, 0, tzinfo=UTC)
    await FileTweetStore(tmp_path).save_tweets([
        _tweet("tw_new", baseline + timedelta(seconds=1), "新增论点B"),
        _tweet("tw_equal", baseline, "边界 digest"),
        _tweet("tw_old", baseline - timedelta(seconds=1), "旧 digest"),
    ])
    previous = await repo.save_review(
        SubjectReview(
            subject_id=subject.subject_id,
            version=1,
            sections=[
                SubjectReviewSection(
                    title="旧分节",
                    body="旧论点A 已在上一版中存在。",
                    cited_tweet_ids=["tw_old"],
                )
            ],
            trend=SubjectReviewTrend(),
            cited_tweet_ids=["tw_old"],
            prev_version=None,
            generated_at=baseline,
            generated_by="llm",
            updated_at=baseline,
        )
    )
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-09",
        generated_at=baseline - timedelta(seconds=1),
        text="不应重复喂入的旧 digest。",
        cited_ids=["tw_old"],
    )
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-10",
        generated_at=baseline,
        text="generated_at 等于 updated_at 的边界 digest 不应喂入。",
        cited_ids=["tw_equal"],
    )
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-11",
        generated_at=baseline + timedelta(seconds=1),
        text="新增论点B 成为本轮增量内容。",
        cited_ids=["tw_new"],
    )
    provider = _StaticProvider(
        """
        {
          "sections": [
            {"title": "旧分节", "body": "旧论点A 已在上一版中存在。", "cited_tweet_ids": ["tw_old"]},
            {"title": "新增分节", "body": "新增论点B 成为本轮增量内容。", "cited_tweet_ids": ["tw_new", "tw_equal"]}
          ],
          "trend": {"emerging": ["新增论点B"], "fading": ["旧论点A"]}
        }
        """
    )

    result = await SubjectReviewService(repo, providers=[provider]).refresh_subject(
        subject.subject_id
    )
    stored = await repo.get_review(subject.subject_id)

    assert result["changed"] is True
    assert stored is not None
    assert stored.version == 2
    assert stored.prev_version == previous.version
    assert [section.title for section in stored.sections] == ["旧分节", "新增分节"]
    assert stored.cited_tweet_ids == ["tw_new"]
    assert provider.prompts
    assert "hour=2026-06-28-11" in provider.prompts[0]
    assert "hour=2026-06-28-10" not in provider.prompts[0]
    assert "hour=2026-06-28-09" not in provider.prompts[0]


@pytest.mark.asyncio
async def test_review_refresh_without_new_digest_does_not_call_llm_or_create_version(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await _create_subject(repo)
    baseline = datetime(2026, 6, 28, 10, 0, tzinfo=UTC)
    previous = await repo.save_review(
        SubjectReview(
            subject_id=subject.subject_id,
            version=3,
            sections=[SubjectReviewSection(title="现有分节", body="现有正文", cited_tweet_ids=[])],
            trend=SubjectReviewTrend(),
            cited_tweet_ids=[],
            prev_version=2,
            generated_at=baseline,
            generated_by="llm",
            updated_at=baseline,
        )
    )
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-10",
        generated_at=baseline,
        text="边界 digest 不应触发新版。",
        cited_ids=[],
    )
    provider = _StaticProvider('{"sections":[],"trend":{"emerging":[],"fading":[]}}')

    result = await SubjectReviewService(repo, providers=[provider]).refresh_subject(
        subject.subject_id
    )

    assert result == {"subject_id": subject.subject_id, "changed": False, "version": 3}
    assert provider.prompts == []
    assert await repo.get_review(subject.subject_id) == previous
    assert [review.version for review in await repo.list_review_history(subject.subject_id)] == [3]
    assert not paths.subject_review_history_doc(tmp_path, subject.subject_id, 4).exists()


@pytest.mark.asyncio
async def test_review_trend_keeps_only_points_traceable_to_previous_or_new_digest(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await _create_subject(repo)
    baseline = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
    await FileTweetStore(tmp_path).save_tweets([
        _tweet("tw_new", baseline + timedelta(seconds=1), "新增论点B"),
    ])
    await repo.save_review(
        SubjectReview(
            subject_id=subject.subject_id,
            version=1,
            sections=[
                SubjectReviewSection(title="旧分节", body="旧论点A 仍可追溯。", cited_tweet_ids=[])
            ],
            trend=SubjectReviewTrend(),
            cited_tweet_ids=[],
            prev_version=None,
            generated_at=baseline,
            generated_by="llm",
            updated_at=baseline,
        )
    )
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-13",
        generated_at=baseline + timedelta(seconds=1),
        text="新增论点B 进入本轮 digest。",
        cited_ids=["tw_new"],
    )
    provider = _StaticProvider(
        """
        {
          "sections": [
            {"title": "合并分节", "body": "旧论点A 仍可追溯。新增论点B 进入本轮 digest。", "cited_tweet_ids": ["tw_new"]}
          ],
          "trend": {
            "emerging": ["新增论点B", "编造论点X"],
            "fading": ["旧论点A"]
          }
        }
        """
    )

    await SubjectReviewService(repo, providers=[provider]).refresh_subject(subject.subject_id)
    stored = await repo.get_review(subject.subject_id)

    assert stored is not None
    assert stored.trend.emerging == ["新增论点B"]
    assert stored.trend.fading == ["旧论点A"]


@pytest.mark.asyncio
async def test_review_citation_validation_requires_digest_cited_set_and_tweet_index(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await _create_subject(repo)
    now = datetime(2026, 6, 28, 14, 0, tzinfo=UTC)
    await FileTweetStore(tmp_path).save_tweets([
        _tweet("tw_valid", now, "valid cited tweet"),
        _tweet("tw_not_source", now, "existing but not in digest cited set"),
    ])
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-14",
        generated_at=now,
        text="引用双重校验。",
        cited_ids=["tw_valid", "tw_missing"],
    )
    provider = _StaticProvider(
        """
        {
          "sections": [
            {
              "title": "引用分节",
              "body": "合法引用保留，越界与悬空引用丢弃。",
              "cited_tweet_ids": ["tw_valid", "tw_not_source", "tw_missing"]
            }
          ],
          "trend": {"emerging": [], "fading": []}
        }
        """
    )

    await SubjectReviewService(repo, providers=[provider]).refresh_subject(subject.subject_id)
    stored = await repo.get_review(subject.subject_id)

    assert stored is not None
    assert stored.sections[0].cited_tweet_ids == ["tw_valid"]
    assert stored.cited_tweet_ids == ["tw_valid"]


@pytest.mark.asyncio
async def test_review_llm_failure_falls_back_with_real_digest_data(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await _create_subject(repo)
    now = datetime(2026, 6, 28, 15, 0, tzinfo=UTC)
    await FileTweetStore(tmp_path).save_tweets([
        _tweet("tw_fallback", now, "fallback source tweet"),
    ])
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-15",
        generated_at=now,
        text="fallback 应吃真实 digest 数据兜底。",
        cited_ids=["tw_fallback"],
    )

    result = await SubjectReviewService(
        repo,
        providers=[_StaticProvider(error=RuntimeError("boom"))],
    ).refresh_subject(subject.subject_id)
    stored = await repo.get_review(subject.subject_id)

    assert result["changed"] is True
    assert stored is not None
    assert stored.version == 1
    assert stored.generated_by == "fallback"
    assert stored.sections[0].title == "2026-06-28-15 滚动综述"
    assert stored.sections[0].body == "fallback 应吃真实 digest 数据兜底。"
    assert stored.cited_tweet_ids == ["tw_fallback"]


@pytest.mark.asyncio
async def test_review_versions_increment_and_history_keeps_every_effective_refresh(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await _create_subject(repo)
    first_time = datetime(2026, 6, 28, 16, 0, tzinfo=UTC)
    await FileTweetStore(tmp_path).save_tweets([
        _tweet("tw_one", first_time, "first"),
        _tweet("tw_two", first_time + timedelta(seconds=2), "second"),
    ])
    service = SubjectReviewService(repo, providers=[])

    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-16",
        generated_at=first_time,
        text="第一版 digest。",
        cited_ids=["tw_one"],
    )
    first = await service.refresh_subject(subject.subject_id)
    first_review = await repo.get_review(subject.subject_id)
    assert first_review is not None

    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-17",
        generated_at=first_review.updated_at + timedelta(seconds=1),
        text="第二版 digest。",
        cited_ids=["tw_two"],
    )
    second = await service.refresh_subject(subject.subject_id)
    latest = await repo.get_review(subject.subject_id)
    history = await repo.list_review_history(subject.subject_id)

    assert first["version"] == 1
    assert second["version"] == 2
    assert latest is not None
    assert latest.version == 2
    assert latest.prev_version == 1
    assert [review.version for review in history] == [1, 2]
    assert paths.subject_review_history_doc(tmp_path, subject.subject_id, 1).exists()
    assert paths.subject_review_history_doc(tmp_path, subject.subject_id, 2).exists()


@pytest.mark.asyncio
async def test_review_empty_payload_is_v0_and_first_real_refresh_starts_at_v1(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await _create_subject(repo)
    service = SubjectReviewService(repo, providers=[])

    empty = await service.get_review_payload(subject.subject_id)
    no_digest_result = await service.refresh_subject(subject.subject_id)

    assert empty == {
        "subject_id": subject.subject_id,
        "version": 0,
        "sections": [],
        "trend": {"emerging": [], "fading": []},
        "cited_tweet_ids": [],
        "prev_version": None,
        "generated_at": None,
        "generated_by": None,
        "updated_at": None,
    }
    assert no_digest_result == {"subject_id": subject.subject_id, "changed": False, "version": 0}
    assert await repo.get_review(subject.subject_id) is None

    now = datetime(2026, 6, 28, 18, 0, tzinfo=UTC)
    await _save_digest(
        repo,
        subject_id=subject.subject_id,
        hour="2026-06-28-18",
        generated_at=now,
        text="首份真实综述来自第一条 digest。",
        cited_ids=[],
    )
    first = await service.refresh_subject(subject.subject_id)
    stored = await repo.get_review(subject.subject_id)

    assert first["changed"] is True
    assert first["version"] == 1
    assert stored is not None
    assert stored.version == 1
    assert stored.prev_version is None
    assert stored.sections
