"""文件层 SubjectStore。

盘面：
- subjects/index.json: {"subject_ids": [...]}
- subjects/{subject_id}.json: Subject
- subjects/{subject_id}/matches/{YYYY-MM}.jsonl: SubjectMatch
- subjects/{subject_id}/digests/{YYYY-MM}.jsonl: SubjectDigest
- subjects/{subject_id}/feedback/{YYYY-MM}.jsonl: SubjectFeedback
- subjects/{subject_id}/eval/{YYYY-MM}.jsonl: SubjectEval
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.storage import paths
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc
from src.storage.jsonl_store import append as append_jsonl
from src.storage.jsonl_store import read_shard, upsert
from src.subjects._time import parse_dt
from src.subjects.constants import NO_LIMIT
from src.subjects.index import load_subject_ids, new_subject_id, save_subject_ids
from src.subjects.models import (
    Provenance,
    Subject,
    SubjectDigest,
    SubjectEval,
    SubjectFeedback,
    SubjectMatch,
    SubjectReview,
    SubjectStatus,
)


class PublishWindowMatches(list[SubjectMatch]):
    def __init__(
        self,
        matches: list[SubjectMatch],
        skipped_no_publish_time_ids: list[str],
    ) -> None:
        super().__init__(matches)
        self.skipped_no_publish_time_ids = skipped_no_publish_time_ids


def utc_now() -> datetime:
    return datetime.now(UTC)


class FileSubjectStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    def _subject_path(self, subject_id: str) -> Path:
        return paths.subject_doc(self._root, subject_id)

    def _load_subject(self, subject_id: str) -> Subject | None:
        doc = read_doc(self._subject_path(subject_id))
        if not doc:
            return None
        return Subject(**doc)

    async def list_subjects(self, status: str | None = None) -> list[Subject]:
        wanted = SubjectStatus(status) if status else None
        subjects = [
            subject
            for subject_id in load_subject_ids(self._root)
            if (subject := self._load_subject(subject_id)) is not None
        ]
        if wanted is not None:
            subjects = [subject for subject in subjects if subject.status == wanted]
        subjects.sort(key=lambda item: item.created_at)
        return subjects

    async def list_active_subjects(self) -> list[Subject]:
        return await self.list_subjects(SubjectStatus.active.value)

    async def active_count(self) -> int:
        return len(await self.list_active_subjects())

    async def get_subject(self, subject_id: str) -> Subject | None:
        return self._load_subject(subject_id)

    async def create_subject(
        self,
        *,
        name: str,
        nl_description: str,
        keywords: list[str] | None = None,
        status: SubjectStatus = SubjectStatus.active,
    ) -> Subject:
        now = utc_now()
        subject = Subject(
            subject_id=new_subject_id(self._root),
            name=name.strip(),
            nl_description=nl_description.strip(),
            keywords=[item.strip() for item in (keywords or []) if item.strip()],
            status=status,
            created_at=now,
            updated_at=now,
            pending_classify=True,
        )
        async with shard_lock(paths.subject_index(self._root)):
            ids = load_subject_ids(self._root)
            ids.append(subject.subject_id)
            atomic_write_doc(
                self._subject_path(subject.subject_id), subject.model_dump(mode="json")
            )
            save_subject_ids(self._root, ids)
        return subject

    async def save_subject(self, subject: Subject) -> Subject:
        updated = subject.model_copy(update={"updated_at": utc_now()})
        async with shard_lock(self._subject_path(updated.subject_id)):
            atomic_write_doc(
                self._subject_path(updated.subject_id), updated.model_dump(mode="json")
            )
        return updated

    async def update_subject(
        self,
        subject_id: str,
        *,
        name: str | None = None,
        nl_description: str | None = None,
        keywords: list[str] | None = None,
        status: SubjectStatus | None = None,
    ) -> Subject | None:
        subject = await self.get_subject(subject_id)
        if subject is None:
            return None
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name.strip()
        if nl_description is not None:
            changes["nl_description"] = nl_description.strip()
        if keywords is not None:
            changes["keywords"] = [item.strip() for item in keywords if item.strip()]
        if status is not None:
            changes["status"] = status
        return await self.save_subject(subject.model_copy(update=changes))

    async def touch_subject(self, subject_id: str, when: datetime | None = None) -> None:
        subject = await self.get_subject(subject_id)
        if subject is None:
            return
        await self.save_subject(subject.model_copy(update={"last_updated_at": when or utc_now()}))

    async def set_pending(
        self,
        subject_id: str,
        *,
        classify: bool | None = None,
        review: bool | None = None,
    ) -> Subject | None:
        subject = await self.get_subject(subject_id)
        if subject is None:
            return None
        changes: dict[str, bool] = {}
        if classify is not None:
            changes["pending_classify"] = classify
        if review is not None:
            changes["pending_review"] = review
        if not changes:
            return subject
        return await self.save_subject(subject.model_copy(update=changes))

    async def list_pending(self, subject_id: str | None = None) -> list[dict[str, bool | str]]:
        if subject_id is not None:
            subject = await self.get_subject(subject_id)
            subjects = [subject] if subject is not None else []
        else:
            subjects = await self.list_subjects()
        items: list[dict[str, bool | str]] = []
        for subject in subjects:
            if subject.pending_classify or subject.pending_review:
                items.append(
                    {
                        "subject_id": subject.subject_id,
                        "pending_classify": subject.pending_classify,
                        "pending_review": subject.pending_review,
                    }
                )
        return items

    async def delete_subject(self, subject_id: str) -> bool:
        subject = await self.get_subject(subject_id)
        if subject is None:
            return False
        async with shard_lock(paths.subject_index(self._root)):
            ids = [item for item in load_subject_ids(self._root) if item != subject_id]
            doc_path = self._subject_path(subject_id)
            if doc_path.exists():
                doc_path.unlink()
            shutil.rmtree(paths.subject_dir(self._root, subject_id), ignore_errors=True)
            save_subject_ids(self._root, ids)
        return True

    def _match_shards(self, subject_id: str) -> list[Path]:
        base = paths.subject_dir(self._root, subject_id) / "matches"
        if not base.exists():
            return []
        return sorted(base.glob("*.jsonl"))

    async def upsert_matches(self, matches: Iterable[SubjectMatch]) -> list[SubjectMatch]:
        grouped: dict[Path, list[dict[str, Any]]] = {}
        saved: list[SubjectMatch] = []
        latest_by_subject: dict[str, datetime] = {}
        for match in matches:
            if not match.relevant:
                continue
            shard = paths.subject_match_shard(self._root, match.subject_id, match.matched_at)
            grouped.setdefault(shard, []).append(match.model_dump(mode="json"))
            saved.append(match)
            previous = latest_by_subject.get(match.subject_id)
            if previous is None or match.matched_at > previous:
                latest_by_subject[match.subject_id] = match.matched_at
        for shard, records in grouped.items():
            async with shard_lock(shard):
                upsert(shard, records, key="tweet_id")
        for subject_id, matched_at in latest_by_subject.items():
            await self.touch_subject(subject_id, matched_at)
        return saved

    async def list_matches(
        self,
        subject_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[SubjectMatch]:
        records: list[dict[str, Any]] = []
        for shard in self._match_shards(subject_id):
            records.extend(read_shard(shard))
        matches = [SubjectMatch(**record) for record in records]
        if since is not None:
            since = paths.as_utc(since)
            matches = [match for match in matches if match.matched_at >= since]
        if until is not None:
            until = paths.as_utc(until)
            matches = [match for match in matches if match.matched_at < until]
        matches.sort(key=lambda item: (item.matched_at, item.tweet_id))
        return matches

    async def count_matches(self, subject_id: str) -> int:
        return len(await self.list_matches(subject_id))

    async def last_classified_at(self, subject_id: str) -> datetime | None:
        matches = await self.list_matches(subject_id)
        if not matches:
            return None
        return max(match.matched_at for match in matches)

    async def save_digest(self, digest: SubjectDigest) -> SubjectDigest:
        path = paths.subject_digest_shard(self._root, digest.subject_id, digest.interval_start)
        async with shard_lock(path):
            append_jsonl(path, digest.model_dump(mode="json"))
        await self.touch_subject(digest.subject_id, digest.generated_at)
        return digest

    async def append_feedback(self, feedback: SubjectFeedback) -> SubjectFeedback:
        path = paths.subject_feedback_shard(self._root, feedback.subject_id, feedback.when)
        async with shard_lock(path):
            append_jsonl(path, feedback.model_dump(mode="json"))
        return feedback

    async def append_eval(self, eval_record: SubjectEval) -> SubjectEval:
        path = paths.subject_eval_shard(self._root, eval_record.subject_id, eval_record.when)
        async with shard_lock(path):
            append_jsonl(path, eval_record.model_dump(mode="json"))
        return eval_record

    def _feedback_paths(self, subject_id: str) -> list[Path]:
        base = paths.subject_dir(self._root, subject_id) / "feedback"
        if not base.exists():
            return []
        return sorted(base.glob("*.jsonl"))

    def _eval_paths(self, subject_id: str) -> list[Path]:
        base = paths.subject_dir(self._root, subject_id) / "eval"
        if not base.exists():
            return []
        return sorted(base.glob("*.jsonl"))

    async def read_feedbacks(self, subject_id: str) -> list[SubjectFeedback]:
        feedbacks: list[SubjectFeedback] = []
        for path in self._feedback_paths(subject_id):
            for record in read_shard(path):
                feedbacks.append(SubjectFeedback(**record))
        feedbacks.sort(key=lambda item: (item.when, item.id))
        return feedbacks

    async def read_evals(self, subject_id: str) -> list[SubjectEval]:
        evals: list[SubjectEval] = []
        for path in self._eval_paths(subject_id):
            for record in read_shard(path):
                try:
                    evals.append(SubjectEval(**record))
                except (TypeError, ValueError):
                    continue
        evals.sort(key=lambda item: (item.when, item.id))
        return evals

    def _digest_paths(self, subject_id: str) -> list[Path]:
        base = paths.subject_dir(self._root, subject_id) / "digests"
        if not base.exists():
            return []
        return sorted(base.glob("*.jsonl"), reverse=True)

    async def list_digests(
        self,
        subject_id: str,
        limit: int = 24,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[SubjectDigest]:
        digests: list[SubjectDigest] = []
        for path in self._digest_paths(subject_id):
            for record in read_shard(path):
                digests.append(SubjectDigest(**record))
        if start is not None:
            start = paths.as_utc(start)
            digests = [digest for digest in digests if digest.interval_start >= start]
        if end is not None:
            end = paths.as_utc(end)
            digests = [digest for digest in digests if digest.interval_end <= end]
        digests.sort(key=lambda item: (item.interval_end, item.generated_at), reverse=True)
        return digests[: max(limit, 0)]

    async def get_digest(
        self,
        subject_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> SubjectDigest | None:
        digests = await self.list_digests(subject_id, limit=1, start=start, end=end)
        return digests[0] if digests else None

    async def save_review(self, review: SubjectReview) -> SubjectReview:
        latest_path = paths.subject_review_doc(self._root, review.subject_id)
        history_path = paths.subject_review_history_doc(
            self._root,
            review.subject_id,
            review.version,
        )
        async with shard_lock(latest_path):
            payload = review.model_dump(mode="json")
            atomic_write_doc(latest_path, payload)
            atomic_write_doc(history_path, payload)
        return review

    async def save_provenance(
        self,
        *,
        subject_id: str,
        kind: str,
        key: str,
        provenance: Provenance,
    ) -> Provenance:
        path = paths.subject_provenance_doc(self._root, subject_id, kind, key)
        async with shard_lock(path):
            atomic_write_doc(path, provenance.model_dump(mode="json"))
        return provenance

    async def read_provenance(
        self,
        *,
        subject_id: str,
        kind: str,
        key: str,
    ) -> Provenance | None:
        doc = read_doc(paths.subject_provenance_doc(self._root, subject_id, kind, key))
        return Provenance(**doc) if doc else None

    async def get_review(self, subject_id: str) -> SubjectReview | None:
        doc = read_doc(paths.subject_review_doc(self._root, subject_id))
        return SubjectReview(**doc) if doc else None

    async def list_review_history(self, subject_id: str) -> list[SubjectReview]:
        base = paths.subject_dir(self._root, subject_id) / "review" / "history"
        if not base.exists():
            return []
        reviews: list[SubjectReview] = []
        for path in sorted(base.glob("*.json"), key=lambda item: int(item.stem)):
            doc = read_doc(path)
            if doc:
                reviews.append(SubjectReview(**doc))
        return reviews

    async def get_tweets_by_ids(self, tweet_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        from src.shared.read_cache import load_all_tweets_map, load_summary_map

        wanted = list(dict.fromkeys([tid for tid in tweet_ids if tid]))
        tweet_map = await load_all_tweets_map(self._root)
        summary_map = await load_summary_map(self._root)
        items: list[dict[str, Any]] = []
        missing: list[str] = []
        for tweet_id in wanted:
            tweet = tweet_map.get(tweet_id)
            if tweet is None:
                missing.append(tweet_id)
                continue
            summary = summary_map.get(tweet_id)
            items.append(
                {
                    "tweet_id": tweet.tweet_id,
                    "text": tweet.text,
                    "summary": summary.summary_text if summary else None,
                    "translation": summary.translation_text if summary else None,
                    "author": tweet.author_username,
                    "author_username": tweet.author_username,
                    "created_at": tweet.created_at,
                    "reference_type": tweet.reference_type.value if tweet.reference_type else None,
                    "referenced_tweet_id": tweet.referenced_tweet_id,
                }
            )
        return items, missing

    async def get_tweet_author_ids(
        self,
        tweet_ids: list[str],
    ) -> tuple[dict[str, str | None], list[str]]:
        from src.shared.read_cache import load_all_tweets_map

        wanted = list(dict.fromkeys([tid for tid in tweet_ids if tid]))
        tweet_map = await load_all_tweets_map(self._root)
        author_ids: dict[str, str | None] = {}
        missing: list[str] = []
        for tweet_id in wanted:
            tweet = tweet_map.get(tweet_id)
            if tweet is None:
                missing.append(tweet_id)
                continue
            author_id = getattr(tweet, "author_user_id", None)
            author_ids[tweet_id] = str(author_id) if author_id else None
        return author_ids, missing

    async def publish_window_matches(
        self,
        subject_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> PublishWindowMatches:
        """按推文发布时间圈定候选，供写入校验与 feed 共用。"""
        all_matches = await self.list_matches(subject_id)
        if not all_matches:
            return PublishWindowMatches([], [])

        items, _missing = await self.get_tweets_by_ids([match.tweet_id for match in all_matches])
        created_map: dict[str, datetime] = {}
        for item in items:
            tweet_id = str(item.get("tweet_id") or "")
            created_at = item.get("created_at")
            if tweet_id and created_at is not None:
                created_map[tweet_id] = paths.as_utc(created_at)

        start_utc = paths.as_utc(start) if start is not None else None
        end_utc = paths.as_utc(end) if end is not None else None
        skipped_no_publish_time_ids: list[str] = []
        matches: list[SubjectMatch] = []
        for match in all_matches:
            created_at = created_map.get(match.tweet_id)
            if created_at is None:
                skipped_no_publish_time_ids.append(match.tweet_id)
                continue
            if start_utc is not None and created_at < start_utc:
                continue
            if end_utc is not None and created_at >= end_utc:
                continue
            matches.append(match)

        matches.sort(key=lambda match: (created_map[match.tweet_id], match.tweet_id))
        return PublishWindowMatches(matches, skipped_no_publish_time_ids)

    async def get_subject_feed(
        self,
        subject_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
        time_axis: str = "ingest",
    ) -> dict[str, Any]:
        if await self.get_subject(subject_id) is None:
            return {
                "items": [],
                "count": 0,
                "has_more": False,
                "next_since": None,
                "last_classified_at": None,
            }
        if time_axis not in {"ingest", "publish"}:
            raise ValueError("time_axis 只能是 ingest 或 publish")
        clamped = min(max(limit, 1), 500)
        matches: list[SubjectMatch]
        if time_axis == "publish":
            matches = await self.publish_window_matches(subject_id, start=since, end=until)
        else:
            matches = await self.list_matches(subject_id, since=since, until=until)
        latest_match_at = await self.last_classified_at(subject_id)
        if time_axis == "ingest" and since is not None:
            since_utc = paths.as_utc(since)
            matches = [match for match in matches if match.matched_at > since_utc]
        total = len(matches)
        page = matches[:clamped]
        items, _missing = await self.get_tweets_by_ids([match.tweet_id for match in page])
        order = {match.tweet_id: idx for idx, match in enumerate(page)}
        items.sort(key=lambda item: order.get(item["tweet_id"], NO_LIMIT))
        next_since = page[-1].matched_at.isoformat() if len(page) < total and page else None
        return {
            "items": items,
            "count": len(items),
            "has_more": len(page) < total,
            "next_since": next_since,
            "last_classified_at": latest_match_at.isoformat() if latest_match_at else None,
        }

    async def get_updates(self, since_cursor: str | None = None, limit: int = 200) -> dict[str, Any]:
        since = parse_dt(since_cursor) if since_cursor else utc_now() - timedelta(hours=24)
        updates: list[dict[str, Any]] = []
        active_subjects = await self.list_active_subjects()
        subject_names = {subject.subject_id: subject.name for subject in active_subjects}
        for subject in active_subjects:
            for match in await self.list_matches(subject.subject_id, since=since):
                if match.matched_at <= since:
                    continue
                updates.append(
                    {
                        "subject_id": subject.subject_id,
                        "subject_name": subject.name,
                        "update_type": "match",
                        "updated_at": match.matched_at,
                        "summary": match.reason or "新增相关推文",
                    }
                )
            for digest in await self.list_digests(subject.subject_id, limit=1000):
                if digest.generated_at > since:
                    updates.append(
                        {
                            "subject_id": subject.subject_id,
                            "subject_name": subject_names.get(subject.subject_id, subject.name),
                            "update_type": "digest",
                            "updated_at": digest.generated_at,
                            "summary": digest.digest_text[:120],
                        }
                    )
        updates.sort(key=lambda item: (item["updated_at"], item["subject_id"]))
        clamped = min(max(limit, 1), 500)
        page = updates[:clamped]
        if page and len(updates) > clamped:
            boundary = page[-1]["updated_at"]
            extra = [item for item in updates[clamped:] if item["updated_at"] == boundary]
            page.extend(extra)
        next_cursor = (
            page[-1]["updated_at"].isoformat() if page else (since_cursor or utc_now().isoformat())
        )
        return {
            "updates": page,
            "next_cursor": next_cursor,
            "count": len(page),
            "has_more": len(page) < len(updates),
        }
