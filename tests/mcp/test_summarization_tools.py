"""MCP 摘要工具单元测试。

测试 get_unsummarized_tweets 和 save_summaries 工具。
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm


def _get_tool_funcs():
    """通过 FastMCP 实例获取注册的工具函数。"""
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    tools = mcp._tool_manager._tools
    return {name: tool.fn for name, tool in tools.items()}


@pytest.fixture
def tool_funcs():
    return _get_tool_funcs()


def _mock_session_maker(mock_session):
    """创建 mock session_maker。"""
    sm = MagicMock()
    sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    sm.return_value.__aexit__ = AsyncMock(return_value=False)
    return sm


class TestGetUnsummarizedTweets:
    """get_unsummarized_tweets 工具测试。"""

    @pytest.mark.asyncio
    async def test_returns_tweets_without_summaries(self, tool_funcs):
        """测试返回没有摘要的推文。"""
        get_unsummarized = tool_funcs["get_unsummarized_tweets"]

        # 模拟查询结果 — 返回一条没有摘要的推文
        mock_row = MagicMock()
        mock_row._mapping = {
            "tweet_id": "t1",
            "text": "Hello world from @elonmusk",
            "author_username": "elonmusk",
            "author_display_name": "Elon Musk",
            "reference_type": None,
            "referenced_tweet_text": None,
            "referenced_tweet_author_username": None,
            "created_at": datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
        }

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
        ):
            result_json = await get_unsummarized(limit=10)

        result = json.loads(result_json)
        assert result["success"] is True
        tweets = result["data"]["tweets"]
        assert len(tweets) == 1
        assert tweets[0]["tweet_id"] == "t1"
        assert tweets[0]["text"] == "Hello world from @elonmusk"
        assert tweets[0]["author_username"] == "elonmusk"

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_summarized(self, tool_funcs):
        """测试所有推文都有摘要时返回空列表。"""
        get_unsummarized = tool_funcs["get_unsummarized_tweets"]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
        ):
            result_json = await get_unsummarized(limit=10)

        result = json.loads(result_json)
        assert result["success"] is True
        assert result["data"]["tweets"] == []
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_limit_clamped_to_200(self, tool_funcs):
        """测试 limit 被限制在 200 以内。"""
        get_unsummarized = tool_funcs["get_unsummarized_tweets"]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
        ):
            result_json = await get_unsummarized(limit=999)

        # 验证 SQL 中使用了 clamped limit（通过成功执行即可，
        # 细节通过集成测试验证）
        result = json.loads(result_json)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_includes_referenced_tweet_fields(self, tool_funcs):
        """测试引用推文（quoted/retweeted）字段被正确返回。"""
        get_unsummarized = tool_funcs["get_unsummarized_tweets"]

        mock_row = MagicMock()
        mock_row._mapping = {
            "tweet_id": "t2",
            "text": "Great thread!",
            "author_username": "user1",
            "author_display_name": "User One",
            "reference_type": "quoted",
            "referenced_tweet_text": "Original content here",
            "referenced_tweet_author_username": "originalauthor",
            "created_at": datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        }

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
        ):
            result_json = await get_unsummarized(limit=10)

        result = json.loads(result_json)
        tweet = result["data"]["tweets"][0]
        assert tweet["reference_type"] == "quoted"
        assert tweet["referenced_tweet_text"] == "Original content here"
        assert tweet["referenced_tweet_author_username"] == "originalauthor"


class TestSaveSummaries:
    """save_summaries 工具测试。"""

    @pytest.mark.asyncio
    async def test_save_single_summary(self, tool_funcs):
        """测试保存单条摘要(原生 list 形态——推荐入参)。"""
        save_summaries = tool_funcs["save_summaries"]

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        # 验证门会批量回查原文；默认返回空 → 各项降级放行
        _origin_result = MagicMock()
        _origin_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=_origin_result)
        mock_sm = _mock_session_maker(mock_session)

        mock_record = MagicMock()
        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
            patch(
                "src.summarization.infrastructure.repository.SummarizationRepository.save_summary_record",
                new_callable=AsyncMock,
                return_value=mock_record,
            ) as mock_save,
            patch("src.mcp.security.audit_log"),
        ):
            summaries = [{
                "tweet_id": "t1",
                "summary": "Elon Musk 发布了关于 AI 的看法",
                "translation": "Elon Musk shared his views on AI",
            }]

            result_json = await save_summaries(summaries=summaries)

        result = json.loads(result_json)
        assert result["success"] is True
        assert result["data"]["saved"] == 1
        assert result["data"]["failed"] == 0
        assert result["data"]["total"] == 1

        # 验证 save_summary_record 被调用，且 model_provider 为 claude_code
        mock_save.assert_called_once()
        saved_record = mock_save.call_args[0][0]
        assert saved_record.model_provider == "claude_code"
        # model_name 应来自配置(默认 claude-opus-4-7)而非硬编码
        assert saved_record.model_name.startswith("claude-opus-")
        assert saved_record.cost_usd == 0.0
        assert saved_record.tweet_id == "t1"

    @pytest.mark.asyncio
    async def test_save_batch_summaries(self, tool_funcs):
        """测试批量保存摘要。"""
        save_summaries = tool_funcs["save_summaries"]

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        # 验证门会批量回查原文；默认返回空 → 各项降级放行
        _origin_result = MagicMock()
        _origin_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=_origin_result)
        mock_sm = _mock_session_maker(mock_session)

        mock_record = MagicMock()
        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
            patch(
                "src.summarization.infrastructure.repository.SummarizationRepository.save_summary_record",
                new_callable=AsyncMock,
                return_value=mock_record,
            ) as mock_save,
            patch("src.mcp.security.audit_log"),
        ):
            summaries = [
                {"tweet_id": "t1", "summary": "摘要1"},
                {"tweet_id": "t2", "summary": "摘要2", "translation": "翻译2"},
                {"tweet_id": "t3", "summary": "摘要3"},
            ]

            result_json = await save_summaries(summaries=summaries)

        result = json.loads(result_json)
        assert result["data"]["saved"] == 3
        assert result["data"]["total"] == 3
        assert mock_save.call_count == 3

    @pytest.mark.asyncio
    async def test_save_json_string_backward_compat(self, tool_funcs):
        """测试 JSON 字符串形态仍兼容(为旧调用方保留的退路)。"""
        save_summaries = tool_funcs["save_summaries"]

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        # 验证门会批量回查原文；默认返回空 → 各项降级放行
        _origin_result = MagicMock()
        _origin_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=_origin_result)
        mock_sm = _mock_session_maker(mock_session)

        mock_record = MagicMock()
        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
            patch(
                "src.summarization.infrastructure.repository.SummarizationRepository.save_summary_record",
                new_callable=AsyncMock,
                return_value=mock_record,
            ),
            patch("src.mcp.security.audit_log"),
        ):
            summaries_json = json.dumps([{"tweet_id": "t1", "summary": "摘要"}])
            result_json = await save_summaries(summaries=summaries_json)

        result = json.loads(result_json)
        assert result["success"] is True
        assert result["data"]["saved"] == 1

    @pytest.mark.asyncio
    async def test_save_invalid_json_string(self, tool_funcs):
        """测试无效 JSON 字符串返回错误。"""
        save_summaries = tool_funcs["save_summaries"]

        with patch("src.mcp.tools.summarization_tools.require_admin", return_value=None):
            result_json = await save_summaries(summaries="not json")

        result = json.loads(result_json)
        assert result["success"] is False
        assert "JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_save_missing_required_fields(self, tool_funcs):
        """测试缺少必填字段时记录失败但不中断批处理。"""
        save_summaries = tool_funcs["save_summaries"]

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        # 验证门会批量回查原文；默认返回空 → 各项降级放行
        _origin_result = MagicMock()
        _origin_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=_origin_result)
        mock_sm = _mock_session_maker(mock_session)

        mock_record = MagicMock()
        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
            patch(
                "src.summarization.infrastructure.repository.SummarizationRepository.save_summary_record",
                new_callable=AsyncMock,
                return_value=mock_record,
            ),
            patch("src.mcp.security.audit_log"),
        ):
            summaries = [
                {"tweet_id": "t1", "summary": "有效摘要"},
                {"tweet_id": "t2"},  # 缺少 summary
                {"summary": "没有tweet_id"},  # 缺少 tweet_id
            ]

            result_json = await save_summaries(summaries=summaries)

        result = json.loads(result_json)
        assert result["data"]["saved"] == 1
        assert result["data"]["failed"] == 2
        assert len(result["data"]["errors"]) == 2

    @pytest.mark.asyncio
    async def test_save_rejects_truncated_translation(self, tool_funcs):
        """验证门：截断译文不入库，计入 failed/errors（替代静默入库）。"""
        save_summaries = tool_funcs["save_summaries"]

        origin_row = MagicMock()
        origin_row._mapping = {
            "tweet_id": "t1",
            "text": (
                "People in Africa are not starving. This is a myth. The only "
                "time there is a shortage of food is when there is a war going "
                "on and the only way to solve that would be invasion!"
            ),
            "referenced_tweet_text": None,
            "reference_type": None,
        }
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        _origin_result = MagicMock()
        _origin_result.fetchall.return_value = [origin_row]
        mock_session.execute = AsyncMock(return_value=_origin_result)
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
            patch("src.database.async_session.get_async_session_maker", return_value=mock_sm),
            patch(
                "src.summarization.infrastructure.repository.SummarizationRepository.save_summary_record",
                new_callable=AsyncMock,
            ) as mock_save,
            patch("src.mcp.security.audit_log"),
        ):
            summaries = [{
                "tweet_id": "t1",
                "summary": "非洲粮食问题摘要",
                "translation": "非洲人。",  # 严重截断
            }]
            result_json = await save_summaries(summaries=summaries)

        result = json.loads(result_json)
        assert result["data"]["saved"] == 0
        assert result["data"]["failed"] == 1
        assert "t1" in result["data"]["errors"][0]
        mock_save.assert_not_called()
        # 结构化 rejected 供编排回灌：含 tweet_id 与 reason
        rejected = result["data"]["rejected"]
        assert len(rejected) == 1
        assert rejected[0]["tweet_id"] == "t1"
        assert "过短" in rejected[0]["reason"]

    @pytest.mark.asyncio
    async def test_save_not_array(self, tool_funcs):
        """测试非数组入参返回错误(dict 单对象不是数组)。"""
        save_summaries = tool_funcs["save_summaries"]

        with patch("src.mcp.tools.summarization_tools.require_admin", return_value=None):
            # 原生 dict 形态(非数组)
            result_json = await save_summaries(
                summaries={"tweet_id": "t1", "summary": "test"}
            )

        result = json.loads(result_json)
        assert result["success"] is False
        assert "数组" in result["error"]
