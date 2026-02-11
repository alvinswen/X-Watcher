"""摘要 ORM 模型单元测试。

测试摘要的 SQLAlchemy ORM 模型。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from src.summarization.infrastructure.models import SummaryOrm
from src.summarization.domain.models import SummaryRecord


class TestSummaryOrm:
    """SummaryOrm 模型测试。"""

    @pytest.fixture
    def sample_summary_data(self):
        """示例摘要数据。"""
        return {
            "summary_id": "550e8400-e29b-41d4-a716-446655440000",
            "tweet_id": "1234567890",
            "summary_text": "这是一条关于AI技术突破的推文摘要，内容涵盖了最新的深度学习模型在自然语言处理领域的重大进展，以及其对未来科技发展的深远影响",
            "translation_text": "This is a summary of a tweet about AI breakthrough",
            "model_provider": "openrouter",
            "model_name": "claude-sonnet-4.5",
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "total_tokens": 300,
            "cost_usd": 0.002,
            "cached": False,
            "is_generated_summary": True,
            "content_hash": "abc123def456",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def test_create_summary_orm(self, sample_summary_data):
        """测试创建 SummaryOrm 实例。"""
        summary = SummaryOrm(**sample_summary_data)
        assert summary.summary_id == sample_summary_data["summary_id"]
        assert summary.tweet_id == sample_summary_data["tweet_id"]
        assert summary.model_provider == "openrouter"

    def test_summary_orm_table_name(self):
        """测试表名。"""
        assert SummaryOrm.__tablename__ == "summaries"

    def test_summary_orm_without_translation(self, sample_summary_data):
        """测试没有翻译的 ORM 记录。"""
        sample_summary_data.pop("translation_text")
        summary = SummaryOrm(**sample_summary_data)
        assert summary.translation_text is None

    def test_summary_orm_cached_true(self, sample_summary_data):
        """测试缓存的 ORM 记录。"""
        sample_summary_data["cached"] = True
        summary = SummaryOrm(**sample_summary_data)
        assert summary.cached is True

    def test_to_domain(self, sample_summary_data):
        """测试转换为领域模型。"""
        orm = SummaryOrm(**sample_summary_data)
        domain = orm.to_domain()

        assert isinstance(domain, SummaryRecord)
        assert domain.summary_id == sample_summary_data["summary_id"]
        assert domain.tweet_id == sample_summary_data["tweet_id"]
        assert domain.summary_text == sample_summary_data["summary_text"]
        assert domain.translation_text == sample_summary_data["translation_text"]
        assert domain.model_provider == sample_summary_data["model_provider"]

    def test_from_domain(self, sample_summary_data):
        """测试从领域模型创建 ORM。"""
        domain = SummaryRecord(**sample_summary_data)
        orm = SummaryOrm.from_domain(domain)

        assert isinstance(orm, SummaryOrm)
        assert orm.summary_id == domain.summary_id
        assert orm.tweet_id == domain.tweet_id
        assert orm.summary_text == domain.summary_text
        assert orm.translation_text == domain.translation_text
        assert orm.model_provider == domain.model_provider
        assert orm.model_name == domain.model_name
        assert orm.prompt_tokens == domain.prompt_tokens
        assert orm.completion_tokens == domain.completion_tokens
        assert orm.total_tokens == domain.total_tokens
        assert orm.cost_usd == domain.cost_usd
        assert orm.cached == domain.cached
        assert orm.content_hash == domain.content_hash

    def test_roundtrip_conversion(self, sample_summary_data):
        """测试往返转换。"""
        # ORM -> Domain -> ORM
        orm1 = SummaryOrm(**sample_summary_data)
        domain = orm1.to_domain()
        orm2 = SummaryOrm.from_domain(domain)

        assert orm1.summary_id == orm2.summary_id
        assert orm1.tweet_id == orm2.tweet_id
        assert orm1.summary_text == orm2.summary_text
        assert orm1.translation_text == orm2.translation_text
        assert orm1.model_provider == orm2.model_provider
        assert orm1.model_name == orm2.model_name
        assert orm1.prompt_tokens == orm2.prompt_tokens
        assert orm1.completion_tokens == orm2.completion_tokens
        assert orm1.total_tokens == orm2.total_tokens
        assert orm1.cost_usd == orm2.cost_usd
        assert orm1.cached == orm2.cached
        assert orm1.content_hash == orm2.content_hash

    def test_summary_orm_provider_validation(self, sample_summary_data):
        """测试提供商验证。"""
        # 有效提供商
        for provider in ["openrouter", "minimax", "open_source"]:
            sample_summary_data["model_provider"] = provider
            summary = SummaryOrm(**sample_summary_data)
            assert summary.model_provider == provider
