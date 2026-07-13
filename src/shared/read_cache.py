"""文件读模型的进程内签名缓存。"""

from __future__ import annotations

from pathlib import Path

from src.scraper.domain.models import Tweet
from src.storage import paths
from src.summarization.domain.models import SummaryRecord

_SummarySignature = tuple[int, int]
_TweetSignature = tuple[tuple[str, int, int], ...]
_summary_cache: dict[str, tuple[_SummarySignature, dict[str, SummaryRecord]]] = {}
_tweet_cache: dict[str, tuple[_TweetSignature, dict[str, Tweet]]] = {}


def _summary_signature(path: Path) -> _SummarySignature:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (-1, -1)
    return (stat.st_mtime_ns, stat.st_size)


async def load_summary_map(data_root: Path) -> dict[str, SummaryRecord]:
    """按 summaries.json 的 mtime_ns+size 读取摘要映射。"""
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore

    root = Path(data_root)
    cache_key = str(root)
    signature = _summary_signature(root / "summaries" / "summaries.json")
    cached = _summary_cache.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    records = await FileSummaryStore(root).get_all_summaries()
    result = {record.tweet_id: record for record in records}
    _summary_cache[cache_key] = (signature, result)
    # 返回进程内共享只读映射；调用方禁止 in-place mutate。
    return result


def _tweet_signature(data_root: Path) -> _TweetSignature:
    entries: list[tuple[str, int, int]] = []
    for shard in paths.iter_canonical_shards(data_root):
        try:
            stat = shard.stat()
        except FileNotFoundError:
            continue
        entries.append((str(shard.relative_to(data_root)), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


async def load_all_tweets_map(data_root: Path) -> dict[str, Tweet]:
    """按全部 canonical 分片的相对路径、mtime_ns、size 读取推文映射。"""
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore

    root = Path(data_root)
    cache_key = str(root)
    signature = _tweet_signature(root)
    cached = _tweet_cache.get(cache_key)
    if cached is not None and cached[0] == signature:
        return cached[1]

    records = await FileTweetStore(root).get_all_tweets()
    result = {record.tweet_id: record for record in records}
    _tweet_cache[cache_key] = (signature, result)
    # 返回进程内共享只读映射；调用方禁止 in-place mutate。
    return result
