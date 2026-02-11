"""批量去重和提前终止测试。

测试 TweetRepository 的 batch_check_exists、
批量去重的 save_tweets 以及 Early Termination 逻辑。
"""

from datetime import datetime, timezone

import pytest

from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.models import TweetOrm
from src.scraper.infrastructure.repository import TweetRepository


def _make_tweet(tweet_id: str, text: str = "test tweet") -> Tweet:
    """创建测试用 Tweet。"""
    return Tweet(
        tweet_id=tweet_id,
        text=text,
        created_at=datetime.now(timezone.utc),
        author_username="testuser",
    )


@pytest.mark.asyncio
class TestBatchCheckExists:
    """测试 batch_check_exists 方法。"""

    async def test_empty_list(self, async_session):
        """空列表返回空集合。"""
        repo = TweetRepository(async_session)
        result = await repo.batch_check_exists([])
        assert result == set()

    async def test_none_exist(self, async_session):
        """数据库为空时全部不存在。"""
        repo = TweetRepository(async_session)
        result = await repo.batch_check_exists(["id1", "id2", "id3"])
        assert result == set()

    async def test_all_exist(self, async_session):
        """全部存在的情况。"""
        repo = TweetRepository(async_session)

        # 预先插入推文
        for tid in ["id1", "id2", "id3"]:
            tweet = _make_tweet(tid)
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        result = await repo.batch_check_exists(["id1", "id2", "id3"])
        assert result == {"id1", "id2", "id3"}

    async def test_partial_exist(self, async_session):
        """部分存在的情况。"""
        repo = TweetRepository(async_session)

        # 只插入 id1 和 id3
        for tid in ["id1", "id3"]:
            tweet = _make_tweet(tid)
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        result = await repo.batch_check_exists(["id1", "id2", "id3"])
        assert result == {"id1", "id3"}


@pytest.mark.asyncio
class TestSaveTweetsWithBatchDedup:
    """测试 save_tweets 的批量去重功能。"""

    async def test_all_new(self, async_session):
        """所有推文都是新的。"""
        repo = TweetRepository(async_session)
        tweets = [_make_tweet(f"new_{i}") for i in range(5)]

        result = await repo.save_tweets(tweets, early_stop_threshold=0)
        assert result.success_count == 5
        assert result.skipped_count == 0

    async def test_all_existing(self, async_session):
        """所有推文都已存在。"""
        repo = TweetRepository(async_session)

        # 预先插入
        for i in range(5):
            tweet = _make_tweet(f"existing_{i}")
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        tweets = [_make_tweet(f"existing_{i}") for i in range(5)]
        result = await repo.save_tweets(tweets, early_stop_threshold=0)
        assert result.success_count == 0
        assert result.skipped_count == 5

    async def test_mixed_new_and_existing(self, async_session):
        """新旧混合。"""
        repo = TweetRepository(async_session)

        # 插入部分
        for tid in ["t1", "t3"]:
            tweet = _make_tweet(tid)
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        tweets = [_make_tweet(f"t{i}") for i in range(1, 6)]
        result = await repo.save_tweets(tweets, early_stop_threshold=0)
        assert result.success_count == 3  # t2, t4, t5
        assert result.skipped_count == 2  # t1, t3

    async def test_empty_list(self, async_session):
        """空推文列表。"""
        repo = TweetRepository(async_session)
        result = await repo.save_tweets([])
        assert result.success_count == 0
        assert result.skipped_count == 0
        assert result.error_count == 0


@pytest.mark.asyncio
class TestEarlyTermination:
    """测试提前终止逻辑。"""

    async def test_early_stop_triggers(self, async_session):
        """连续已存在推文触发提前终止。"""
        repo = TweetRepository(async_session)

        # 插入 id_0 到 id_9
        for i in range(10):
            tweet = _make_tweet(f"id_{i}")
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        # 发送 15 条推文：前 5 条是新的，后 10 条全部已存在
        tweets = [_make_tweet(f"new_{i}") for i in range(5)]
        tweets += [_make_tweet(f"id_{i}") for i in range(10)]

        result = await repo.save_tweets(tweets, early_stop_threshold=5)
        assert result.success_count == 5  # 5 条新的
        # 第 6-10 条触发连续 5 条已存在 -> 提前终止，剩余 5 条也标记跳过
        assert result.skipped_count == 10  # 5 条正常跳过 + 5 条提前终止

    async def test_early_stop_disabled(self, async_session):
        """early_stop_threshold=0 禁用提前终止。"""
        repo = TweetRepository(async_session)

        # 插入全部
        for i in range(10):
            tweet = _make_tweet(f"id_{i}")
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        tweets = [_make_tweet(f"id_{i}") for i in range(10)]
        result = await repo.save_tweets(tweets, early_stop_threshold=0)
        assert result.success_count == 0
        assert result.skipped_count == 10  # 逐条跳过，没有提前终止

    async def test_early_stop_reset_on_new_tweet(self, async_session):
        """遇到新推文时重置连续计数。"""
        repo = TweetRepository(async_session)

        # 插入 old_0 到 old_3
        for i in range(4):
            tweet = _make_tweet(f"old_{i}")
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        # 交错排列：2 旧 + 1 新 + 2 旧 + 1 新 + 2 旧
        tweets = [
            _make_tweet("old_0"),  # existing
            _make_tweet("old_1"),  # existing
            _make_tweet("fresh_1"),  # new -> reset
            _make_tweet("old_2"),  # existing
            _make_tweet("old_3"),  # existing
            _make_tweet("fresh_2"),  # new -> reset
            _make_tweet("extra_1"),  # new
            _make_tweet("extra_2"),  # new
        ]

        result = await repo.save_tweets(tweets, early_stop_threshold=3)
        # 没有连续 3 条已存在（最大连续 2），所以不会提前终止
        assert result.success_count == 4  # fresh_1, fresh_2, extra_1, extra_2
        assert result.skipped_count == 4  # old_0, old_1, old_2, old_3

    async def test_early_stop_at_threshold_boundary(self, async_session):
        """精确在阈值边界触发。"""
        repo = TweetRepository(async_session)

        # 插入 3 条
        for i in range(3):
            tweet = _make_tweet(f"exist_{i}")
            orm = TweetOrm.from_domain(tweet)
            async_session.add(orm)
        await async_session.flush()

        # 1 新 + 3 旧 + 2 新（不会被处理）
        tweets = [
            _make_tweet("new_0"),    # new -> success, reset
            _make_tweet("exist_0"),  # existing, consecutive=1
            _make_tweet("exist_1"),  # existing, consecutive=2
            _make_tweet("exist_2"),  # existing, consecutive=3 -> early stop!
            _make_tweet("new_1"),    # 不会被处理
            _make_tweet("new_2"),    # 不会被处理
        ]

        result = await repo.save_tweets(tweets, early_stop_threshold=3)
        assert result.success_count == 1  # new_0
        assert result.skipped_count == 5  # 3 existing + 2 remaining
