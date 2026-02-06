"""新闻抓取器包。

提供从 X 平台抓取推文数据的功能。
"""

from src.scraper.client import TwitterClient, TwitterClientError
from src.scraper.domain.models import Media, ReferenceType, Tweet
from src.scraper.infrastructure.repository import TweetRepository
from src.scraper.parser import TweetParser
from src.scraper.scraping_service import ScrapingService
from src.scraper.task_registry import TaskRegistry, TaskStatus
from src.scraper.validator import TweetValidator

__all__ = [
    "TwitterClient",
    "TwitterClientError",
    "Media",
    "ReferenceType",
    "Tweet",
    "TweetRepository",
    "TweetParser",
    "TweetValidator",
    "TaskRegistry",
    "TaskStatus",
    "ScrapingService",
]
