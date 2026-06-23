"""浏览/feed 返回包装(对齐旧 browse/feed 响应结构)。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """分页结果(对齐旧 BrowseTweetListResponse/AuthorTimelineResponse)。"""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class Feed(BaseModel, Generic[T]):
    """游标式 feed 结果(对齐旧 FeedResult/FeedResponse)。"""

    items: list[T]
    count: int
    total: int
    has_more: bool
