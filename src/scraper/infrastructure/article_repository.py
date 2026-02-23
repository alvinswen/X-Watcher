"""X Articles 数据访问层。

提供文章的保存和查询操作。
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper.domain.models import Article
from src.scraper.infrastructure.article_models import ArticleOrm

logger = logging.getLogger(__name__)


def _orm_to_domain(orm: ArticleOrm) -> Article:
    """将 ORM 模型转换为领域模型。"""
    return Article(
        tweet_id=orm.tweet_id,
        title=orm.title,
        preview_text=orm.preview_text,
        cover_image_url=orm.cover_image_url,
        content=orm.content,
        content_html=orm.content_html,
        author_username=orm.author_username,
        fetched_at=orm.fetched_at,
    )


class ArticleRepository:
    """文章仓库。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def article_exists(self, tweet_id: str) -> bool:
        """检查文章是否已存在。"""
        stmt = select(ArticleOrm.tweet_id).where(ArticleOrm.tweet_id == tweet_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def save_article(self, article: Article) -> bool:
        """保存文章（不存在时插入，已存在时跳过）。

        Returns:
            bool: True 表示新增，False 表示已存在跳过
        """
        if await self.article_exists(article.tweet_id):
            logger.debug("文章已存在，跳过: tweet_id=%s", article.tweet_id)
            return False

        orm_article = ArticleOrm(
            tweet_id=article.tweet_id,
            title=article.title,
            preview_text=article.preview_text,
            cover_image_url=article.cover_image_url,
            content=article.content,
            content_html=article.content_html,
            author_username=article.author_username,
            fetched_at=article.fetched_at,
        )
        self._session.add(orm_article)
        await self._session.flush()
        logger.info("文章已保存: tweet_id=%s, title=%s", article.tweet_id, article.title)
        return True

    async def get_article(self, tweet_id: str) -> Article | None:
        """根据 tweet_id 获取文章。"""
        stmt = select(ArticleOrm).where(ArticleOrm.tweet_id == tweet_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_articles_by_author(
        self,
        username: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Article]:
        """查询指定作者的文章列表（按抓取时间倒序）。"""
        stmt = (
            select(ArticleOrm)
            .where(ArticleOrm.author_username == username)
            .order_by(ArticleOrm.fetched_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [_orm_to_domain(orm) for orm in result.scalars().all()]

    async def count_articles(self) -> int:
        """统计文章总数。"""
        stmt = select(func.count()).select_from(ArticleOrm)
        result = await self._session.execute(stmt)
        return result.scalar_one()
