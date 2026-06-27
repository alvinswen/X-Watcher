"""status 统计响应模型(无 main 依赖,供 status route + 文件层 status 门面共享)。

⚠️ 这些模型原在 src/api/routes/status.py,但 status.py `from src.main import ...` 形成
status→main→status 循环;文件层门面(FileStatusReadStore)在非 main-first 上下文(MCP/CLI/冷 import)
构造这些模型会触发循环 import。抽到本无依赖模块,门面与 status.py 都从这里 import,断环。
"""

from datetime import datetime

from pydantic import BaseModel


class TweetStats(BaseModel):
    total: int
    latest_tweet_at: datetime | None
    today_count: int


class FollowStats(BaseModel):
    total: int
    active: int
    inactive: int


class SummaryStats(BaseModel):
    total: int
    pending_tweets: int
