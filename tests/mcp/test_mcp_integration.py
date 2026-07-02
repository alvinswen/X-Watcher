"""MCP 工具集成测试。

使用真实内存数据库，验证 MCP 工具的端到端流程：
数据写入 → 工具调用 → 服务层查询 → 返回结果。
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ScraperFollow
from src.database.x_user_profile_model import XUserProfileOrm
from src.scraper.infrastructure.models import TweetOrm
from src.subjects.models import SubjectMatch
from src.subjects.store import FileSubjectStore
from src.summarization.infrastructure.models import SummaryOrm

# ── 辅助 ──────────────────────────────────────────────────────────


def _get_tool_funcs():
    """通过 FastMCP 实例获取注册的工具函数。"""
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    tools = mcp._tool_manager._tools
    return {name: tool.fn for name, tool in tools.items()}


def test_run_mcp_server_rejects_weak_jwt_secret(monkeypatch, capsys):
    """测试 MCP 入口对弱默认 JWT 密钥 fail-loud 拒起。"""
    from src.config import clear_settings_cache
    from src.mcp import server as mcp_server

    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")
    clear_settings_cache()

    with (
        patch.object(mcp_server, "init_mcp_logging") as init_logging,
        patch.object(mcp_server, "configure_transport") as configure_transport,
        patch.object(mcp_server, "create_mcp_server") as create_mcp_server,
        pytest.raises(SystemExit) as exc_info,
    ):
        mcp_server.run_mcp_server(transport="stdio")

    assert exc_info.value.code == 1
    init_logging.assert_not_called()
    configure_transport.assert_not_called()
    create_mcp_server.assert_not_called()
    stderr = capsys.readouterr().err
    assert "JWT 签名密钥强度校验未通过" in stderr
    assert "默认值" in stderr
    assert 'python -c "import secrets;print(secrets.token_urlsafe(32))"' in stderr
    assert "Traceback" not in stderr

    clear_settings_cache()


def test_run_mcp_server_allows_strong_jwt_secret(monkeypatch):
    """测试 MCP 入口在强 JWT 密钥下正常进入运行流程。"""
    from src.config import clear_settings_cache
    from src.mcp import server as mcp_server

    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)
    clear_settings_cache()
    mcp = MagicMock()

    with (
        patch.object(mcp_server, "init_mcp_logging") as init_logging,
        patch.object(mcp_server, "configure_transport") as configure_transport,
        patch.object(mcp_server, "create_mcp_server", return_value=mcp) as create_mcp_server,
    ):
        mcp_server.run_mcp_server(transport="stdio")

    init_logging.assert_called_once_with(stderr_only=True)
    configure_transport.assert_called_once_with("stdio")
    create_mcp_server.assert_called_once_with(
        host="0.0.0.0",
        port=8001,
        use_auth=False,
    )
    mcp.run.assert_called_once_with(transport="stdio")

    clear_settings_cache()


@pytest.fixture
def tool_funcs():
    return _get_tool_funcs()


# ── 数据准备 fixtures ─────────────────────────────────────────────


@pytest.fixture
async def seed_tweets(async_session: AsyncSession):
    """准备推文和摘要测试数据。"""
    base_time = datetime(2026, 2, 20, 10, 0, 0, tzinfo=UTC)

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


# ── get_feed 集成测试 ─────────────────────────────────────────────


class TestGetFeedIntegration:
    @pytest.mark.asyncio
    async def test_feed_returns_real_tweets(self, tool_funcs, test_session_factory, seed_tweets):
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
    async def test_feed_filter_by_author(self, tool_funcs, test_session_factory, seed_tweets):
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
    async def test_search_no_results(self, tool_funcs, test_session_factory, seed_tweets):
        """测试搜索无结果时的返回。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            result = await tool_funcs["search_tweets"](q="nonexistent_keyword_xyz")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] == 0


# ── Subject 工具集成测试 ──────────────────────────────────────────


class TestSubjectToolsIntegration:
    @pytest.mark.asyncio
    async def test_subject_digest_publish_requires_write_scope(self, tool_funcs):
        import src.mcp.auth as auth_mod

        original_transport = auth_mod._transport
        try:
            auth_mod._transport = "sse"
            result = await tool_funcs["put_subject_digest"](
                subject_id="sub_missing",
                interval_start="2026-06-28T10:00:00Z",
                interval_end="2026-06-28T11:00:00Z",
                time_axis="publish",
                digest_text="无权限不应写入",
            )
        finally:
            auth_mod._transport = original_transport

        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "permission"

    @pytest.mark.asyncio
    async def test_subject_feed_publish_and_digest_accepts_structured_highlights(
        self, tool_funcs, tmp_path
    ):
        repo = FileSubjectStore(tmp_path)
        subject = await repo.create_subject(
            name="发布轴议题",
            nl_description="验证 MCP 发布轴与结构化 highlights",
        )
        base = datetime(2026, 6, 28, 10, tzinfo=UTC)
        await repo.upsert_matches(
            [
                SubjectMatch(
                    subject_id=subject.subject_id,
                    tweet_id="publish_in",
                    matched_at=base - timedelta(days=1),
                ),
                SubjectMatch(
                    subject_id=subject.subject_id,
                    tweet_id="ingest_only",
                    matched_at=base + timedelta(minutes=5),
                ),
                SubjectMatch(
                    subject_id=subject.subject_id,
                    tweet_id="missing",
                    matched_at=base + timedelta(minutes=6),
                ),
            ]
        )

        async def fake_get_tweets_by_ids(tweet_ids: list[str]):
            created_by_id = {
                "publish_in": base + timedelta(minutes=5),
                "ingest_only": base - timedelta(days=1),
            }
            items = [
                {"tweet_id": tweet_id, "created_at": created_by_id[tweet_id]}
                for tweet_id in tweet_ids
                if tweet_id in created_by_id
            ]
            missing = [tweet_id for tweet_id in tweet_ids if tweet_id not in created_by_id]
            return items, missing

        repo.get_tweets_by_ids = fake_get_tweets_by_ids  # type: ignore[method-assign]

        with patch("src.mcp.tools.subject_tools.get_subject_repo", return_value=repo):
            feed_result = await tool_funcs["get_subject_feed"](
                subject_id=subject.subject_id,
                since=base.isoformat(),
                until=(base + timedelta(hours=1)).isoformat(),
                time_axis="publish",
            )
            feed_data = json.loads(feed_result)
            assert feed_data["success"] is True
            assert [item["tweet_id"] for item in feed_data["data"]["items"]] == ["publish_in"]

            digest_result = await tool_funcs["put_subject_digest"](
                subject_id=subject.subject_id,
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
                time_axis="publish",
                digest_text="发布轴 MCP 正文",
                highlights=[
                    {"point": "发布轴命中", "cited_tweet_ids": ["publish_in"]},
                ],
                cited="publish_in",
            )
            digest_data = json.loads(digest_result)
            assert digest_data["success"] is True
            assert digest_data["data"]["skipped_no_publish_time"] == 1
            assert digest_data["data"]["skipped_no_publish_time_ids"] == ["missing"]

            invalid_result = await tool_funcs["put_subject_digest"](
                subject_id=subject.subject_id,
                interval_start=base.isoformat(),
                interval_end=(base + timedelta(hours=1)).isoformat(),
                digest_text="非法 highlights",
                highlights=["not-an-object"],
            )
            invalid_data = json.loads(invalid_result)
            assert invalid_data["success"] is False
            assert invalid_data["error_type"] == "validation"

    @pytest.mark.asyncio
    async def test_subject_review_accepts_structured_and_string_sections_trend(
        self, tool_funcs, tmp_path
    ):
        repo = FileSubjectStore(tmp_path)
        subject = await repo.create_subject(
            name="综述议题",
            nl_description="验证 MCP sections/trend 容错",
        )
        await repo.set_pending(subject.subject_id, review=True)
        covered_until = datetime(2026, 6, 28, 12, tzinfo=UTC)

        with patch("src.mcp.tools.subject_tools.get_subject_repo", return_value=repo):
            structured_result = await tool_funcs["put_subject_review"](
                subject_id=subject.subject_id,
                prev_version=0,
                sections=[{"title": "总览", "body": "结构化章节"}],
                covered_until=covered_until.isoformat(),
                trend={"emerging": ["发布轴"], "fading": []},
            )
            structured_data = json.loads(structured_result)
            assert structured_data["success"] is True
            assert structured_data["data"]["version"] == 1

            string_result = await tool_funcs["put_subject_review"](
                subject_id=subject.subject_id,
                prev_version=1,
                sections=json.dumps([{"title": "后续", "body": "字符串章节"}]),
                covered_until=(covered_until + timedelta(hours=1)).isoformat(),
                trend=json.dumps({"emerging": ["容错"], "fading": []}),
            )
            string_data = json.loads(string_result)
            assert string_data["success"] is True
            assert string_data["data"]["version"] == 2


# ── browse 集成测试 ───────────────────────────────────────────────


class TestBrowseIntegration:
    @pytest.mark.asyncio
    async def test_daily_stats_with_real_data(self, tool_funcs, test_session_factory, seed_tweets):
        """测试真实数据的每日统计。"""
        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=test_session_factory,
        ):
            # 使用 tz_offset=0 (UTC) 简化测试
            result = await tool_funcs["get_daily_stats"](year=2026, month=2, tz_offset=0)

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
            result = await tool_funcs["browse_tweets"](date="2026-02-20", tz_offset=0)

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] >= 1
        assert data["data"]["date"] == "2026-02-20"


# ── admin 工具集成测试 ────────────────────────────────────────────


class TestAdminToolsIntegration:
    @pytest.mark.asyncio
    async def test_manage_follows_list(self, tool_funcs, test_session_factory, seed_follows):
        """测试列出关注列表。"""
        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=test_session_factory,
            ),
            patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
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
            patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
        ):
            result = await tool_funcs["manage_follows"](action="list", include_inactive=True)

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


# ── get_follow_accounts_info 集成测试 ─────────────────────────────


class TestFollowAccountsInfoIntegration:
    @pytest.mark.asyncio
    async def test_profiles_returns_cached_profile_fields(
        self, tool_funcs, async_session, test_session_factory
    ):
        """测试 profiles 类型返回档案字段（bio 映射 description、tweet_count 映射 statuses_count）。"""
        async_session.add(
            XUserProfileOrm(
                platform_user_id="uid_tony",
                username="tdinh_me",
                display_name="Tony Dinh",
                description="Indie hacker building apps",
                followers_count=150000,
                following_count=300,
                statuses_count=417,
                fetched_at=datetime(2026, 6, 1, 0, 0, 0),
            )
        )
        await async_session.commit()

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=test_session_factory,
            ),
            patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
        ):
            result = await tool_funcs["get_follow_accounts_info"](info_type="profiles")

        data = json.loads(result)
        assert data["success"] is True, f"profiles 查询失败: {data.get('error')}"
        assert data["data"]["count"] == 1
        profile = data["data"]["profiles"][0]
        assert profile["username"] == "tdinh_me"
        assert profile["display_name"] == "Tony Dinh"
        assert profile["bio"] == "Indie hacker building apps"
        assert profile["followers_count"] == 150000
        assert profile["following_count"] == 300
        assert profile["tweet_count"] == 417


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
            # Admin
            "manage_follows",
            "trigger_scrape",
            "trigger_backfill",
            "get_task_status",
            "batch_summarize",
            "get_follow_accounts_info",
            # Summarization
            "get_unsummarized_tweets",
            "save_summaries",
            # Subject（CHG-004 · 议题 continuous-query 一期）
            "list_subjects",
            "get_subject_feed",
            "get_subject_candidate_set",
            "get_subject_digest",
            "get_subject_updates",
            "get_tweets_by_ids",
            "put_subject_matches",
            "put_subject_digest",
            "put_subject_review",
            "put_subject_feedback",
            "get_subject_feedback",
            "put_subject_eval",
            "get_subject_eval",
            "run_subject_hygiene_check",
            "get_subject_correction_rate",
            "get_pending_jobs",
            # Subject Review（CHG-006 · L2 活综述）
            "get_subject_review",
            "refresh_subject_review",
        }
        assert (
            expected == tool_names
        ), f"差异: 多余={tool_names - expected}, 缺少={expected - tool_names}"

    def test_all_resources_registered(self):
        """验证全部资源已注册。"""
        from src.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        resource_uris = set(mcp._resource_manager._resources.keys())
        expected = {
            "xwatcher://status",
            "xwatcher://follows",
            "xwatcher://config",
            "xwatcher://recipes/daily-summary",
            "xwatcher://recipes/claude-code-summarize",
        }
        assert (
            expected == resource_uris
        ), f"差异: 多余={resource_uris - expected}, 缺少={expected - resource_uris}"
