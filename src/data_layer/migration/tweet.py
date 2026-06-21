"""tweet 单元迁移:tweets(40K)→ FileTweetStore.save_tweets(early_stop_threshold=0)+ by-day 视图。

要点(以源码为准):
- 复用 TweetOrm.to_domain()(权威 ORM→域转换:media/referenced_tweet_media→list[Media],
  reference_type→enum;它把 created_at 强制成 aware UTC)→ 再 naive() 归一(对齐文件层 naive 约定)。
  注:文件层 _to_record 写盘时又把 naive→aware UTC,故传 aware/naive 落盘字节一致;naive() 保证 UTC 归一。
- early_stop_threshold=0 关掉"连续跳过早停"(= export/import seed_tweets 范式),全量写。
- 幂等:迁移前 rm -rf tweets/ + _views/。by-day 视图由 save_tweets 自动 by_day_upsert 重建。
- dropped_columns:db_created_at/db_updated_at(DB audit,域无)。
- 校验口径(分两层,量大):① 全 canonical 分片 rec 计数 == pg 且每条 tweet_id 都属于源;
  ② 抽样 200 条深比对 on-disk rec == _to_record(源域)(byte-faithful)。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore, _to_record
from src.scraper.infrastructure.models import TweetOrm
from src.storage import paths


def _to_domain(o: TweetOrm):
    t = o.to_domain()  # 权威转换(created_at 被强制 aware UTC)
    return t.model_copy(update={"created_at": naive(t.created_at)})


async def _seed_and_validate(domains, pg_count: int, data_root: Path) -> MigrationReport:
    root = Path(data_root)
    shutil.rmtree(root / "tweets", ignore_errors=True)
    shutil.rmtree(root / "_views", ignore_errors=True)
    rep = MigrationReport(entity="tweet", pg_count=pg_count)
    rep.dropped_columns = ["db_created_at", "db_updated_at"]
    store = FileTweetStore(data_root)
    await store.save_tweets(domains, early_stop_threshold=0)

    src_by_id = {t.tweet_id: t for t in domains}
    total = 0
    unknown = 0
    sample_checked = 0
    sample_bad = 0
    for shard in paths.iter_canonical_shards(root):
        with shard.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                rec = json.loads(line)
                tid = rec.get("tweet_id")
                if tid not in src_by_id:
                    unknown += 1
                    continue
                if sample_checked < 200:
                    sample_checked += 1
                    if rec != _to_record(src_by_id[tid]):
                        sample_bad += 1
    rep.written = total
    if total == pg_count and unknown == 0 and sample_bad == 0:
        rep.validated = total
    else:
        rep.validated = 0
        if total != pg_count:
            rep.mismatches.append(f"tweet count: shards={total} pg={pg_count}")
        if unknown:
            rep.mismatches.append(f"tweet: {unknown} shard recs with unknown tweet_id")
        if sample_bad:
            rep.mismatches.append(f"tweet sample: {sample_bad}/{sample_checked} recs != _to_record(source)")
    return rep


@register("tweet")
async def migrate_tweet(session, data_root: Path) -> MigrationReport:
    rows = (await session.execute(select(TweetOrm))).scalars().all()
    domains = [_to_domain(o) for o in rows]
    return await _seed_and_validate(domains, len(rows), data_root)
