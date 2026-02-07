"""新闻去重模块。

提供推文去重功能，包括精确重复检测和相似内容检测。
"""

from src.deduplication.domain.models import (
    DeduplicationGroup,
    DeduplicationResult,
    DeduplicationType,
    DuplicateGroup,
    SimilarGroup,
)

__all__ = [
    "DeduplicationGroup",
    "DeduplicationResult",
    "DeduplicationType",
    "DuplicateGroup",
    "SimilarGroup",
]
