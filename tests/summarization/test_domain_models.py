"""摘要领域模型单元测试。

测试 SummaryRecord(唯一活体 · MCP Agent 回写通道契约)。
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.summarization.domain.models import SummaryRecord


class TestSummaryRecord:
    """摘要记录模型测试。"""

    @pytest.fixture
    def sample_record_data(self):
        """示例摘要记录数据。"""
        return {
            "summary_id": "550e8400-e29b-41d4-a716-446655440000",
            "tweet_id": "1234567890",
            # 50 字摘要（符合最小长度要求）
            "summary_text": "这是一条关于AI技术突破的推文摘要，内容涵盖了最新的深度学习模型在自然语言处理领域的重大进展，以及其对未来科技发展的深远影响",
            "translation_text": "This is a summary of a tweet about AI breakthrough",
            "model_provider": "openrouter",
            "model_name": "claude-sonnet-4.5",
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "total_tokens": 300,
            "cost_usd": 0.002,
            "cached": False,
            "content_hash": "abc123def456",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def test_create_valid_summary_record(self, sample_record_data):
        """测试创建有效的摘要记录。"""
        record = SummaryRecord(**sample_record_data)
        assert record.summary_id == sample_record_data["summary_id"]
        assert record.tweet_id == sample_record_data["tweet_id"]
        assert record.summary_text == sample_record_data["summary_text"]
        assert record.model_provider == "openrouter"

    def test_summary_record_without_translation(self, sample_record_data):
        """测试没有翻译的摘要记录。"""
        sample_record_data.pop("translation_text")
        record = SummaryRecord(**sample_record_data)
        assert record.translation_text is None

    def test_summary_record_with_cached_true(self, sample_record_data):
        """测试缓存的摘要记录。"""
        sample_record_data["cached"] = True
        record = SummaryRecord(**sample_record_data)
        assert record.cached is True

    def test_summary_record_summary_text_length_validation(self, sample_record_data):
        """测试摘要文本长度限制（1-500 字）。"""
        # 太短（空字符串）
        sample_record_data["summary_text"] = ""
        with pytest.raises(ValidationError):
            SummaryRecord(**sample_record_data)

        # 太长
        sample_record_data["summary_text"] = "a" * 501
        with pytest.raises(ValidationError):
            SummaryRecord(**sample_record_data)

    def test_summary_record_valid_summary_text_length(self, sample_record_data):
        """测试有效的摘要文本长度。"""
        # 边界值测试
        sample_record_data["summary_text"] = "a"  # 最小值
        record = SummaryRecord(**sample_record_data)
        assert len(record.summary_text) == 1

        sample_record_data["summary_text"] = "a" * 500  # 最大值
        record = SummaryRecord(**sample_record_data)
        assert len(record.summary_text) == 500

        # 测试短推文原文（智能长度策略）
        sample_record_data["summary_text"] = "Short tweet"
        sample_record_data["is_generated_summary"] = False
        record = SummaryRecord(**sample_record_data)
        assert record.summary_text == "Short tweet"
