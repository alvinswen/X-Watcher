"""AnalyticsService 单元测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.infrastructure.models import TweetOrm
from src.topic.infrastructure.models import TopicAccountOrm, TopicOrm


@pytest.fixture
async def analytics_topic(async_session: AsyncSession):
    """创建测试主题并关联账号。"""
    topic = TopicOrm(name="测试分析主题", user_id=0)
    async_session.add(topic)
    await async_session.flush()

    accounts = [
        TopicAccountOrm(topic_id=topic.id, username="analyst_a"),
        TopicAccountOrm(topic_id=topic.id, username="analyst_b"),
    ]
    for acc in accounts:
        async_session.add(acc)
    await async_session.flush()

    return topic


@pytest.fixture
async def analytics_tweets(async_session: AsyncSession, analytics_topic):
    """创建分布在不同 30 分钟时段的推文。

    以 now 为基准，在不同 slot 中插入推文：
    - slot 0 (now - 5min): 1 条 (analyst_a)
    - slot 1 (now - 35min): 2 条 (analyst_a + analyst_b)
    - slot 3 (now - 95min): 1 条 (analyst_b)
    """
    now = datetime.now(timezone.utc)

    tweets = [
        # slot 0: 当前半小时
        TweetOrm(
            tweet_id="at_1",
            text="Tweet in current slot",
            created_at=now - timedelta(minutes=5),
            db_created_at=now,
            author_username="analyst_a",
            author_display_name="Analyst A",
            media=None,
        ),
        # slot 1: 前一个半小时 (2 条)
        TweetOrm(
            tweet_id="at_2",
            text="Tweet in slot 1 by a",
            created_at=now - timedelta(minutes=35),
            db_created_at=now,
            author_username="analyst_a",
            author_display_name="Analyst A",
            media=None,
        ),
        TweetOrm(
            tweet_id="at_3",
            text="Tweet in slot 1 by b",
            created_at=now - timedelta(minutes=40),
            db_created_at=now,
            author_username="analyst_b",
            author_display_name="Analyst B",
            media=None,
        ),
        # slot 3: 3 个半小时之前 (1 条)
        TweetOrm(
            tweet_id="at_4",
            text="Tweet in slot 3",
            created_at=now - timedelta(minutes=95),
            db_created_at=now,
            author_username="analyst_b",
            author_display_name="Analyst B",
            media=None,
        ),
    ]

    for t in tweets:
        async_session.add(t)
    await async_session.commit()

    return tweets


@pytest.mark.asyncio
async def test_posting_frequency_normal_distribution(
    async_session: AsyncSession, analytics_topic, analytics_tweets
):
    """正常分组：不同 slot 的推文应正确计数。"""
    from src.analytics.services.analytics_service import AnalyticsService

    service = AnalyticsService(async_session)
    result = await service.get_posting_frequency(
        topic_id=analytics_topic.id,
        tz_offset=0,
        slots=50,
    )

    # 应返回 3 个有推文的时段（稀疏表示）
    assert len(result["distribution"]) == 3

    # 总推文数 = 4
    assert result["total_tweets"] == 4

    # 验证 counts：按时间排序，最早的 slot 在前
    counts = [d["count"] for d in result["distribution"]]
    assert sorted(counts, reverse=True) == [2, 1, 1]


@pytest.mark.asyncio
async def test_posting_frequency_empty_topic(async_session: AsyncSession):
    """空主题（无关联账号）应返回空 distribution。"""
    from src.analytics.services.analytics_service import AnalyticsService

    # 创建无账号的主题
    topic = TopicOrm(name="空主题", user_id=0)
    async_session.add(topic)
    await async_session.commit()

    service = AnalyticsService(async_session)
    result = await service.get_posting_frequency(
        topic_id=topic.id,
        tz_offset=0,
        slots=50,
    )

    assert result["distribution"] == []
    assert result["total_tweets"] == 0


@pytest.mark.asyncio
async def test_posting_frequency_no_tweets(
    async_session: AsyncSession, analytics_topic
):
    """有账号但无推文的主题应返回空 distribution。"""
    from src.analytics.services.analytics_service import AnalyticsService

    service = AnalyticsService(async_session)
    result = await service.get_posting_frequency(
        topic_id=analytics_topic.id,
        tz_offset=0,
        slots=50,
    )

    assert result["distribution"] == []
    assert result["total_tweets"] == 0


@pytest.mark.asyncio
async def test_posting_frequency_timezone_offset(
    async_session: AsyncSession, analytics_topic, analytics_tweets
):
    """时区偏移应影响 slot 标签，但不影响总数。"""
    from src.analytics.services.analytics_service import AnalyticsService

    service = AnalyticsService(async_session)

    # UTC 查询
    result_utc = await service.get_posting_frequency(
        topic_id=analytics_topic.id,
        tz_offset=0,
        slots=50,
    )

    # UTC+8 查询 (tz_offset=-480)
    result_cst = await service.get_posting_frequency(
        topic_id=analytics_topic.id,
        tz_offset=-480,
        slots=50,
    )

    # 总数应相同
    assert result_utc["total_tweets"] == result_cst["total_tweets"]

    # slot 标签应不同（偏移了 8 小时）
    utc_slots = [d["slot"] for d in result_utc["distribution"]]
    cst_slots = [d["slot"] for d in result_cst["distribution"]]
    assert utc_slots != cst_slots


@pytest.mark.asyncio
async def test_posting_frequency_case_insensitive(
    async_session: AsyncSession,
):
    """username 大小写不敏感匹配。"""
    from src.analytics.services.analytics_service import AnalyticsService

    now = datetime.now(timezone.utc)

    # topic_account 存大写
    topic = TopicOrm(name="大小写测试", user_id=0)
    async_session.add(topic)
    await async_session.flush()
    acc = TopicAccountOrm(topic_id=topic.id, username="UserA")
    async_session.add(acc)

    # 推文存小写
    tweet = TweetOrm(
        tweet_id="case_t1",
        text="Case test",
        created_at=now - timedelta(minutes=5),
        db_created_at=now,
        author_username="usera",
        author_display_name="User A",
        media=None,
    )
    async_session.add(tweet)
    await async_session.commit()

    service = AnalyticsService(async_session)
    result = await service.get_posting_frequency(
        topic_id=topic.id,
        tz_offset=0,
        slots=50,
    )

    assert result["total_tweets"] == 1
    assert len(result["distribution"]) == 1


@pytest.mark.asyncio
async def test_posting_frequency_custom_slots(
    async_session: AsyncSession, analytics_topic, analytics_tweets
):
    """自定义 slots 数量应限制时间范围。"""
    from src.analytics.services.analytics_service import AnalyticsService

    service = AnalyticsService(async_session)

    # 只看最近 2 个 slot (1小时)，应排除 slot 3 (95min前) 的推文
    result = await service.get_posting_frequency(
        topic_id=analytics_topic.id,
        tz_offset=0,
        slots=2,
    )

    # slot 3 距今 95 分钟，超过 2 * 30 = 60 分钟，应被排除
    assert result["total_tweets"] == 3  # 只有前 3 条推文在范围内


@pytest.mark.asyncio
async def test_posting_frequency_slot_label_format(
    async_session: AsyncSession, analytics_topic, analytics_tweets
):
    """slot 标签应为 'YYYY-MM-DD HH:MM' 格式。"""
    from src.analytics.services.analytics_service import AnalyticsService

    service = AnalyticsService(async_session)
    result = await service.get_posting_frequency(
        topic_id=analytics_topic.id,
        tz_offset=0,
        slots=50,
    )

    import re
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
    for d in result["distribution"]:
        assert pattern.match(d["slot"]), f"slot 标签格式错误: {d['slot']}"

    # 分钟部分应为 00 或 30（30分钟对齐）
    for d in result["distribution"]:
        minutes = int(d["slot"][-2:])
        assert minutes in (0, 30), f"slot 未对齐到 30 分钟: {d['slot']}"
