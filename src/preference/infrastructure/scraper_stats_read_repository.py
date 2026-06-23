"""scraper_config 账号聚合读门面:tweet 聚合三段(period-bucket max / 时间范围 / 周期分析)。

复刻 src/preference/api/scraper_config_router.py 三个管理端点对 TweetOrm 的聚合直查,
file 模式下不依赖 ORM,改组合既有 FileTweetStore 在 Python 槽内聚合;sqlalchemy 模式下
薄 wrapper 转调与原端点等价的内联 SQL(SQL 行为零变化)。两侧返回同形态数据,端点据此组装
FollowStatsResponse / TweetTimeRangeResponse / FetchAnalysisResponse。

⚠️ #7 round 陷阱(本片核心):max_period_counts 的 period_bucket = cast((now-created)/N, Integer)。
生产 PG cast(... AS integer) 是 round-half-up,SQLite 整数除法是 floor——二者对同一边界推文
归入不同 bucket(secs_ago % N >= N/2 时 PG 进位 / SQLite 截断)。file 复刻必须 round-half-up:
bucket = (secs_ago + interval_secs // 2) // interval_secs,不能用 floor `//`。
SQLite 对此操作是失效 oracle(floor≠round 都可能巧合相等),故 file/sqlalchemy 两路均钉死
PG round-half-up:sqlalchemy 路径保留原 cast 表达式(生产 PG 上即 round-half-up),file 路径
用整数式 round-half-up;跨模式测试对 #7 用钉 PG 语义的固定值断言(floor 实现翻红),不靠 SQLite 对账。

#8 tweet_time_range(per-author min/max/count)+ #9 period_analysis(显式窗口逐周期 count)
无 round 陷阱,SQLite 是有效 oracle。
created_at 比较统一经 paths.as_utc 归一(aware),匹配 file 落盘 +00:00 与 ORM aware 取值。
author 匹配复刻旧 SQL func.lower(author_username) + in_([u.lower()...])(大小写不敏感)。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.storage import paths


def _bucket_round_half_up(secs_ago: int, interval_secs: int) -> int:
    """复刻生产 PG cast(secs_ago / interval_secs AS integer) 的 round-half-up 进位。

    secs_ago = now_epoch - created_epoch(>=0,窗口内)。
    整数式 round-half-up(避浮点精度):(secs_ago + interval_secs // 2) // interval_secs。
    ⚠️ 不能用 floor `//`(secs_ago // interval_secs)——那是 SQLite 语义,与生产 PG 不符。
    """
    return (secs_ago + interval_secs // 2) // interval_secs


class FileScraperStatsReadStore:
    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def max_period_counts(
        self, usernames: list[str], interval_hours: int, num_periods: int = 14
    ) -> dict[str, int]:
        """各用户在 [now - num_periods*interval, now) 窗口内,按 period-bucket 分组的最大推文数。

        返回 {username_lower: max_count}(无推文的用户不出现,端点用 .get(lower, 0) 兜底)。
        bucket = round-half-up((now - created) / interval)(复刻 PG cast 进位语义)。
        now 用调用时 datetime.now(UTC),与端点一致(端点每次取 now)。
        """
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        if not usernames:
            return {}

        now = datetime.now(timezone.utc)
        interval = timedelta(hours=interval_hours)
        interval_secs = int(interval.total_seconds())
        cutoff = now - (num_periods * interval)
        now_epoch = int(now.timestamp())

        wanted = {u.lower() for u in usernames}
        tweet_store = FileTweetStore(self._root)

        # (username_lower, bucket) → count
        bucket_counts: dict[tuple[str, int], int] = {}
        for username in sorted(wanted):
            page = 1
            while True:
                p = await tweet_store.get_by_author_range(
                    username, cutoff, now, page=page, page_size=500
                )
                for tw in p.items:
                    created = paths.as_utc(tw.created_at)
                    # 窗口复刻旧 SQL:cutoff <= created < now(get_by_author_range 已半开,稳妥再核)
                    if not (cutoff <= created < now):
                        continue
                    secs_ago = now_epoch - int(created.timestamp())
                    bucket = _bucket_round_half_up(secs_ago, interval_secs)
                    key = (username, bucket)
                    bucket_counts[key] = bucket_counts.get(key, 0) + 1
                if not p.items or page >= p.total_pages:
                    break
                page += 1

        max_map: dict[str, int] = {}
        for (username_lower, _bucket), cnt in bucket_counts.items():
            if username_lower not in max_map or cnt > max_map[username_lower]:
                max_map[username_lower] = cnt
        return max_map

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

        now = datetime.now(timezone.utc)
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


class SqlalchemyScraperStatsReadStore:
    """sqlalchemy 模式 scraper 账号聚合门面:转调与原端点等价的内联 SQL(SQL 行为零变化)。

    把原三个端点内联的 tweet 聚合段原样搬进本 wrapper(同 cast/lower/group_by/window),
    使端点改走 provider 后 sqlalchemy 路径产同结果。⚠️ max_period_counts 保留原 cast 表达式
    (生产 PG 上即 round-half-up),不改写为整数式——sqlalchemy 路径的 round 语义随底层 dialect。
    """

    def __init__(self, session) -> None:
        self._session = session

    async def max_period_counts(
        self, usernames: list[str], interval_hours: int, num_periods: int = 14
    ) -> dict[str, int]:
        from sqlalchemy import Integer, cast, func, select

        from src.database.dialect import sql_epoch
        from src.scraper.infrastructure.models import TweetOrm

        if not usernames:
            return {}

        session = self._session
        now = datetime.now(timezone.utc)
        interval = timedelta(hours=interval_hours)
        cutoff = now - (num_periods * interval)
        interval_secs = int(interval.total_seconds())
        now_epoch = int(now.timestamp())

        # period_bucket = cast((now - created_at) / interval_secs, Integer)
        # 生产 PG 上 cast(... AS integer) = round-half-up;SQLite = floor(失效 oracle,见模块 docstring)
        bucket_expr = cast(
            (now_epoch - sql_epoch(TweetOrm.created_at, bind=session)) / interval_secs,
            Integer,
        )
        stmt = (
            select(
                func.lower(TweetOrm.author_username).label("username_lower"),
                func.count().label("cnt"),
            )
            .where(
                func.lower(TweetOrm.author_username).in_([u.lower() for u in usernames]),
                TweetOrm.created_at >= cutoff,
                TweetOrm.created_at < now,
            )
            .group_by(func.lower(TweetOrm.author_username), bucket_expr)
        )
        result = await session.execute(stmt)
        rows = result.all()

        max_map: dict[str, int] = {}
        for username_val, cnt in rows:
            if username_val not in max_map or cnt > max_map[username_val]:
                max_map[username_val] = cnt
        return max_map

    async def tweet_time_range(
        self, usernames: list[str]
    ) -> dict[str, tuple[datetime | None, datetime | None, int]]:
        from sqlalchemy import func, select

        from src.scraper.infrastructure.models import TweetOrm

        if not usernames:
            return {}

        session = self._session
        lower_usernames = [u.lower() for u in usernames]
        stmt = (
            select(
                func.lower(TweetOrm.author_username).label("username_lower"),
                func.min(TweetOrm.created_at).label("earliest"),
                func.max(TweetOrm.created_at).label("latest"),
                func.count().label("cnt"),
            )
            .where(func.lower(TweetOrm.author_username).in_(lower_usernames))
            .group_by(func.lower(TweetOrm.author_username))
        )
        result = await session.execute(stmt)
        return {r[0]: (r[1], r[2], r[3]) for r in result.all()}

    async def period_analysis(
        self, username: str, interval_hours: int, periods: int
    ) -> list[tuple[datetime, datetime, int]]:
        from sqlalchemy import func, select

        from src.scraper.infrastructure.models import TweetOrm

        session = self._session
        now = datetime.now(timezone.utc)
        interval = timedelta(hours=interval_hours)

        result: list[tuple[datetime, datetime, int]] = []
        for i in range(periods):
            period_end = now - (i * interval)
            period_start = period_end - interval
            stmt = (
                select(func.count())
                .select_from(TweetOrm)
                .where(
                    func.lower(TweetOrm.author_username) == username.lower(),
                    TweetOrm.created_at >= period_start,
                    TweetOrm.created_at < period_end,
                )
            )
            r = await session.execute(stmt)
            count = r.scalar() or 0
            result.append((period_start, period_end, count))
        result.reverse()  # 正序(最早在前)
        return result
