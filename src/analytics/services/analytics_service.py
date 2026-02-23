"""统计分析查询服务。"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.infrastructure.models import TweetOrm
from src.topic.infrastructure.models import TopicAccountOrm

logger = logging.getLogger(__name__)


class AnalyticsService:
    """统计分析查询服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_posting_frequency(
        self,
        topic_id: int,
        tz_offset: int = 0,
        slots: int = 50,
    ) -> dict:
        """获取主题下所有关联账号在最近 N 个半小时时段的发文频次分布。

        Args:
            topic_id: 主题 ID
            tz_offset: JS getTimezoneOffset() 值（分钟），UTC+8 为 -480
            slots: 返回多少个半小时时段，默认 50

        Returns:
            包含 distribution（稀疏时段列表）和 total_tweets 的字典
        """
        # 1. 获取主题关联的账号列表
        stmt = select(TopicAccountOrm.username).where(
            TopicAccountOrm.topic_id == topic_id
        )
        result = await self._session.execute(stmt)
        usernames = [row[0] for row in result.fetchall()]

        now_utc = datetime.now(timezone.utc)
        total_minutes = slots * 30
        start_utc = now_utc - timedelta(minutes=total_minutes)

        # 2. 无关联账号时直接返回空结果
        if not usernames:
            return {
                "distribution": [],
                "total_tweets": 0,
                "time_range_start": start_utc,
                "time_range_end": now_utc,
            }

        # 3. 构建 30 分钟分组的 SQL 聚合
        # tz_offset 来自 JS getTimezoneOffset()，含义为 UTC - local
        # local = UTC + (-tz_offset) minutes
        offset_modifier = f"{-tz_offset} minutes"

        # strftime('%s', ...) → Unix 时间戳(字符串)
        # cast 为整数 → 整除 1800（截断为整数）再乘回 → slot 起始时间戳
        local_ts = func.strftime("%s", TweetOrm.created_at, offset_modifier)
        # 显式 cast 除法结果为 Integer 以确保截断（SQLAlchemy 的 / 会生成浮点除法）
        slot_ts = cast(cast(local_ts, Integer) / 1800, Integer) * 1800
        slot_label = func.strftime("%Y-%m-%d %H:%M", slot_ts, "unixepoch")

        stmt = (
            select(
                slot_label.label("slot"),
                func.count().label("count"),
            )
            .where(
                func.lower(TweetOrm.author_username).in_(
                    [u.lower() for u in usernames]
                ),
                TweetOrm.created_at >= start_utc,
                TweetOrm.created_at < now_utc,
            )
            .group_by(slot_label)
            .order_by(slot_label)
        )

        result = await self._session.execute(stmt)
        rows = result.fetchall()

        distribution = [{"slot": row.slot, "count": row.count} for row in rows]
        total_tweets = sum(d["count"] for d in distribution)

        logger.info(
            "发文频次查询完成: topic_id=%d, slots=%d, 有推文时段=%d, 总数=%d",
            topic_id,
            slots,
            len(distribution),
            total_tweets,
        )

        return {
            "distribution": distribution,
            "total_tweets": total_tweets,
            "time_range_start": start_utc,
            "time_range_end": now_utc,
        }
