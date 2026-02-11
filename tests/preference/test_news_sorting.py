"""个性化新闻流排序业务逻辑测试。

测试 get_sorted_news 方法的排序和过滤逻辑。
"""

from datetime import datetime, timezone

import pytest

from src.preference.domain.models import FilterType, SortType
from src.preference.infrastructure.preference_repository import PreferenceRepository
from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository
from src.preference.services.preference_service import PreferenceService
from src.preference.services.relevance_service import KeywordRelevanceService
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.repository import TweetRepository


@pytest.mark.asyncio
class TestNewsSorting:
    """个性化新闻流排序测试类。"""

    async def test_get_sorted_news_by_time(self, async_session):
        """测试按时间排序新闻。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        relevance_service = KeywordRelevanceService()
        service = PreferenceService(pref_repo, scraper_repo, relevance_service)

        # 先将用户添加到抓取列表（这样 initialize_user_follows 才能复制到用户关注列表）
        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")
        await scraper_repo.create_scraper_follow("user2", "理由2", "admin")
        await scraper_repo.create_scraper_follow("user3", "理由3", "admin")

        # 创建推文（不同时间）
        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id="1", text="Oldest tweet", created_at=now.replace(hour=10), author_username="user1"),
            Tweet(tweet_id="2", text="Newest tweet", created_at=now.replace(hour=14), author_username="user2"),
            Tweet(tweet_id="3", text="Middle tweet", created_at=now.replace(hour=12), author_username="user3"),
        ])

        # Act
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.TIME,
            limit=100,
        )

        # Assert - 应该按时间倒序排列（最新的在前）
        assert len(result) == 3
        assert result[0]["tweet"]["tweet_id"] == "2"  # 最新
        assert result[1]["tweet"]["tweet_id"] == "3"  # 中间
        assert result[2]["tweet"]["tweet_id"] == "1"  # 最旧
        assert result[0]["relevance_score"] is None  # 时间排序没有相关性分数

    async def test_get_sorted_news_by_priority(self, async_session):
        """测试按优先级排序新闻。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        relevance_service = KeywordRelevanceService()
        service = PreferenceService(pref_repo, scraper_repo, relevance_service)

        # 添加抓取账号
        await scraper_repo.create_scraper_follow("high", "高优先级", "admin")
        await scraper_repo.create_scraper_follow("low", "低优先级", "admin")
        await scraper_repo.create_scraper_follow("medium", "中优先级", "admin")

        # 创建推文
        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id="1", text="Low priority", created_at=now, author_username="low"),
            Tweet(tweet_id="2", text="High priority", created_at=now, author_username="high"),
            Tweet(tweet_id="3", text="Medium priority", created_at=now, author_username="medium"),
        ])

        # 设置关注和优先级
        await service.initialize_user_follows(user_id=1)
        await service.update_priority(1, "high", 9)
        await service.update_priority(1, "medium", 5)
        await service.update_priority(1, "low", 2)

        # Act
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.PRIORITY,
            limit=100,
        )

        # Assert - 应该按优先级降序排列
        assert len(result) == 3
        assert result[0]["tweet"]["author_username"] == "high"  # 优先级 9
        assert result[1]["tweet"]["author_username"] == "medium"  # 优先级 5
        assert result[2]["tweet"]["author_username"] == "low"  # 优先级 2

    async def test_get_sorted_news_by_relevance(self, async_session):
        """测试按相关性排序新闻。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        relevance_service = KeywordRelevanceService()
        service = PreferenceService(pref_repo, scraper_repo, relevance_service)

        # 添加抓取账号
        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")
        await scraper_repo.create_scraper_follow("user2", "理由2", "admin")

        # 创建推文 - 第2条推文与 AI 相关性高
        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id="1", text="Some random tweet", created_at=now, author_username="user1"),
            Tweet(tweet_id="2", text="AI AI AI multiple times", created_at=now, author_username="user2"),
            Tweet(tweet_id="3", text="Another random tweet", created_at=now, author_username="user1"),
        ])

        # 设置关注
        await service.initialize_user_follows(user_id=1)

        # Act - 使用 RELEVANCE 排序（没有关键词过滤时，所有相关性为0，回退到时间排序）
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.RELEVANCE,
            limit=100,
        )

        # Assert - 没有关键词时所有推文相关性都是 0
        assert len(result) == 3
        # 所有相关性分数应该都是 0（因为没有关键词过滤）
        for item in result:
            assert item["relevance_score"] == 0.0

    async def test_get_sorted_news_applies_keyword_filter(self, async_session):
        """测试应用关键词过滤规则（排除包含关键词的内容）。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        relevance_service = KeywordRelevanceService()
        service = PreferenceService(pref_repo, scraper_repo, relevance_service)

        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")

        # 创建推文
        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id="1", text="AI is amazing", created_at=now, author_username="user1"),
            Tweet(tweet_id="2", text="Blockchain news", created_at=now, author_username="user1"),
            Tweet(tweet_id="3", text="More AI content", created_at=now, author_username="user1"),
        ])

        await service.initialize_user_follows(user_id=1)
        # 添加关键词过滤规则（排除包含 blockchain 的推文）
        await service.add_filter(1, FilterType.KEYWORD, "blockchain")

        # Act - 应用过滤规则后，应该排除包含 blockchain 的推文
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.TIME,
            limit=100,
        )

        # Assert - 应该排除包含 "blockchain" 的推文
        assert len(result) == 2
        tweet_ids = [r["tweet"]["tweet_id"] for r in result]
        assert "1" in tweet_ids
        assert "3" in tweet_ids
        assert "2" not in tweet_ids

    async def test_get_sorted_news_ignores_non_followed_users(self, async_session):
        """测试只返回关注用户的推文。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        relevance_service = KeywordRelevanceService()
        service = PreferenceService(pref_repo, scraper_repo, relevance_service)

        await scraper_repo.create_scraper_follow("followed", "理由1", "admin")
        await scraper_repo.create_scraper_follow("not_followed", "理由2", "admin")

        # 创建推文
        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id="1", text="Tweet from followed user", created_at=now, author_username="followed"),
            Tweet(tweet_id="2", text="Tweet from non-followed user", created_at=now, author_username="not_followed"),
        ])

        # 只关注 followed 用户
        await service.add_follow(1, "followed")

        # Act
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.TIME,
            limit=100,
        )

        # Assert - 只返回关注用户的推文
        assert len(result) == 1
        assert result[0]["tweet"]["author_username"] == "followed"

    async def test_get_sorted_news_relevance_service_fallback(self, async_session):
        """测试相关性服务不可用时回退到时间排序。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        # 不传入 relevance_service，模拟服务不可用
        service = PreferenceService(pref_repo, scraper_repo, relevance_service=None)

        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")

        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id="1", text="First", created_at=now.replace(hour=10), author_username="user1"),
            Tweet(tweet_id="2", text="Second", created_at=now.replace(hour=14), author_username="user1"),
        ])

        await service.initialize_user_follows(user_id=1)

        # Act - 即使指定 RELEVANCE 排序，没有服务也应该回退到时间排序
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.RELEVANCE,
            limit=100,
        )

        # Assert - 应该回退到时间排序
        assert len(result) == 2
        assert result[0]["tweet"]["tweet_id"] == "2"  # 最新

    async def test_get_sorted_news_respects_limit(self, async_session):
        """测试限制返回数量。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        relevance_service = KeywordRelevanceService()
        service = PreferenceService(pref_repo, scraper_repo, relevance_service)

        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")

        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id=str(i), text=f"Tweet {i}", created_at=now, author_username="user1")
            for i in range(10)
        ])

        await service.initialize_user_follows(user_id=1)

        # Act
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.TIME,
            limit=5,
        )

        # Assert - 只返回 5 条
        assert len(result) == 5

    async def test_get_sorted_news_initializes_user_follows(self, async_session):
        """测试首次调用时自动初始化用户关注列表。"""
        # Arrange
        scraper_repo = ScraperConfigRepository(async_session)
        pref_repo = PreferenceRepository(async_session)
        tweet_repo = TweetRepository(async_session)
        relevance_service = KeywordRelevanceService()
        service = PreferenceService(pref_repo, scraper_repo, relevance_service)

        # 添加抓取账号
        await scraper_repo.create_scraper_follow("user1", "理由1", "admin")

        now = datetime.now(timezone.utc)
        await tweet_repo.save_tweets([
            Tweet(tweet_id="1", text="Tweet", created_at=now, author_username="user1"),
        ])

        # Act - 用户未初始化，应该自动初始化
        result = await service.get_sorted_news(
            user_id=1,
            sort_type=SortType.TIME,
            limit=100,
        )

        # Assert - 返回结果且用户已初始化
        assert len(result) == 1
        follows = await pref_repo.get_follows_by_user(1)
        assert len(follows) == 1
