"""Subject L2 活综述生成与刷新任务。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from returns.result import Success

from src.data_layer.provider import get_subject_repo
from src.scraper.task_registry import TaskRegistry, TaskStatus
from src.storage import paths
from src.storage.index import TweetIdIndex
from src.subjects.models import (
    SubjectDigest,
    SubjectReview,
    SubjectReviewSection,
    SubjectReviewTrend,
)
from src.summarization.domain.models import LLMResponse

logger = logging.getLogger(__name__)

MAX_REVIEW_DIGESTS = 10_000
_BACKGROUND_TASKS: set[asyncio.Task] = set()


class ReviewRefreshAlreadyRunningError(RuntimeError):
    """已有 review 刷新任务在运行。"""


class SubjectReviewService:
    def __init__(self, repo=None, providers: list[Any] | None = None) -> None:
        self._repo = repo if repo is not None else get_subject_repo()
        self._providers = providers
        self._registry = TaskRegistry.get_instance()

    async def get_review_payload(self, subject_id: str) -> dict | None:
        if await self._repo.get_subject(subject_id) is None:
            return None
        stored = await self._repo.get_review(subject_id)
        if stored is None:
            return self.empty_review_payload(subject_id)
        return stored.model_dump(mode="json")

    @staticmethod
    def empty_review_payload(subject_id: str) -> dict:
        return {
            "subject_id": subject_id,
            "version": 0,
            "sections": [],
            "trend": {"emerging": [], "fading": []},
            "cited_tweet_ids": [],
            "prev_version": None,
            "generated_at": None,
            "generated_by": None,
            "updated_at": None,
        }

    async def refresh_subject(self, subject_id: str) -> dict:
        subject = await self._repo.get_subject(subject_id)
        if subject is None:
            raise ValueError("议题不存在")

        previous = await self._repo.get_review(subject_id)
        fresh_items = await self._new_digest_items(subject_id, previous)
        current_version = previous.version if previous is not None else 0
        if not fresh_items:
            return {
                "subject_id": subject_id,
                "changed": False,
                "version": current_version,
            }

        index = TweetIdIndex.build(self._repo._root)  # noqa: SLF001 - file repo exposes root only internally
        allowed_ids = self._digest_cited_id_set(fresh_items)
        try:
            built = await self._build_llm_review(
                subject_id=subject_id,
                subject_name=subject.name,
                previous=previous,
                fresh_items=fresh_items,
                allowed_ids=allowed_ids,
                tweet_index=index,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SubjectReview LLM 生成失败，降级 fallback: subject_id=%s error=%s",
                subject_id,
                exc,
            )
            built = self._build_fallback_review(
                subject_id=subject_id,
                previous=previous,
                fresh_items=fresh_items,
                allowed_ids=allowed_ids,
                tweet_index=index,
            )
        saved = await self._repo.save_review(built)
        return {
            "subject_id": subject_id,
            "changed": True,
            "version": saved.version,
            "generated_by": saved.generated_by,
        }

    async def start_refresh(self, subject_id: str | None = None) -> dict:
        if self._has_running_refresh_task():
            raise ReviewRefreshAlreadyRunningError("已有综述刷新任务进行中")
        if subject_id is not None and await self._repo.get_subject(subject_id) is None:
            raise ValueError("议题不存在")

        task_id = self._registry.create_task(
            task_name=f"议题综述刷新 {subject_id or '全部活跃议题'}",
            metadata={
                "subject_id": subject_id,
                "task_type": "subject_review_refresh",
            },
        )
        task = asyncio.create_task(
            self._run_refresh_task(task_id, subject_id),
            name=f"subject-review-refresh-{subject_id or 'all'}",
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return {"task_id": task_id, "status": TaskStatus.PENDING.value}

    async def _run_refresh_task(self, task_id: str, subject_id: str | None) -> None:
        try:
            self._registry.update_task_status(task_id, TaskStatus.RUNNING)
            subjects = (
                [await self._repo.get_subject(subject_id)]
                if subject_id is not None
                else await self._repo.list_active_subjects()
            )
            subjects = [subject for subject in subjects if subject is not None]
            total = len(subjects)
            items: list[dict] = []
            any_changed = False
            for index, subject in enumerate(subjects, start=1):
                result = await self.refresh_subject(subject.subject_id)
                items.append(result)
                any_changed = any_changed or bool(result.get("changed"))
                self._registry.update_progress(task_id, index, total)
            result_payload: dict = {"changed": any_changed, "items": items}
            if subject_id is not None:
                result_payload = items[0] if items else {"subject_id": subject_id, "changed": False, "version": 0}
            self._registry.update_task_status(task_id, TaskStatus.COMPLETED, result=result_payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("SubjectReview 刷新任务失败: subject_id=%s", subject_id)
            self._registry.update_task_status(task_id, TaskStatus.FAILED, error=str(exc))

    def _has_running_refresh_task(self) -> bool:
        for task in self._registry.get_all_tasks():
            metadata = task.get("metadata") or {}
            status = task.get("status")
            if isinstance(status, TaskStatus):
                status = status.value
            if (
                metadata.get("task_type") == "subject_review_refresh"
                and status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}
            ):
                return True
        return False

    async def _new_digest_items(
        self,
        subject_id: str,
        previous: SubjectReview | None,
    ) -> list[SubjectDigest]:
        baseline = paths.as_utc(previous.updated_at) if previous is not None else None
        items = await self._repo.list_digests(subject_id, limit=MAX_REVIEW_DIGESTS)
        if baseline is not None:
            items = [item for item in items if paths.as_utc(item.generated_at) > baseline]
        items.sort(key=lambda item: paths.as_utc(item.generated_at))
        return items

    @staticmethod
    def _digest_cited_id_set(items: list[SubjectDigest]) -> set[str]:
        cited: set[str] = set()
        for item in items:
            cited.update(item.cited_tweet_ids)
        return cited

    async def _build_llm_review(
        self,
        *,
        subject_id: str,
        subject_name: str,
        previous: SubjectReview | None,
        fresh_items: list[SubjectDigest],
        allowed_ids: set[str],
        tweet_index: TweetIdIndex,
    ) -> SubjectReview:
        prompt = self._format_review_prompt(
            subject_name=subject_name,
            previous=previous,
            fresh_items=fresh_items,
        )
        response = await self._call_review_llm(prompt)
        payload = self._parse_review_response(response.content)
        sections, cited_ids = self._validated_sections(
            payload.get("sections"),
            allowed_ids=allowed_ids,
            tweet_index=tweet_index,
        )
        if not sections:
            raise ValueError("LLM review sections 为空")
        version = (previous.version if previous is not None else 0) + 1
        trend = SubjectReviewTrend()
        if previous is not None and version >= 2:
            trend = self._validated_trend(
                payload.get("trend"),
                source_text=self._trend_source_text(previous, fresh_items),
            )
        now = datetime.now(UTC)
        return SubjectReview(
            subject_id=subject_id,
            version=version,
            sections=sections,
            trend=trend,
            cited_tweet_ids=cited_ids,
            prev_version=previous.version if previous is not None else None,
            generated_at=now,
            generated_by="llm",
            updated_at=now,
        )

    def _build_fallback_review(
        self,
        *,
        subject_id: str,
        previous: SubjectReview | None,
        fresh_items: list[SubjectDigest],
        allowed_ids: set[str],
        tweet_index: TweetIdIndex,
    ) -> SubjectReview:
        sections = []
        if previous is not None:
            for section in previous.sections:
                sections.append(
                    SubjectReviewSection(
                        title=section.title,
                        body=section.body,
                        cited_tweet_ids=[
                            tweet_id
                            for tweet_id in section.cited_tweet_ids
                            if tweet_id in allowed_ids and tweet_index.contains(tweet_id)
                        ],
                    )
                )
        for item in fresh_items:
            valid_ids = [
                tweet_id
                for tweet_id in item.cited_tweet_ids
                if tweet_id in allowed_ids and tweet_index.contains(tweet_id)
            ]
            body = item.digest_text.strip()
            if not body and item.highlights:
                body = "；".join(highlight.point for highlight in item.highlights)
            sections.append(
                SubjectReviewSection(
                    title=f"{item.hour} 滚动综述",
                    body=body or "本轮新增 digest 暂无正文。",
                    cited_tweet_ids=valid_ids,
                )
            )
        cited_ids = self._section_cited_union(sections)
        now = datetime.now(UTC)
        return SubjectReview(
            subject_id=subject_id,
            version=(previous.version if previous is not None else 0) + 1,
            sections=sections,
            trend=SubjectReviewTrend(),
            cited_tweet_ids=cited_ids,
            prev_version=previous.version if previous is not None else None,
            generated_at=now,
            generated_by="fallback",
            updated_at=now,
        )

    @staticmethod
    def _format_review_prompt(
        *,
        subject_name: str,
        previous: SubjectReview | None,
        fresh_items: list[SubjectDigest],
    ) -> str:
        previous_text = "（无上一版综述）"
        if previous is not None:
            previous_text = "\n".join(
                f"## {section.title}\n{section.body}\n引用: {', '.join(section.cited_tweet_ids)}"
                for section in previous.sections
            )
        item_text = "\n\n".join(
            "\n".join([
                f"### digest hour={item.hour}; generated_at={item.generated_at.isoformat()}",
                f"digest_text: {item.digest_text}",
                "highlights:",
                *[
                    f"- {highlight.point} | cited_tweet_ids={','.join(highlight.cited_tweet_ids)}"
                    for highlight in item.highlights
                ],
                f"cited_tweet_ids: {', '.join(item.cited_tweet_ids)}",
            ])
            for item in fresh_items
        )
        return f"""你在为议题「{subject_name}」生成 L2 活综述。
请把上一版综述与本轮新增 L1 digest 合并为一份从议题建立至今的全量累积综述。
只能使用“上一版综述”和“本轮新增 digest”中出现的信息，不得编造。

## 上一版综述
{previous_text}

## 本轮新增 digest
{item_text}

## 输出要求
- sections: 2~6 个分节，每节包含 title、body、cited_tweet_ids。
- trend.emerging: 仅列本轮 digest 新出现、上一版未覆盖的论点。
- trend.fading: 仅列上一版有、但本轮新增 digest 未再出现的论点。
- 首版无上一版可比时，trend 两组都返回空数组。
- cited_tweet_ids 只能来自本轮新增 digest 的 cited_tweet_ids，不得编造。

严格返回 JSON，不要添加 markdown：
{{"sections":[{{"title":"...","body":"...","cited_tweet_ids":["tw_1"]}}],"trend":{{"emerging":["..."],"fading":["..."]}}}}
"""

    async def _call_review_llm(self, prompt: str) -> LLMResponse:
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
            raise RuntimeError(f"全部 review LLM provider 调用失败: {last_error}")

    @staticmethod
    def _parse_review_response(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        data = json.loads(cleaned.strip())
        if not isinstance(data, dict):
            raise ValueError("review LLM 输出不是 JSON object")
        return data

    @staticmethod
    def _validated_sections(
        raw_sections: Any,
        *,
        allowed_ids: set[str],
        tweet_index: TweetIdIndex,
    ) -> tuple[list[SubjectReviewSection], list[str]]:
        sections: list[SubjectReviewSection] = []
        if not isinstance(raw_sections, list):
            return sections, []
        for raw in raw_sections:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            body = str(raw.get("body") or "").strip()
            raw_ids = raw.get("cited_tweet_ids")
            if not title or not body:
                continue
            valid_ids: list[str] = []
            if isinstance(raw_ids, list):
                for item in raw_ids:
                    tweet_id = str(item)
                    if tweet_id in allowed_ids and tweet_index.contains(tweet_id):
                        valid_ids.append(tweet_id)
            sections.append(
                SubjectReviewSection(
                    title=title[:120],
                    body=body[:3000],
                    cited_tweet_ids=list(dict.fromkeys(valid_ids)),
                )
            )
        return sections, SubjectReviewService._section_cited_union(sections)

    @staticmethod
    def _section_cited_union(sections: list[SubjectReviewSection]) -> list[str]:
        cited_ids: list[str] = []
        for section in sections:
            for tweet_id in section.cited_tweet_ids:
                if tweet_id not in cited_ids:
                    cited_ids.append(tweet_id)
        return cited_ids

    @staticmethod
    def _validated_trend(raw_trend: Any, *, source_text: str) -> SubjectReviewTrend:
        if not isinstance(raw_trend, dict):
            return SubjectReviewTrend()
        source = SubjectReviewService._normalized_text(source_text)

        def valid_points(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            points: list[str] = []
            for item in value:
                point = str(item).strip()
                if point and SubjectReviewService._normalized_text(point) in source:
                    points.append(point[:240])
            return points

        return SubjectReviewTrend(
            emerging=valid_points(raw_trend.get("emerging")),
            fading=valid_points(raw_trend.get("fading")),
        )

    @staticmethod
    def _normalized_text(value: str) -> str:
        return "".join(str(value).lower().split())

    @staticmethod
    def _trend_source_text(previous: SubjectReview, fresh_items: list[SubjectDigest]) -> str:
        previous_parts = [section.body for section in previous.sections]
        item_parts: list[str] = []
        for item in fresh_items:
            item_parts.append(item.digest_text)
            item_parts.extend(highlight.point for highlight in item.highlights)
        return "\n".join([*previous_parts, *item_parts])
