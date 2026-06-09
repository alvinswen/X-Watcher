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


def _synthetic_tweets(n: int, *, run_tag: str):
    from datetime import datetime, timezone

    from src.scraper.domain.models import Tweet

    return [
        Tweet(
            tweet_id=f"bench-{run_tag}-{i}",
            text=f"bench write {i}",
            created_at=datetime(2026, 6, 1, 0, 0, (i % 60), tzinfo=timezone.utc).replace(tzinfo=None),
            author_username="benchwriter",
        )
        for i in range(n)
    ]


def build_write_case(*, data_root: str, batch_size: int = 100) -> BenchCase:
    """写路径:save_tweets([batch_size 合成新推])。
    file:setup copytree data_root→fresh temp + 指向 temp;thunk 写合成批;teardown 删 temp。
    db  :thunk save_tweets 后 rollback(只 flush 不 commit,pg 不污染)。
    合成批=全新 tweet_id 避开 save_tweets 去重早停(报告诚实标合成写批)。
    """
    import shutil
    import tempfile

    state: dict = {"tmp": None, "run": 0}

    # ---- file side ----
    def file_setup():
        state["run"] += 1
        tmp = tempfile.mkdtemp(prefix="xw-bench-write-")
        src = Path(data_root)
        if src.exists():
            shutil.copytree(src, tmp, dirs_exist_ok=True)
        state["tmp"] = tmp

    def file_thunk():
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        store = FileTweetStore(Path(state["tmp"]))
        batch = _synthetic_tweets(batch_size, run_tag=f"f{state['run']}")
        return store.save_tweets(batch, early_stop_threshold=0)

    def file_teardown():
        if state["tmp"]:
            shutil.rmtree(state["tmp"], ignore_errors=True)
            state["tmp"] = None

    # ---- db side ----
    db_state: dict = {"run": 0}

    async def db_thunk():
        from src.scraper.infrastructure.repository import TweetRepository

        db_state["run"] += 1
        maker = _async_session_maker()
        async with maker() as s:
            batch = _synthetic_tweets(batch_size, run_tag=f"d{db_state['run']}")
            try:
                return await TweetRepository(s).save_tweets(batch, early_stop_threshold=0)
            finally:
                await s.rollback()  # 只 flush 未 commit → 撤销,pg 不污染

    return BenchCase(
        name=f"写 save_tweets(batch={batch_size} 合成新推)",
        file=Side(thunk=file_thunk, setup=file_setup, teardown=file_teardown),
        db=Side(thunk=db_thunk),
        note="file: temp 副本(copytree 计时区外)+合成批; db: flush 后 rollback。合成写批非真数据写",
    )


# ---- Task 6: 聚合用例 + copytree 探针 + asyncio.run 桥基线 ----
async def seed_tiny_summary_fixture(data_root: str, n: int = 2) -> None:
    """往 data_root 写 n 条合成 summary(file 模式),供聚合单测。"""
    from datetime import datetime, timezone

    from src.summarization.domain.models import SummaryRecord
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

    store = FileSummaryStore(Path(data_root))
    records = []
    for i in range(n):
        records.append(SummaryRecord(
            summary_id=f"tiny-sum-{i}",
            tweet_id=f"tiny-{i}",
            summary_text=f"s{i}",
            model_provider="openai",
            model_name="gpt",
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
            cost_usd=0.001,
            content_hash=f"h{i}",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
        ))
    await store.seed(records)


def build_aggregate_case(*, data_root: str) -> BenchCase:
    """聚合:file get_cost_stats(读时全扫) ↔ DB SummarizationRepository.get_cost_stats(SUM/GROUP BY)。"""
    def file_thunk():
        from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

        return FileSummaryStore(Path(data_root)).get_cost_stats()

    async def db_thunk():
        maker = _async_session_maker()
        async with maker() as s:
            from src.summarization.infrastructure.repository import SummarizationRepository

            return await SummarizationRepository(s).get_cost_stats()

    return BenchCase(
        name="聚合 get_cost_stats",
        file=Side(thunk=file_thunk),
        db=Side(thunk=db_thunk),
        note="读时全扫聚合 vs SUM/GROUP BY",
    )


def _dir_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def build_copytree_probe(*, data_root: str):
    """返回 0-arg probe:计时 get_import_repo(dry_run=True) 构造期 copytree + 返回 (秒, 体积MB)。
    用 file 模式;构造后立即 close 清理 temp。"""
    def probe():
        from time import perf_counter

        mb = _dir_size_mb(Path(data_root))
        with data_layer_mode("file", data_root=data_root):
            from src.data_layer.provider import get_import_repo

            t0 = perf_counter()
            repo = get_import_repo(dry_run=True)
            secs = perf_counter() - t0
            if hasattr(repo, "close"):
                repo.close()
        return secs, mb

    return probe


async def measure_bridge_overhead_ms(n: int = 7) -> float:
    """测 asyncio.run(trivial) loop 起停开销中位(毫秒)。须在无 running loop 的线程跑。"""
    import asyncio
    from statistics import median
    from time import perf_counter

    async def _trivial():
        return None

    def _one() -> float:
        t0 = perf_counter()
        asyncio.run(_trivial())
        return (perf_counter() - t0) * 1000.0

    # 当前协程已在 loop 内,asyncio.run 不能嵌套 → 在 worker 线程跑
    samples = await asyncio.to_thread(lambda: [_one() for _ in range(n)])
    return median(samples)
