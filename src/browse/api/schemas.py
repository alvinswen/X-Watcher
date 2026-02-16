"""Browse API 数据模型。

定义推文浏览 API 的响应数据模型。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import UTCDatetimeModel


class DailyCount(BaseModel):
    """每日推文数量。"""

    date: str = Field(..., description="日期，YYYY-MM-DD 格式")
    count: int = Field(..., description="推文数量")


class DailyStatsResponse(BaseModel):
    """每日统计响应。"""

    year: int = Field(..., description="年份")
    month: int = Field(..., description="月份")
    days: list[DailyCount] = Field(..., description="每日推文数量列表")


class AuthorInfo(UTCDatetimeModel):
    """作者信息。"""

    author_username: str = Field(..., description="作者用户名")
    author_display_name: str | None = Field(None, description="作者显示名称")
    tweet_count: int = Field(..., description="推文数量")
    last_tweet_at: datetime = Field(..., description="最后一条推文时间")


class AuthorListResponse(BaseModel):
    """作者列表响应。"""

    authors: list[AuthorInfo] = Field(..., description="作者列表")
    total: int = Field(..., description="作者总数")


class BrowseTweetItem(UTCDatetimeModel):
    """推文浏览条目。"""

    tweet_id: str = Field(..., description="推文唯一 ID")
    created_at: datetime = Field(..., description="推文发布时间")
    author_username: str = Field(..., description="作者用户名")
    author_display_name: str | None = Field(None, description="作者显示名称")
    summary_text: str | None = Field(None, description="中文摘要")
    translation_text: str | None = Field(None, description="中文翻译")
    text: str = Field(..., description="推文原文")
    reference_type: str | None = Field(None, description="引用类型")
    referenced_tweet_id: str | None = Field(None, description="引用推文 ID")
    referenced_tweet_text: str | None = Field(None, description="引用推文原文")
    referenced_tweet_author_username: str | None = Field(
        None, description="引用推文作者用户名"
    )
    media: list[dict] | None = Field(None, description="媒体附件")
    referenced_tweet_media: list[dict] | None = Field(
        None, description="引用推文媒体附件"
    )


class BrowseTweetListResponse(BaseModel):
    """推文浏览列表响应。"""

    items: list[BrowseTweetItem] = Field(..., description="推文列表")
    total: int = Field(..., description="推文总数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页条数")
    total_pages: int = Field(..., description="总页数")
