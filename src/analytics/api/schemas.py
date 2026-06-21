"""发文频次分析 API 请求和响应模型。"""

from pydantic import BaseModel


# ── 发文频次分析模型 ──


class TimeRangeResponse(BaseModel):
    """时间范围响应。"""

    start: str
    end: str


class FrequencySlotResponse(BaseModel):
    """单个时段发文计数。"""

    slot: str
    count: int


class PostingFrequencyResponse(BaseModel):
    """发文频次分析响应。"""

    topic_id: int
    topic_name: str
    slot_minutes: int
    slots: int
    tz_offset: int
    time_range: TimeRangeResponse
    distribution: list[FrequencySlotResponse]
    total_tweets: int
