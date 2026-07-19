"""关注列表管理 API 请求/响应模型单元测试。

测试关注列表管理相关的 Pydantic 数据模型。
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.preference.api.schemas import (
    CreateScraperFollowRequest,
    ScraperFollowResponse,
    UpdateScraperFollowRequest,
)


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

    def test_scraper_follow_response(self):
        """测试抓取账号响应。"""
        now = datetime.now(UTC)
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
