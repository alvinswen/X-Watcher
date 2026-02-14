#!/usr/bin/env python
"""Debug fetch: 诊断推文抓取管道问题。

从 TwitterAPI.io 获取指定用户的推文，保存原始 API 响应，
并生成逐条推文的管道处理报告，与数据库已存数据做对比。

Usage:
    python scripts/debug_fetch.py <username> [--count N] [--output-dir DIR]

Examples:
    python scripts/debug_fetch.py elonmusk --count 10
    python scripts/debug_fetch.py sama --count 50 --output-dir my_reports
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8")

import httpx
from sqlalchemy import select

from src.config import get_settings
from src.database.async_session import get_async_session_maker
from src.scraper.client import (
    _convert_twitterapi_date_to_iso,
    _extract_full_text,
    _extract_media_from_tweet_obj,
)
from src.scraper.infrastructure.models import TweetOrm
from src.scraper.infrastructure.repository import TweetRepository
from src.scraper.parser import TweetParser
from src.scraper.validator import TweetValidator


# ──────────────────────────────────────────────
# 1. CLI 参数解析
# ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="诊断推文抓取管道：获取原始 API 数据并与数据库对比",
    )
    parser.add_argument("username", help="Twitter 用户名（不带 @）")
    parser.add_argument("--count", type=int, default=20, help="请求推文数量（默认 20）")
    parser.add_argument("--output-dir", default="debug_reports", help="输出目录（默认 debug_reports）")
    return parser.parse_args()


# ──────────────────────────────────────────────
# 2. 直接调用 TwitterAPI.io 获取原始数据
# ──────────────────────────────────────────────

async def fetch_raw(username: str, settings: Any) -> dict:
    """直接调用 TwitterAPI.io，返回未转换的原始 JSON。"""
    async with httpx.AsyncClient(
        base_url=settings.twitter_base_url,
        headers={
            "X-API-Key": settings.twitter_api_key,
            "Content-Type": "application/json",
        },
        timeout=30.0,
    ) as client:
        resp = await client.get(
            "/user/last_tweets",
            params={"userName": username, "includeReplies": False},
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────
# 3. v2 格式转换 + 诊断信息收集
#    逻辑复制自 client.py:340-473，额外记录诊断数据
# ──────────────────────────────────────────────

def _detect_text_source(tweet_obj: dict) -> dict:
    """检测文本来源及各候选长度。"""
    candidates = {}
    note_tweet = tweet_obj.get("note_tweet")
    if isinstance(note_tweet, dict):
        note_text = note_tweet.get("text")
        if note_text and isinstance(note_text, str):
            candidates["note_tweet.text"] = len(note_text)

    full_text = tweet_obj.get("full_text")
    if full_text and isinstance(full_text, str):
        candidates["full_text"] = len(full_text)

    text = tweet_obj.get("text")
    if text and isinstance(text, str):
        candidates["text"] = len(text)

    if not candidates:
        return {"source": None, "candidates": {}}

    best = max(candidates, key=candidates.get)
    return {"source": best, "candidates": candidates}


def convert_to_v2_with_diagnostics(
    raw_data: dict, username: str
) -> tuple[dict, list[dict]]:
    """将 TwitterAPI.io 原始响应转换为 v2 格式，同时收集诊断信息。

    Returns:
        (v2_response, per_tweet_diagnostics)
    """
    # 提取 tweets 数组（同 client.py:342-353 的格式检测逻辑）
    tweets_array = None
    format_detected = None

    if "data" in raw_data and isinstance(raw_data.get("data"), dict):
        inner_data = raw_data.get("data", {})
        if "tweets" in inner_data:
            tweets_array = inner_data.get("tweets", [])
            format_detected = "nested (data.tweets)"
    elif "tweets" in raw_data:
        tweets_array = raw_data.get("tweets", [])
        format_detected = "direct (tweets)"

    if tweets_array is None:
        # 可能已经是标准格式，或格式无法识别
        return raw_data, []

    # 转换逻辑，复制自 client.py:356-473
    tweets_data: list[dict] = []
    users_map: dict[str, dict] = {}
    all_media: list[dict] = []
    diagnostics: list[dict] = []

    for idx, tweet in enumerate(tweets_array):
        diag: dict[str, Any] = {"index": idx, "raw_tweet_id": tweet.get("id")}

        # 文本来源诊断
        text_info = _detect_text_source(tweet)
        diag["text_source"] = text_info["source"]
        diag["text_candidates"] = text_info["candidates"]

        tweet_id = tweet.get("id")
        tweet_text = _extract_full_text(tweet) or tweet.get("text", "")
        diag["text_length"] = len(tweet_text) if tweet_text else 0

        # 日期转换
        created_at_raw = tweet.get("createdAt")
        created_at_iso = _convert_twitterapi_date_to_iso(created_at_raw)
        diag["date_raw"] = created_at_raw
        diag["date_converted"] = created_at_iso

        # 引用关系
        referenced_tweets: list[dict] = []
        retweeted_tweet_obj = tweet.get("retweeted_tweet")
        quoted_tweet_obj = tweet.get("quoted_tweet")

        referenced_tweet_text = None
        referenced_tweet_media = None
        referenced_tweet_author_username = None

        if isinstance(retweeted_tweet_obj, dict) and retweeted_tweet_obj.get("id"):
            referenced_tweets.append({
                "type": "retweeted",
                "id": str(retweeted_tweet_obj["id"]),
            })
            referenced_tweet_text = _extract_full_text(retweeted_tweet_obj)
            referenced_tweet_media = _extract_media_from_tweet_obj(retweeted_tweet_obj)
            rt_author = retweeted_tweet_obj.get("author")
            if isinstance(rt_author, dict):
                referenced_tweet_author_username = rt_author.get("userName")
            diag["reference_type"] = "retweeted"
        elif isinstance(quoted_tweet_obj, dict) and quoted_tweet_obj.get("id"):
            referenced_tweets.append({
                "type": "quoted",
                "id": str(quoted_tweet_obj["id"]),
            })
            referenced_tweet_text = _extract_full_text(quoted_tweet_obj)
            referenced_tweet_media = _extract_media_from_tweet_obj(quoted_tweet_obj)
            qt_author = quoted_tweet_obj.get("author")
            if isinstance(qt_author, dict):
                referenced_tweet_author_username = qt_author.get("userName")
            diag["reference_type"] = "quoted"
        elif tweet.get("isReply") and tweet.get("inReplyToId"):
            referenced_tweets.append({
                "type": "replied_to",
                "id": str(tweet["inReplyToId"]),
            })
            diag["reference_type"] = "replied_to"
        else:
            diag["reference_type"] = None

        # 截断检测
        diag["ref_text_truncated"] = False
        if referenced_tweet_text and len(referenced_tweet_text) < 300:
            stripped = referenced_tweet_text.rstrip()
            if stripped.endswith("\u2026") or stripped.endswith("..."):
                diag["ref_text_truncated"] = True

        diag["ref_text_length"] = len(referenced_tweet_text) if referenced_tweet_text else 0
        diag["ref_author"] = referenced_tweet_author_username

        # 构建标准推文
        standard_tweet: dict[str, Any] = {
            "id": tweet_id,
            "text": tweet_text,
            "created_at": created_at_iso,
        }
        if referenced_tweets:
            standard_tweet["referenced_tweets"] = referenced_tweets
        if referenced_tweet_text:
            standard_tweet["referenced_tweet_text"] = referenced_tweet_text
        if referenced_tweet_media:
            standard_tweet["referenced_tweet_media"] = referenced_tweet_media
        if referenced_tweet_author_username:
            standard_tweet["referenced_tweet_author_username"] = referenced_tweet_author_username

        # 主推文媒体
        main_media = _extract_media_from_tweet_obj(tweet)
        diag["media_count"] = len(main_media)
        if main_media:
            media_keys = [m["media_key"] for m in main_media]
            standard_tweet["attachments"] = {"media_keys": media_keys}
            all_media.extend(main_media)

        # 引用推文媒体
        diag["ref_media_count"] = len(referenced_tweet_media) if referenced_tweet_media else 0

        # author 信息
        author_obj = tweet.get("author")
        if isinstance(author_obj, dict):
            author_id_val = str(author_obj.get("id") or author_obj.get("userName", ""))
            if author_id_val:
                standard_tweet["author_id"] = author_id_val
                users_map[author_id_val] = {
                    "username": author_obj.get("userName"),
                    "name": author_obj.get("name"),
                }
            diag["author_from_api"] = author_obj.get("userName")
        else:
            diag["author_from_api"] = None

        tweets_data.append(standard_tweet)
        diagnostics.append(diag)

    # 构造标准响应
    standard_response: dict[str, Any] = {"data": tweets_data}
    includes: dict[str, Any] = {}
    if users_map:
        includes["users"] = [
            {"id": uid, "username": info["username"], "name": info["name"]}
            for uid, info in users_map.items()
        ]
    if all_media:
        includes["media"] = all_media
    if includes:
        standard_response["includes"] = includes

    # author_id 补丁（复制自 scraping_service.py:249-270）
    if "data" in standard_response and isinstance(standard_response["data"], list):
        needs_author_info = any(
            t.get("author_id") is None for t in standard_response["data"]
        )
        if needs_author_info:
            for t in standard_response["data"]:
                t["author_id"] = username
            standard_response.setdefault("includes", {})["users"] = [
                {"id": username, "username": username, "name": username}
            ]

    return standard_response, diagnostics


# ──────────────────────────────────────────────
# 4. 文本清理差异分析
# ──────────────────────────────────────────────

def analyze_text_cleaning(original: str, cleaned: str) -> list[dict]:
    """分析 validator._clean_text 对文本做了哪些变更。"""
    changes: list[dict] = []

    newline_count = len(re.findall(r"[\n\r]+", original))
    if newline_count:
        changes.append({"type": "newline_removed", "count": newline_count})

    multi_space_count = len(re.findall(r"\s{2,}", original))
    if multi_space_count:
        changes.append({"type": "space_collapsed", "count": multi_space_count})

    stripped_diff = len(original) - len(original.strip())
    if stripped_diff > 0:
        changes.append({"type": "whitespace_stripped", "chars": stripped_diff})

    if len(original) > 25000:
        changes.append({"type": "truncated", "original_length": len(original)})

    if len(original) != len(cleaned):
        changes.append({
            "type": "length_change",
            "before": len(original),
            "after": len(cleaned),
        })

    return changes


# ──────────────────────────────────────────────
# 5. 数据库对比
# ──────────────────────────────────────────────

async def get_db_data(tweet_ids: list[str]) -> tuple[set[str], dict, dict]:
    """查询 DB 中已有的推文和去重信息。

    Returns:
        (existing_ids, db_tweets_by_id, dedup_map)
    """
    if not tweet_ids:
        return set(), {}, {}

    session_maker = get_async_session_maker()
    async with session_maker() as session:
        repo = TweetRepository(session)
        existing_ids = await repo.batch_check_exists(tweet_ids)

        db_tweets: dict = {}
        dedup_map: dict = {}
        if existing_ids:
            stmt = select(TweetOrm).where(TweetOrm.tweet_id.in_(existing_ids))
            result = await session.execute(stmt)
            for orm in result.scalars().all():
                db_tweets[orm.tweet_id] = orm.to_domain()
                if orm.deduplication_group_id:
                    dedup_map[orm.tweet_id] = str(orm.deduplication_group_id)

    return existing_ids, db_tweets, dedup_map


def compare_tweets(fresh: Any, stored: Any) -> dict:
    """逐字段对比新处理的推文与 DB 已存推文。"""
    diffs: dict[str, Any] = {}

    simple_fields = [
        "text", "author_username", "author_display_name",
        "referenced_tweet_id", "reference_type",
        "referenced_tweet_text", "referenced_tweet_author_username",
    ]
    for field in simple_fields:
        fresh_val = getattr(fresh, field, None)
        stored_val = getattr(stored, field, None)
        # reference_type 是 enum，转为 str 对比
        if hasattr(fresh_val, "value"):
            fresh_val = fresh_val.value
        if hasattr(stored_val, "value"):
            stored_val = stored_val.value
        if fresh_val != stored_val:
            diffs[field] = {"fresh": str(fresh_val)[:200], "stored": str(stored_val)[:200]}

    # created_at 对比（忽略微秒差异）
    if fresh.created_at and stored.created_at:
        f_ts = fresh.created_at.replace(microsecond=0)
        s_ts = stored.created_at.replace(microsecond=0)
        if f_ts != s_ts:
            diffs["created_at"] = {
                "fresh": str(fresh.created_at),
                "stored": str(stored.created_at),
            }

    # media 对比
    fresh_media_keys = {m.media_key for m in (fresh.media or [])}
    stored_media_keys = {m.media_key for m in (stored.media or [])}
    if fresh_media_keys != stored_media_keys:
        diffs["media"] = {
            "fresh_count": len(fresh_media_keys),
            "stored_count": len(stored_media_keys),
            "only_in_fresh": sorted(fresh_media_keys - stored_media_keys),
            "only_in_stored": sorted(stored_media_keys - fresh_media_keys),
        }

    # referenced_tweet_media 对比
    fresh_ref_media = {m.media_key for m in (fresh.referenced_tweet_media or [])}
    stored_ref_media = {m.media_key for m in (stored.referenced_tweet_media or [])}
    if fresh_ref_media != stored_ref_media:
        diffs["referenced_tweet_media"] = {
            "fresh_count": len(fresh_ref_media),
            "stored_count": len(stored_ref_media),
        }

    return diffs


def simulate_early_stop(
    tweet_ids: list[str], existing_ids: set[str], threshold: int = 5
) -> tuple[bool, int | None]:
    """模拟 repository 的 early stop 逻辑。"""
    consecutive = 0
    for i, tid in enumerate(tweet_ids):
        if tid in existing_ids:
            consecutive += 1
            if consecutive >= threshold:
                return True, i
        else:
            consecutive = 0
    return False, None


# ──────────────────────────────────────────────
# 6. 报告生成
# ──────────────────────────────────────────────

def build_report(
    args: argparse.Namespace,
    v2_data: dict,
    conversion_diags: list[dict],
    parsed_tweets: list,
    validation_results: list,
    existing_ids: set[str],
    db_tweets: dict,
    dedup_map: dict,
    early_stop: tuple[bool, int | None],
) -> dict:
    """构建结构化报告数据。"""
    from returns.result import Success, Failure

    tweet_ids = [t.get("id") for t in v2_data.get("data", [])]

    parse_success = len(parsed_tweets)
    parse_failed = len(tweet_ids) - parse_success

    valid_count = 0
    invalid_count = 0
    cleaned_tweets_map: dict[str, Any] = {}

    for vr in validation_results:
        match vr:
            case Success(tweet):
                valid_count += 1
                cleaned_tweets_map[tweet.tweet_id] = tweet
            case Failure(error):
                invalid_count += 1

    already_in_db = len([tid for tid in tweet_ids if tid and tid in existing_ids])
    new_count = valid_count - len([
        tid for tid in cleaned_tweets_map if tid in existing_ids
    ])

    summary = {
        "api_returned": len(tweet_ids),
        "parse_success": parse_success,
        "parse_failed": parse_failed,
        "validation_pass": valid_count,
        "validation_fail": invalid_count,
        "already_in_db": already_in_db,
        "new": new_count,
        "in_dedup_group": len(dedup_map),
        "early_stop_would_trigger": early_stop[0],
        "early_stop_at_index": early_stop[1],
    }

    # 构建逐条推文报告
    # 建立 parsed_tweets 的 tweet_id → 对象映射
    parsed_map = {t.tweet_id: t for t in parsed_tweets}

    tweets_report = []
    for i, tid in enumerate(tweet_ids):
        if not tid:
            continue

        entry: dict[str, Any] = {
            "index": i,
            "tweet_id": str(tid),
        }

        # 转换阶段诊断
        if i < len(conversion_diags):
            entry["conversion"] = conversion_diags[i]

        # 解析阶段
        parsed = parsed_map.get(str(tid))
        if parsed:
            entry["parse_status"] = "success"
            entry["parsed_text_length"] = len(parsed.text) if parsed.text else 0
        else:
            entry["parse_status"] = "failed"
            tweets_report.append(entry)
            continue

        # 验证阶段
        cleaned = cleaned_tweets_map.get(str(tid))
        if cleaned:
            entry["validation_status"] = "pass"
            # 文本清理差异
            if parsed.text and cleaned.text:
                entry["text_cleaning"] = analyze_text_cleaning(parsed.text, cleaned.text)
                entry["text_length_before_clean"] = len(parsed.text)
                entry["text_length_after_clean"] = len(cleaned.text)
        else:
            entry["validation_status"] = "fail"
            tweets_report.append(entry)
            continue

        # DB 对比
        entry["exists_in_db"] = str(tid) in existing_ids
        entry["in_dedup_group"] = dedup_map.get(str(tid))

        if str(tid) in existing_ids and str(tid) in db_tweets:
            stored = db_tweets[str(tid)]
            diffs = compare_tweets(cleaned, stored)
            entry["db_comparison"] = {
                "match": len(diffs) == 0,
                "differences": diffs,
            }

        tweets_report.append(entry)

    return {
        "meta": {
            "username": args.username,
            "requested_count": args.count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "summary": summary,
        "tweets": tweets_report,
    }


def generate_text_report(report: dict) -> str:
    """生成人类可读的 .txt 报告。"""
    lines: list[str] = []
    meta = report["meta"]
    summary = report["summary"]

    lines.append("=" * 60)
    lines.append("DEBUG FETCH REPORT")
    lines.append(f"User: @{meta['username']} | Requested: {meta['requested_count']} | Time: {meta['timestamp']}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  API returned:           {summary['api_returned']}")
    lines.append(f"  Parse success:          {summary['parse_success']}")
    lines.append(f"  Parse failed:           {summary['parse_failed']}")
    lines.append(f"  Validation pass:        {summary['validation_pass']}")
    lines.append(f"  Validation fail:        {summary['validation_fail']}")
    lines.append(f"  Already in DB:          {summary['already_in_db']}")
    lines.append(f"  New tweets:             {summary['new']}")
    lines.append(f"  In dedup group:         {summary['in_dedup_group']}")

    if summary["early_stop_would_trigger"]:
        lines.append(f"  Early stop:             YES (at index #{summary['early_stop_at_index']})")
    else:
        lines.append(f"  Early stop:             NO")

    for tweet in report["tweets"]:
        lines.append("")
        lines.append("=" * 60)

        status_parts = []
        if tweet.get("parse_status") == "failed":
            status_parts.append("PARSE_FAILED")
        elif tweet.get("validation_status") == "fail":
            status_parts.append("VALIDATION_FAILED")
        elif tweet.get("exists_in_db"):
            status_parts.append("EXISTS_IN_DB")
        else:
            status_parts.append("NEW")

        if tweet.get("in_dedup_group"):
            status_parts.append(f"DEDUP_GROUP={tweet['in_dedup_group']}")

        status_str = " | ".join(status_parts)
        lines.append(f"TWEET #{tweet['index']} | ID: {tweet['tweet_id']} | {status_str}")
        lines.append("=" * 60)

        # 转换阶段
        conv = tweet.get("conversion", {})
        if conv:
            lines.append("")
            lines.append("--- Stage 1: v2 Conversion ---")
            lines.append(f"  text source:      {conv.get('text_source', 'N/A')}")
            candidates = conv.get("text_candidates", {})
            if candidates:
                lines.append(f"  text candidates:  {candidates}")
            lines.append(f"  text length:      {conv.get('text_length', 'N/A')}")
            lines.append(f"  date raw:         {conv.get('date_raw', 'N/A')}")
            lines.append(f"  date converted:   {conv.get('date_converted', 'N/A')}")
            lines.append(f"  media count:      {conv.get('media_count', 0)}")
            lines.append(f"  reference type:   {conv.get('reference_type', 'None')}")
            if conv.get("ref_text_truncated"):
                lines.append(f"  WARNING: ref text appears truncated ({conv.get('ref_text_length')} chars)")
            if conv.get("ref_author"):
                lines.append(f"  ref author:       {conv.get('ref_author')}")

        # 解析阶段
        lines.append("")
        lines.append(f"--- Stage 2: Parse ---")
        lines.append(f"  status:           {tweet.get('parse_status', 'N/A')}")
        if tweet.get("parse_status") == "failed":
            continue
        lines.append(f"  parsed text len:  {tweet.get('parsed_text_length', 'N/A')}")

        # 验证阶段
        lines.append("")
        lines.append(f"--- Stage 3: Validation ---")
        lines.append(f"  status:           {tweet.get('validation_status', 'N/A')}")
        if tweet.get("validation_status") == "fail":
            continue

        cleaning = tweet.get("text_cleaning", [])
        if cleaning:
            for change in cleaning:
                ctype = change.get("type", "")
                if ctype == "newline_removed":
                    lines.append(f"  text change:      {change['count']} newlines removed")
                elif ctype == "space_collapsed":
                    lines.append(f"  text change:      {change['count']} multi-spaces collapsed")
                elif ctype == "whitespace_stripped":
                    lines.append(f"  text change:      {change['chars']} whitespace chars stripped")
                elif ctype == "length_change":
                    lines.append(f"  text length:      {change['before']} -> {change['after']}")
        else:
            lines.append(f"  text change:      (none)")

        # DB 对比
        lines.append("")
        lines.append(f"--- Stage 4: DB Comparison ---")
        lines.append(f"  exists in DB:     {tweet.get('exists_in_db', False)}")

        db_comp = tweet.get("db_comparison")
        if db_comp:
            if db_comp["match"]:
                lines.append(f"  comparison:       ALL FIELDS MATCH")
            else:
                lines.append(f"  comparison:       DIFFERENCES FOUND")
                for field, diff in db_comp["differences"].items():
                    if isinstance(diff, dict) and "fresh" in diff:
                        lines.append(f"    {field}:")
                        lines.append(f"      fresh:  {diff['fresh']}")
                        lines.append(f"      stored: {diff['stored']}")
                    else:
                        lines.append(f"    {field}: {diff}")

    lines.append("")
    lines.append("=" * 60)
    lines.append("END OF REPORT")
    lines.append("=" * 60)
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 7. 主函数
# ──────────────────────────────────────────────

async def main() -> None:
    args = parse_args()
    settings = get_settings()

    # 创建输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / f"{args.username}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching tweets for @{args.username} (count={args.count})...")

    # Step 1: 获取原始 API 数据
    try:
        raw_data = await fetch_raw(args.username, settings)
    except httpx.HTTPStatusError as e:
        print(f"API 请求失败: {e.response.status_code} - {e.response.text[:200]}")
        return
    except Exception as e:
        print(f"API 请求失败: {e}")
        return

    (output_dir / "raw_response.json").write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 统计原始推文数量
    raw_tweets = []
    if isinstance(raw_data.get("data"), dict) and "tweets" in raw_data["data"]:
        raw_tweets = raw_data["data"]["tweets"]
    elif "tweets" in raw_data:
        raw_tweets = raw_data["tweets"]
    print(f"  Raw response saved ({len(raw_tweets)} tweets)")

    # Step 2: v2 转换
    v2_data, conversion_diags = convert_to_v2_with_diagnostics(raw_data, args.username)
    (output_dir / "v2_converted.json").write_text(
        json.dumps(v2_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    v2_count = len(v2_data.get("data", []))
    print(f"  v2 converted ({v2_count} tweets)")

    # Step 3: 解析
    parser = TweetParser()
    parsed_tweets = parser.parse_tweet_response(v2_data)
    print(f"  Parsed: {len(parsed_tweets)} success, {v2_count - len(parsed_tweets)} failed")

    # Step 4: 验证
    validator = TweetValidator()
    validation_results = validator.validate_and_clean_batch(parsed_tweets)

    from returns.result import Success, Failure
    valid = sum(1 for vr in validation_results if isinstance(vr, Success))
    invalid = sum(1 for vr in validation_results if isinstance(vr, Failure))
    print(f"  Validated: {valid} pass, {invalid} fail")

    # Step 5: DB 对比
    tweet_ids = [str(t.get("id")) for t in v2_data.get("data", []) if t.get("id")]
    existing_ids, db_tweets, dedup_map = await get_db_data(tweet_ids)
    print(f"  DB check: {len(existing_ids)} already exist, {len(dedup_map)} in dedup groups")

    # Early stop 模拟
    early_stop = simulate_early_stop(tweet_ids, existing_ids)
    if early_stop[0]:
        print(f"  Early stop would trigger at index #{early_stop[1]}")

    # Step 6: 生成报告
    report = build_report(
        args, v2_data, conversion_diags,
        parsed_tweets, validation_results,
        existing_ids, db_tweets, dedup_map,
        early_stop,
    )

    (output_dir / "pipeline_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "pipeline_report.txt").write_text(
        generate_text_report(report), encoding="utf-8"
    )

    print(f"\nReport saved to {output_dir}/")
    print()

    # 终端汇总
    s = report["summary"]
    print("SUMMARY:")
    print(f"  API returned:     {s['api_returned']}")
    print(f"  Parse OK/Fail:    {s['parse_success']}/{s['parse_failed']}")
    print(f"  Valid/Invalid:    {s['validation_pass']}/{s['validation_fail']}")
    print(f"  In DB/New:        {s['already_in_db']}/{s['new']}")
    if s["in_dedup_group"] > 0:
        print(f"  In dedup group:   {s['in_dedup_group']}")
    if s["early_stop_would_trigger"]:
        print(f"  Early stop:       at index #{s['early_stop_at_index']}")


if __name__ == "__main__":
    asyncio.run(main())
