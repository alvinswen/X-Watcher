"""CHG-069 验证门口径修正 · save_summaries 链路回归（闸结构零改动，仅第 ③ 闸判定变化）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

_CREATED_AT = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.mcp.server import create_mcp_server

    registered = create_mcp_server()._tool_manager._tools
    return {name: tool.fn for name, tool in registered.items()}


def _tweet(tweet_id: str, text: str) -> Tweet:
    return Tweet(
        tweet_id=tweet_id,
        text=text,
        author_username="alice",
        created_at=_CREATED_AT,
    )


async def _seed(root: Path, *tweets: Tweet) -> None:
    await FileTweetStore(root).save_tweets(list(tweets), early_stop_threshold=0)


async def _save(save_summaries, summaries):
    with (
        patch("src.mcp.tools.summarization_tools.require_admin", return_value=None),
        patch("src.mcp.security.audit_log"),
    ):
        return json.loads(await save_summaries(summaries=summaries))


@pytest.mark.asyncio
async def test_short_english_missing_translation_rejected_via_gate(
    tools, tmp_path: Path
) -> None:
    # 行为反转链（01 § 4.4 行 2）：短外文缺译 → verification_failed（修前放行）
    await _seed(tmp_path, _tweet("short-en", "Today. 10am PT."))
    result = await _save(
        tools["save_summaries"],
        [{"tweet_id": "short-en", "summary": "短推文摘要"}],
    )
    assert result["data"]["saved"] == 0
    assert result["data"]["rejected"] == [
        {
            "tweet_id": "short-en",
            "category": "verification_failed",
            "reason": "英文推文缺少翻译",
        }
    ]


@pytest.mark.asyncio
async def test_url_glued_chinese_translation_saved_round_trip(
    tools, tmp_path: Path
) -> None:
    # 误杀消除链（01 § 4.4 行 3）：B 实证样例译文过门并落库可读
    orig = "More info at https://t.co/nJ14cKHO07, you can still start today!"
    trans = "更多信息请见 https://t.co/nJ14cKHO07，你今天仍然可以开始！"
    await _seed(tmp_path, _tweet("b-sample", orig))
    result = await _save(
        tools["save_summaries"],
        [{"tweet_id": "b-sample", "summary": "介绍了开始参与的方式", "translation": trans}],
    )
    assert result["data"]["saved"] == 1
    assert result["data"]["failed"] == 0
    stored = await FileSummaryStore(tmp_path).get_summary_by_tweet("b-sample")
    assert stored is not None
    assert stored.translation_text == trans


@pytest.mark.asyncio
async def test_pure_mentions_links_empty_translation_saved(
    tools, tmp_path: Path
) -> None:
    # 无可译内容链（01 § 4.4 行 4）：纯 @串+链接留空译文过门，translation_text 落空
    await _seed(
        tmp_path, _tweet("c-sample", "@AndyBeard @MFacchinello https://t.co/BlhXBWh0fV")
    )
    result = await _save(
        tools["save_summaries"],
        [{"tweet_id": "c-sample", "summary": "纯提及与链接，无实质内容"}],
    )
    assert result["data"]["saved"] == 1
    assert result["data"]["failed"] == 0
    stored = await FileSummaryStore(tmp_path).get_summary_by_tweet("c-sample")
    assert stored is not None
    assert stored.translation_text is None
