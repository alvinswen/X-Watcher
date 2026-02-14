"""Feed API 数据模型。

定义 Feed API 的请求参数和响应数据模型。
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from src.shared.schemas import UTCDatetimeModel


class FeedTweetItem(UTCDatetimeModel):
    """Feed 推文条目响应模型。"""

    tweet_id: str = Field(..., description="推文唯一 ID")
    text: str = Field(..., description="推文正文")
    author_username: str = Field(..., description="作者用户名")
    author_display_name: str | None = Field(None, description="作者显示名称")
    created_at: datetime = Field(..., description="推文原始发布时间")
    db_created_at: datetime = Field(..., description="入库时间")
    reference_type: str | None = Field(None, description="引用类型")
    referenced_tweet_id: str | None = Field(None, description="引用推文 ID")
    media: list[dict] | None = Field(None, description="媒体附件")
    summary_text: str | None = Field(None, description="中文摘要")
    translation_text: str | None = Field(None, description="中文翻译")


class FeedResponse(UTCDatetimeModel):
    """Feed API 响应模型。"""

    items: list[FeedTweetItem] = Field(..., description="推文列表")
    count: int = Field(..., description="本次返回条数")
    total: int = Field(..., description="满足条件的总条数")
    since: datetime = Field(..., description="实际起始时间")
    until: datetime = Field(..., description="实际截止时间")
    has_more: bool = Field(..., description="是否还有更多推文")


@dataclass
class FeedResult:
    """Service 层内部结果数据类。"""

    items: list[dict]
    count: int
    total: int
    has_more: bool
