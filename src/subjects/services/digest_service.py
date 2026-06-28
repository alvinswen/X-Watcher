"""Subject L1 滚动新闻生成。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from returns.result import Success

from src.data_layer.provider import get_subject_repo
from src.storage.index import TweetIdIndex
from src.subjects.models import SubjectDigest, SubjectHighlight
from src.subjects.store import hour_bucket, hour_window
from src.summarization.domain.models import LLMResponse

logger = logging.getLogger(__name__)

MAX_DIGEST_TWEETS = 50


class SubjectDigestService:
    """按 UTC 小时桶整窗口重算 SubjectDigest。"""

    def __init__(self, repo=None, providers: list[Any] | None = None) -> None:
        self._repo = repo if repo is not None else get_subject_repo()
        self._providers = providers

    async def rollup_subject_hour(self, subject_id: str, hour: str) -> SubjectDigest | None:
        subject = await self._repo.get_subject(subject_id)
        if subject is None:
            return None

        start, end = hour_window(hour)
        matches = await self._repo.list_matches(subject_id, since=start, until=end)
        tweet_ids = [match.tweet_id for match in matches]
        tweet_items, _missing = await self._repo.get_tweets_by_ids(tweet_ids)

        index = TweetIdIndex.build(self._repo._root)  # noqa: SLF001 - file repo exposes root only internally
        match_id_set = set(tweet_ids)

        try:
            digest = await self._build_llm_digest(
                subject_id=subject_id,
                subject_name=subject.name,
                hour=hour,
                tweet_items=tweet_items,
                match_id_set=match_id_set,
                tweet_index=index,
                total_match_count=len(tweet_ids),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SubjectDigest LLM 生成失败，降级 fallback: subject_id=%s hour=%s error=%s",
                subject_id,
                hour,
                exc,
            )
            digest = self._build_fallback_digest(
                subject_id=subject_id,
                subject_name=subject.name,
                hour=hour,
                tweet_items=tweet_items,
                match_id_set=match_id_set,
                tweet_index=index,
                total_match_count=len(tweet_ids),
            )
        return await self._repo.save_digest(digest)

    async def _build_llm_digest(
        self,
        *,
        subject_id: str,
        subject_name: str,
        hour: str,
        tweet_items: list[dict],
        match_id_set: set[str],
        tweet_index: TweetIdIndex,
        total_match_count: int,
    ) -> SubjectDigest:
        prompt_items = self._prepare_prompt_items(tweet_items)
        if not prompt_items:
            raise ValueError("桶内无可提供给 LLM 的推文")

        prompt = self._format_digest_prompt(
            subject_name=subject_name,
            hour=hour,
            total_match_count=total_match_count,
            prompt_items=prompt_items,
        )
        response = await self._call_digest_llm(prompt)
        payload = self._parse_digest_response(response.content)
        highlights, cited_ids = self._validated_highlights(
            payload.get("highlights"),
            match_id_set=match_id_set,
            tweet_index=tweet_index,
        )
        digest_text = str(payload.get("digest_text") or "").strip()
        if not digest_text:
            raise ValueError("LLM digest_text 为空")
        if total_match_count > MAX_DIGEST_TWEETS:
            cap_note = f"（基于本小时最近 {MAX_DIGEST_TWEETS} 条/共 {total_match_count} 条）"
            if cap_note not in digest_text:
                digest_text = f"{digest_text}{cap_note}"
        return SubjectDigest(
            subject_id=subject_id,
            hour=hour,
            tweet_count=total_match_count,
            digest_text=digest_text,
            highlights=highlights,
            cited_tweet_ids=cited_ids,
            generated_at=datetime.now(timezone.utc),
            generated_by="llm",
        )

    def _build_fallback_digest(
        self,
        *,
        subject_id: str,
        subject_name: str,
        hour: str,
        tweet_items: list[dict],
        match_id_set: set[str],
        tweet_index: TweetIdIndex,
        total_match_count: int,
    ) -> SubjectDigest:
        valid_ids = [
            item["tweet_id"]
            for item in tweet_items
            if item["tweet_id"] in match_id_set and tweet_index.contains(item["tweet_id"])
        ]
        valid_set = set(valid_ids)
        highlights: list[SubjectHighlight] = []
        for item in tweet_items[:5]:
            tweet_id = item["tweet_id"]
            if tweet_id not in valid_set:
                continue
            point = item.get("summary") or item.get("text") or "新增相关推文"
            highlights.append(
                SubjectHighlight(point=str(point)[:180], cited_tweet_ids=[tweet_id])
            )
        digest_text = (
            f"该小时共有 {total_match_count} 条与「{subject_name}」相关的推文。"
            if total_match_count
            else f"该小时暂无与「{subject_name}」相关的推文。"
        )
        if total_match_count > MAX_DIGEST_TWEETS:
            digest_text = f"{digest_text}（基于本小时最近 {MAX_DIGEST_TWEETS} 条/共 {total_match_count} 条）"
        return SubjectDigest(
            subject_id=subject_id,
            hour=hour,
            tweet_count=total_match_count,
            digest_text=digest_text,
            highlights=highlights,
            cited_tweet_ids=valid_ids,
            generated_at=datetime.now(timezone.utc),
            generated_by="fallback",
        )

    @staticmethod
    def _prepare_prompt_items(tweet_items: list[dict]) -> list[dict]:
        def sort_key(item: dict) -> datetime:
            created = item.get("created_at")
            if isinstance(created, datetime):
                return created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            if created:
                return datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            return datetime.min.replace(tzinfo=timezone.utc)

        ordered = sorted(tweet_items, key=sort_key, reverse=True)
        prepared: list[dict] = []
        for item in ordered[:MAX_DIGEST_TWEETS]:
            body = item.get("summary") or item.get("text") or ""
            prepared.append({
                "tweet_id": item.get("tweet_id"),
                "author": item.get("author_username") or item.get("author") or "",
                "content": str(body).replace("\n", " ")[:500],
            })
        return prepared

    @staticmethod
    def _format_digest_prompt(
        *,
        subject_name: str,
        hour: str,
        total_match_count: int,
        prompt_items: list[dict],
    ) -> str:
        items = "\n".join(
            f'- tweet_id={item["tweet_id"]}; 作者=@{item["author"]}; 内容={item["content"]}'
            for item in prompt_items
        )
        cap_note = (
            f"\n注意：本小时共有 {total_match_count} 条相关推文，以下仅提供最近 {MAX_DIGEST_TWEETS} 条。"
            if total_match_count > MAX_DIGEST_TWEETS
            else ""
        )
        return f"""你在为议题「{subject_name}」生成一条“滚动新闻”摘要，覆盖 UTC 小时桶 {hour} 内的相关推文。
请使用简体中文，客观、信息密度高、不夸张。
{cap_note}

## 可引用推文
{items}

## 输出要求
- digest_text：100~200 字的本小时综述。
- highlights：3~6 条关键看点，每条 point 一句话，cited_tweet_ids 列出支撑该看点的推文 id。
- cited_tweet_ids 只能来自本次提供的 tweet_id 列表，不得编造；无可引用则该看点不要写。

严格返回 JSON，不要添加 markdown：
{{"digest_text":"...","highlights":[{{"point":"...","cited_tweet_ids":["tw_8841"]}}]}}
"""

    async def _call_digest_llm(self, prompt: str) -> LLMResponse:
        from src.summarization.llm.config import LLMProviderConfig
        from src.summarization.services.summarization_service import (
            SummarizationService,
            _build_providers_from_config,
            _get_global_llm_semaphore,
        )

        providers = self._providers
        if providers is None:
            providers = _build_providers_from_config(LLMProviderConfig.from_env())
        if not providers:
            raise RuntimeError("未配置 LLM provider")

        async with _get_global_llm_semaphore():
            last_error: Exception | None = None
            for provider in providers:
                result = await provider.complete(
                    prompt,
                    max_tokens=SummarizationService.DEFAULT_MAX_TOKENS,
                )
                if isinstance(result, Success):
                    return result.unwrap()
                last_error = result.failure()
            raise RuntimeError(f"全部 digest LLM provider 调用失败: {last_error}")

    @staticmethod
    def _parse_digest_response(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        data = json.loads(cleaned.strip())
        if not isinstance(data, dict):
            raise ValueError("digest LLM 输出不是 JSON object")
        return data

    @staticmethod
    def _validated_highlights(
        raw_highlights: Any,
        *,
        match_id_set: set[str],
        tweet_index: TweetIdIndex,
    ) -> tuple[list[SubjectHighlight], list[str]]:
        highlights: list[SubjectHighlight] = []
        cited_union: list[str] = []
        if not isinstance(raw_highlights, list):
            return highlights, cited_union
        for raw in raw_highlights:
            if not isinstance(raw, dict):
                continue
            point = str(raw.get("point") or "").strip()
            raw_ids = raw.get("cited_tweet_ids")
            if not point or not isinstance(raw_ids, list):
                continue
            valid_ids: list[str] = []
            for tweet_id in raw_ids:
                tweet_id = str(tweet_id)
                if tweet_id in match_id_set and tweet_index.contains(tweet_id):
                    valid_ids.append(tweet_id)
                    if tweet_id not in cited_union:
                        cited_union.append(tweet_id)
            if valid_ids:
                highlights.append(SubjectHighlight(point=point[:240], cited_tweet_ids=valid_ids))
        return highlights, cited_union

    async def rollup_matches(self, matches) -> None:
        affected = {
            (match.subject_id, hour_bucket(match.matched_at))
            for match in matches
        }
        for subject_id, hour in affected:
            try:
                await self.rollup_subject_hour(subject_id, hour)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "滚动 SubjectDigest 失败，不阻断主链路: subject_id=%s hour=%s error=%s",
                    subject_id,
                    hour,
                    exc,
                )

    async def rollup_current_hour_for_active_subjects(self) -> None:
        hour = hour_bucket(datetime.now(timezone.utc))
        for subject in await self._repo.list_active_subjects():
            try:
                await self.rollup_subject_hour(subject.subject_id, hour)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "滚动当前小时 SubjectDigest 失败: subject_id=%s hour=%s error=%s",
                    subject.subject_id,
                    hour,
                    exc,
                )
