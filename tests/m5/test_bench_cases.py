import os

from src.data_layer.bench.cases import data_layer_mode


def test_data_layer_mode_sets_and_restores_env():
    os.environ.pop("XWATCHER_DATA_LAYER", None)
    os.environ.pop("XWATCHER_DATA_ROOT", None)
    with data_layer_mode("file", data_root="/tmp/xw-bench-x"):
        assert os.environ["XWATCHER_DATA_LAYER"] == "file"
        assert os.environ["XWATCHER_DATA_ROOT"] == "/tmp/xw-bench-x"
    # 退出后还原(原本未设 → 删除)
    assert "XWATCHER_DATA_LAYER" not in os.environ
    assert "XWATCHER_DATA_ROOT" not in os.environ


def test_data_layer_mode_restores_prior_value():
    os.environ["XWATCHER_DATA_LAYER"] = "sqlalchemy"
    with data_layer_mode("file", data_root="/tmp/xw-bench-y"):
        assert os.environ["XWATCHER_DATA_LAYER"] == "file"
    assert os.environ["XWATCHER_DATA_LAYER"] == "sqlalchemy"
    os.environ.pop("XWATCHER_DATA_LAYER", None)


import asyncio
from datetime import datetime, timezone

from src.data_layer.bench.cases import (
    build_read_cases,
    seed_tiny_tweet_fixture,
)
from src.data_layer.bench.harness import Side


async def test_tiny_fixture_then_file_get_all_thunk_counts(tmp_path):
    await seed_tiny_tweet_fixture(str(tmp_path), n=3)
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    store = FileTweetStore(tmp_path)
    tweets = await store.get_all_tweets()
    assert len(tweets) == 3


def test_build_read_cases_shape():
    cases = build_read_cases(data_root="/tmp/xw-bench-z")
    names = {c.name for c in cases}
    assert "全量读 get_all_tweets↔export.get_tweets" in names
    assert "索引读 get_tweets_by_author" in names
    assert any("by-day" in n for n in names)
    for c in cases:
        assert isinstance(c.file, Side)
        if "by-day" in c.name or "分页" in c.name:
            assert c.db is None
        else:
            assert c.db is not None


async def test_write_case_file_side_does_not_mutate_origin(tmp_path):
    from src.data_layer.bench.cases import build_write_case, seed_tiny_tweet_fixture
    from src.data_layer.bench.harness import measure_side
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    origin = tmp_path / "origin"
    await seed_tiny_tweet_fixture(str(origin), n=3)

    case = build_write_case(data_root=str(origin), batch_size=5)
    await measure_side(case.file, n_warm=1)

    # 原盘仍只有 3 条(写发生在 temp 副本,teardown 已清理)
    after = await FileTweetStore(origin).get_all_tweets()
    assert len(after) == 3
