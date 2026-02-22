"""特征工程：构建 24 维小时分布向量。"""

import numpy as np
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.domain.models import AccountDistribution
from src.scraper.infrastructure.models import TweetOrm


EPSILON = 1e-10


async def build_hourly_distributions(
    session: AsyncSession,
    usernames: list[str],
    min_tweets: int = 20,
) -> tuple[list[AccountDistribution], list[str]]:
    """构建每个账号的 24 维小时分布向量。

    Args:
        session: 数据库会话
        usernames: 要分析的账号用户名列表
        min_tweets: 最小推文数阈值

    Returns:
        tuple: (有效分布列表, 因数据不足被排除的用户名列表)
    """
    distributions: list[AccountDistribution] = []
    excluded: list[str] = []

    for username in usernames:
        # 用 strftime 提取小时（SQLite），func.lower 做大小写不敏感匹配
        hour_expr = cast(func.strftime("%H", TweetOrm.created_at), Integer)
        stmt = (
            select(hour_expr.label("hour"), func.count().label("count"))
            .where(func.lower(TweetOrm.author_username) == username.lower())
            .group_by(hour_expr)
        )
        result = await session.execute(stmt)
        rows = result.fetchall()

        # 构建 24 维计数向量
        counts = np.zeros(24, dtype=np.float64)
        for row in rows:
            counts[row.hour] = row.count

        total = int(counts.sum())
        if total < min_tweets:
            excluded.append(username)
            continue

        # 归一化为概率分布 + Laplace 平滑
        distribution = (counts + EPSILON) / (total + 24 * EPSILON)

        distributions.append(
            AccountDistribution(
                username=username,
                distribution=distribution.tolist(),
                tweet_count=total,
            )
        )

    return distributions, excluded
