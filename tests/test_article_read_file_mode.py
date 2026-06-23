"""article 反连接读门面(get_unarticled_tweets)在 XWATCHER_DATA_LAYER=file 下走文件层。

复刻 backfill_articles_for_user 内联的「找无 article 记录的作者推文」反连接查询:
- 路径可证:种子只进文件层 → 断言返回正确 tweet_ids(排除已有 article 的、过滤作者、DESC、limit)。
- 跨模式对账:同数据分别 seed file 与 sqlalchemy(内存 sqlite),两 store 返回同 tweet_ids。
- 服务层接线:backfill_articles_for_user file 模式从门面拿 tweet_ids(monkeypatch client)。
- 故障注入:漏反连接过滤应翻红。
⚠️ 无 round 陷阱豁免:过滤/排序/截断,无除法分桶 → SQLite 是有效 oracle。
created_at 用非 NULL 且互异(limit-边界 tie-order 是已知限制,见门面 docstring)。
"""
from datetime import datetime, timedelta, timezone

import pytest


# ── 种子助手 ───────────────────────────────────────────────


def _tweet(tid, author, created_at, text="hello world"):
    from src.scraper.domain.models import Tweet
    return Tweet(tweet_id=tid, text=text, created_at=created_at, author_username=author,
                 author_display_name=f"{author} disp")


def _article(tid, author):
    from src.scraper.domain.models import Article
    return Article(tweet_id=tid, title=f"t-{tid}", author_username=author,
                   fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc))


async def _seed_tweets(root, tweets):
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    await FileTweetStore(root).save_tweets(list(tweets), early_stop_threshold=0)


async def _seed_articles(root, articles):
    from src.scraper.infrastructure.file_article_repository import FileArticleStore
    await FileArticleStore(root).seed(list(articles))


# ── file 路径可证 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unarticled_excludes_articled_filters_author_desc(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    # alice: t1(最新)/t2/t3;t2 已有 article → 排除。bob: t4(他人作者)→ 排除。
    await _seed_tweets(tmp_path, [
        _tweet("t1", "alice", base + timedelta(hours=3)),
        _tweet("t2", "alice", base + timedelta(hours=2)),
        _tweet("t3", "alice", base + timedelta(hours=1)),
        _tweet("t4", "bob", base + timedelta(hours=5)),
    ])
    await _seed_articles(tmp_path, [_article("t2", "alice")])

    from src.data_layer.provider import get_article_read_repo

    ids = await get_article_read_repo().get_unarticled_tweets("alice", max_tweets=200)
    # DESC by created_at:t1(h3) > t3(h1);t2 排除(有 article);t4 排除(作者 bob)
    assert ids == ["t1", "t3"]


@pytest.mark.asyncio
async def test_unarticled_limit_truncation(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("a", "alice", base + timedelta(hours=1)),
        _tweet("b", "alice", base + timedelta(hours=2)),
        _tweet("c", "alice", base + timedelta(hours=3)),
    ])
    from src.data_layer.provider import get_article_read_repo

    # limit=2 取 DESC 前 2 条:c(h3) > b(h2)
    ids = await get_article_read_repo().get_unarticled_tweets("alice", max_tweets=2)
    assert ids == ["c", "b"]


@pytest.mark.asyncio
async def test_unarticled_case_sensitive_author(monkeypatch, tmp_path):
    """作者名精确匹配(大小写敏感),复刻 ORM `==`。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("x", "Alice", base + timedelta(hours=1)),
        _tweet("y", "alice", base + timedelta(hours=2)),
    ])
    from src.data_layer.provider import get_article_read_repo

    assert await get_article_read_repo().get_unarticled_tweets("alice") == ["y"]
    assert await get_article_read_repo().get_unarticled_tweets("Alice") == ["x"]


@pytest.mark.asyncio
async def test_unarticled_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_article_read_repo

    assert await get_article_read_repo().get_unarticled_tweets("nobody") == []


@pytest.mark.asyncio
async def test_unarticled_all_articled(monkeypatch, tmp_path):
    """该作者全部推文都有 article → 返回空。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("p", "alice", base + timedelta(hours=1)),
        _tweet("q", "alice", base + timedelta(hours=2)),
    ])
    await _seed_articles(tmp_path, [_article("p", "alice"), _article("q", "alice")])
    from src.data_layer.provider import get_article_read_repo

    assert await get_article_read_repo().get_unarticled_tweets("alice") == []


# ── 故障注入 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_faultinj_missing_antijoin_filter(monkeypatch, tmp_path):
    """故意取消反连接过滤(把 articled 集合清空)→ 已有 article 的推文混入 → 断言翻红。

    用 monkeypatch 把 get_all_articles 返回空,模拟"漏掉反连接过滤"的实现 bug:
    此时 t2(有 article)会错误地出现在结果里,正确行为应排除它。
    """
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("t1", "alice", base + timedelta(hours=2)),
        _tweet("t2", "alice", base + timedelta(hours=1)),
    ])
    await _seed_articles(tmp_path, [_article("t2", "alice")])

    from src.data_layer.provider import get_article_read_repo

    # 正确行为:t2 被排除
    assert await get_article_read_repo().get_unarticled_tweets("alice") == ["t1"]

    # 注入 bug:articled 集合被清空(反连接过滤失效)
    import src.scraper.infrastructure.file_article_repository as far

    async def _broken_get_all(self):
        return []

    monkeypatch.setattr(far.FileArticleStore, "get_all_articles", _broken_get_all)
    buggy = await get_article_read_repo().get_unarticled_tweets("alice")
    # bug 下 t2 错误混入 → 与正确结果不同,证明测试对反连接过滤敏感(故障可被捕获)
    assert buggy == ["t1", "t2"]
    assert buggy != ["t1"]


# ── 跨模式对账(file vs sqlalchemy SQLite)────────────────────


async def _build_sqlite_session():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from src.database.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    return engine, session


@pytest.mark.asyncio
async def test_cross_mode_unarticled_equivalence(monkeypatch, tmp_path):
    """同数据 file vs sqlalchemy(SQLite)产同 tweet_ids 列表(含顺序)。"""
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    # alice 4 条互异 created_at;a2/a4 已有 article → 反连接剩 a1/a3。bob 1 条(应被作者过滤掉)。
    tweet_specs = [
        ("a1", "alice", base + timedelta(hours=4)),
        ("a2", "alice", base + timedelta(hours=3)),
        ("a3", "alice", base + timedelta(hours=2)),
        ("a4", "alice", base + timedelta(hours=1)),
        ("b1", "bob", base + timedelta(hours=5)),
    ]
    articled = [("a2", "alice"), ("a4", "alice")]

    # ── 文件层种子 ──
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    await _seed_tweets(tmp_path, [_tweet(t, a, c) for (t, a, c) in tweet_specs])
    await _seed_articles(tmp_path, [_article(t, a) for (t, a) in articled])

    # ── sqlalchemy(SQLite)种子 ──
    from src.scraper.infrastructure.article_models import ArticleOrm
    from src.scraper.infrastructure.models import TweetOrm
    engine, session = await _build_sqlite_session()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for (t, a, c) in tweet_specs:
        session.add(TweetOrm(tweet_id=t, text="x", created_at=c.replace(tzinfo=None),
                             db_created_at=now, author_username=a,
                             author_display_name=f"{a} disp", media=None))
    for (t, a) in articled:
        session.add(ArticleOrm(tweet_id=t, title=f"t-{t}", author_username=a,
                               fetched_at=datetime(2024, 1, 1)))
    await session.commit()

    from src.data_layer.provider import get_article_read_repo

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_ids = await get_article_read_repo().get_unarticled_tweets("alice", max_tweets=200)
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_ids = await get_article_read_repo(session).get_unarticled_tweets("alice", max_tweets=200)

    assert f_ids == s_ids == ["a1", "a3"]

    # limit 截断也对齐
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    f_lim = await get_article_read_repo().get_unarticled_tweets("alice", max_tweets=1)
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")
    s_lim = await get_article_read_repo(session).get_unarticled_tweets("alice", max_tweets=1)
    assert f_lim == s_lim == ["a1"]

    await session.close()
    await engine.dispose()


# ── 服务层接线点 file 模式可跑 ──────────────────────────────


@pytest.mark.asyncio
async def test_backfill_service_file_mode_uses_facade(monkeypatch, tmp_path):
    """backfill_articles_for_user file 模式从门面拿 tweet_ids(不碰 PG session_maker)。

    seed 文件层 2 条无 article 的 alice 推文;mock client.fetch_article 返 404(全 skipped)。
    断言 checked==2 证明服务层确实从文件层门面取到 2 个 tweet_id。
    """
    from unittest.mock import AsyncMock, Mock

    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_tweets(tmp_path, [
        _tweet("s1", "alice", base + timedelta(hours=2)),
        _tweet("s2", "alice", base + timedelta(hours=1)),
    ])

    from src.scraper.client import TwitterClientError
    from src.scraper.scraping_service import ScrapingService
    from returns.result import Failure

    client = AsyncMock()
    # 两条都 404 → 全部 skipped,不触发 save(避免 file 模式 save 路径,本片只验读门面接线)
    client.fetch_article = AsyncMock(
        return_value=Failure(TwitterClientError("资源未找到", status_code=404))
    )
    service = ScrapingService(client=client, parser=Mock(), validator=Mock(),
                              repository=AsyncMock())

    # 若服务层仍直查 PG(未走门面),file 模式无 PG → get_async_session_maker 会崩;
    # 走门面则 checked==2(从文件层门面取到 s1/s2)。
    result = await service.backfill_articles_for_user("alice", max_tweets=10)
    assert result["checked"] == 2
    assert result["skipped"] == 2
    assert result["found"] == 0
    # DESC:s1 先于 s2
    assert client.fetch_article.call_args_list[0].args == ("s1",)
    assert client.fetch_article.call_args_list[1].args == ("s2",)
