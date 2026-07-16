"""Subject L1 滚动新闻服务壳。

A1 阶段已移除服务端生成与 rollup 链路；历史 digest 仍由 store 读接口提供。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.data_layer.provider import get_subject_repo
from src.storage import paths
from src.subjects.constants import SUBJECT_NOT_FOUND
from src.subjects.models import SubjectDigest, SubjectHighlight
from src.subjects.provenance import assemble_provenance, build_digest_provenance_key
from src.subjects.store import utc_now

MAX_DIGEST_TEXT = 4000


class SubjectDigestService:
    """保留服务壳，待 A2/B 通过外部技能回写产物。"""

    def __init__(self, repo: Any | None = None) -> None:
        repo_factory = get_subject_repo
        self._repo: Any = repo if repo is not None else repo_factory()

    async def write_digest(
        self,
        *,
        subject_id: str,
        interval_start: datetime,
        interval_end: datetime,
        time_axis: str = "ingest",
        digest_text: str,
        highlights: list[SubjectHighlight] | None = None,
        cited_tweet_ids: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if await self._repo.get_subject(subject_id) is None:
            raise LookupError(SUBJECT_NOT_FOUND)
        start = paths.as_utc(interval_start)
        end = paths.as_utc(interval_end)
        if start > end:
            raise ValueError("区间非法: interval_start 必须小于等于 interval_end")
        if time_axis not in {"ingest", "publish"}:
            raise ValueError("time_axis 只能是 ingest 或 publish")
        text = digest_text.strip()
        if not text:
            raise ValueError("digest_text 不能为空")
        if len(text) > MAX_DIGEST_TEXT:
            raise ValueError("digest_text 超过 4000 字上限")

        skipped_no_publish_time_ids: list[str] = []
        if time_axis == "publish":
            matches = await self._repo.publish_window_matches(
                subject_id,
                start=start,
                end=end,
            )
            skipped_no_publish_time_ids = list(getattr(matches, "skipped_no_publish_time_ids", []))
        else:
            matches = await self._repo.list_matches(subject_id, since=start, until=end)
        allowed_ids = {match.tweet_id for match in matches}
        stored_highlights = highlights or []
        cited = list(dict.fromkeys(cited_tweet_ids or []))
        highlight_cited = [
            tweet_id for highlight in stored_highlights for tweet_id in highlight.cited_tweet_ids
        ]
        missing_cited = [
            tweet_id
            for tweet_id in list(dict.fromkeys(cited + highlight_cited))
            if tweet_id not in allowed_ids
        ]
        if missing_cited:
            raise ValueError(f"cited_tweet_ids 越出本区间命中: {missing_cited}")

        now = utc_now()
        prov = (
            assemble_provenance(
                raw=provenance,
                recomputed_ids=[match.tweet_id for match in matches],
                generated_at=now,
            )
            if provenance is not None
            else None
        )
        digest = SubjectDigest(
            subject_id=subject_id,
            interval_start=start,
            interval_end=end,
            time_axis=time_axis,
            tweet_count=len(matches),
            digest_text=text,
            highlights=stored_highlights,
            cited_tweet_ids=cited,
            generated_at=now,
        )
        await self._repo.save_digest(digest)
        data: dict[str, Any] = {
            "subject_id": subject_id,
            "interval_start": start.isoformat(),
            "interval_end": end.isoformat(),
            "skipped_no_publish_time": len(skipped_no_publish_time_ids),
        }
        if skipped_no_publish_time_ids:
            data["skipped_no_publish_time_ids"] = skipped_no_publish_time_ids
        if prov is not None:
            key = build_digest_provenance_key(start, time_axis, now)
            try:
                await self._repo.save_provenance(
                    subject_id=subject_id,
                    kind="digests",
                    key=key,
                    provenance=prov,
                )
                data["provenance_written"] = True
                data["provenance_key"] = key
            except OSError:
                data["provenance_written"] = False
        return data
