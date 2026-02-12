"""推文领域模型。

定义推文相关的 Pydantic 数据模型。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ReferenceType(str, Enum):
    """引用类型枚举。

    表示推文之间的引用关系类型。
    """

    retweeted = "retweeted"
    quoted = "quoted"
    replied_to = "replied_to"


class Media(BaseModel):
    """媒体附件模型。

    表示推文中包含的图片、视频等媒体信息。
    """

    media_key: str = Field(..., description="媒体唯一标识")
    type: str = Field(..., description="媒体类型：photo, video, animated_gif 等")
    url: str | None = Field(None, description="媒体 URL")
    preview_image_url: str | None = Field(None, description="预览图片 URL")
    width: int | None = Field(None, description="媒体宽度（像素）")
    height: int | None = Field(None, description="媒体高度（像素）")
    alt_text: str | None = Field(None, description="媒体替代文本")


class Tweet(BaseModel):
    """推文模型。

    表示一条推文的完整信息。
    """

    tweet_id: str = Field(..., description="推文唯一 ID")
    text: str = Field(..., description="推文内容")
    created_at: datetime = Field(..., description="推文创建时间")
    author_username: str = Field(..., description="作者用户名")
    author_display_name: str | None = Field(None, description="作者显示名称")
    referenced_tweet_id: str | None = Field(None, description="引用的推文 ID")
    reference_type: ReferenceType | None = Field(None, description="引用类型")
    media: list[Media] | None = Field(None, description="媒体附件列表")
    referenced_tweet_text: str | None = Field(None, description="被引用/转发推文的完整文本")
    referenced_tweet_media: list[Media] | None = Field(None, description="被引用/转发推文的媒体附件")

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            ReferenceType: lambda v: v.value,
        },
    )


class SaveResult(BaseModel):
    """保存结果模型。

    表示批量保存推文的结果统计。
    """

    success_count: int = Field(..., description="成功保存的推文数量")
    skipped_count: int = Field(..., description="跳过的推文数量（已存在）")
    error_count: int = Field(..., description="保存失败的推文数量")
