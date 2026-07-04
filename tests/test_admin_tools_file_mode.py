"""admin_tools MCP 聚合工具在 XWATCHER_DATA_LAYER=file 下走文件层(pg 下线 A2-2b')。

路径可证:种子只进文件层 store → MCP 工具经 _tool_manager._tools[].fn 调用 →
断言聚合出现即证读文件层(无 pg/session)。覆盖:
- get_follow_accounts_info:profiles / stats(每账号总推文)/ analysis(逐周期 count)
故障注入:接缝改名 / 逻辑破坏须翻红。
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

# ── 辅助 ─────────────────────────────────────────────────────────────


def _tool_funcs():
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    return {name: t.fn for name, t in mcp._tool_manager._tools.items()}


def _make_tweet(tweet_id, author, created_at, text="t"):
    from src.scraper.domain.models import Tweet

    return Tweet(
        tweet_id=tweet_id,
        text=text,
        created_at=created_at,
        author_username=author,
        author_display_name=author.title(),
    )


def _make_summary(summary_id, tweet_id):
    from src.summarization.domain.models import SummaryRecord

    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return SummaryRecord(
        summary_id=summary_id,
        tweet_id=tweet_id,
        summary_text="摘要",
        model_provider="test",
        model_name="m",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0.0,
        content_hash="h" + tweet_id,
        created_at=now,
        updated_at=now,
    )


def _make_profile(uid, username, fetched_at):
    from src.preference.domain.models import XUserProfile

    return XUserProfile(
        platform_user_id=uid,
        username=username,
        display_name=username.title(),
        description=f"bio {username}",
        followers_count=100,
        following_count=10,
        statuses_count=42,
        fetched_at=fetched_at,
    )


@pytest.fixture
def file_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    # 旁路 admin 鉴权(纯数据层接线测试)
    monkeypatch.setattr("src.mcp.tools.admin_tools.require_admin", lambda: None)
    return tmp_path


# ── get_follow_accounts_info ─────────────────────────────────────────


class TestFollowAccountsInfoFileMode:
    @pytest.mark.asyncio
    async def test_profiles_reads_file_layer(self, file_mode):
        """profiles 走 get_profile_repo:种子两档案 → 字段映射(bio/tweet_count)。"""
        from src.preference.infrastructure.file_profile_repository import FileProfileStore

        store = FileProfileStore(file_mode)
        await store.seed([
            _make_profile("u1", "alice", datetime(2026, 6, 1, tzinfo=timezone.utc)),
            _make_profile("u2", "bob", datetime(2026, 6, 2, tzinfo=timezone.utc)),
        ])

        result = await _tool_funcs()["get_follow_accounts_info"](info_type="profiles")
        data = json.loads(result)
        assert data["success"] is True, data
        assert data["data"]["count"] == 2
        by_name = {p["username"]: p for p in data["data"]["profiles"]}
        assert by_name["alice"]["bio"] == "bio alice"
        assert by_name["alice"]["tweet_count"] == 42
        assert by_name["alice"]["followers_count"] == 100

    @pytest.mark.asyncio
    async def test_stats_total_tweets_from_file_layer(self, file_mode):
        """stats:活跃账号(follows 文件层)+ 每账号总推文(tweet 聚合门面)。"""
        from src.preference.infrastructure.file_follow_repository import FileFollowStore
        from src.summarization.infrastructure.file_summarization_read_repository import (
            FileSummarizationReadStore,
        )

        follows = FileFollowStore(file_mode)
        await follows.create_scraper_follow("alice", "r", "admin")
        await follows.create_scraper_follow("bob", "r", "admin")

        read = FileSummarizationReadStore(file_mode)
        base = datetime(2026, 6, 10, tzinfo=timezone.utc)
        await read.seed_tweets([
            _make_tweet("1", "alice", base),
            _make_tweet("2", "alice", base + timedelta(hours=1)),
            _make_tweet("3", "bob", base + timedelta(hours=2)),
        ])

        result = await _tool_funcs()["get_follow_accounts_info"](info_type="stats")
        data = json.loads(result)
        assert data["success"] is True, data
        by_name = {s["username"]: s for s in data["data"]["stats"]}
        assert by_name["alice"]["total_tweets"] == 2
        assert by_name["bob"]["total_tweets"] == 1

    @pytest.mark.asyncio
    async def test_analysis_periods_from_file_layer(self, file_mode):
        """analysis:指定账号逐周期 count 走 tweet 聚合门面(periods 非空,含本期推文)。"""
        from src.summarization.infrastructure.file_summarization_read_repository import (
            FileSummarizationReadStore,
        )

        read = FileSummarizationReadStore(file_mode)
        now = datetime.now(timezone.utc)
        await read.seed_tweets([
            _make_tweet("1", "alice", now - timedelta(hours=1)),
            _make_tweet("2", "alice", now - timedelta(hours=2)),
        ])

        result = await _tool_funcs()["get_follow_accounts_info"](
            info_type="analysis", username="alice"
        )
        data = json.loads(result)
        assert data["success"] is True, data
        assert data["data"]["username"] == "alice"
        assert len(data["data"]["periods"]) == 14
        total = sum(p["new_tweets"] for p in data["data"]["periods"])
        assert total == 2

    @pytest.mark.asyncio
    async def test_profiles_breaks_when_facade_renamed(self, file_mode, monkeypatch):
        """故障注入:get_all_profiles 改名 → profiles 报失败(证经门面)。"""
        from src.preference.infrastructure.file_profile_repository import FileProfileStore

        store = FileProfileStore(file_mode)
        await store.seed([_make_profile("u1", "alice", datetime(2026, 6, 1, tzinfo=timezone.utc))])

        monkeypatch.delattr(FileProfileStore, "get_all_profiles")
        result = await _tool_funcs()["get_follow_accounts_info"](info_type="profiles")
        data = json.loads(result)
        assert data["success"] is False
