"""抓取统计领域模型。

记录每个用户的抓取历史统计，用于动态计算 limit。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class FetchStats(BaseModel):
    """抓取统计模型。

    记录单个用户的历史抓取数据，用于预测下次合理的 limit 值。
    """

    username: str = Field(..., description="Twitter 用户名")
    last_fetch_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="上次抓取时间",
    )
    last_fetched_count: int = Field(
        default=0, ge=0, description="上次 API 返回的推文数"
    )
    last_new_count: int = Field(
        default=0, ge=0, description="上次新增的推文数"
    )
    total_fetches: int = Field(
        default=0, ge=0, description="总抓取次数"
    )
    avg_new_rate: float = Field(
        default=1.0, ge=0.0, le=1.0, description="EMA 平滑的新推文率 (0-1)"
    )
    consecutive_empty_fetches: int = Field(
        default=0, ge=0, description="连续 0 新推文次数"
    )
