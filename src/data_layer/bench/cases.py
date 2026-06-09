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


def build_read_cases(*, data_root: str, author: str = DEFAULT_AUTHOR,
                     by_day=None) -> list[BenchCase]:
    """读用例:handle(file store / db repo+session)在 setup(计时外)lazy-once 获取,
    thunk 只测操作本身(不含 FileTweetStore 构造的 index+view rebuild ~0.69s)。
    by_day: file-only by-day 测哪天(默认 2026-05-29 = data_migrated 高峰日 488 推)。"""
    from datetime import date, datetime, timezone

    if by_day is None:
        by_day = date(2026, 5, 29)

    cases: list[BenchCase] = []

    # 1) 全量读:file get_all_tweets() ↔ DB(sync)ExportRepository.get_tweets()
    f1: dict = {}
    def f1_setup():
        if "h" not in f1:
            from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
            f1["h"] = FileTweetStore(Path(data_root))
    def f1_thunk():
        return f1["h"].get_all_tweets()

    d1: dict = {}
    def d1_setup():
        if "h" not in d1:
            repo, session = _sync_export_repo()
            d1["h"], d1["s"] = repo, session
    def d1_thunk():
        return d1["h"].get_tweets(since=None, until=None, authors=None)

    cases.append(BenchCase(
        name="全量读 get_all_tweets↔export.get_tweets",
        file=Side(thunk=f1_thunk, setup=f1_setup),
        db=Side(thunk=d1_thunk, setup=d1_setup),
        note="749 分片全扫 vs SELECT 全表(最大疑点;handle 计时外)",
    ))

    # 2) 索引读:file get_tweets_by_author ↔ DB(async)TweetRepository.get_tweets_by_author
    f2: dict = {}
    def f2_setup():
        if "h" not in f2:
            from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
            f2["h"] = FileTweetStore(Path(data_root))
    def f2_thunk():
        return f2["h"].get_tweets_by_author(author, limit=100)

    d2: dict = {}
    async def d2_setup():
        if "h" not in d2:
            from src.scraper.infrastructure.repository import TweetRepository
            s = _async_session_maker()()
            d2["h"], d2["s"] = TweetRepository(s), s
    async def d2_thunk():
        return await d2["h"].get_tweets_by_author(author, limit=100)

    cases.append(BenchCase(
        name="索引读 get_tweets_by_author",
        file=Side(thunk=f2_thunk, setup=f2_setup),
        db=Side(thunk=d2_thunk, setup=d2_setup),
        note=f"扫作者分片+排序 vs B-tree 索引(author={author};handle 计时外)",
    ))

    # 3) file-only by-day
    f3: dict = {}
    def f3_setup():
        if "h" not in f3:
            from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
            f3["h"] = FileTweetStore(Path(data_root))
    def f3_thunk():
        return f3["h"].get_by_day(by_day, tz_offset_min=0, min_text_length=0, limit=None)

    cases.append(BenchCase(
        name=f"by-day get_by_day(file-only,{by_day})",
        file=Side(thunk=f3_thunk, setup=f3_setup),
        db=None,
        note="DB 侧无 repo 配对,由 feed/browse 服务层查询承接(handle 计时外)",
    ))

    # 4) file-only 分页
    f4: dict = {}
    def f4_setup():
        if "h" not in f4:
            from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
            f4["h"] = FileTweetStore(Path(data_root))
    def f4_thunk():
        return f4["h"].get_by_author_range(
            author,
            since=datetime(2000, 1, 1, tzinfo=timezone.utc),
            until=datetime(2100, 1, 1, tzinfo=timezone.utc),
            page=1, page_size=50,
        )

    cases.append(BenchCase(
        name="分页 get_by_author_range(file-only)",
        file=Side(thunk=f4_thunk, setup=f4_setup),
        db=None,
        note=f"DB 侧无 repo 配对(author={author};handle 计时外)",
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
    """写路径:save_tweets([batch_size 合成新推]),只测写本身(store 构造/session 获取在计时外)。
    file:setup copytree→fresh temp + 构造 store(计时外);thunk save_tweets;teardown 删 temp。
    db  :setup lazy-once session;thunk save_tweets;teardown rollback(只 flush 不 commit,pg 不污染)。
    合成批=全新 tweet_id 避开去重早停(报告诚实标合成写批)。"""
    import shutil
    import tempfile

    fstate: dict = {"tmp": None, "store": None, "run": 0}

    def file_setup():
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        fstate["run"] += 1
        tmp = tempfile.mkdtemp(prefix="xw-bench-write-")
        src = Path(data_root)
        if src.exists():
            shutil.copytree(src, tmp, dirs_exist_ok=True)
        fstate["tmp"] = tmp
        fstate["store"] = FileTweetStore(Path(tmp))  # 构造计时外

    def file_thunk():
        batch = _synthetic_tweets(batch_size, run_tag=f"f{fstate['run']}")
        return fstate["store"].save_tweets(batch, early_stop_threshold=0)

    def file_teardown():
        if fstate["tmp"]:
            shutil.rmtree(fstate["tmp"], ignore_errors=True)
            fstate["tmp"] = None
            fstate["store"] = None

    dstate: dict = {"s": None, "repo": None, "run": 0}

    async def db_setup():
        if dstate["s"] is None:
            from src.scraper.infrastructure.repository import TweetRepository
            s = _async_session_maker()()
            dstate["s"], dstate["repo"] = s, TweetRepository(s)

    async def db_thunk():
        dstate["run"] += 1
        batch = _synthetic_tweets(batch_size, run_tag=f"d{dstate['run']}")
        return await dstate["repo"].save_tweets(batch, early_stop_threshold=0)

    async def db_teardown():
        if dstate["s"] is not None:
            await dstate["s"].rollback()  # 撤销本轮写,pg 不污染(untimed)

    return BenchCase(
        name=f"写 save_tweets(batch={batch_size} 合成新推)",
        file=Side(thunk=file_thunk, setup=file_setup, teardown=file_teardown),
        db=Side(thunk=db_thunk, setup=db_setup, teardown=db_teardown),
        note="只测写本身;file temp 副本+合成批,db flush 后 rollback。合成写批非真数据写",
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
    """聚合:file get_cost_stats(读时全扫) ↔ DB get_cost_stats(SUM/GROUP BY)。handle 计时外。"""
    f: dict = {}
    def file_setup():
        if "h" not in f:
            from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
            f["h"] = FileSummaryStore(Path(data_root))
    def file_thunk():
        return f["h"].get_cost_stats()

    d: dict = {}
    async def db_setup():
        if "h" not in d:
            from src.summarization.infrastructure.repository import SummarizationRepository
            s = _async_session_maker()()
            d["h"], d["s"] = SummarizationRepository(s), s
    async def db_thunk():
        return await d["h"].get_cost_stats()

    return BenchCase(
        name="聚合 get_cost_stats",
        file=Side(thunk=file_thunk, setup=file_setup),
        db=Side(thunk=db_thunk, setup=db_setup),
        note="读时全扫聚合 vs SUM/GROUP BY(handle 计时外)",
    )


def build_handle_acquisition_case(*, data_root: str) -> BenchCase:
    """handle 获取成本:file FileTweetStore 构造(TweetIdIndex.build 全扫 + views.rebuild_by_day
    全重建,写密集)↔ DB 从连接池获取 session。这是 file 模式相对 DB 的"取 repo"开销(真实 app
    每抓取周期付一次,非每请求)。"""
    def file_thunk():
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
        return FileTweetStore(Path(data_root))

    async def db_thunk():
        s = _async_session_maker()()
        await s.close()

    return BenchCase(
        name="handle 获取 FileTweetStore 构造↔db session 获取",
        file=Side(thunk=file_thunk),
        db=Side(thunk=db_thunk),
        note="file=TweetIdIndex.build 全扫+views.rebuild_by_day 全重建(写);db=连接池取 session",
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


# ---- Task 7: runner 依赖的助手 ----
def probe_real_author(data_root: str) -> str:
    """从 data_migrated tweets 盘面取一个真实作者名(canonical 分片目录名)。"""
    base = Path(data_root) / "tweets"
    if base.exists():
        for child in sorted(base.iterdir()):
            if child.is_dir():
                return child.name
    return DEFAULT_AUTHOR


async def measure_nit3_engine_ms(n: int = 7) -> float:
    """测 file 模式 export/import 路径仍建的 sync engine+Session 开销中位(毫秒)。"""
    import asyncio
    from statistics import median
    from time import perf_counter

    def _one() -> float:
        from sqlalchemy.orm import Session

        from src.database.models import get_engine

        t0 = perf_counter()
        with Session(get_engine()):
            pass
        return (perf_counter() - t0) * 1000.0

    return median(await asyncio.to_thread(lambda: [_one() for _ in range(n)]))
