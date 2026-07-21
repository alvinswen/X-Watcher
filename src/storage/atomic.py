"""原子写(临时文件 + fsync + os.replace)与进程内分片锁。"""

from __future__ import annotations

import asyncio
import os
import uuid
import weakref
from pathlib import Path

# WeakValueDictionary:无人持有的分片锁被 GC 回收,避免分片 path 随时间无界增长
# (tweets 按 <author>/<月> 分片)致全局锁 dict 内存泄漏式膨胀。
_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def shard_lock(path: Path) -> asyncio.Lock:
    """返回 path 对应的进程内 asyncio.Lock(同 path 同锁)。

    必须以 `async with shard_lock(p):` 使用——调用方持有返回的强引用贯穿临界区。
    GC 正确性(单事件循环):shard_lock 同步执行、内部无 await,两协程不会在函数内交错
    重复建锁;任一协程在临界区内持返回的强引用 → WeakValueDictionary 条目至少有一个
    强引用在、不被中途回收 → 互斥性保持。临界区全部退出、无人持有后,锁被 GC 回收、
    条目自动从 dict 移除(无界增长止血)。
    """
    key = str(path)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def atomic_replace(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
