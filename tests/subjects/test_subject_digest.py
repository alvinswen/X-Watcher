from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from returns.result import Failure, Success

from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.subjects.models import SubjectMatch
from src.subjects.services.digest_service import SubjectDigestService
from src.subjects.store import FileSubjectStore, hour_bucket
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
                model="fake-digest-model",
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


@pytest.mark.asyncio
async def test_digest_llm_success_validates_citations_and_marks_generated_by_llm(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="Digest 议题",
        nl_description="用于验证 LLM digest 引用校验",
    )
    created_at = datetime(2026, 6, 27, 9, 10, tzinfo=timezone.utc)
    await FileTweetStore(tmp_path).save_tweets(
        [
            _tweet("tw_valid", created_at, "valid matched tweet"),
            _tweet("tw_outside", created_at, "existing but not matched"),
        ]
    )
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject.subject_id,
                tweet_id="tw_valid",
                matched_at=created_at,
                reason="valid",
            ),
            SubjectMatch(
                subject_id=subject.subject_id,
                tweet_id="tw_missing",
                matched_at=created_at + timedelta(minutes=1),
                reason="missing from tweet index",
            ),
        ]
    )

    provider = _StaticProvider(
        """
        {
          "digest_text": "本小时围绕 Digest 议题出现新的有效进展。",
          "highlights": [
            {
              "point": "有效引用会被保留，越界和悬空引用会被丢弃。",
              "cited_tweet_ids": ["tw_valid", "tw_missing", "tw_outside"]
            },
            {
              "point": "没有任何有效引用的看点不会落盘。",
              "cited_tweet_ids": ["tw_missing", "tw_outside"]
            }
          ]
        }
        """
    )

    digest = await SubjectDigestService(repo, providers=[provider]).rollup_subject_hour(
        subject.subject_id,
        hour_bucket(created_at),
    )

    assert digest is not None
    assert digest.generated_by == "llm"
    assert digest.tweet_count == 2
    assert digest.cited_tweet_ids == ["tw_valid"]
    assert [item.cited_tweet_ids for item in digest.highlights] == [["tw_valid"]]
    assert len(digest.highlights) == 1
    assert provider.prompts and "tw_valid" in provider.prompts[0]

    stored = await repo.get_digest(subject.subject_id, hour_bucket(created_at))
    assert stored is not None
    assert stored.generated_by == "llm"
    assert stored.cited_tweet_ids == ["tw_valid"]


@pytest.mark.asyncio
async def test_digest_llm_parse_failure_falls_back_without_raising(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="Fallback 议题",
        nl_description="用于验证 LLM 失败降级",
    )
    created_at = datetime(2026, 6, 27, 10, 0, tzinfo=timezone.utc)
    await FileTweetStore(tmp_path).save_tweets(
        [_tweet("tw_fallback", created_at, "fallback source tweet")]
    )
    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject.subject_id,
                tweet_id="tw_fallback",
                matched_at=created_at,
                reason="fallback",
            )
        ]
    )

    digest = await SubjectDigestService(
        repo,
        providers=[_StaticProvider("not json")],
    ).rollup_subject_hour(subject.subject_id, hour_bucket(created_at))

    assert digest is not None
    assert digest.generated_by == "fallback"
    assert digest.tweet_count == 1
    assert digest.cited_tweet_ids == ["tw_fallback"]
    assert digest.highlights[0].cited_tweet_ids == ["tw_fallback"]


@pytest.mark.asyncio
async def test_digest_rollup_recomputes_whole_window_without_duplicate_counts(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="幂等议题",
        nl_description="用于验证同小时 digest 整窗口覆写",
    )
    created_at = datetime(2026, 6, 27, 11, 0, tzinfo=timezone.utc)
    await FileTweetStore(tmp_path).save_tweets(
        [
            _tweet("tw_first", created_at, "first source tweet"),
            _tweet("tw_second", created_at + timedelta(minutes=5), "second source tweet"),
        ]
    )
    service = SubjectDigestService(repo, providers=[_StaticProvider("not json")])

    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject.subject_id,
                tweet_id="tw_first",
                matched_at=created_at,
                reason="first",
            )
        ]
    )
    first = await service.rollup_subject_hour(subject.subject_id, hour_bucket(created_at))
    assert first is not None
    assert first.tweet_count == 1

    await repo.upsert_matches(
        [
            SubjectMatch(
                subject_id=subject.subject_id,
                tweet_id="tw_second",
                matched_at=created_at + timedelta(minutes=5),
                reason="second",
            )
        ]
    )
    second = await service.rollup_subject_hour(subject.subject_id, hour_bucket(created_at))
    repeat = await service.rollup_subject_hour(subject.subject_id, hour_bucket(created_at))

    assert second is not None
    assert repeat is not None
    assert second.tweet_count == 2
    assert repeat.tweet_count == 2
    assert [digest.hour for digest in await repo.list_digests(subject.subject_id)] == [
        hour_bucket(created_at)
    ]
