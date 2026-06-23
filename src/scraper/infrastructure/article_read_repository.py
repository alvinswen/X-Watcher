"""文件版 article 反连接读门面:找"还没有 article 记录的推文"。

复刻 `src/scraper/scraping_service.py` 的 `backfill_articles_for_user` 内联的那段
直查 ORM 反连接查询(TweetOrm LEFT JOIN ArticleOrm ... ArticleOrm.tweet_id IS NULL),
file 模式下不依赖 ORM,改组合既有 file store 在 Python 槽内做集合差 + 排序 + 截断:
- get_unarticled_tweets:作者名**精确**匹配(大小写敏感,== 非小写化)、该推文在
  articles 集合无记录、按 created_at DESC、limit max_tweets,返回 list[str](tweet_id)。

⚠️ 无 round 陷阱豁免:本片是过滤/排序/截断,无除法分桶,SQLite 是有效 oracle。
created_at 比较经 as_utc 归一(file 落盘 aware +00:00);DESC 排序加 tweet_id 作确定性
tie-break(真实数据 created_at 基本互异;limit-边界同 created_at 的 tie-order 是已知限制,
跨模式对账测试只用非 NULL 且互异的 created_at,见 tests/test_article_read_file_mode.py)。
"""
from __future__ import annotations

from pathlib import Path

from src.storage import paths


class FileArticleReadStore:
    """组合 FileTweetStore + FileArticleStore 的 file 模式反连接读门面。"""

    def __init__(self, data_root: Path) -> None:
        self._root = Path(data_root)

    async def get_unarticled_tweets(self, username: str, max_tweets: int = 200) -> list[str]:
        from src.scraper.infrastructure.file_article_repository import FileArticleStore
        from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

        # 有 article 记录的 tweet_id 集合(反连接 IS NULL 的取反)
        articles = await FileArticleStore(self._root).get_all_articles()
        articled_ids = {a.tweet_id for a in articles}

        # 该作者(精确匹配,大小写敏感)且尚无 article 记录的推文
        tweets = await FileTweetStore(self._root).get_all_tweets()
        candidates = [
            t for t in tweets
            if t.author_username == username and t.tweet_id not in articled_ids
        ]

        # created_at DESC;同 created_at 时按 tweet_id 给确定性 tie-break(降序键取负不可行,
        # 用 reverse=True 配 (created_at, tweet_id) 复合键:两者同向降序)
        candidates.sort(key=lambda t: (paths.as_utc(t.created_at), t.tweet_id), reverse=True)

        limit = max(max_tweets, 0)
        return [t.tweet_id for t in candidates[:limit]]


class SqlalchemyArticleReadStore:
    """sqlalchemy 模式:逐字复刻原内联反连接 SQL,SQL 字节零变化。"""

    def __init__(self, session) -> None:
        self._session = session

    async def get_unarticled_tweets(self, username: str, max_tweets: int = 200) -> list[str]:
        from sqlalchemy import select

        from src.scraper.infrastructure.article_models import ArticleOrm
        from src.scraper.infrastructure.models import TweetOrm

        stmt = (
            select(TweetOrm.tweet_id)
            .outerjoin(ArticleOrm, TweetOrm.tweet_id == ArticleOrm.tweet_id)
            .where(
                TweetOrm.author_username == username,
                ArticleOrm.tweet_id.is_(None),
            )
            .order_by(TweetOrm.created_at.desc())
            .limit(max_tweets)
        )
        rows = await self._session.execute(stmt)
        return [row[0] for row in rows]
