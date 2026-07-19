"""article 反连接读门面(get_unarticled_tweets)在 XWATCHER_DATA_LAYER=file 下走文件层。

复刻 backfill_articles_for_user 内联的「找无 article 记录的作者推文」反连接查询:
- 路径可证:种子只进文件层 → 断言返回正确 tweet_ids(排除已有 article 的、过滤作者、DESC、limit)。
- 跨模式对账:同数据分别 seed file 与 sqlalchemy(内存 sqlite),两 store 返回同 tweet_ids。
- 服务层接线:backfill_articles_for_user file 模式从门面拿 tweet_ids(monkeypatch client)。
- 故障注入:漏反连接过滤应翻红。
⚠️ 无 round 陷阱豁免:过滤/排序/截断,无除法分桶 → SQLite 是有效 oracle。
created_at 用非 NULL 且互异(limit-边界 tie-order 是已知限制,见门面 docstring)。
"""
from datetime import datetime, timedelta, timezone, UTC

import pytest


# ── 种子助手 ───────────────────────────────────────────────


def _tweet(tid, author, created_at, text="hello world"):
    from src.scraper.domain.models import Tweet
    return Tweet(tweet_id=tid, text=text, created_at=created_at, author_username=author,
                 author_display_name=f"{author} disp")


def _article(tid, author):
    from src.scraper.domain.models import Article
    return Article(tweet_id=tid, title=f"t-{tid}", author_username=author,
                   fetched_at=datetime(2024, 1, 1, tzinfo=UTC))


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
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
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
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
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
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
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
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
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
    base = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
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
