"""Feed 领域内部数据模型。"""

from dataclasses import dataclass
from typing import Any


@dataclass
class FeedResult:
    """Service 层内部结果数据类。"""

    items: list[dict[str, Any]]
    count: int
    total: int
    has_more: bool
