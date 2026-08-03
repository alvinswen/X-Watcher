"""信源候选试读、预审、终审与查询编排。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from returns.result import Failure

from src.data_layer.repositories import SourceCandidateStore
from src.preference.domain.models import XUserProfile
from src.preference.infrastructure.follow_store import DuplicateError, FollowStore
from src.preference.services.scraper_config_service import ScraperConfigService
from src.scraper.client import TwitterClient
from src.scraper.parser import TweetParser
from src.source_candidates.models import (
    CandidateAssessment,
    CandidateDecision,
    CandidateSample,
    CandidateScores,
    CandidateStatus,
    SourceCandidate,
)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


class CandidateValidationError(ValueError):
    """候选动作未通过业务校验。"""


class CandidateNotFoundError(LookupError):
    """候选或外部账号不存在。"""


class CandidateExternalError(RuntimeError):
    """外部档案或样本调用失败。"""


class CandidateInternalError(RuntimeError):
    """跨域写入失败，需要重试或人工恢复。"""


class CandidatePermissionError(PermissionError):
    """候选动作被事前开关拒绝。"""


class CandidateService:
    def __init__(
        self,
        store: SourceCandidateStore,
        follow_store: FollowStore,
        scraper_config_service: ScraperConfigService,
        twitter_client: TwitterClient,
    ) -> None:
        self._store = store
        self._follow_store = follow_store
        self._scraper_config_service = scraper_config_service
        self._twitter_client = twitter_client

    async def _require_candidate(self, candidate_id: str) -> SourceCandidate:
        normalized = candidate_id.lower()
        if not _USERNAME_RE.fullmatch(normalized):
            raise CandidateValidationError("候选标识必须是 1~15 位字母、数字或下划线")
        candidate = await self._store.get_candidate(normalized)
        if candidate is None:
            raise CandidateNotFoundError("候选不存在")
        return candidate

    async def ensure_fetchable(self, candidate_id: str) -> SourceCandidate:
        """试读付费动作前校验候选存在且未进入终态。"""
        candidate = await self._require_candidate(candidate_id)
        if candidate.status.is_terminal:
            raise CandidateValidationError("终态候选不再试读")
        return candidate

    async def fetch_sample(self, candidate_id: str) -> dict[str, Any]:
        candidate = await self.ensure_fetchable(candidate_id)

        profile_result = await self._twitter_client.fetch_user_info_by_username(
            candidate.username
        )
        if isinstance(profile_result, Failure):
            raise CandidateExternalError(profile_result.failure().message)
        profile_data = profile_result.unwrap()
        profile_fetched_at = datetime.now(UTC)
        profile = XUserProfile.from_api_response(profile_data, profile_fetched_at)
        platform_user_id = str(profile_data.get("id") or "") or None
        if platform_user_id is not None:
            conflict = await self._store.get_candidate_by_platform_user_id(platform_user_id)
            if conflict is not None and conflict.candidate_id != candidate.candidate_id:
                raise CandidateValidationError(
                    f"该账号与候选 {conflict.candidate_id} 为同一账号（改名）"
                )
        candidate.platform_user_id = platform_user_id
        candidate.profile_snapshot = profile.model_dump(mode="json")
        candidate.profile_fetched_at = profile_fetched_at
        await self._store.upsert_candidate(candidate)

        if bool(profile_data.get("unavailable")):
            reason = str(profile_data.get("unavailableReason") or "未知原因")
            raise CandidateNotFoundError(f"账号不可用: {reason}（已写回候选档案）")

        tweets_result = await self._twitter_client.fetch_user_tweets(candidate.username)
        if isinstance(tweets_result, Failure):
            raise CandidateExternalError(tweets_result.failure().message)
        tweets = TweetParser().parse_tweet_response(tweets_result.unwrap())
        tweets.sort(key=lambda tweet: tweet.created_at, reverse=True)
        sample_fetched_at = datetime.now(UTC)
        candidate.sample = CandidateSample(
            tweets=[tweet.model_dump(mode="json") for tweet in tweets[:20]],
            fetched_at=sample_fetched_at,
        )
        await self._store.upsert_candidate(candidate)
        return {
            "candidate_id": candidate.candidate_id,
            "platform_user_id": candidate.platform_user_id,
            "profile_fetched_at": profile_fetched_at.isoformat(),
            "sample_count": len(candidate.sample.tweets),
            "sample_fetched_at": sample_fetched_at.isoformat(),
            "unavailable": False,
        }

    async def submit_assessment(
        self,
        *,
        candidate_id: str,
        originality_score: int,
        difference_score: int,
        expertise_score: int,
        recommendation: str,
        evidence_tweet_ids: list[str],
        assessed_by: str,
    ) -> dict[str, Any]:
        candidate = await self._require_candidate(candidate_id)
        if candidate.status.is_terminal:
            raise CandidateValidationError("已批准或已否决候选不能写入预审")
        if not recommendation.strip():
            raise CandidateValidationError("推荐意见不能为空")
        if not evidence_tweet_ids:
            raise CandidateValidationError("证据推文编号不能为空")
        sample_ids = {
            str(tweet.get("tweet_id") or tweet.get("id") or "")
            for tweet in (candidate.sample.tweets if candidate.sample else [])
        }
        if not sample_ids:
            raise CandidateValidationError("证据必须来自试读样本集，当前样本集为空")
        missing = set(evidence_tweet_ids) - sample_ids
        if missing:
            raise CandidateValidationError(
                f"证据必须来自试读样本集，当前样本集不含该编号: {sorted(missing)}"
            )
        try:
            scores = CandidateScores(
                originality=originality_score,
                difference=difference_score,
                expertise=expertise_score,
            )
        except ValueError as exc:
            raise CandidateValidationError("三维评分必须分别在 0 到 10 之间") from exc
        now = datetime.now(UTC)
        candidate.assessment = CandidateAssessment(
            scores=scores,
            recommendation=recommendation.strip(),
            evidence_tweet_ids=evidence_tweet_ids,
            assessed_at=now,
            assessed_by=assessed_by,
        )
        candidate.status = CandidateStatus.ASSESSED
        await self._store.upsert_candidate(candidate)
        return {
            "candidate_id": candidate.candidate_id,
            "status": candidate.status.value,
            "assessed_at": now.isoformat(),
        }

    async def review(
        self,
        *,
        candidate_id: str,
        decision: str,
        decided_by: str,
        brief_intro: str | None = None,
        reject_reason: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise CandidateValidationError("decision 只能是 approve 或 reject")
        candidate = await self._require_candidate(candidate_id)
        if candidate.status.is_terminal:
            current = candidate.decision.model_dump(mode="json") if candidate.decision else None
            raise CandidateValidationError(
                f"候选已是终态 {candidate.status.value}，先到先得不覆盖；decision={current}"
            )

        now = datetime.now(UTC)
        if decision == "reject":
            candidate.status = CandidateStatus.REJECTED
            candidate.decision = CandidateDecision(
                verdict="reject",
                decided_by=decided_by,
                decided_at=now,
                reject_reason=reject_reason,
            )
            await self._store.upsert_candidate(candidate)
            return {"candidate_id": candidate.candidate_id, "status": "rejected"}

        if brief_intro is not None and len(brief_intro) > 50:
            raise CandidateValidationError("极简介绍不能超过 50 个字符（业务语义 ≤10 汉字）")
        reason = (
            f"信源评审转正: 引用{candidate.mining.citation_total}次/"
            f"{candidate.mining.source_diversity}源"
        )
        if candidate.assessment is not None:
            reason += f";预审:{candidate.assessment.recommendation[:50]}"
        added_by = f"candidate_review:{decided_by}"
        follow = None
        created_now = False
        try:
            follow = await self._scraper_config_service.add_scraper_follow(
                username=candidate.username,
                reason=reason,
                added_by=added_by,
                platform_user_id=candidate.platform_user_id,
                brief_intro=brief_intro,
            )
            created_now = True
        except DuplicateError as exc:
            existing = await self._follow_store.get_follow_by_username(candidate.username)
            if (
                existing is None
                or not existing.is_active
                or existing.username.lower() != candidate.username.lower()
                or not existing.added_by.startswith("candidate_review:")
            ):
                raise CandidateValidationError(
                    "抓取名单存在同名冲突；请排查名单冲突后重试终审"
                ) from exc
            follow = existing

        candidate.status = CandidateStatus.APPROVED
        candidate.decision = CandidateDecision(
            verdict="approve",
            decided_by=decided_by,
            decided_at=now,
            follow_id=follow.id,
            follow_username=follow.username,
        )
        try:
            await self._store.upsert_candidate(candidate)
        except Exception as exc:
            compensation = "无需补偿"
            if created_now:
                try:
                    await self._follow_store.deactivate_follow(candidate.username)
                    compensation = "已停用本次新增关注"
                except Exception as compensation_exc:
                    compensation = f"补偿失败: {compensation_exc}"
            raise CandidateInternalError(
                "候选终态写入失败；"
                f"{compensation}。人工恢复：在关注管理停用该账号后重试终审"
            ) from exc

        result: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "status": "approved",
            "follow_id": follow.id,
            "follow_username": follow.username,
            "platform_user_id": candidate.platform_user_id,
        }
        if candidate.assessment is None:
            result["notice"] = "该候选尚无预审结论"
        return result

    async def list_candidates(
        self,
        *,
        status: CandidateStatus | None = None,
        subject_id: str | None = None,
        candidate_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
        statuses: list[CandidateStatus] | None = None,
        include_profile_fields: bool = False,
    ) -> dict[str, Any]:
        if statuses is not None and status is not None:
            raise CandidateValidationError("status 与 statuses 不能同时给定")
        if page < 1:
            raise CandidateValidationError("page 必须大于等于 1")
        if not 1 <= page_size <= 100:
            raise CandidateValidationError("page_size 必须在 1 到 100 之间")
        if candidate_id is not None:
            candidate = await self._require_candidate(candidate_id)
            return {"candidate": candidate.model_dump(mode="json")}
        if statuses is not None:
            allowed = set(statuses)
            candidates = [
                candidate
                for candidate in await self._store.list_candidates(subject_id=subject_id)
                if candidate.status in allowed
            ]
        else:
            candidates = await self._store.list_candidates(
                status=status, subject_id=subject_id
            )
        total = len(candidates)
        start = (page - 1) * page_size
        page_items = candidates[start : start + page_size]
        summaries = [
            self._summary(candidate, include_profile_fields=include_profile_fields)
            for candidate in page_items
        ]
        return {
            "candidates": summaries,
            "count": len(summaries),
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def _summary(
        candidate: SourceCandidate, *, include_profile_fields: bool = False
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "username": candidate.username,
            "platform_user_id": candidate.platform_user_id,
            "status": candidate.status.value,
            "citation_total": candidate.mining.citation_total,
            "source_diversity": candidate.mining.source_diversity,
            "subject_tags": candidate.mining.subject_tags,
            "first_discovered_at": candidate.mining.first_discovered_at.isoformat(),
            "last_mined_at": candidate.mining.last_mined_at.isoformat(),
            "sample_fetched_at": (
                candidate.sample.fetched_at.isoformat() if candidate.sample else None
            ),
            "assessed_at": (
                candidate.assessment.assessed_at.isoformat()
                if candidate.assessment
                else None
            ),
            "decided_at": (
                candidate.decision.decided_at.isoformat() if candidate.decision else None
            ),
        }
        if include_profile_fields:
            snapshot = candidate.profile_snapshot or {}
            data["display_name"] = snapshot.get("display_name")
            data["verified_type"] = snapshot.get("verified_type")
            data["is_automated"] = snapshot.get("is_automated")
        return data
