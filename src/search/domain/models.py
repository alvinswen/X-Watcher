"""Search 领域内部数据模型。"""

from dataclasses import dataclass
from typing import Any


@dataclass
class SearchResult:
    """Service 层内部结果数据类。"""

    items: list[dict[str, Any]]
    total: int
