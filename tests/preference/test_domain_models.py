"""偏好管理领域模型单元测试。

测试偏好管理相关的领域模型。
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.preference.domain.models import (
    ScraperFollow,
    TwitterFollow,
    FilterRule,
    FilterType,
    SortType,
)
from src.database.models import (
    ScraperFollow as ScraperFollowORM,
    TwitterFollow as TwitterFollowORM,
    FilterRule as FilterRuleORM,
)


class TestScraperFollow:
    """ScraperFollow 领域模型测试。"""

    @pytest.fixture
    def sample_scraper_follow_data(self):
        """示例抓取账号数据。"""
        return {
            "id": 1,
            "username": "karpathy",
            "added_at": datetime.now(timezone.utc),
            "reason": "AI 研究相关",
            "added_by": "admin@metalight.ai",
            "is_active": True,
        }

    def test_create_valid_scraper_follow(self, sample_scraper_follow_data):
        """测试创建有效的抓取账号领域模型。"""
        follow = ScraperFollow(**sample_scraper_follow_data)
        assert follow.username == "karpathy"
        assert follow.reason == "AI 研究相关"
        assert follow.is_active is True

    def test_scraper_follow_inactive(self, sample_scraper_follow_data):
        """测试未启用的抓取账号。"""
        sample_scraper_follow_data["is_active"] = False
        follow = ScraperFollow(**sample_scraper_follow_data)
        assert follow.is_active is False

    def test_scraper_follow_from_orm(self, sample_scraper_follow_data):
        """测试从 ORM 模型转换。"""
        orm = ScraperFollowORM(
            id=1,
            username="karpathy",
            added_at=datetime.now(timezone.utc),
            reason="AI 研究相关",
            added_by="admin@metalight.ai",
            is_active=True,
        )
        domain = ScraperFollow.from_orm(orm)
        assert domain.id == orm.id
        assert domain.username == orm.username
        assert domain.reason == orm.reason

    def test_scraper_follow_to_dict(self, sample_scraper_follow_data):
        """测试转换为字典。"""
        follow = ScraperFollow(**sample_scraper_follow_data)
        data = follow.model_dump()
        assert "id" in data
        assert "username" in data
        assert data["username"] == "karpathy"


class TestTwitterFollow:
    """TwitterFollow 领域模型测试。"""

    @pytest.fixture
    def sample_twitter_follow_data(self):
        """示例用户关注数据。"""
        return {
            "id": 1,
            "user_id": 1,
            "username": "ylecun",
            "priority": 7,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def test_create_valid_twitter_follow(self, sample_twitter_follow_data):
        """测试创建有效的用户关注模型。"""
        follow = TwitterFollow(**sample_twitter_follow_data)
        assert follow.username == "ylecun"
        assert follow.priority == 7
        assert follow.user_id == 1

    def test_twitter_follow_default_priority(self):
        """测试默认优先级。"""
        data = {
            "id": 1,
            "user_id": 1,
            "username": "testuser",
            "priority": 5,  # 默认值
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        follow = TwitterFollow(**data)
        assert follow.priority == 5

    def test_twitter_follow_priority_boundary(self):
        """测试优先级边界值。"""
        base_data = {
            "id": 1,
            "user_id": 1,
            "username": "testuser",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # 最小优先级
        base_data["priority"] = 1
        follow = TwitterFollow(**base_data)
        assert follow.priority == 1

        # 最大优先级
        base_data["priority"] = 10
        follow = TwitterFollow(**base_data)
        assert follow.priority == 10

    def test_twitter_follow_invalid_priority(self):
        """测试无效优先级。"""
        data = {
            "id": 1,
            "user_id": 1,
            "username": "testuser",
            "priority": 11,  # 超出范围
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        with pytest.raises(ValidationError):
            TwitterFollow(**data)

    def test_twitter_follow_from_orm(self):
        """测试从 ORM 模型转换。"""
        orm = TwitterFollowORM(
            id=1,
            user_id=1,
            username="ylecun",
            priority=7,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        domain = TwitterFollow.from_orm(orm)
        assert domain.id == orm.id
        assert domain.username == orm.username
        assert domain.priority == orm.priority


class TestFilterRule:
    """FilterRule 领域模型测试。"""

    @pytest.fixture
    def sample_filter_rule_data(self):
        """示例过滤规则数据。"""
        return {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "user_id": 1,
            "filter_type": FilterType.KEYWORD,
            "value": "crypto",
            "created_at": datetime.now(timezone.utc),
        }

    def test_create_valid_filter_rule(self, sample_filter_rule_data):
        """测试创建有效的过滤规则。"""
        rule = FilterRule(**sample_filter_rule_data)
        assert rule.filter_type == FilterType.KEYWORD
        assert rule.value == "crypto"

    def test_filter_rule_keyword_type(self):
        """测试关键词过滤规则。"""
        rule = FilterRule(
            id="filter-1",
            user_id=1,
            filter_type=FilterType.KEYWORD,
            value="AI",
            created_at=datetime.now(timezone.utc),
        )
        assert rule.filter_type == FilterType.KEYWORD

    def test_filter_rule_hashtag_type(self):
        """测试话题标签过滤规则。"""
        rule = FilterRule(
            id="filter-2",
            user_id=1,
            filter_type=FilterType.HASHTAG,
            value="LLM",
            created_at=datetime.now(timezone.utc),
        )
        assert rule.filter_type == FilterType.HASHTAG

    def test_filter_rule_content_type(self):
        """测试内容类型过滤规则。"""
        rule = FilterRule(
            id="filter-3",
            user_id=1,
            filter_type=FilterType.CONTENT_TYPE,
            value="retweet",
            created_at=datetime.now(timezone.utc),
        )
        assert rule.filter_type == FilterType.CONTENT_TYPE

    def test_filter_rule_from_orm(self):
        """测试从 ORM 模型转换。"""
        orm = FilterRuleORM(
            id="550e8400-e29b-41d4-a716-446655440000",
            user_id=1,
            filter_type="keyword",
            value="test",
            created_at=datetime.now(timezone.utc),
        )
        domain = FilterRule.from_orm(orm)
        assert domain.id == orm.id
        assert domain.filter_type == FilterType.KEYWORD
        assert domain.value == orm.value


class TestFilterType:
    """FilterType 枚举测试。"""

    def test_filter_type_values(self):
        """测试枚举值。"""
        assert FilterType.KEYWORD == "keyword"
        assert FilterType.HASHTAG == "hashtag"
        assert FilterType.CONTENT_TYPE == "content_type"

    def test_filter_type_iteration(self):
        """测试枚举遍历。"""
        types = [ft for ft in FilterType]
        assert len(types) == 3
        assert FilterType.KEYWORD in types


class TestSortType:
    """SortType 枚举测试。"""

    def test_sort_type_values(self):
        """测试枚举值。"""
        assert SortType.TIME == "time"
        assert SortType.RELEVANCE == "relevance"
        assert SortType.PRIORITY == "priority"

    def test_sort_type_iteration(self):
        """测试枚举遍历。"""
        types = [st for st in SortType]
        assert len(types) == 3
        assert SortType.TIME in types
