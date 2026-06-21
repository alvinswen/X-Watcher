"""article 单元迁移:articles → FileArticleStore.seed。

dropped_columns:db_created_at(DB audit 时间戳,域无)。
注意:fetched_at 是 DateTime(timezone=True)=aware → naive()。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.scraper.domain.models import Article
from src.scraper.infrastructure.article_models import ArticleOrm
from src.scraper.infrastructure.file_article_repository import FileArticleStore


def _to_domain(o: ArticleOrm) -> Article:
    return Article(
        tweet_id=o.tweet_id,
        title=o.title,
        preview_text=o.preview_text,
        cover_image_url=o.cover_image_url,
        content=o.content,
        content_html=o.content_html,
        author_username=o.author_username,
        fetched_at=naive(o.fetched_at),
    )


@register("article")
async def migrate_article(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(ArticleOrm))).scalars().all()
    rep = MigrationReport(entity="article", pg_count=len(rows))
    rep.dropped_columns = ["db_created_at"]
    store = FileArticleStore(data_root)
    store._path.unlink(missing_ok=True)
    domains = [_to_domain(o) for o in rows]
    await store.seed(domains)
    rep.written = len(domains)
    back = {a.tweet_id: a for a in await store.get_all_articles()}
    src = {a.tweet_id: a for a in domains}
    rep.validated = 0
    for tid, sd in src.items():
        bd = back.get(tid)
        if bd is not None and bd.model_dump() == sd.model_dump():
            rep.validated += 1
        else:
            rep.mismatches.append(f"article tweet_id={tid}: readback != source")
    return rep
