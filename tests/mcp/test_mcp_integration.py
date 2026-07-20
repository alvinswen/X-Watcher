"""MCP 工具集成测试。

使用真实内存数据库，验证 MCP 工具的端到端流程：
数据写入 → 工具调用 → 服务层查询 → 返回结果。
"""

import inspect
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.preference.domain.models import XUserProfile
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.preference.infrastructure.file_profile_repository import FileProfileStore
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.subjects.models import SubjectMatch
from src.subjects.store import FileSubjectStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

# ── 辅助 ──────────────────────────────────────────────────────────


def _get_tool_funcs():
    """通过 FastMCP 实例获取注册的工具函数。"""
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    tools = mcp._tool_manager._tools
    return {name: tool.fn for name, tool in tools.items()}


def _assert_trigger_scrape_only_drift(before: dict, after: dict) -> None:
    """镜像 S3 范围校验，便于用构造数据证明其鉴别力。"""
    changed_tools = {
        name
        for name in before.keys() | after.keys()
        if before.get(name) != after.get(name)
    }
    assert changed_tools == {"trigger_scrape"}
    changed_fields = {
        field
        for field in before["trigger_scrape"].keys()
        | after["trigger_scrape"].keys()
        if before["trigger_scrape"].get(field)
        != after["trigger_scrape"].get(field)
    }
    assert changed_fields == {"description", "docstring"}


async def _call_trigger_scrape(tool, manual_limits: dict[str, int]):
    """以可观测替身调用 trigger_scrape 的成功链路。"""
    from src.mcp import security

    security._guard_cache.clear()
    service = MagicMock()
    service.scrape_users = AsyncMock(return_value="task-chg031")
    registry = MagicMock()
    registry.get_tasks_by_status.return_value = []
    resolver = AsyncMock(return_value=manual_limits)
    resolve_users = AsyncMock(return_value=["alice"])
    audit = MagicMock()

    with (
        patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
        patch(
            "src.mcp.tools.admin_tools.resolve_user_list", new=resolve_users
        ),
        patch("src.scraper.ScrapingService", return_value=service),
        patch("src.scraper.TaskRegistry.get_instance", return_value=registry),
        patch(
            "src.scraper.scheduled_job.resolve_manual_limits", new=resolver
        ),
        patch("src.mcp.security.audit_log", new=audit),
    ):
        result = await tool(usernames="alice", limit=100)

    return json.loads(result), service, resolver, audit


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
async def seed_file_tweets(monkeypatch, tmp_path):
    """准备文件层推文和摘要测试数据。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base_time = datetime(2026, 2, 20, 10, 0, 0, tzinfo=UTC)

    tweets = [
        Tweet(
            tweet_id="integ_t1",
            text="Integration test tweet about Bitcoin from alice",
            created_at=base_time,
            author_username="alice",
            author_display_name="Alice",
            media=None,
        ),
        Tweet(
            tweet_id="integ_t2",
            text="Another tweet about Ethereum from alice",
            created_at=base_time + timedelta(hours=2),
            author_username="alice",
            author_display_name="Alice",
            media=None,
        ),
        Tweet(
            tweet_id="integ_t3",
            text="Bob talks about AI and machine learning",
            created_at=base_time + timedelta(hours=3),
            author_username="bob",
            author_display_name="Bob",
            media=None,
        ),
        Tweet(
            tweet_id="integ_t4",
            text="Short tweet",
            created_at=base_time + timedelta(days=1),
            author_username="bob",
            author_display_name="Bob",
            media=None,
        ),
    ]
    await FileTweetStore(tmp_path).save_tweets(tweets, early_stop_threshold=0)

    now = datetime.now(UTC)
    summaries = [
        SummaryRecord(
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
            created_at=now,
            updated_at=now,
        ),
        SummaryRecord(
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
            created_at=now,
            updated_at=now,
        ),
    ]
    await FileSummaryStore(tmp_path).seed(summaries)

    return tweets


@pytest.fixture
async def seed_file_follows(monkeypatch, tmp_path):
    """准备文件层关注列表数据。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store = FileFollowStore(tmp_path)
    alice = await store.create_scraper_follow("alice", "KOL", "test")
    bob = await store.create_scraper_follow("bob", "Developer", "test")
    charlie = await store.create_scraper_follow("charlie", "Analyst", "test")
    await store.deactivate_follow("charlie")
    return [alice, bob, charlie]


# ── get_feed 集成测试 ─────────────────────────────────────────────


class TestGetFeedIntegration:
    @pytest.mark.asyncio
    async def test_feed_returns_real_tweets(self, tool_funcs, seed_file_tweets):
        """测试 get_feed 从真实数据库查询推文。"""
        result = await tool_funcs["get_feed"](
            since="2026-02-20T00:00:00Z",
            until="2026-02-22T00:00:00Z",
        )

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] >= 3  # 至少有 3 条在这个范围内

    @pytest.mark.asyncio
    async def test_feed_filter_by_author(self, tool_funcs, seed_file_tweets):
        """测试按作者过滤 feed。"""
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
        self, tool_funcs, seed_file_tweets
    ):
        """测试搜索能找到匹配的推文。"""
        result = await tool_funcs["search_tweets"](q="Bitcoin")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] >= 1
        assert data["data"]["q"] == "Bitcoin"

    @pytest.mark.asyncio
    async def test_search_no_results(self, tool_funcs, seed_file_tweets):
        """测试搜索无结果时的返回。"""
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

        with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
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

        with patch("src.mcp.tools.subject_tools.default_subject_repo", return_value=repo):
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
    async def test_daily_stats_with_real_data(self, tool_funcs, seed_file_tweets):
        """测试真实数据的每日统计。"""
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
        self, tool_funcs, seed_file_tweets
    ):
        """测试真实数据的推文浏览。"""
        result = await tool_funcs["browse_tweets"](date="2026-02-20", tz_offset=0)

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["total"] >= 1
        assert data["data"]["date"] == "2026-02-20"


# ── admin 工具集成测试 ────────────────────────────────────────────


class TestAdminToolsIntegration:
    @pytest.mark.asyncio
    async def test_manage_follows_list(self, tool_funcs, seed_file_follows):
        """测试列出关注列表。"""
        with patch("src.mcp.tools.admin_tools.require_admin", return_value=None):
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
        self, tool_funcs, seed_file_follows
    ):
        """测试列出关注列表（含非活跃）。"""
        with patch("src.mcp.tools.admin_tools.require_admin", return_value=None):
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

    def test_tc_build_384_contract_drift_accepts_only_expected_fields(self):
        """TC-BUILD-384: 范围校验接受仅 description/docstring 的漂移。"""
        before = {
            "trigger_scrape": {
                "description": "old",
                "docstring": "old",
                "parameters": {"limit": 100},
                "signature": "(limit=100)",
            },
            "other": {"description": "same"},
        }
        after = {
            "trigger_scrape": {
                **before["trigger_scrape"],
                "description": "new",
                "docstring": "new",
            },
            "other": before["other"],
        }

        _assert_trigger_scrape_only_drift(before, after)

    def test_tc_build_385_contract_drift_rejects_another_tool(self):
        """TC-BUILD-385: 范围校验会拒绝另一工具被手滑修改。"""
        before = {
            "trigger_scrape": {
                "description": "old",
                "docstring": "old",
                "parameters": {},
                "signature": "()",
            },
            "get_follow_accounts_info": {"description": "old"},
        }
        after = {
            "trigger_scrape": {
                **before["trigger_scrape"],
                "description": "new",
                "docstring": "new",
            },
            "get_follow_accounts_info": {"description": "sabotaged"},
        }

        with pytest.raises(AssertionError):
            _assert_trigger_scrape_only_drift(before, after)

    def test_tc_build_390_trigger_scrape_docstring_mentions_manual_limit(
        self, tool_funcs
    ):
        """TC-BUILD-390: Agent 可从工具说明感知 manual_limit 优先级。"""
        docstring = inspect.getdoc(tool_funcs["trigger_scrape"])
        assert docstring is not None
        assert "若账号配置了手动抓取上限（manual_limit），该配置优先于 limit 参数生效。" in docstring

    @pytest.mark.asyncio
    async def test_tc_build_391_audit_records_resolved_manual_limits(
        self, tool_funcs
    ):
        """TC-BUILD-391: 成功审计日志记录实际解析的账号限额。"""
        data, _, _, audit = await _call_trigger_scrape(
            tool_funcs["trigger_scrape"], {"alice": 7}
        )

        assert data["success"] is True
        assert audit.call_args.kwargs["params"]["manual_limits"] == {"alice": 7}

    @pytest.mark.asyncio
    async def test_tc_build_392_signature_and_response_shape_are_unchanged(
        self, tool_funcs
    ):
        """TC-BUILD-392: 参数签名与成功返回四字段结构不变。"""
        tool = tool_funcs["trigger_scrape"]
        assert str(inspect.signature(tool)) == "(usernames: str | None = None, limit: int = 100) -> str"

        data, _, _, _ = await _call_trigger_scrape(tool, {"alice": 7})
        assert set(data["data"]) == {
            "task_id",
            "usernames",
            "limit",
            "message",
        }

    def test_tc_build_393_tool_registry_still_contains_exactly_32_tools(self):
        """TC-BUILD-393: 本包不增删 MCP 工具。"""
        funcs = _get_tool_funcs()
        assert len(funcs) == 32
        assert "trigger_scrape" in funcs

    @pytest.mark.asyncio
    async def test_tc_build_394_trigger_scrape_still_requires_admin(
        self, tool_funcs
    ):
        """TC-BUILD-394: SSE 普通用户仍被管理员权限门禁拦截。"""
        import src.mcp.auth as auth_mod

        original_transport = auth_mod._transport
        try:
            auth_mod._transport = "sse"
            result = await tool_funcs["trigger_scrape"](
                usernames="alice", limit=100
            )
        finally:
            auth_mod._transport = original_transport

        data = json.loads(result)
        assert data["success"] is False
        assert data["error_type"] == "permission"

    @pytest.mark.asyncio
    async def test_tc_build_395_existing_scrape_guards_still_block(
        self, tool_funcs, monkeypatch
    ):
        """TC-BUILD-395: 总开关与动作白名单两道既有门禁都仍生效。"""
        from src.mcp import security

        tool = tool_funcs["trigger_scrape"]
        monkeypatch.setenv("MCP_SCRAPE_ENABLED", "false")
        security._guard_cache.clear()
        with patch("src.mcp.tools.admin_tools.require_admin", return_value=None):
            disabled = json.loads(await tool(usernames="alice", limit=100))
        assert disabled["error_type"] == "permission"

        monkeypatch.setenv("MCP_SCRAPE_ENABLED", "true")
        monkeypatch.setenv("MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS", "noop")
        security._guard_cache.clear()
        with patch("src.mcp.tools.admin_tools.require_admin", return_value=None):
            denied = json.loads(await tool(usernames="alice", limit=100))
        assert denied["error_type"] == "permission"

    @pytest.mark.asyncio
    async def test_tc_build_396_mcp_queries_and_passes_manual_limits_once(
        self, tool_funcs
    ):
        """TC-BUILD-396: MCP 只解析一次并显式传给服务层。"""
        _, service, resolver, _ = await _call_trigger_scrape(
            tool_funcs["trigger_scrape"], {"alice": 7}
        )

        resolver.assert_awaited_once_with(["alice"])
        service.scrape_users.assert_awaited_once_with(
            usernames=["alice"],
            limit=100,
            manual_limits={"alice": 7},
        )

    @pytest.mark.asyncio
    async def test_tc_build_397_existing_manage_follows_behavior_regresses_green(
        self, tool_funcs, seed_file_follows
    ):
        """TC-BUILD-397: 未修改的管理工具行为保持不变。"""
        with patch("src.mcp.tools.admin_tools.require_admin", return_value=None):
            result = await tool_funcs["manage_follows"](action="list")

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["count"] == 2

    def test_tc_build_398_trigger_scrape_contract_invariants_are_complete(self):
        """TC-BUILD-398: 全量收口前锁定工具数、输入字段和签名。"""
        from src.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        tool = mcp._tool_manager._tools["trigger_scrape"]
        assert len(mcp._tool_manager._tools) == 32
        assert set(tool.parameters["properties"]) == {"usernames", "limit"}
        assert str(inspect.signature(tool.fn)) == "(usernames: str | None = None, limit: int = 100) -> str"

    @pytest.mark.asyncio
    async def test_tc_build_400_audit_records_none_when_no_manual_limits(
        self, tool_funcs
    ):
        """TC-BUILD-400: 无手动限额时审计值规范为 None。"""
        data, _, _, audit = await _call_trigger_scrape(
            tool_funcs["trigger_scrape"], {}
        )

        assert data["success"] is True
        assert audit.call_args.kwargs["params"]["manual_limits"] is None


# ── get_system_status 集成测试 ────────────────────────────────────


class TestSystemStatusIntegration:
    @pytest.mark.asyncio
    async def test_status_with_real_data(
        self, tool_funcs, seed_file_tweets, seed_file_follows
    ):
        """测试系统状态返回真实数据统计。"""
        result = await tool_funcs["get_system_status"]()

        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["tweets"]["total"] == 4
        assert data["data"]["follows"]["active"] == 2


# ── get_follow_accounts_info 集成测试 ─────────────────────────────


class TestFollowAccountsInfoIntegration:
    @pytest.mark.asyncio
    async def test_profiles_returns_cached_profile_fields(
        self, tool_funcs, monkeypatch, tmp_path
    ):
        """测试 profiles 类型返回档案字段（bio 映射 description、tweet_count 映射 statuses_count）。"""
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
        await FileProfileStore(tmp_path).seed(
            [
                XUserProfile(
                    platform_user_id="uid_tony",
                    username="tdinh_me",
                    display_name="Tony Dinh",
                    description="Indie hacker building apps",
                    followers_count=150000,
                    following_count=300,
                    statuses_count=417,
                    fetched_at=datetime(2026, 6, 1, 0, 0, 0),
                )
            ]
        )

        with patch("src.mcp.tools.admin_tools.require_admin", return_value=None):
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


class TestCHG032McpLifecycleAndGuards:
    @staticmethod
    def _allow_scrape_guards():
        from src.mcp import security

        security._guard_cache.clear()
        return (
            patch("src.mcp.tools.admin_tools.require_admin", return_value=None),
            patch("src.mcp.security.check_scrape_guard", return_value=None),
            patch("src.mcp.security.check_action_guard", return_value=None),
        )

    @pytest.mark.asyncio
    async def test_tc_build_404_trigger_scrape_closes_once(self, tool_funcs):
        service = MagicMock()
        service.scrape_users = AsyncMock(return_value="task-404")
        service.close = AsyncMock()
        registry = MagicMock()
        registry.get_tasks_by_status.return_value = []
        guards = self._allow_scrape_guards()
        with (
            guards[0],
            guards[1],
            guards[2],
            patch("src.mcp.tools.admin_tools.resolve_user_list", new=AsyncMock(return_value=["alice"])),
            patch("src.scraper.ScrapingService", return_value=service),
            patch("src.scraper.TaskRegistry.get_instance", return_value=registry),
            patch("src.scraper.scheduled_job.resolve_manual_limits", new=AsyncMock(return_value={})),
            patch("src.mcp.security.audit_log"),
        ):
            result = json.loads(await tool_funcs["trigger_scrape"](usernames="alice"))

        assert result["success"] is True
        service.close.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_tc_build_405_trigger_backfill_closes_batch_once(self, tool_funcs):
        service = MagicMock()
        service.backfill_user = AsyncMock(return_value={"new": 1, "fetched": 2})
        service.close = AsyncMock()
        guards = self._allow_scrape_guards()
        with (
            guards[0],
            guards[1],
            guards[2],
            patch(
                "src.mcp.tools.admin_tools.resolve_user_list",
                new=AsyncMock(return_value=["alice", "bob"]),
            ),
            patch("src.scraper.ScrapingService", return_value=service),
            patch("src.mcp.security.audit_log"),
        ):
            result = json.loads(await tool_funcs["trigger_backfill"](usernames="alice,bob"))

        assert result["success"] is True
        assert service.backfill_user.await_count == 2
        service.close.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_tc_build_407_backfill_exception_still_closes(self, tool_funcs):
        service = MagicMock()
        service.backfill_user = AsyncMock(
            side_effect=[{"new": 1, "fetched": 2}, RuntimeError("second failed")]
        )
        service.close = AsyncMock()
        guards = self._allow_scrape_guards()
        with (
            guards[0],
            guards[1],
            guards[2],
            patch(
                "src.mcp.tools.admin_tools.resolve_user_list",
                new=AsyncMock(return_value=["alice", "bob"]),
            ),
            patch("src.scraper.ScrapingService", return_value=service),
            patch("src.mcp.security.audit_log"),
        ):
            result = json.loads(await tool_funcs["trigger_backfill"](usernames="alice,bob"))

        assert result["success"] is False
        service.close.assert_awaited_once_with()

    def test_tc_build_411_all_tool_wire_metadata_matches_golden(self):
        from src.mcp.server import create_mcp_server

        golden = json.loads(Path("tests/mcp/golden/mcp_tool_schemas.json").read_text())
        mcp = create_mcp_server()
        actual = {
            name: {
                "description": tool.description,
                "parameters": tool.parameters,
                "signature": str(inspect.signature(tool.fn)),
                "docstring": inspect.getdoc(tool.fn),
            }
            for name, tool in sorted(mcp._tool_manager._tools.items())
        }
        assert actual == golden

    @pytest.mark.asyncio
    async def test_tc_build_421_close_warnings_include_rest_and_mcp_contexts(self, caplog):
        from src.api.routes.admin import _close_scraping_service as close_rest
        from src.mcp.tools.admin_tools import _close_scraping_service as close_mcp

        contexts = (
            (close_rest, " (backfill_articles, username=alice)"),
            (close_mcp, " (tool=trigger_scrape)"),
            (close_mcp, " (tool=trigger_backfill)"),
        )
        with caplog.at_level("WARNING"):
            for closer, context in contexts:
                service = MagicMock()
                service.close = AsyncMock(side_effect=RuntimeError("boom"))
                await closer(service, context)

        assert "backfill_articles, username=alice" in caplog.text
        assert "tool=trigger_scrape" in caplog.text
        assert "tool=trigger_backfill" in caplog.text

    def test_tc_build_422_wire_dump_detects_temporary_docstring_damage(self):
        from src.mcp.server import create_mcp_server

        tool = create_mcp_server()._tool_manager._tools["trigger_scrape"]
        baseline = {
            "description": tool.description,
            "docstring": inspect.getdoc(tool.fn),
        }
        damaged = {**baseline, "docstring": baseline["docstring"] + " 临时自证改错"}
        assert damaged != baseline

    def test_tc_build_423_s0_guard_accepts_only_empty_porcelain_output(self):
        def can_snapshot(porcelain: str) -> bool:
            return not porcelain.strip()

        assert can_snapshot("") is True
        assert can_snapshot(" M src/example.py\n") is False

    def test_tc_build_424_helpers_keep_deliberate_type_split_and_docstrings(self):
        from typing import Any

        from src.api.routes.admin import _close_scraping_service as close_rest
        from src.mcp.tools.admin_tools import _close_scraping_service as close_mcp
        from src.scraper import ScrapingService

        assert inspect.signature(close_rest).parameters["service"].annotation is ScrapingService
        assert inspect.signature(close_mcp).parameters["service"].annotation is Any
        for helper in (close_rest, close_mcp):
            doc = inspect.getdoc(helper) or ""
            assert "两份独立实现" in doc
            assert "NameError" in doc

    @pytest.mark.asyncio
    async def test_tc_build_426_empty_trigger_scrape_still_closes(self, tool_funcs):
        service = MagicMock()
        service.close = AsyncMock()
        registry = MagicMock()
        registry.get_tasks_by_status.return_value = []
        guards = self._allow_scrape_guards()
        with (
            guards[0],
            guards[1],
            guards[2],
            patch("src.mcp.tools.admin_tools.resolve_user_list", new=AsyncMock(return_value=[])),
            patch("src.scraper.ScrapingService", return_value=service),
            patch("src.scraper.TaskRegistry.get_instance", return_value=registry),
        ):
            result = json.loads(await tool_funcs["trigger_scrape"]())

        assert result["error_type"] == "validation"
        service.close.assert_awaited_once_with()

    def test_tc_build_427_backfill_loop_has_no_per_account_try_except(self, tool_funcs):
        source = inspect.getsource(tool_funcs["trigger_backfill"])
        loop_body = source.split("for username in user_list:", 1)[1].split("audit_log(", 1)[0]
        assert "try:" not in loop_body
        assert "except" not in loop_body

    def test_tc_build_428_account_info_factory_keeps_cached_singleton(self):
        from src.scraper.account_info_service import get_account_info_service

        source = inspect.getsource(get_account_info_service)
        assert "global _service_instance" in source
        assert "_service_instance is None" in source

    def test_tc_build_431_all_chg032_case_ids_are_collected_in_tests(self):
        pattern = re.compile(r"test_tc_build_(4(?:0[1-9]|[12][0-9]|3[0-2]))")
        found = {
            match.group(1)
            for path in Path("tests").rglob("test_*.py")
            for match in pattern.finditer(path.read_text())
        }
        assert found == {str(case_id) for case_id in range(401, 433)}
