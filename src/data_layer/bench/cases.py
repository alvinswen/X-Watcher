"""子项目 6 性能基准:路径用例 + mode 切换 + session 助手。

lazy import store/repo(import 即建 DB 引擎的副作用延迟到调用期,镜像 provider 范式)。
"""
from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from src.data_layer.bench.harness import Side


@contextlib.contextmanager
def data_layer_mode(mode: str, *, data_root: str | None = None):
    """临时设 XWATCHER_DATA_LAYER(+可选 DATA_ROOT),退出还原(原无则删)。"""
    keys = {"XWATCHER_DATA_LAYER": mode}
    if data_root is not None:
        keys["XWATCHER_DATA_ROOT"] = data_root
    prior = {k: os.environ.get(k) for k in keys}
    try:
        for k, v in keys.items():
            os.environ[k] = v
        yield
    finally:
        for k, old in prior.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


@dataclass
class BenchCase:
    name: str
    file: Side
    db: Side | None
    note: str = ""


# ---- tiny fixture(单测/冒烟用,不依赖 pg)----
async def seed_tiny_tweet_fixture(data_root: str, n: int = 3) -> None:
    """往 data_root 写 n 条合成推文(file 模式),供单测验证 thunk 正确性。"""
    from datetime import datetime, timezone

    from src.scraper.domain.models import Tweet
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    store = FileTweetStore(Path(data_root))
    tweets = [
        Tweet(
            tweet_id=f"tiny-{i}",
            text=f"hello {i}",
            created_at=datetime(2026, 1, 1, 12, 0, i, tzinfo=timezone.utc).replace(tzinfo=None),
            author_username="alice",
        )
        for i in range(n)
    ]
    await store.save_tweets(tweets, early_stop_threshold=0)


# ---- DB session 助手 ----
def _sync_export_repo():
    """sync ExportRepository(get_engine + Session);返回 (repo, session)。调用方负责 session.close()。"""
    from sqlalchemy.orm import Session

    from src.database.models import get_engine
    from src.sync.infrastructure.export_repository import ExportRepository

    session = Session(get_engine())
    return ExportRepository(session), session


def _async_session_maker():
    from src.database.async_session import get_async_session_maker

    return get_async_session_maker()


# ---- 读用例 ----
DEFAULT_AUTHOR = "elonmusk"


def build_read_cases(*, data_root: str, author: str = DEFAULT_AUTHOR) -> list[BenchCase]:
    from datetime import date, datetime, timezone

    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    cases: list[BenchCase] = []

    # 1) 全量读
    def file_get_all():
        return FileTweetStore(Path(data_root)).get_all_tweets()

    def db_get_all():
        repo, session = _sync_export_repo()
        try:
            return repo.get_tweets(since=None, until=None, authors=None)
        finally:
            session.close()

    cases.append(BenchCase(
        name="全量读 get_all_tweets↔export.get_tweets",
        file=Side(thunk=file_get_all),
        db=Side(thunk=db_get_all),
        note="749 分片全扫 vs SELECT 全表(最大疑点)",
    ))

    # 2) 索引读
    def file_by_author():
        return FileTweetStore(Path(data_root)).get_tweets_by_author(author, limit=100)

    async def db_by_author():
        maker = _async_session_maker()
        async with maker() as s:
            from src.scraper.infrastructure.repository import TweetRepository
            return await TweetRepository(s).get_tweets_by_author(author, limit=100)

    cases.append(BenchCase(
        name="索引读 get_tweets_by_author",
        file=Side(thunk=file_by_author),
        db=Side(thunk=db_by_author),
        note=f"扫作者分片+排序 vs B-tree 索引(author={author})",
    ))

    # 3) file-only by-day
    def file_by_day():
        return FileTweetStore(Path(data_root)).get_by_day(
            date(2026, 1, 1), tz_offset_min=0, min_text_length=0, limit=None
        )

    cases.append(BenchCase(
        name="by-day get_by_day(file-only)",
        file=Side(thunk=file_by_day),
        db=None,
        note="DB 侧无 repo 配对,由 feed/browse 服务层查询承接",
    ))

    # 4) file-only 分页
    def file_pagination():
        return FileTweetStore(Path(data_root)).get_by_author_range(
            author,
            since=datetime(2000, 1, 1, tzinfo=timezone.utc),
            until=datetime(2100, 1, 1, tzinfo=timezone.utc),
            page=1, page_size=50,
        )

    cases.append(BenchCase(
        name="分页 get_by_author_range(file-only)",
        file=Side(thunk=file_pagination),
        db=None,
        note=f"DB 侧无 repo 配对(author={author})",
    ))

    return cases
