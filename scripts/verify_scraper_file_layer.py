"""M-5 子项目 3 联调三级证据:provider 切换 / 真实调用点读真数据 / scheduler-log 同步写 round-trip。

用法:XWATCHER_DATA_LAYER=file XWATCHER_DATA_ROOT=./data_migrated .venv/bin/python scripts/verify_scraper_file_layer.py
判绿:进程退码 0 + 末行打印 'VERIFY OK'(勿用 cmd|tail 取 $?,会吞 SystemExit)。
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path


def _fail(msg: str) -> None:
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


async def _amain() -> None:
    os.environ["XWATCHER_DATA_LAYER"] = "file"
    data_root = os.environ.get("XWATCHER_DATA_ROOT", "./data_migrated")
    os.environ["XWATCHER_DATA_ROOT"] = data_root

    from src.data_layer.provider import (
        get_article_repo,
        get_fetch_stats_repo,
        get_scheduler_log_repo,
        get_scheduler_log_sync_writer,
        get_tweet_repo,
    )
    from src.scraper.infrastructure.file_article_repository import FileArticleStore
    from src.scraper.infrastructure.file_fetch_stats_repository import FileFetchStatsStore
    from src.scraper.infrastructure.file_scheduler_log_repository import FileSchedulerLogStore
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    # —— 级 1:provider 切换 ——
    if not isinstance(get_tweet_repo(), FileTweetStore):
        _fail("get_tweet_repo 非 FileTweetStore")
    if not isinstance(get_article_repo(), FileArticleStore):
        _fail("get_article_repo 非 FileArticleStore")
    if not isinstance(get_fetch_stats_repo(), FileFetchStatsStore):
        _fail("get_fetch_stats_repo 非 FileFetchStatsStore")
    if not isinstance(get_scheduler_log_repo(), FileSchedulerLogStore):
        _fail("get_scheduler_log_repo 非 FileSchedulerLogStore")
    print("级1 provider 切换 OK")

    # —— 级 2:真实调用点读真数据 ——
    tweets = await get_tweet_repo().get_all_tweets()
    if len(tweets) != 41018:
        _fail(f"tweet 计数 {len(tweets)} != 41018")
    n_article = await get_article_repo().count_articles()
    if n_article != 50:
        _fail(f"article 计数 {n_article} != 50")
    # fetch_stats 无 get_all:从盘面取 username 列表,再走真实调用点 batch_get_stats
    fs_path = Path(data_root) / "fetch_stats" / "fetch_stats.json"
    fs_usernames = list(json.loads(fs_path.read_text(encoding="utf-8"))["fetch_stats"].keys())
    fs_map = await get_fetch_stats_repo().batch_get_stats(fs_usernames)
    if len(fs_map) != 90:
        _fail(f"fetch_stats 计数 {len(fs_map)} != 90")
    print(f"级2 真数据读取 OK(tweet={len(tweets)} article={n_article} fetch_stats={len(fs_map)})")

    # —— 级 3:scheduler-log 同步写 → 异步读 round-trip(pg 0 行,自造端到端验同步写路)——
    with tempfile.TemporaryDirectory() as td:
        os.environ["XWATCHER_DATA_ROOT"] = td  # 隔离临时 root,不污染 data_migrated
        from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog

        # 同步桥接:本协程内不能直接 asyncio.run(已在 running loop)→ 用 to_thread 跑同步写
        writer = get_scheduler_log_sync_writer()
        log = SchedulerExecutionLog(job_id="verify-job-1", event_type=SchedulerEventType.MISSED)
        await asyncio.to_thread(writer.write_log, log)  # 线程内无 running loop → 内部 asyncio.run OK

        logs = await get_scheduler_log_repo().get_recent_logs(limit=10)
        if not any(l.job_id == "verify-job-1" for l in logs):
            _fail("scheduler-log 同步写后异步读不到")
        print(f"级3 scheduler-log 同步写 round-trip OK(读回 {len(logs)} 条)")

    print("VERIFY OK")


if __name__ == "__main__":
    asyncio.run(_amain())
