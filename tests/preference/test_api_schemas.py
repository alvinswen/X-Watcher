"""偏好管理 API 请求/响应模型单元测试。

测试偏好管理相关的 Pydantic 数据模型。
"""

from datetime import datetime, timezone
from enum import Enum

import pytest
from pydantic import ValidationError

from src.preference.api.schemas import (
    CreateFollowRequest,
    FollowResponse,
    UpdatePriorityRequest,
    CreateFilterRequest,
    FilterResponse,
    UpdateSortingRequest,
    SortingPreferenceResponse,
    PreferenceResponse,
    CreateScraperFollowRequest,
    ScraperFollowResponse,
    UpdateScraperFollowRequest,
    TweetWithRelevance,
    FilterType,
    SortType,
)


class TestFilterType:
    """过滤类型枚举测试。"""

    def test_filter_type_values(self):
        """测试过滤类型枚举值。"""
        assert FilterType.KEYWORD == "keyword"
        assert FilterType.HASHTAG == "hashtag"
        assert FilterType.CONTENT_TYPE == "content_type"

    def test_filter_type_comparison(self):
        """测试过滤类型比较。"""
        assert FilterType.KEYWORD == "keyword"
        assert FilterType.HASHTAG != FilterType.KEYWORD


class TestSortType:
    """排序类型枚举测试。"""

    def test_sort_type_values(self):
        """测试排序类型枚举值。"""
        assert SortType.TIME == "time"
        assert SortType.RELEVANCE == "relevance"
        assert SortType.PRIORITY == "priority"


class TestCreateFollowRequest:
    """创建关注请求模型测试。"""

    def test_create_valid_follow_request(self):
        """测试创建有效的关注请求。"""
        request = CreateFollowRequest(username="karpathy")
        assert request.username == "karpathy"
        assert request.priority == 5  # 默认值

    def test_create_follow_request_with_custom_priority(self):
        """测试创建带自定义优先级的关注请求。"""
        request = CreateFollowRequest(username="samalt", priority=8)
        assert request.username == "samalt"
        assert request.priority == 8

    def test_create_follow_request_with_at_symbol(self):
        """测试创建带 @ 符号的关注请求。"""
        request = CreateFollowRequest(username="@ylecun")
        assert request.username == "ylecun"  # 应该去除 @ 符号

    def test_create_follow_request_invalid_username_too_long(self):
        """测试用户名超过 15 字符时验证失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateFollowRequest(username="thisusernameistoolong")
        assert "username" in str(exc_info.value).lower()

    def test_create_follow_request_invalid_username_special_chars(self):
        """测试用户名包含非法字符时验证失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateFollowRequest(username="user@name")
        assert "username" in str(exc_info.value).lower()

    def test_create_follow_request_priority_too_low(self):
        """测试优先级低于 1 时验证失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateFollowRequest(username="testuser", priority=0)
        assert "priority" in str(exc_info.value).lower()

    def test_create_follow_request_priority_too_high(self):
        """测试优先级高于 10 时验证失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateFollowRequest(username="testuser", priority=11)
        assert "priority" in str(exc_info.value).lower()

    def test_create_follow_request_valid_boundary_priorities(self):
        """测试边界优先级值。"""
        request1 = CreateFollowRequest(username="user1", priority=1)
        assert request1.priority == 1

        request2 = CreateFollowRequest(username="user2", priority=10)
        assert request2.priority == 10


class TestUpdatePriorityRequest:
    """更新优先级请求模型测试。"""

    def test_update_priority_valid(self):
        """测试有效的优先级更新。"""
        request = UpdatePriorityRequest(priority=7)
        assert request.priority == 7

    def test_update_priority_boundary_values(self):
        """测试边界优先级值。"""
        request1 = UpdatePriorityRequest(priority=1)
        assert request1.priority == 1

        request2 = UpdatePriorityRequest(priority=10)
        assert request2.priority == 10

    def test_update_priority_invalid_too_low(self):
        """测试优先级低于 1 时验证失败。"""
        with pytest.raises(ValidationError):
            UpdatePriorityRequest(priority=0)

    def test_update_priority_invalid_too_high(self):
        """测试优先级高于 10 时验证失败。"""
        with pytest.raises(ValidationError):
            UpdatePriorityRequest(priority=11)


class TestCreateFilterRequest:
    """创建过滤规则请求模型测试。"""

    def test_create_keyword_filter(self):
        """测试创建关键词过滤规则。"""
        request = CreateFilterRequest(
            filter_type=FilterType.KEYWORD, value="crypto"
        )
        assert request.filter_type == FilterType.KEYWORD
        assert request.value == "crypto"

    def test_create_hashtag_filter(self):
        """测试创建话题标签过滤规则。"""
        request = CreateFilterRequest(
            filter_type=FilterType.HASHTAG, value="AI"
        )
        assert request.filter_type == FilterType.HASHTAG
        assert request.value == "AI"

    def test_create_content_type_filter(self):
        """测试创建内容类型过滤规则。"""
        request = CreateFilterRequest(
            filter_type=FilterType.CONTENT_TYPE, value="retweet"
        )
        assert request.filter_type == FilterType.CONTENT_TYPE
        assert request.value == "retweet"

    def test_create_filter_value_too_long(self):
        """测试过滤值超过 500 字符时验证失败。"""
        with pytest.raises(ValidationError):
            CreateFilterRequest(
                filter_type=FilterType.KEYWORD, value="a" * 501
            )

    def test_create_filter_empty_value(self):
        """测试空过滤值时验证失败。"""
        with pytest.raises(ValidationError):
            CreateFilterRequest(filter_type=FilterType.KEYWORD, value="")


class TestUpdateSortingRequest:
    """更新排序偏好请求模型测试。"""

    def test_update_sorting_time(self):
        """测试设置时间排序。"""
        request = UpdateSortingRequest(sort_type=SortType.TIME)
        assert request.sort_type == SortType.TIME

    def test_update_sorting_relevance(self):
        """测试设置相关性排序。"""
        request = UpdateSortingRequest(sort_type=SortType.RELEVANCE)
        assert request.sort_type == SortType.RELEVANCE

    def test_update_sorting_priority(self):
        """测试设置优先级排序。"""
        request = UpdateSortingRequest(sort_type=SortType.PRIORITY)
        assert request.sort_type == SortType.PRIORITY

    def test_update_sorting_invalid_type(self):
        """测试无效排序类型时验证失败。"""
        with pytest.raises(ValidationError):
            UpdateSortingRequest(sort_type="invalid")


class TestCreateScraperFollowRequest:
    """创建抓取账号请求模型测试。"""

    def test_create_valid_scraper_follow(self):
        """测试创建有效的抓取账号。"""
        request = CreateScraperFollowRequest(
            username="elonmusk",
            reason="Tesla 相关动态",
            added_by="admin@metalight.ai"
        )
        assert request.username == "elonmusk"
        assert request.reason == "Tesla 相关动态"
        assert request.added_by == "admin@metalight.ai"

    def test_create_scraper_follow_with_at_symbol(self):
        """测试创建带 @ 符号的抓取账号。"""
        request = CreateScraperFollowRequest(
            username="@sama",
            reason="OpenAI 相关",
            added_by="admin"
        )
        assert request.username == "sama"

    def test_create_scraper_follow_invalid_username(self):
        """测试无效用户名时验证失败。"""
        with pytest.raises(ValidationError):
            CreateScraperFollowRequest(
                username="invalid user!",
                reason="test",
                added_by="admin"
            )

    def test_create_scraper_follow_empty_reason(self):
        """测试空理由时验证失败。"""
        with pytest.raises(ValidationError):
            CreateScraperFollowRequest(
                username="testuser",
                reason="",
                added_by="admin"
            )

    def test_create_scraper_follow_empty_added_by(self):
        """测试空添加者时验证失败。"""
        with pytest.raises(ValidationError):
            CreateScraperFollowRequest(
                username="testuser",
                reason="test reason",
                added_by=""
            )


class TestUpdateScraperFollowRequest:
    """更新抓取账号请求模型测试。"""

    def test_update_reason_only(self):
        """测试只更新理由。"""
        request = UpdateScraperFollowRequest(reason="更新后的理由")
        assert request.reason == "更新后的理由"
        assert request.is_active is None

    def test_update_is_active_only(self):
        """测试只更新激活状态。"""
        request = UpdateScraperFollowRequest(is_active=False)
        assert request.is_active is False
        assert request.reason is None

    def test_update_both_fields(self):
        """测试同时更新多个字段。"""
        request = UpdateScraperFollowRequest(
            reason="新理由",
            is_active=True
        )
        assert request.reason == "新理由"
        assert request.is_active is True

    def test_update_all_fields_none(self):
        """测试所有字段为 None。"""
        request = UpdateScraperFollowRequest()
        assert request.reason is None
        assert request.is_active is None


class TestResponseModels:
    """响应模型测试。"""

    def test_follow_response(self):
        """测试关注响应。"""
        now = datetime.now(timezone.utc)
        response = FollowResponse(
            id=1,
            user_id=1,
            username="karpathy",
            priority=5,
            created_at=now,
            updated_at=now
        )
        assert response.username == "karpathy"
        assert response.priority == 5

    def test_filter_response(self):
        """测试过滤规则响应。"""
        now = datetime.now(timezone.utc)
        response = FilterResponse(
            id="550e8400-e29b-41d4-a716-446655440000",
            user_id=1,
            filter_type=FilterType.KEYWORD,
            value="AI",
            created_at=now
        )
        assert response.filter_type == FilterType.KEYWORD
        assert response.value == "AI"

    def test_sorting_preference_response(self):
        """测试排序偏好响应。"""
        response = SortingPreferenceResponse(
            sort_type=SortType.RELEVANCE
        )
        assert response.sort_type == SortType.RELEVANCE

    def test_preference_response(self):
        """测试完整偏好响应。"""
        now = datetime.now(timezone.utc)
        response = PreferenceResponse(
            user_id=1,
            sorting=SortingPreferenceResponse(sort_type=SortType.TIME),
            follows=[
                FollowResponse(
                    id=1,
                    user_id=1,
                    username="user1",
                    priority=5,
                    created_at=now,
                    updated_at=now
                )
            ],
            filters=[
                FilterResponse(
                    id="filter-1",
                    user_id=1,
                    filter_type=FilterType.KEYWORD,
                    value="test",
                    created_at=now
                )
            ]
        )
        assert response.user_id == 1
        assert response.sorting.sort_type == SortType.TIME
        assert len(response.follows) == 1
        assert len(response.filters) == 1

    def test_scraper_follow_response(self):
        """测试抓取账号响应。"""
        now = datetime.now(timezone.utc)
        response = ScraperFollowResponse(
            id=1,
            username="testuser",
            added_at=now,
            reason="测试账号",
            added_by="admin",
            is_active=True
        )
        assert response.username == "testuser"
        assert response.is_active is True

    def test_tweet_with_relevance(self):
        """测试带相关性分数的推文。"""
        tweet = {
            "id": "123",
            "text": "This is a test tweet",
            "author": "testuser",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        response = TweetWithRelevance(
            tweet=tweet,
            relevance_score=0.85
        )
        assert response.tweet["id"] == "123"
        assert response.relevance_score == 0.85

    def test_tweet_with_relevance_without_score(self):
        """测试不带相关性分数的推文（非相关性排序）。"""
        tweet = {
            "id": "456",
            "text": "Another test tweet",
            "author": "user2",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        response = TweetWithRelevance(tweet=tweet)
        assert response.tweet["id"] == "456"
        assert response.relevance_score is None
