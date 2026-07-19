"""关注列表管理领域模型单元测试。

测试关注列表管理相关的领域模型。
"""

from datetime import datetime, timezone, UTC

import pytest

from src.preference.domain.models import (
    ScraperFollow,
)


class TestScraperFollow:
    """ScraperFollow 领域模型测试。"""

    @pytest.fixture
    def sample_scraper_follow_data(self):
        """示例抓取账号数据。"""
        return {
            "id": 1,
            "username": "karpathy",
            "added_at": datetime.now(UTC),
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

    def test_scraper_follow_to_dict(self, sample_scraper_follow_data):
        """测试转换为字典。"""
        follow = ScraperFollow(**sample_scraper_follow_data)
        data = follow.model_dump()
        assert "id" in data
        assert "username" in data
        assert data["username"] == "karpathy"
