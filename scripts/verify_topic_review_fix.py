"""验证 task 9 + task 10 修复:
1. _build_prompt 不再按 dict 顺序截断 author
2. _query_tweets 把 referenced_tweet_text 送进 prompt

跑法: python scripts/verify_topic_review_fix.py
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from src.database.async_session import get_async_session_maker
from src.scraper.infrastructure.models import TweetOrm
from src.topic.services.topic_summary_service import TopicSummaryService

# 抑制 SQL echo 噪声,只打印业务结果
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


TOPIC_ID = 4
SINCE = datetime(2026, 5, 1, 6, 11, 48, tzinfo=timezone.utc)
UNTIL = datetime(2026, 5, 8, 6, 11, 48, tzinfo=timezone.utc)
KEY_TWEET_ID = "2052105960488144910"  # hwchase17 RT @Vtrivedy10 (2688 字符本体)
EXPECTED_DB_ACTIVE_AUTHORS = 43


async def main() -> None:
    factory = get_async_session_maker()
    svc = TopicSummaryService.get_instance()

    async with factory() as session:
        result = await svc.prepare_summary_data(
            session,
            topic_id=TOPIC_ID,
            time_span_hours=24 * 7,
            deadline=UNTIL,
            since=SINCE,
            until=UNTIL,
            review_mode=True,
            tz_offset=-480,
        )

    prompt = result.get("default_prompt", "")
    pool = result.get("allowed_tweet_ids", [])
    tweet_count = result.get("tweet_count", 0)
    account_count = result.get("account_count", 0)

    print("=" * 60)
    print(f"topic_id={TOPIC_ID} window={SINCE.isoformat()} ~ {UNTIL.isoformat()}")
    print(f"prepare_summary_data 返回:")
    print(f"  tweet_count        = {tweet_count}")
    print(f"  account_count      = {account_count} (topic 总账号数)")
    print(f"  allowed_tweet_ids  = {len(pool)} 条")
    print()

    # 反查 DB:tweet_id_pool 对应哪些 author(权威来源,不靠 regex)
    async with factory() as session:
        rows = await session.execute(
            select(TweetOrm.tweet_id, TweetOrm.author_username).where(
                TweetOrm.tweet_id.in_(pool)
            )
        )
        author_by_tid = {tid: uname.lower() for tid, uname in rows.all()}
    authors_in_prompt = set(author_by_tid.values())

    print(f"prompt 实际覆盖 author 数: {len(authors_in_prompt)}")
    print(f"DB 真实 active author 数: {EXPECTED_DB_ACTIVE_AUTHORS}")
    delta = EXPECTED_DB_ACTIVE_AUTHORS - len(authors_in_prompt)
    if delta == 0:
        print("  ✅ 所有 active author 都进了 prompt")
    else:
        print(f"  ⚠️  少 {delta} 个 author 没进 prompt(可能预算紧或公平兜底没塞进)")
    print()

    # 各 author 入选条数分布(top 10 + bottom 10)
    from collections import Counter
    cnt = Counter(author_by_tid.values())
    top = cnt.most_common()
    print(f"各 author 入选推文数分布(共 {len(top)} 个):")
    for u, n in top[:10]:
        print(f"  {u:<20} {n} 条")
    if len(top) > 20:
        print("  ...")
        for u, n in top[-10:]:
            print(f"  {u:<20} {n} 条")
    print()

    # 关键 hwchase17 长推是否入选
    if KEY_TWEET_ID in pool:
        idx = pool.index(KEY_TWEET_ID)
        print(f"✅ hwchase17 关键长推 {KEY_TWEET_ID} 入选 (allowed pool 第 {idx + 1} 条)")
    else:
        print(f"❌ hwchase17 关键长推 {KEY_TWEET_ID} 未入选")
    print()

    # ref_text 抽样:扫 prompt 里有几条 "↪ via" 行
    ref_lines = [ln for ln in prompt.split("\n") if ln.startswith("  ↪ via")]
    print(f"prompt 中 RT/quote 引用行 (↪ via ...): {len(ref_lines)} 条")
    if ref_lines:
        print(f"  样本 1: {ref_lines[0][:200]}")
        if len(ref_lines) > 1:
            print(f"  样本 2: {ref_lines[1][:200]}")

    # 长推命中率:DB 内 ≥300 字符的长推中,有多少进了 prompt
    print()
    sample_text = prompt
    print(f"prompt 总长度: {len(prompt)} 字符 / 估 {len(prompt) // 4} ~ token")


if __name__ == "__main__":
    asyncio.run(main())
