"""文件版 status 统计读门面:4 个 count/max/today-count/反连接 聚合统计。

复刻旧 status 概览端点的 4 段聚合(`src/api/routes/status.py` 的 `_get_*_stats`),
file 模式下不依赖 ORM count,改组合既有 file store 在 Python 槽内计数:
- get_tweet_stats:get_all_tweets → total / max(created_at,aware) / today_count(UTC 午夜起)。
- get_follow_stats:get_all_follows(include_inactive=True) → total / active(is_active) / inactive。
- get_summary_stats:get_all_summaries → total;pending = 反连接 count
  (全 tweet_id − 有 summary 的 tweet_id 集合),复刻旧 LEFT JOIN ... IS NULL count。
- get_topic_stats:list_all → topic total;最近一条 task(created_at DESC,任意状态)取
  completed_at + status,复刻旧 `order_by(created_at.desc()).limit(1)`。

⚠️ 无 round 陷阱豁免:本片全是 count/max/today-count,无除法分桶,SQLite 是有效 oracle。
created_at 比较统一经 as_utc 归一(file 落盘 aware +00:00;比较安全),返回值保 aware datetime
匹配旧 ORM(TweetOrm.from_orm 补 tzinfo=UTC)。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.storage import paths

# 注:status 统计模型(TweetStats/FollowStats/SummaryStats/TopicStats)在方法内延迟 import,
# 因 src.api.routes.status 顶层 import src.main → 模块加载期回引 status.router 形成循环;
# provider 延迟 import 本门面,故方法内再延迟 import 模型即可避环(承本仓 lazy import 纪律)。


class FileStatusReadStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def get_tweet_stats(self):
        from src.api.routes.status import TweetStats
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        tweets = await FileTweetStore(self._root).get_all_tweets()
        total = len(tweets)

        # max(created_at):aware 比较,空集 → None(镜像 func.max 空表返 NULL)
        latest = None
        if tweets:
            latest = max(paths.as_utc(t.created_at) for t in tweets)

        # today_count:created_at >= 今日 UTC 午夜(复刻旧 datetime.now(UTC).replace(hour=0...))
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_count = sum(
            1 for t in tweets if paths.as_utc(t.created_at) >= today_start
        )

        return TweetStats(
            total=total,
            latest_tweet_at=latest,
            today_count=today_count,
        )

    async def get_follow_stats(self):
        from src.api.routes.status import FollowStats
        from src.data_layer.provider import get_follows_repo

        # 源无 is_active 过滤=全部 → include_inactive=True;active 在 Python 槽数
        follows = await get_follows_repo().get_all_follows(include_inactive=True)
        total = len(follows)
        active = sum(1 for f in follows if f.is_active)
        return FollowStats(total=total, active=active, inactive=total - active)

    async def get_summary_stats(self):
        from src.api.routes.status import SummaryStats
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

        summaries = await FileSummaryStore(self._root).get_all_summaries()
        total = len(summaries)

        # 反连接 count:全 tweet_id − 有 summary 的 tweet_id 集合(复刻 LEFT JOIN ... IS NULL count)
        # get_unsummarized_tweets 把 limit 钳到 ≤200 不能取全量计数,故直接集合差计数。
        summarized_ids = {s.tweet_id for s in summaries}
        tweets = await FileTweetStore(self._root).get_all_tweets()
        pending_tweets = sum(1 for t in tweets if t.tweet_id not in summarized_ids)

        return SummaryStats(total=total, pending_tweets=pending_tweets)

    async def get_topic_stats(self):
        from src.api.routes.status import TopicStats
        from src.data_layer.provider import get_topic_store, get_topic_summary_task_store

        topics = await get_topic_store().list_all()
        total = len(topics)

        # 最近一条 task(created_at DESC,任意状态;list_tasks 已按 created_at DESC 排序)
        tasks = await get_topic_summary_task_store().list_tasks()
        latest = tasks[0] if tasks else None
        latest_summary_at = latest.completed_at if latest else None
        latest_summary_status = latest.status.value if latest else None

        return TopicStats(
            total=total,
            latest_summary_at=latest_summary_at,
            latest_summary_status=latest_summary_status,
        )


class SqlalchemyStatusReadStore:
    """sqlalchemy 模式薄 wrapper:转调旧 `_get_*_stats(session)`,SQL 字节零变化。

    保持旧 status route 的 ORM count/max/反连接查询逐字不动 → 零行为变化;
    仅把 4 段统一收到一个门面对象,使 3 个 status 消费者改走 provider。
    """

    def __init__(self, session) -> None:
        self._session = session

    async def get_tweet_stats(self):
        from src.api.routes.status import _get_tweet_stats

        return await _get_tweet_stats(self._session)

    async def get_follow_stats(self):
        from src.api.routes.status import _get_follow_stats

        return await _get_follow_stats(self._session)

    async def get_summary_stats(self):
        from src.api.routes.status import _get_summary_stats

        return await _get_summary_stats(self._session)

    async def get_topic_stats(self):
        from src.api.routes.status import _get_topic_stats

        return await _get_topic_stats(self._session)
