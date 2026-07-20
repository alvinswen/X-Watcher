"""mcp follows 资源在文件层（file 唯一数据层）下运行。
路径可证:种子只进文件层,资源返回即证读文件层(非空 DB session)。"""

import json

import pytest
from mcp.server.fastmcp import FastMCP


@pytest.mark.asyncio
async def test_follows_resource_reads_file_layer(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.preference.infrastructure.file_follow_repository import FileFollowStore

    store = FileFollowStore(tmp_path)
    await store.create_scraper_follow("zoe", "r", "admin")
    await store.create_scraper_follow("amy", "r", "admin")
    await store.update_scraper_follow("zoe", is_active=False)  # inactive

    from src.mcp.resources import providers

    mcp = FastMCP("test")
    providers.register(mcp)
    raw = await mcp._resource_manager._resources["xwatcher://follows"].read()
    data = json.loads(raw)

    # 保序:username 升序(repo 默认 added_at DESC,资源层须重排)
    assert [f["username"] for f in data["follows"]] == ["amy", "zoe"]
    # 保 inactive:get_all_follows(include_inactive=True),否则 zoe 被丢 count=1
    assert data["count"] == 2
    assert {f["username"]: f["is_active"] for f in data["follows"]} == {"amy": True, "zoe": False}
