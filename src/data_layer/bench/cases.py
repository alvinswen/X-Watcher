"""子项目 6 性能基准:路径用例 + mode 切换 + session 助手。

lazy import store/repo(import 即建 DB 引擎的副作用延迟到调用期,镜像 provider 范式)。
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path


@contextlib.contextmanager
def data_layer_mode(mode: str, *, data_root: str | None = None):
    """临时设 XWATCHER_DATA_LAYER(+可选 DATA_ROOT),退出还原(原无则删)。"""
    keys = {"XWATCHER_DATA_LAYER": mode}
    if data_root is not None:
        keys["XWATCHER_DATA_ROOT"] = data_root
    prior = {k: os.environ.get(k) for k in keys}
    try:
        for k, v in keys.items():
            os.environ[k] = v
        yield
    finally:
        for k, old in prior.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
