# src/scraper/infrastructure/file_article_repository.py
"""文件版 ArticleStore:data/articles/articles.json 单集合文档。

盘面: {"articles": {<tweet_id>: {…8字段…}}}
- 键=tweet_id(调用方提供的不可变主键,无 id 分配);无外部 FK
- shard_lock 下 load→mutate→atomic_write_doc(写路径);读路径无锁(同前七片)
- save_article insert-if-not-exists:命中跳过返 False(保留原记录、不覆盖),未命中写入返 True
- get_articles_by_author 过滤 author + fetched_at DESC(None 殿后,≡ sqlite NULL DESC)+ limit/offset
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.scraper.domain.models import Article
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


class FileArticleStore:
    """ArticleStore 的文件实现(5 方法 + seed 测试种子)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "articles" / "articles.json"

    def _load(self) -> dict[str, Any]:
        doc = read_doc(self._path)
        if doc is None:
            return {"articles": {}}
        return doc

    @staticmethod
    def _to_domain(rec: dict[str, Any]) -> Article:
        return Article(**rec)

    # —— 测试种子(非契约方法):按列表顺序写入,控制插入序 ——
    async def seed(self, articles: list[Article]) -> None:
        async with shard_lock(self._path):
            recs = {a.tweet_id: a.model_dump(mode="json") for a in articles}
            atomic_write_doc(self._path, {"articles": recs})

    async def article_exists(self, tweet_id: str) -> bool:
        return tweet_id in self._load()["articles"]

    async def save_article(self, article: Article) -> bool:
        async with shard_lock(self._path):
            doc = self._load()
            articles = doc["articles"]
            if article.tweet_id in articles:
                return False                       # 跳过、保留原记录(不覆盖)
            articles[article.tweet_id] = article.model_dump(mode="json")
            atomic_write_doc(self._path, doc)
            return True

    async def get_article(self, tweet_id: str) -> Article | None:
        rec = self._load()["articles"].get(tweet_id)
        return self._to_domain(rec) if rec is not None else None

    async def get_articles_by_author(self, username: str, *,
                                     limit: int = 50, offset: int = 0) -> list[Article]:
        recs = [r for r in self._load()["articles"].values()
                if r.get("author_username") == username]
        # fetched_at DESC 且 None 殿后(≡ sqlite ORDER BY fetched_at DESC:NULL 最小→末尾);
        # 相同/None 段保插入序(list.sort 稳定 + dict 插入序 ≡ sqlite 表扫描序)。
        # ISO 字符串字典序==时序(fixtures 用统一 naive datetime 保证)。
        recs.sort(key=lambda r: (r.get("fetched_at") is not None, r.get("fetched_at") or ""),
                  reverse=True)
        page = recs[offset:offset + limit]
        return [self._to_domain(r) for r in page]

    async def count_articles(self) -> int:
        return len(self._load()["articles"])

    async def get_all_articles(self) -> list[Article]:
        """枚举全部文章记录(无序;Export 全量读)。"""
        return [self._to_domain(r) for r in self._load()["articles"].values()]

    async def overwrite_article(self, fields: dict[str, Any]) -> None:
        """按 tweet_id 插入或全字段覆盖(import 写底座;fields=导出格式 8 字段)。"""
        async with shard_lock(self._path):
            doc = self._load()
            doc["articles"][fields["tweet_id"]] = dict(fields)
            atomic_write_doc(self._path, doc)
