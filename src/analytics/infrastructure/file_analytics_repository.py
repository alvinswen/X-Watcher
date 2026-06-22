"""文件版 analytics 读门面:posting_frequency 30 分钟槽聚合。

复刻 src/analytics/services/analytics_service.py 的 SQL 槽聚合(dialect epoch//1800 +
-tz_offset 偏移 + UTC 标签),组合 FileTopicStore(取账号)+ FileTweetStore(per-account
翻页取窗内推文)。无 summary 联结(本聚合只需 tweet)。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


class FileAnalyticsStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def get_posting_frequency(
        self, topic_id: int, tz_offset: int = 0, slots: int = 50
    ) -> dict:
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        from src.topic.infrastructure.file_topic_repository import FileTopicStore

        accounts = await FileTopicStore(self._root).get_accounts(topic_id)
        usernames = [a.username for a in accounts]

        now_utc = datetime.now(timezone.utc)
        start_utc = now_utc - timedelta(minutes=slots * 30)

        if not usernames:
            return {
                "distribution": [],
                "total_tweets": 0,
                "time_range_start": start_utc,
                "time_range_end": now_utc,
            }

        tweet_store = FileTweetStore(self._root)
        in_window = []
        for username in sorted({u.lower() for u in usernames}):
            page = 1
            while True:
                p = await tweet_store.get_by_author_range(
                    username, start_utc, now_utc, page=page, page_size=500
                )
                in_window.extend(p.items)
                if not p.items or page >= p.total_pages:
                    break
                page += 1

        counter: Counter[str] = Counter()
        for tw in in_window:
            created = tw.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            local_epoch = int((created + timedelta(minutes=-tz_offset)).timestamp())
            slot_ts = (local_epoch // 1800) * 1800
            label = datetime.fromtimestamp(slot_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            counter[label] += 1

        distribution = [{"slot": s, "count": counter[s]} for s in sorted(counter)]
        return {
            "distribution": distribution,
            "total_tweets": sum(d["count"] for d in distribution),
            "time_range_start": start_utc,
            "time_range_end": now_utc,
        }
