# src/sync/infrastructure/file_import_repository.py
"""文件版 Import 门面:6 import_* 重写策略分支(insert/skip/overwrite-by-key/merge)。

- 非 topics:get-by-key 查存在 → 调 Task 1 的 upsert_*(record-level 直存导出格式 dict)。
- topics:直接读写 topics.json 四集合 doc(route-I 例外:create_task/create_summary 写死 now()
  与 oracle 从 dict 取 created_at 冲突;直操可用 import dict 的 created_at)。
- seed_*/export_* 委派 FileExportStore(read-back 复用 export 片);import 与 seed 共享自有写 store
  实例(tweets 索引一致性)。两侧 import_* 同签名收 list[dict]+strategy(str enum 比较跨类成立)。
- ⚠️ tz_offset 存而不投(沿用第六片 B):export_serializers 硬编码 0,fixtures 恒 0。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.preference.infrastructure.file_schedule_repository import FileScheduleStore
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.scraper.infrastructure.file_article_repository import FileArticleStore
from src.topic.infrastructure.file_topic_summary_task_repository import FileTopicSummaryTaskStore
from src.topic.infrastructure.file_topic_repository import FileTopicStore
from src.sync.domain.models import ConflictStrategy, ImportStats
from src.sync.infrastructure.file_export_repository import FileExportStore
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc

_FIXED = "2000-01-01T00:00:00"  # 非导出面时间戳(topic/account)用固定值,避 now()非确定性


def _to_naive(s):
    """ISO 串/datetime → naive UTC datetime(逐字对齐 oracle _iso_to_naive_dt:先 astimezone(utc) 再剥 tz)。None→None。"""
    if s is None:
        return None
    dt = datetime.fromisoformat(s) if isinstance(s, str) else s
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _naive_str(v):
    """aware ISO 串 → naive ISO 串(剥 tz);None→None。"""
    n = _to_naive(v)
    return n.isoformat() if n is not None else None


# 各实体业务时间戳字段:import 写入须把导出格式的 aware("+00:00")串归一为 naive 串,
# 对齐 oracle dict_to_*(_iso_to_naive_dt)+ 文件世界 naive 约定(seed/create 存 naive)。
# 否则 import 的 aware 串与 seed 的 naive 串混存,会令 get_all_follows 等按 domain datetime
# 排序时 "naive vs aware 不可比" 崩溃(实测 FOL 混合案)。
_DT_FIELDS = {
    "follows": ("added_at", "backfill_completed_at"),
    "schedule": ("next_run_time", "updated_at"),
    "tweets": ("created_at",),
    "summaries": ("created_at",),
    "articles": ("fetched_at",),
}


def _naive_item(item, kind):
    """返回 item 副本:把该实体的 datetime 字段转 naive ISO 串(对齐 oracle/文件世界 naive 约定)。"""
    return {**item, **{f: _naive_str(item.get(f)) for f in _DT_FIELDS[kind] if f in item}}


class FileImportStore:
    def __init__(self, data_root: Path) -> None:
        root = Path(data_root)
        self._root = root
        self._follows = FileFollowStore(root)
        self._schedule = FileScheduleStore(root)
        self._tweets = FileTweetStore(root)
        self._summaries = FileSummaryStore(root)
        self._articles = FileArticleStore(root)
        self._tasks_store = FileTopicSummaryTaskStore(root)
        self._topic_store = FileTopicStore(root)
        self._topics_path = root / "topics" / "topics.json"

    # ── seed(初态,委派 FileExportStore 同款,两侧 case 共用)──
    async def seed_follows(self, follows):
        await self._follows.seed(follows)

    async def seed_schedule(self, config):
        await self._schedule.seed(config)

    async def seed_tweets(self, tweets):
        await self._tweets.save_tweets(tweets, early_stop_threshold=0)

    async def seed_summaries(self, records):
        await self._summaries.seed(records)

    async def seed_articles(self, articles):
        await self._articles.seed(articles)

    async def seed_topics(self, topics, accounts=None, tasks=None, summaries=None):
        await self._tasks_store.seed(topics, tasks=tasks or [], summaries=summaries or [])
        for topic_id, usernames in (accounts or {}).items():
            await self._topic_store.replace_accounts(topic_id, list(usernames))

    # ── export(read-back,委派 FileExportStore 新建实例:扫盘,索引/视图无关)──
    async def export_follows(self):
        return await FileExportStore(self._root).export_follows()

    async def export_schedule_config(self):
        return await FileExportStore(self._root).export_schedule_config()

    async def export_tweets(self, since=None, until=None, authors=None):
        return await FileExportStore(self._root).export_tweets(since, until, authors)

    async def export_summaries(self, tweet_ids=None):
        return await FileExportStore(self._root).export_summaries(tweet_ids)

    async def export_articles(self, tweet_ids=None):
        return await FileExportStore(self._root).export_articles(tweet_ids)

    async def export_topics(self):
        return await FileExportStore(self._root).export_topics()

    # ── import(策略分支,逐字镜像 oracle ImportRepository 语义)──
    async def import_follows(self, items, strategy) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "follows")    # 存 naive 串(对齐 oracle/文件世界,避混存崩排序)
            existing = await self._follows.get_follow_by_username(item["username"])
            if existing is None:
                await self._follows.upsert_follow(item); stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._follows.upsert_follow(item); stats.updated += 1
            elif strategy == ConflictStrategy.merge:
                imp = _to_naive(item.get("added_at"))
                cur = _to_naive(existing.added_at)
                if imp and cur and imp > cur:
                    await self._follows.upsert_follow(item); stats.updated += 1
                else:
                    stats.skipped += 1
        return stats

    async def import_schedule_config(self, item, strategy) -> ImportStats:
        stats = ImportStats()
        if item is None:
            return stats
        item = _naive_item(item, "schedule")
        existing = await self._schedule.get_schedule_config()
        if existing is None:
            await self._schedule.overwrite_schedule_config(item); stats.inserted += 1
        elif strategy == ConflictStrategy.skip:
            stats.skipped += 1
        else:
            await self._schedule.overwrite_schedule_config(item); stats.updated += 1
        return stats

    async def import_tweets(self, items, strategy) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "tweets")
            if not await self._tweets.tweet_exists(item["tweet_id"]):
                await self._tweets.upsert_tweets([item]); stats.inserted += 1
            elif strategy == ConflictStrategy.merge:
                stats.skipped += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._tweets.upsert_tweets([item]); stats.updated += 1
        return stats

    async def import_summaries(self, items, strategy) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "summaries")
            if not await self._summaries.summary_exists(item["summary_id"]):
                await self._summaries.upsert_summary(item); stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.merge:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._summaries.upsert_summary(item); stats.updated += 1
        return stats

    async def import_articles(self, items, strategy) -> ImportStats:
        stats = ImportStats()
        for item in items:
            item = _naive_item(item, "articles")
            if await self._articles.get_article(item["tweet_id"]) is None:
                await self._articles.overwrite_article(item); stats.inserted += 1
            elif strategy == ConflictStrategy.skip:
                stats.skipped += 1
            elif strategy == ConflictStrategy.merge:
                stats.skipped += 1
            elif strategy == ConflictStrategy.overwrite:
                await self._articles.overwrite_article(item); stats.updated += 1
        return stats

    # ── topics:直接四集合 doc 操作(route-I 例外)──
    def _load_topics_doc(self) -> dict:
        doc = read_doc(self._topics_path)
        if doc is None:
            doc = {}
        doc.setdefault("topics", {}); doc.setdefault("accounts", {})
        doc.setdefault("tasks", {}); doc.setdefault("summaries", {})
        seq = doc.setdefault("_seq", {})
        for k in ("topics", "accounts", "tasks", "summaries"):
            seq.setdefault(k, 0)
        return doc

    @staticmethod
    def _find_topic_id(doc, name):
        for r in doc["topics"].values():
            if r["name"] == name:
                return r["id"]
        return None

    def _add_account(self, doc, topic_id, username):
        doc["_seq"]["accounts"] = int(doc["_seq"]["accounts"]) + 1
        aid = doc["_seq"]["accounts"]
        doc["accounts"][str(aid)] = {"id": aid, "topic_id": topic_id,
                                     "username": username, "added_at": _FIXED}

    def _create_task(self, doc, topic_id, td):
        # ⚠️ task/summary 的 created_at/deadline 必来自 td(import dict,已是导出格式 ISO 串);
        # 缺省即契约违例,刻意不回填 now()(对齐确定性纪律,区别于 oracle 的 `or datetime.now()` 兜底)。
        doc["_seq"]["tasks"] = int(doc["_seq"]["tasks"]) + 1
        tkid = doc["_seq"]["tasks"]
        doc["tasks"][str(tkid)] = {
            "id": tkid, "topic_id": topic_id, "time_span_hours": td["time_span_hours"],
            "deadline": _naive_str(td["deadline"]), "custom_prompt": td.get("custom_prompt"),
            "tz_offset": td.get("tz_offset", 0), "status": td.get("status", "pending"),
            "error_message": td.get("error_message"), "created_at": _naive_str(td.get("created_at")),
            "started_at": _naive_str(td.get("started_at")), "completed_at": _naive_str(td.get("completed_at"))}
        sd = td.get("summary")
        if sd:
            doc["_seq"]["summaries"] = int(doc["_seq"]["summaries"]) + 1
            sid = doc["_seq"]["summaries"]
            doc["summaries"][str(sid)] = {
                "id": sid, "task_id": tkid, "content": sd["content"],
                "llm_provider": sd["llm_provider"], "llm_model": sd["llm_model"],
                "prompt_tokens": sd.get("prompt_tokens", 0),
                "completion_tokens": sd.get("completion_tokens", 0),
                "total_tokens": sd.get("total_tokens", 0), "cost_usd": sd.get("cost_usd", 0.0),
                "tweet_count": sd.get("tweet_count", 0), "account_count": sd.get("account_count", 0),
                "created_at": _naive_str(sd.get("created_at")), "metadata_json": {}}

    def _create_topic(self, doc, item):
        doc["_seq"]["topics"] = int(doc["_seq"]["topics"]) + 1
        tid = doc["_seq"]["topics"]
        doc["topics"][str(tid)] = {"id": tid, "name": item["name"],
                                   "description": item.get("description"), "user_id": None,
                                   "created_at": _FIXED, "updated_at": _FIXED}
        for u in item.get("accounts", []):
            self._add_account(doc, tid, u)
        for td in item.get("summary_tasks", []):
            self._create_task(doc, tid, td)

    def _overwrite_topic(self, doc, tid, item):
        # ⚠️ 忠实复现 oracle 运行行为(owner CR-020 决定 A):旧 ORM `TopicOrm.summary_tasks`
        # 是 lazy="noload"(@77e41a4 本有),旧 _overwrite_topic 的 `list(existing.summary_tasks)`
        # 恒空 → 删除循环空转 → 旧 task/summary 实际从不删除、新 task 追加。accounts 是
        # lazy="selectin" 故删除循环正常 → 清空重建。本处只更新 description + 重建 accounts +
        # 追加新 summary_tasks(保留旧),与 oracle byte 一致(非候选自创语义,是复现旧实现的潜在 bug)。
        doc["topics"][str(tid)]["description"] = item.get("description")
        doc["topics"][str(tid)]["updated_at"] = _FIXED
        doc["accounts"] = {k: a for k, a in doc["accounts"].items() if a["topic_id"] != tid}
        for u in item.get("accounts", []):
            self._add_account(doc, tid, u)
        for td in item.get("summary_tasks", []):       # 旧 task 保留(noload 既有行为),仅追加新
            self._create_task(doc, tid, td)

    def _merge_topic(self, doc, tid, item):
        existing = {a["username"] for a in doc["accounts"].values() if a["topic_id"] == tid}
        for u in item.get("accounts", []):
            if u not in existing:
                self._add_account(doc, tid, u)

    async def import_topics(self, items, strategy) -> ImportStats:
        stats = ImportStats()
        async with shard_lock(self._topics_path):
            doc = self._load_topics_doc()
            for item in items:
                tid = self._find_topic_id(doc, item["name"])
                if tid is None:
                    self._create_topic(doc, item); stats.inserted += 1
                elif strategy == ConflictStrategy.skip:
                    stats.skipped += 1
                elif strategy == ConflictStrategy.overwrite:
                    self._overwrite_topic(doc, tid, item); stats.updated += 1
                elif strategy == ConflictStrategy.merge:
                    self._merge_topic(doc, tid, item); stats.updated += 1
            atomic_write_doc(self._topics_path, doc)
        return stats
