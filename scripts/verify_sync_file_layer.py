"""M-5 子项目 5 联调三级证据:provider 切换 / export 读真数据 / export→import round-trip + dry_run 不落盘。

用法:XWATCHER_DATA_LAYER=file XWATCHER_DATA_ROOT=./data_migrated .venv/bin/python scripts/verify_sync_file_layer.py
判绿:进程退码 0 + 末行打印 'VERIFY OK'(勿用 cmd|tail 取 $?)。
"""

import json
import os
import shutil
import sys
import tempfile


def _fail(msg: str) -> None:
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    os.environ["XWATCHER_DATA_LAYER"] = "file"
    data_root = os.environ.get("XWATCHER_DATA_ROOT", "./data_migrated")
    os.environ["XWATCHER_DATA_ROOT"] = data_root

    from src.data_layer.provider import (
        get_export_repo,
        get_import_repo,
        _FileExportSyncAdapter,
        _FileImportSyncAdapter,
    )
    from src.sync.domain.models import ConflictStrategy

    # 级 1:provider 切换
    if not isinstance(get_export_repo(), _FileExportSyncAdapter):
        _fail("get_export_repo 非 _FileExportSyncAdapter")
    if not isinstance(get_import_repo(), _FileImportSyncAdapter):
        _fail("get_import_repo 非 _FileImportSyncAdapter")
    print("级1 provider 切换 OK")

    # 级 2:export 真实调用点读真数据
    exp = get_export_repo()
    follows = exp.get_follows()
    tweets = exp.get_tweets(since=None, until=None, authors=None)
    summaries = exp.get_summaries(tweet_ids=None)
    articles = exp.get_articles(tweet_ids=None)
    topics = exp.get_topics()
    if len(tweets) != 41018:
        _fail(f"export tweets {len(tweets)} != 41018")
    print(f"级2 export 读真数据 OK(follows={len(follows)} tweets={len(tweets)} "
          f"summaries={len(summaries)} articles={len(articles)} topics={len(topics)})")

    # 级 3:export→import round-trip + dry_run 不落盘
    dst = tempfile.mkdtemp(prefix="xw-verify-import-")
    try:
        os.environ["XWATCHER_DATA_ROOT"] = dst
        repo = get_import_repo(dry_run=False)
        stats = repo.import_follows(follows, ConflictStrategy.skip)
        repo.close()
        if stats.inserted != len(follows):
            _fail(f"round-trip import follows inserted {stats.inserted} != {len(follows)}")
        ff = os.path.join(dst, "follows", "follows.json")
        before = open(ff, "rb").read()
        repo2 = get_import_repo(dry_run=True)
        repo2.import_follows([{"username": "__verify_ghost__", "is_active": True,
                               "added_by": "v", "reason": "v"}], ConflictStrategy.skip)
        repo2.close()
        after = open(ff, "rb").read()
        if after != before:
            _fail("dry_run 改动了真 data_root(应不落盘)")
        loaded = json.loads(after.decode())
        if any(f.get("username") == "__verify_ghost__" for f in loaded["follows"].values()):
            _fail("dry_run ghost 落盘了")
        print(f"级3 round-trip(import {stats.inserted} follows)+ dry_run 不落盘 OK")
    finally:
        shutil.rmtree(dst, ignore_errors=True)
        os.environ["XWATCHER_DATA_ROOT"] = data_root

    print("VERIFY OK")


if __name__ == "__main__":
    main()
