"""Subject L1 滚动新闻服务壳。

A1 阶段已移除服务端生成与 rollup 链路；历史 digest 仍由 store 读接口提供。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from src.data_layer.provider import get_subject_repo


class SubjectDigestService:
    """保留服务壳，待 A2/B 通过外部技能回写产物。"""

    def __init__(self, repo: Any | None = None, providers: list[Any] | None = None) -> None:
        repo_factory = cast(Callable[[], Any], get_subject_repo)
        self._repo: Any = repo if repo is not None else repo_factory()
        self._providers: list[Any] | None = providers
