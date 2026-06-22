"""搜索 API 数据模型。"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import UTCDatetimeModel


class SearchTweetItem(UTCDatetimeModel):
    """搜索结果推文条目。"""

    tweet_id: str = Field(..., description="推文唯一 ID")
    text: str = Field(..., description="推文正文")
    author_username: str = Field(..., description="作者用户名")
    author_display_name: str | None = Field(None, description="作者显示名称")
    created_at: datetime = Field(..., description="推文原始发布时间")
    db_created_at: datetime | None = Field(None, description="入库时间(file 模式无来源返 None)")
    reference_type: str | None = Field(None, description="引用类型")
    referenced_tweet_id: str | None = Field(None, description="引用推文 ID")
    referenced_tweet_text: str | None = Field(None, description="被引用推文正文")
    referenced_tweet_author_username: str | None = Field(
        None, description="被引用推文作者"
    )
    media: list[dict] | None = Field(None, description="媒体附件")
    referenced_tweet_media: list[dict] | None = Field(
        None, description="被引用推文媒体附件"
    )
    summary_text: str | None = Field(None, description="中文摘要")
    translation_text: str | None = Field(None, description="中文翻译")


class SearchResponse(BaseModel):
    """搜索 API 响应模型。"""

    items: list[SearchTweetItem] = Field(..., description="搜索结果列表")
    count: int = Field(..., description="本次返回条数")
    total: int = Field(..., description="匹配总条数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页条数")
    total_pages: int = Field(..., description="总页数")
    q: str = Field(..., description="搜索关键词")


@dataclass
class SearchResult:
    """Service 层内部结果数据类。"""

    items: list[dict]
    total: int
