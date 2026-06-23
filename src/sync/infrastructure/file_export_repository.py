# src/sync/infrastructure/file_export_repository.py
"""文件版 Export 门面:组合 7 个已迁 File*Store,产 serializers 同构的序列化 dict。

候选契约 = 旧 ExportRepository 6 读方法的「序列化输出」重表达(ORM 列表 → list[dict]/dict|None);
parity store 额外暴露 seed_*(委派各底层 store 的 seed/save)供 case 播种。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.preference.infrastructure.file_schedule_repository import FileScheduleStore
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.scraper.infrastructure.file_article_repository import FileArticleStore
from src.topic.infrastructure.file_topic_repository import FileTopicStore
from src.topic.infrastructure.file_topic_summary_task_repository import FileTopicSummaryTaskStore
from src.sync.infrastructure import export_serializers as S


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class FileExportStore:
    def __init__(self, data_root: Path) -> None:
        root = Path(data_root)
        self._follows = FileFollowStore(root)
        self._schedule = FileScheduleStore(root)
        self._tweets = FileTweetStore(root)
        self._summaries = FileSummaryStore(root)
        self._articles = FileArticleStore(root)
        self._topics = FileTopicStore(root)
        self._tasks = FileTopicSummaryTaskStore(root)

    # ── seed(parity 播种,委派底层 store)──
    async def seed_follows(self, follows):
        await self._follows.seed(follows)

    async def seed_schedule(self, config):
        await self._schedule.seed(config)

    async def seed_tweets(self, tweets):
        await self._tweets.save_tweets(tweets, early_stop_threshold=0)

    async def seed_summaries(self, records):
        await self._summaries.seed(records)

    async def seed_articles(self, articles):
        await self._articles.seed(articles)

    async def seed_topics(self, topics, accounts=None, tasks=None, summaries=None):
        # topics/tasks/summaries 写四集合(accounts 被置空),随后逐 topic 回填 accounts
        await self._tasks.seed(topics, tasks=tasks or [], summaries=summaries or [])
        for topic_id, usernames in (accounts or {}).items():
            await self._topics.replace_accounts(topic_id, list(usernames))

    # ── export(6 读,序列化 dict)──
    async def export_follows(self) -> list[dict]:
        follows = await self._follows.get_all_follows(include_inactive=True)
        return [S.follow_to_export_dict(f) for f in follows]

    async def export_schedule_config(self) -> dict | None:
        c = await self._schedule.get_schedule_config()
        return S.schedule_to_export_dict(c) if c is not None else None

    async def export_tweets(self, since=None, until=None, authors=None) -> list[dict]:
        tweets = await self._tweets.get_all_tweets()
        authors_set = set(authors) if authors else None
        out = []
        for t in tweets:
            ts = _as_utc(t.created_at)
            if since is not None and ts < _as_utc(since):
                continue
            if until is not None and ts > _as_utc(until):   # until 闭区间(≡ 旧 <=)
                continue
            if authors_set is not None and t.author_username not in authors_set:
                continue
            out.append(S.tweet_to_export_dict(t))
        return out

    async def export_summaries(self, tweet_ids=None) -> list[dict]:
        summaries = await self._summaries.get_all_summaries()
        if tweet_ids is not None:
            wanted = set(tweet_ids)
            summaries = [s for s in summaries if s.tweet_id in wanted]
        return [S.summary_to_export_dict(s) for s in summaries]

    async def export_articles(self, tweet_ids=None) -> list[dict]:
        articles = await self._articles.get_all_articles()
        if tweet_ids is not None:
            wanted = set(tweet_ids)
            articles = [a for a in articles if a.tweet_id in wanted]
        return [S.article_to_export_dict(a) for a in articles]

    async def export_topics(self) -> list[dict]:
        topics = await self._topics.list_all()
        out = []
        for t in topics:
            accounts = [a.username for a in await self._topics.get_accounts(t.id)]
            tasks = await self._tasks.list_tasks(topic_id=t.id)
            out.append(S.topic_to_export_dict(t.name, t.description, accounts, tasks))
        return out
