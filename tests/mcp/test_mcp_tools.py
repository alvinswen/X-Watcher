"""MCP 工具单元测试。

测试所有 Phase 1 MCP 工具的参数解析、服务调用和返回格式。
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 辅助：创建工具函数引用 ────────────────────────────────────────


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
    """创建 mock session_maker，使 async with session_maker() as session 工作。"""
    sm = MagicMock()
    sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    sm.return_value.__aexit__ = AsyncMock(return_value=False)
    return sm


# ── get_feed 测试 ─────────────────────────────────────────────────


class TestGetFeed:
    @pytest.mark.asyncio
    async def test_get_feed_success(self, tool_funcs):
        """测试正常查询 feed。"""
        mock_result = MagicMock()
        mock_result.items = [
            {
                "tweet_id": "123",
                "text": "Hello world",
                "author_username": "testuser",
                "created_at": datetime(2026, 2, 24, tzinfo=timezone.utc),
            }
        ]
        mock_result.count = 1
        mock_result.total = 1
        mock_result.has_more = False

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.feed.services.feed_service.FeedService.get_feed",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result = await tool_funcs["get_feed"](
                since="2026-02-24T00:00:00Z",
                until="2026-02-25T00:00:00Z",
            )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["count"] == 1
        assert data["data"]["total"] == 1
        assert data["data"]["has_more"] is False

    @pytest.mark.asyncio
    async def test_get_feed_invalid_date(self, tool_funcs):
        """测试无效日期参数。"""
        result = await tool_funcs["get_feed"](since="not-a-date")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "validation"

    @pytest.mark.asyncio
    async def test_get_feed_default_until(self, tool_funcs):
        """测试 until 默认为当前时间。"""
        mock_result = MagicMock()
        mock_result.items = []
        mock_result.count = 0
        mock_result.total = 0
        mock_result.has_more = False

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.feed.services.feed_service.FeedService.get_feed",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result = await tool_funcs["get_feed"](
                since="2026-02-24T00:00:00Z",
            )

        data = json.loads(result)
        assert data["success"] is True


# ── search_tweets 测试 ────────────────────────────────────────────


class TestSearchTweets:
    @pytest.mark.asyncio
    async def test_search_success(self, tool_funcs):
        """测试正常搜索。"""
        mock_result = MagicMock()
        mock_result.items = [{"tweet_id": "456", "text": "test tweet"}]
        mock_result.total = 1

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.search.services.search_service.SearchService.search_tweets",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result = await tool_funcs["search_tweets"](q="test")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["q"] == "test"

    @pytest.mark.asyncio
    async def test_search_empty_query(self, tool_funcs):
        """测试空搜索关键词。"""
        result = await tool_funcs["search_tweets"](q="")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "validation"

    @pytest.mark.asyncio
    async def test_search_whitespace_query(self, tool_funcs):
        """测试纯空格搜索关键词。"""
        result = await tool_funcs["search_tweets"](q="   ")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "validation"


# ── get_daily_stats 测试 ──────────────────────────────────────────


class TestGetDailyStats:
    @pytest.mark.asyncio
    async def test_success(self, tool_funcs):
        """测试正常获取每日统计。"""
        mock_stats = [
            {"date": "2026-02-24", "count": 10},
            {"date": "2026-02-25", "count": 5},
        ]

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.browse.services.browse_service.BrowseService.get_daily_stats",
                new_callable=AsyncMock,
                return_value=mock_stats,
            ),
        ):
            result = await tool_funcs["get_daily_stats"](year=2026, month=2)

        data = json.loads(result)
        assert data["success"] is True
        assert len(data["data"]["daily_stats"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_month(self, tool_funcs):
        """测试无效月份。"""
        result = await tool_funcs["get_daily_stats"](year=2026, month=13)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "validation"


# ── get_authors_for_date 测试 ─────────────────────────────────────


class TestGetAuthorsForDate:
    @pytest.mark.asyncio
    async def test_success(self, tool_funcs):
        """测试正常获取作者列表。"""
        mock_authors = [
            {
                "author_username": "user1",
                "author_display_name": "User One",
                "tweet_count": 5,
                "last_tweet_at": datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc),
                "reason": "KOL",
            }
        ]

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.browse.services.browse_service.BrowseService.get_authors",
                new_callable=AsyncMock,
                return_value=mock_authors,
            ),
        ):
            result = await tool_funcs["get_authors_for_date"](date="2026-02-24")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["count"] == 1


# ── browse_tweets 测试 ────────────────────────────────────────────


class TestBrowseTweets:
    @pytest.fixture(autouse=True)
    def _pin_sqlalchemy_layer(self, monkeypatch):
        """钉 sqlalchemy:本组 patch BrowseService.get_tweets(=测 ORM 路径)。A1-2 接线后
        browse_tweets 走 get_browse_repo,若本机 .env=file 则返 FileBrowseReadStore 绕过
        patch、命中真数据 → 漂移。钉 sqlalchemy 使 get_browse_repo 返 BrowseService、patch 命中
        (沿 A1-1 I-1 / 3aa66d2 范式)。"""
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")

    @pytest.mark.asyncio
    async def test_success(self, tool_funcs):
        """测试正常浏览推文。"""
        mock_items = [{"tweet_id": "789", "text": "Hello"}]
        mock_total = 1

        mock_session = AsyncMock()
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.browse.services.browse_service.BrowseService.get_tweets",
                new_callable=AsyncMock,
                return_value=(mock_items, mock_total),
            ),
        ):
            result = await tool_funcs["browse_tweets"](date="2026-02-24")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] == 1

    @pytest.mark.asyncio
    async def test_invalid_page(self, tool_funcs):
        """测试无效页码。"""
        result = await tool_funcs["browse_tweets"](date="2026-02-24", page=0)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "validation"


# ── get_system_status 测试 ────────────────────────────────────────


class TestGetSystemStatus:
    @pytest.mark.asyncio
    async def test_success(self, tool_funcs):
        """测试正常获取系统状态。"""
        mock_session = AsyncMock()

        # Mock execute 返回不同的 scalar/first 值
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar.return_value = 100
            result.first.return_value = None
            return result

        mock_session.execute = mock_execute
        mock_sm = _mock_session_maker(mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_sm,
            ),
            patch(
                "src.config.get_settings",
            ) as mock_settings,
        ):
            mock_settings.return_value.database_url = "sqlite:///./test.db"
            result = await tool_funcs["get_system_status"]()

        data = json.loads(result)
        assert data["success"] is True
        assert "tweets" in data["data"]
        assert "follows" in data["data"]
        assert "summaries" in data["data"]
        assert "topics" not in data["data"]
        assert "scheduler" not in data["data"]
        assert "system" in data["data"]


# ── helpers 测试 ──────────────────────────────────────────────────


class TestHelpers:
    def test_success_response(self):
        from src.mcp.helpers import success_response

        result = json.loads(success_response({"key": "value"}))
        assert result["success"] is True
        assert result["data"]["key"] == "value"

    def test_error_response(self):
        from src.mcp.helpers import error_response

        result = json.loads(error_response("test error", "validation"))
        assert result["success"] is False
        assert result["error"] == "test error"
        assert result["error_type"] == "validation"

    def test_datetime_serialization(self):
        from src.mcp.helpers import success_response

        dt = datetime(2026, 2, 24, 12, 0, tzinfo=timezone.utc)
        result = json.loads(success_response({"time": dt}))
        assert result["data"]["time"] == "2026-02-24T12:00:00+00:00"


# ── auth 测试 ─────────────────────────────────────────────────────


class TestMCPAuth:
    def test_stdio_default_admin(self):
        from src.mcp.auth import configure_transport, get_transport, is_admin

        configure_transport("stdio")
        assert is_admin() is True
        assert get_transport() == "stdio"

    def test_sse_no_token_not_admin(self):
        from src.mcp.auth import configure_transport, get_transport, is_admin

        configure_transport("sse")
        # HTTP 模式下无 ContextVar token → 非 admin
        assert is_admin() is False
        assert get_transport() == "sse"

    def test_sse_admin_token_in_context(self):
        from mcp.server.auth.middleware.auth_context import auth_context_var
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
        from mcp.server.auth.provider import AccessToken

        from src.mcp.auth import configure_transport, is_admin

        configure_transport("sse")

        # 模拟 per-request ContextVar 中有 admin token
        token = AccessToken(
            token="test-admin-key",
            client_id="admin",
            scopes=["admin", "user"],
        )
        auth_user = AuthenticatedUser(token)
        ctx_token = auth_context_var.set(auth_user)
        try:
            assert is_admin() is True
        finally:
            auth_context_var.reset(ctx_token)

    def test_require_admin_pass(self):
        from src.mcp.auth import configure_transport, require_admin

        configure_transport("stdio")
        assert require_admin() is None

    def test_require_admin_fail(self):
        from src.mcp.auth import configure_transport, require_admin

        configure_transport("sse")
        result = require_admin()
        assert result is not None
        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "permission"


# ── server 测试 ───────────────────────────────────────────────────


class TestMCPServer:
    def test_create_server(self):
        from src.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        assert mcp.name == "x-watcher"

    # 注：工具/资源注册完整性测试在 test_mcp_integration.py::TestToolRegistration 中


class TestTriggerScrape:
    """trigger_scrape 工具的 skip_summarization 参数测试。"""

    @pytest.mark.asyncio
    async def test_trigger_scrape_passes_skip_summarization_to_service(self, tool_funcs):
        """测试 skip_summarization=True 传递给 ScrapingService。"""
        trigger_scrape = tool_funcs["trigger_scrape"]

        mock_service_instance = AsyncMock()
        mock_service_instance.scrape_users = AsyncMock(return_value="task-123")

        with (
            patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
            patch("src.mcp.security.check_scrape_guard", return_value=None),
            patch(
                "src.mcp.tools.admin_tools.resolve_user_list",
                new_callable=AsyncMock,
                return_value=["user1"],
            ),
            patch("src.mcp.security.audit_log"),
            patch("src.scraper.task_registry.TaskRegistry.get_instance") as mock_registry,
            patch(
                "src.scraper.ScrapingService", return_value=mock_service_instance
            ) as mock_service_cls,
        ):
            mock_registry.return_value.get_tasks_by_status.return_value = []

            result_json = await trigger_scrape(
                usernames="user1",
                limit=10,
                skip_summarization=True,
            )

            # 验证 ScrapingService 被传入 skip_summarization=True
            mock_service_cls.assert_called_once_with(skip_summarization=True)

            result = json.loads(result_json)
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_trigger_scrape_default_skip_summarization_false(self, tool_funcs):
        """测试默认 skip_summarization=False。"""
        trigger_scrape = tool_funcs["trigger_scrape"]

        mock_service_instance = AsyncMock()
        mock_service_instance.scrape_users = AsyncMock(return_value="task-123")

        with (
            patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
            patch("src.mcp.security.check_scrape_guard", return_value=None),
            patch(
                "src.mcp.tools.admin_tools.resolve_user_list",
                new_callable=AsyncMock,
                return_value=["user1"],
            ),
            patch("src.mcp.security.audit_log"),
            patch("src.scraper.task_registry.TaskRegistry.get_instance") as mock_registry,
            patch(
                "src.scraper.ScrapingService", return_value=mock_service_instance
            ) as mock_service_cls,
        ):
            mock_registry.return_value.get_tasks_by_status.return_value = []

            await trigger_scrape(
                usernames="user1",
                limit=10,
            )

            # 默认不传 skip_summarization，应为 False
            mock_service_cls.assert_called_once_with(skip_summarization=False)
