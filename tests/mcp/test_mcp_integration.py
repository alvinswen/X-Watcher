"""MCP 工具集成测试。

使用真实内存数据库，验证 MCP 工具的端到端流程：
数据写入 → 工具调用 → 服务层查询 → 返回结果。
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScraperFollow
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.topic.infrastructure.models import TopicOrm, TopicAccountOrm


# ── 辅助 ──────────────────────────────────────────────────────────


def _get_tool_funcs():
    """通过 FastMCP 实例获取注册的工具函数。"""
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    tools = mcp._tool_manager._tools
    return {name: tool.fn for name, tool in tools.items()}


@pytest.fixture
def tool_funcs():
    return _get_tool_funcs()


# ── 数据准备 fixtures ─────────────────────────────────────────────


@pytest.fixture
async def seed_tweets(async_session: AsyncSession):
    """准备推文和摘要测试数据。"""
    base_time = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc)

    tweets = [
        TweetOrm(
            tweet_id="integ_t1",
            text="Integration test tweet about Bitcoin from alice",
            created_at=base_time,
            db_created_at=base_time,
            author_username="alice",
            author_display_name="Alice",
            media=None,
        ),
        TweetOrm(
            tweet_id="integ_t2",
            text="Another tweet about Ethereum from alice",
            created_at=base_time + timedelta(hours=2),
            db_created_at=base_time + timedelta(hours=2),
            author_username="alice",
            author_display_name="Alice",
            media=None,
        ),
        TweetOrm(
            tweet_id="integ_t3",
            text="Bob talks about AI and machine learning",
            created_at=base_time + timedelta(hours=3),
            db_created_at=base_time + timedelta(hours=3),
            author_username="bob",
            author_display_name="Bob",
            media=None,
        ),
        TweetOrm(
            tweet_id="integ_t4",
            text="Short tweet",
            created_at=base_time + timedelta(days=1),
            db_created_at=base_time + timedelta(days=1),
            author_username="bob",
            author_display_name="Bob",
            media=None,
        ),
    ]
    async_session.add_all(tweets)

    summaries = [
        SummaryOrm(
            summary_id="sum_integ_1",
            tweet_id="integ_t1",
            summary_text="关于比特币的集成测试推文",
            translation_text="集成测试推文，关于比特币，来自 alice",
            model_provider="test",
            model_name="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            cached=False,
            is_generated_summary=True,
            content_hash="hash_integ_1",
        ),
        SummaryOrm(
            summary_id="sum_integ_2",
            tweet_id="integ_t3",
            summary_text="Bob 谈论 AI 和机器学习",
            translation_text="Bob 讨论人工智能与机器学习",
            model_provider="test",
            model_name="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            cached=False,
            is_generated_summary=True,
            content_hash="hash_integ_2",
        ),
    ]
    async_session.add_all(summaries)
    await async_session.commit()

    return tweets


@pytest.fixture
async def seed_follows(async_session: AsyncSession):
    """准备关注列表数据。"""
    follows = [
        ScraperFollow(
            username="alice",
            reason="KOL",
            is_active=True,
            added_by="test",
        ),
        ScraperFollow(
            username="bob",
            reason="Developer",
            is_active=True,
            added_by="test",
        ),
        ScraperFollow(
            username="charlie",
            reason="Analyst",
            is_active=False,
            added_by="test",
        ),
    ]
    async_session.add_all(follows)
    await async_session.commit()
    return follows


@pytest.fixture
async def seed_topics(async_session: AsyncSession):
    """准备主题数据。"""
    topic = TopicOrm(name="Crypto Watch", description="Monitor crypto KOLs")
    async_session.add(topic)
    await async_session.flush()

    accounts = [
        TopicAccountOrm(topic_id=topic.id, username="alice"),
        TopicAccountOrm(topic_id=topic.id, username="bob"),
    ]
    async_session.add_all(accounts)
    await async_session.commit()
    return topic


# ── get_feed 集成测试 ─────────────────────────────────────────────


class TestGetFeedIntegration:
    @pytest.mark.asyncio
    async def test_feed_returns_real_tweets(
        self, tool_funcs, test_session_factory, seed_tweets
    ):
        """测试 get_feed 从真实数据库查询推文。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["get_feed"](
                since="2026-02-20T00:00:00Z",
                until="2026-02-22T00:00:00Z",
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] >= 3  # 至少有 3 条在这个范围内

    @pytest.mark.asyncio
    async def test_feed_filter_by_author(
        self, tool_funcs, test_session_factory, seed_tweets
    ):
        """测试按作者过滤 feed。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["get_feed"](
                since="2026-02-20T00:00:00Z",
                until="2026-02-22T00:00:00Z",
                author="alice",
            )

        data = json.loads(result)
        assert data["success"] is True
        # alice 有 2 条推文在这个时间范围内
        for item in data["data"]["items"]:
            assert item["author_username"].lower() == "alice"


# ── search_tweets 集成测试 ────────────────────────────────────────


class TestSearchTweetsIntegration:
    @pytest.mark.asyncio
    async def test_search_finds_matching_tweets(
        self, tool_funcs, test_session_factory, seed_tweets
    ):
        """测试搜索能找到匹配的推文。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["search_tweets"](q="Bitcoin")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] >= 1
        assert data["data"]["q"] == "Bitcoin"

    @pytest.mark.asyncio
    async def test_search_no_results(
        self, tool_funcs, test_session_factory, seed_tweets
    ):
        """测试搜索无结果时的返回。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["search_tweets"](q="nonexistent_keyword_xyz")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] == 0


# ── browse 集成测试 ───────────────────────────────────────────────


class TestBrowseIntegration:
    @pytest.mark.asyncio
    async def test_daily_stats_with_real_data(
        self, tool_funcs, test_session_factory, seed_tweets
    ):
        """测试真实数据的每日统计。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            # 使用 tz_offset=0 (UTC) 简化测试
            result = await tool_funcs["get_daily_stats"](
                year=2026, month=2, tz_offset=0
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["year"] == 2026
        assert data["data"]["month"] == 2
        # 至少有数据（seed_tweets 创建了 2026-02-20 和 2026-02-21 的推文）
        assert len(data["data"]["daily_stats"]) >= 1

    @pytest.mark.asyncio
    async def test_browse_tweets_with_real_data(
        self, tool_funcs, test_session_factory, seed_tweets
    ):
        """测试真实数据的推文浏览。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["browse_tweets"](
                date="2026-02-20", tz_offset=0
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] >= 1
        assert data["data"]["date"] == "2026-02-20"


# ── topic 集成测试 ────────────────────────────────────────────────


class TestTopicIntegration:
    @pytest.mark.asyncio
    async def test_list_topics_with_real_data(
        self, tool_funcs, test_session_factory, seed_topics
    ):
        """测试列出真实主题。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["list_topics"]()

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["count"] >= 1
        topic_names = [t["name"] for t in data["data"]["topics"]]
        assert "Crypto Watch" in topic_names

    @pytest.mark.asyncio
    async def test_get_topic_detail(
        self, tool_funcs, test_session_factory, seed_topics
    ):
        """测试获取主题详情。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["get_topic"](topic_id=seed_topics.id)

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["name"] == "Crypto Watch"
        assert len(data["data"]["accounts"]) == 2

    @pytest.mark.asyncio
    async def test_manage_topic_create_and_delete(
        self, tool_funcs, test_session_factory, seed_topics
    ):
        """测试创建和删除主题的完整流程。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            # 创建新主题
            create_result = await tool_funcs["manage_topic"](
                action="create",
                name="AI Research",
                description="Monitor AI researchers",
            )
            create_data = json.loads(create_result)
            assert create_data["success"] is True
            assert create_data["data"]["action"] == "created"
            new_id = create_data["data"]["topic"]["id"]

            # 删除
            delete_result = await tool_funcs["manage_topic"](
                action="delete", topic_id=new_id
            )
            delete_data = json.loads(delete_result)
            assert delete_data["success"] is True
            assert delete_data["data"]["action"] == "deleted"


# ── admin 工具集成测试 ────────────────────────────────────────────


class TestAdminToolsIntegration:
    @pytest.mark.asyncio
    async def test_manage_follows_list(
        self, tool_funcs, test_session_factory, seed_follows
    ):
        """测试列出关注列表。"""
        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=test_session_factory,
            ),
            patch("src.mcp.auth.require_admin", return_value=None),
        ):
            result = await tool_funcs["manage_follows"](action="list")

        data = json.loads(result)
        assert data["success"] is True
        # 默认不含 inactive
        assert data["data"]["count"] == 2
        usernames = [f["username"] for f in data["data"]["follows"]]
        assert "alice" in usernames
        assert "bob" in usernames

    @pytest.mark.asyncio
    async def test_manage_follows_list_include_inactive(
        self, tool_funcs, test_session_factory, seed_follows
    ):
        """测试列出关注列表（含非活跃）。"""
        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=test_session_factory,
            ),
            patch("src.mcp.auth.require_admin", return_value=None),
        ):
            result = await tool_funcs["manage_follows"](
                action="list", include_inactive=True
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["count"] == 3

    @pytest.mark.asyncio
    async def test_admin_tools_require_permission(self, tool_funcs):
        """测试 admin 工具在无权限时拒绝访问。"""
        import src.mcp.auth as auth_mod

        original_transport = auth_mod._transport
        try:
            auth_mod._transport = "sse"
            # HTTP 模式下无 ContextVar token → is_admin() 返回 False
            result = await tool_funcs["manage_follows"](action="list")
        finally:
            auth_mod._transport = original_transport

        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "permission"


# ── get_system_status 集成测试 ────────────────────────────────────


class TestSystemStatusIntegration:
    @pytest.mark.asyncio
    async def test_status_with_real_data(
        self, tool_funcs, test_session_factory, seed_tweets, seed_follows
    ):
        """测试系统状态返回真实数据统计。"""
        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=test_session_factory,
            ),
            patch("src.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.database_url = "sqlite:///:memory:"
            result = await tool_funcs["get_system_status"]()

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["tweets"]["total"] == 4
        assert data["data"]["follows"]["active"] == 2


# ── 工具注册完整性测试 ────────────────────────────────────────────


class TestToolRegistration:
    def test_all_tools_registered(self):
        """验证全部工具已注册。"""
        from src.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        tool_names = set(mcp._tool_manager._tools.keys())
        expected = {
            # Phase 1: Feed + Browse + Status (7)
            "get_feed",
            "search_tweets",
            "get_daily_stats",
            "get_authors_for_date",
            "browse_tweets",
            "get_system_status",
            "get_audit_log",
            # Phase 2: Topic + Analytics (6)
            "list_topics",
            "get_topic",
            "manage_topic",
            "manage_topic_accounts",
            "get_topic_summary",
            "get_posting_frequency",
            # Phase 3: Admin (7)
            "manage_follows",
            "trigger_scrape",
            "trigger_backfill",
            "get_task_status",
            "manage_scheduler",
            "batch_summarize",
            "get_follow_accounts_info",
            # Phase 3: Summarization (2)
            "get_unsummarized_tweets",
            "save_summaries",
        }
        assert expected == tool_names, f"差异: 多余={tool_names - expected}, 缺少={expected - tool_names}"

    def test_all_resources_registered(self):
        """验证全部资源已注册。"""
        from src.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        resource_uris = set(mcp._resource_manager._resources.keys())
        expected = {
            "xwatcher://status",
            "xwatcher://follows",
            "xwatcher://topics",
            "xwatcher://config",
            "xwatcher://recipes/daily-summary",
            "xwatcher://recipes/claude-code-summarize",
        }
        assert expected == resource_uris, f"差异: 多余={resource_uris - expected}, 缺少={expected - resource_uris}"
