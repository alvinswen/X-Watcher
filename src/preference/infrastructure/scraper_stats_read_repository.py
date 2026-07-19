"""scraper_config 账号聚合读门面:tweet 聚合两段(时间范围 / 周期分析)。

复刻 src/preference/api/scraper_config_router.py 三个管理端点对 TweetOrm 的聚合直查,
file 模式下不依赖 ORM,改组合既有 FileTweetStore 在 Python 槽内聚合;sqlalchemy 模式下
薄 wrapper 转调与原端点等价的内联 SQL(SQL 行为零变化)。两侧返回同形态数据,端点据此组装
TweetTimeRangeResponse / FetchAnalysisResponse。

#8 tweet_time_range(per-author min/max/count)+ #9 period_analysis(显式窗口逐周期 count)
无 round 陷阱,SQLite 是有效 oracle。
created_at 比较统一经 paths.as_utc 归一(aware),匹配 file 落盘 +00:00 与 ORM aware 取值。
author 匹配复刻旧 SQL func.lower(author_username) + in_([u.lower()...])(大小写不敏感)。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

from src.storage import paths

class FileScraperStatsReadStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def tweet_time_range(
        self, usernames: list[str]
    ) -> dict[str, tuple[datetime | None, datetime | None, int]]:
        """各用户 (earliest, latest, count)。返回 {username_lower: (min, max, cnt)}。

        复刻旧 SQL group_by(lower(author)) min/max(created_at)/count();无推文的用户不出现
        (端点用 lower 键缺省 None/None/0 兜底)。min/max 按 aware instant 比。
        """
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        if not usernames:
            return {}

        wanted = {u.lower() for u in usernames}
        tweet_store = FileTweetStore(self._root)

        agg: dict[str, tuple[datetime, datetime, int]] = {}
        for username in sorted(wanted):
            tweets = await tweet_store.get_tweets_by_author(username, limit=10_000_000)
            # get_tweets_by_author 已按 lower 精确匹配
            for tw in tweets:
                created = paths.as_utc(tw.created_at)
                if username not in agg:
                    agg[username] = (created, created, 1)
                else:
                    cur_min, cur_max, cnt = agg[username]
                    agg[username] = (
                        created if created < cur_min else cur_min,
                        created if created > cur_max else cur_max,
                        cnt + 1,
                    )
        return {u: (mn, mx, c) for u, (mn, mx, c) in agg.items()}

    async def period_analysis(
        self, username: str, interval_hours: int, periods: int
    ) -> list[tuple[datetime, datetime, int]]:
        """指定用户的显式窗口逐周期 count,正序(最早在前)。

        复刻 #9:period_end = now - i*interval(i=0..periods-1),period_start = period_end - interval,
        count(period_start <= created < period_end);最后 reverse 成正序。
        now 用调用时 datetime.now(UTC),与端点一致。
        """
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        now = datetime.now(UTC)
        interval = timedelta(hours=interval_hours)
        wanted = username.lower()

        tweet_store = FileTweetStore(self._root)
        # 一次取该 author 全部推文(lower 精确匹配),逐周期 Python 计数
        tweets = await tweet_store.get_tweets_by_author(wanted, limit=10_000_000)
        created_list = [paths.as_utc(tw.created_at) for tw in tweets]

        result: list[tuple[datetime, datetime, int]] = []
        for i in range(periods):
            period_end = now - (i * interval)
            period_start = period_end - interval
            count = sum(1 for c in created_list if period_start <= c < period_end)
            result.append((period_start, period_end, count))
        result.reverse()  # 正序(最早在前),复刻端点 period_stats.reverse()
        return result
