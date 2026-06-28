"""文件层 SubjectStore。

盘面：
- subjects/index.json: {"subject_ids": [...]}
- subjects/{subject_id}.json: Subject
- subjects/{subject_id}/matches/{YYYY-MM}.jsonl: SubjectMatch
- subjects/{subject_id}/digests/{YYYY-MM-DD-HH}.json: SubjectDigest
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from src.storage import paths
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc
from src.storage.jsonl_store import read_shard, upsert
from src.subjects.index import load_subject_ids, new_subject_id, save_subject_ids
from src.subjects.models import Subject, SubjectDigest, SubjectMatch, SubjectReview, SubjectStatus

_NO_LIMIT = 10**12


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return paths.as_utc(value)
    return paths.as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def hour_bucket(dt: datetime) -> str:
    return paths.as_utc(dt).strftime("%Y-%m-%d-%H")


def hour_window(hour: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(hour, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    return start, start + timedelta(hours=1)


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
        )
        async with shard_lock(paths.subject_index(self._root)):
            ids = load_subject_ids(self._root)
            ids.append(subject.subject_id)
            atomic_write_doc(self._subject_path(subject.subject_id), subject.model_dump(mode="json"))
            save_subject_ids(self._root, ids)
        return subject

    async def save_subject(self, subject: Subject) -> Subject:
        updated = subject.model_copy(update={"updated_at": utc_now()})
        async with shard_lock(self._subject_path(updated.subject_id)):
            atomic_write_doc(self._subject_path(updated.subject_id), updated.model_dump(mode="json"))
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
        changes: dict = {}
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

    async def delete_subject(self, subject_id: str) -> bool:
        subject = await self.get_subject(subject_id)
        if subject is None:
            return False
        async with shard_lock(paths.subject_index(self._root)):
            ids = [item for item in load_subject_ids(self._root) if item != subject_id]
            doc_path = self._subject_path(subject_id)
            if doc_path.exists():
                doc_path.unlink()
            shutil.rmtree(self._root / "subjects" / subject_id, ignore_errors=True)
            save_subject_ids(self._root, ids)
        return True

    def _match_shards(self, subject_id: str) -> list[Path]:
        base = self._root / "subjects" / subject_id / "matches"
        if not base.exists():
            return []
        return sorted(base.glob("*.jsonl"))

    async def upsert_matches(self, matches: Iterable[SubjectMatch]) -> list[SubjectMatch]:
        grouped: dict[Path, list[dict]] = {}
        saved: list[SubjectMatch] = []
        for match in matches:
            if not match.relevant:
                continue
            shard = paths.subject_match_shard(self._root, match.subject_id, match.matched_at)
            grouped.setdefault(shard, []).append(match.model_dump(mode="json"))
            saved.append(match)
        for shard, records in grouped.items():
            async with shard_lock(shard):
                upsert(shard, records, key="tweet_id")
        for match in saved:
            await self.touch_subject(match.subject_id, match.matched_at)
        return saved

    async def list_matches(
        self,
        subject_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[SubjectMatch]:
        records: list[dict] = []
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

    async def match_hours_for_tweets(self, tweet_ids: list[str]) -> set[tuple[str, str]]:
        wanted = set(tweet_ids)
        affected: set[tuple[str, str]] = set()
        for subject in await self.list_subjects():
            for match in await self.list_matches(subject.subject_id):
                if match.tweet_id in wanted:
                    affected.add((match.subject_id, hour_bucket(match.matched_at)))
        return affected

    async def save_digest(self, digest: SubjectDigest) -> SubjectDigest:
        path = paths.subject_digest_doc(self._root, digest.subject_id, digest.hour)
        async with shard_lock(path):
            atomic_write_doc(path, digest.model_dump(mode="json"))
        await self.touch_subject(digest.subject_id, digest.generated_at)
        return digest

    def _digest_paths(self, subject_id: str) -> list[Path]:
        base = self._root / "subjects" / subject_id / "digests"
        if not base.exists():
            return []
        return sorted(base.glob("*.json"), reverse=True)

    async def list_digests(self, subject_id: str, limit: int = 24) -> list[SubjectDigest]:
        digests: list[SubjectDigest] = []
        for path in self._digest_paths(subject_id):
            doc = read_doc(path)
            if doc:
                digests.append(SubjectDigest(**doc))
        digests.sort(key=lambda item: item.hour, reverse=True)
        return digests[: max(limit, 0)]

    async def get_digest(self, subject_id: str, hour: str | None = None) -> SubjectDigest | None:
        if hour is not None:
            doc = read_doc(paths.subject_digest_doc(self._root, subject_id, hour))
            return SubjectDigest(**doc) if doc else None
        digests = await self.list_digests(subject_id, limit=1)
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

    async def get_review(self, subject_id: str) -> SubjectReview | None:
        doc = read_doc(paths.subject_review_doc(self._root, subject_id))
        return SubjectReview(**doc) if doc else None

    async def list_review_history(self, subject_id: str) -> list[SubjectReview]:
        base = self._root / "subjects" / subject_id / "review" / "history"
        if not base.exists():
            return []
        reviews: list[SubjectReview] = []
        for path in sorted(base.glob("*.json"), key=lambda item: int(item.stem)):
            doc = read_doc(path)
            if doc:
                reviews.append(SubjectReview(**doc))
        return reviews

    async def get_tweets_by_ids(self, tweet_ids: list[str]) -> tuple[list[dict], list[str]]:
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

        wanted = list(dict.fromkeys([tid for tid in tweet_ids if tid]))
        tweet_map = {tweet.tweet_id: tweet for tweet in await FileTweetStore(self._root).get_all_tweets()}
        summary_map = {
            summary.tweet_id: summary
            for summary in await FileSummaryStore(self._root).get_all_summaries()
        }
        items: list[dict] = []
        missing: list[str] = []
        for tweet_id in wanted:
            tweet = tweet_map.get(tweet_id)
            if tweet is None:
                missing.append(tweet_id)
                continue
            summary = summary_map.get(tweet_id)
            items.append({
                "tweet_id": tweet.tweet_id,
                "text": tweet.text,
                "summary": summary.summary_text if summary else None,
                "translation": summary.translation_text if summary else None,
                "author": tweet.author_username,
                "author_username": tweet.author_username,
                "created_at": tweet.created_at,
                "reference_type": tweet.reference_type.value if tweet.reference_type else None,
                "referenced_tweet_id": tweet.referenced_tweet_id,
            })
        return items, missing

    async def get_subject_feed(
        self,
        subject_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
    ) -> dict:
        if await self.get_subject(subject_id) is None:
            return {"items": [], "count": 0, "has_more": False, "next_since": None}
        clamped = min(max(limit, 1), 500)
        matches = await self.list_matches(subject_id, since=since, until=until)
        if since is not None:
            since_utc = paths.as_utc(since)
            matches = [match for match in matches if match.matched_at > since_utc]
        total = len(matches)
        page = matches[:clamped]
        items, _missing = await self.get_tweets_by_ids([match.tweet_id for match in page])
        order = {match.tweet_id: idx for idx, match in enumerate(page)}
        items.sort(key=lambda item: order.get(item["tweet_id"], _NO_LIMIT))
        next_since = page[-1].matched_at.isoformat() if len(page) < total and page else None
        return {
            "items": items,
            "count": len(items),
            "has_more": len(page) < total,
            "next_since": next_since,
        }

    async def get_updates(self, since_cursor: str | None = None, limit: int = 200) -> dict:
        since = parse_dt(since_cursor) if since_cursor else utc_now() - timedelta(hours=24)
        updates: list[dict] = []
        active_subjects = await self.list_active_subjects()
        subject_names = {subject.subject_id: subject.name for subject in active_subjects}
        for subject in active_subjects:
            for match in await self.list_matches(subject.subject_id, since=since):
                if match.matched_at <= since:
                    continue
                updates.append({
                    "subject_id": subject.subject_id,
                    "subject_name": subject.name,
                    "update_type": "match",
                    "updated_at": match.matched_at,
                    "summary": match.reason or "新增相关推文",
                })
            for digest in await self.list_digests(subject.subject_id, limit=1000):
                if digest.generated_at > since:
                    updates.append({
                        "subject_id": subject.subject_id,
                        "subject_name": subject_names.get(subject.subject_id, subject.name),
                        "update_type": "digest",
                        "updated_at": digest.generated_at,
                        "summary": digest.digest_text[:120],
                    })
        updates.sort(key=lambda item: (item["updated_at"], item["subject_id"]))
        clamped = min(max(limit, 1), 500)
        page = updates[:clamped]
        if page and len(updates) > clamped:
            boundary = page[-1]["updated_at"]
            extra = [item for item in updates[clamped:] if item["updated_at"] == boundary]
            page.extend(extra)
        next_cursor = (
            page[-1]["updated_at"].isoformat()
            if page
            else (since_cursor or utc_now().isoformat())
        )
        return {
            "updates": page,
            "next_cursor": next_cursor,
            "count": len(page),
            "has_more": len(page) < len(updates),
        }
